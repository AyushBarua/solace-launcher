"""
SuggestionEngine v2 — data-driven therapy recommendations.

Built on core/patient_model.py (per-direction ability vs healthy reference,
improvement trends from warmup history, pain rate, per-game stats).

What it does after EVERY session:
  1. Adapts that game's difficulty from how the session actually went
     (duration + pain check-in), stored per game.
  2. Re-evaluates the patient's weakest DIRECTION (flexion, extension,
     pronation, supination — not just an axis) and rotates the target if
     progress has plateaued.
  3. Scores every installed game on: how well it trains what the patient
     needs (weighted by urgency — declining directions score higher),
     difficulty fit for the patient's current ability, variety (avoids
     recommending the same game forever), and pain guard.
  4. Advances the 4-phase journey on data, not just session counts, and
     graduates on DEGREES-based improvement.

Public API (consumed by launcher.py, ui/journey_banner.py):
  PHASE_NAMES, PHASE_GOALS, PHASE2_MIN_SESSIONS, PHASE3_SQUEEZE_SESSIONS
  _get_easiest_game(games), _get_weakness_game(games, weakness)
  seed_journey_from_baseline(sm)
  update_journey(sm, session, games) -> JourneyCard dict
  get_current_card(sm, games)        -> JourneyCard dict (no state change)
  get_game_difficulty(sm, game_id)   -> float 0.15..1.0
"""
from __future__ import annotations
from typing import Optional
from core.session_manager import SessionManager
from core.patient_model import (
    DIRECTIONS, ability, trends, improvement_pct, pain_rate,
    game_stats,
)
from core import therapy_plan as tp

# ── Journey phases ────────────────────────────────────────────────────────────

# Names/goals come from the evidence-based phase model (therapy_plan.PHASES).
PHASE_NAMES = {n: tp.PHASES[n]["name"] for n in tp.PHASES}
PHASE_GOALS = {n: tp.PHASES[n]["goal"] for n in tp.PHASES}

PHASE2_MIN_SESSIONS      = 3    # sessions before phase 2 → 3
PHASE3_SQUEEZE_SESSIONS  = 5    # kept for journey_banner compatibility
PHASE3_PLATEAU_SESSIONS  = 6    # plateaued this long → rotate target
PHASE3_GRADUATE_SESSIONS = 15   # minimum phase-3 sessions before graduation

DIFF_MIN, DIFF_MAX = 0.15, 1.0

_DIR_LABEL = {
    "flexion": "handle-twist (flexion)", "extension": "handle-twist (extension)",
    "pronation": "wheel-tilt (pronation)", "supination": "wheel-tilt (supination)",
}


# Games the engine must never auto-recommend (still playable from the Library).
REC_EXCLUDE = {"tilting_maze_game"}


# ── Game metadata helpers ─────────────────────────────────────────────────────

def _movement_directions(game: dict) -> set:
    """Which anatomical directions (or 'squeeze') a game trains."""
    dirs = set()
    for m in (game.get("movements") or []):
        ml = m.lower()
        if "flex" in ml:
            dirs.update(("flexion", "extension"))
        if "pronation" in ml or "supination" in ml:
            dirs.update(("pronation", "supination"))
        if "hybrid" in ml or "combined" in ml:
            dirs.update(DIRECTIONS)
        if "squeeze" in ml:
            dirs.add("squeeze")
    return dirs or set(DIRECTIONS)      # untagged → treat as general


def _get_easiest_game(games: list[dict]) -> Optional[dict]:
    """Beginner-tagged installed game, else any installed game.
    Never returns a REC_EXCLUDE game."""
    for g in games:
        if (g.get("difficulty_tag") == "beginner" and g.get("is_installed")
                and g.get("id") not in REC_EXCLUDE):
            return g
    for g in games:
        if g.get("is_installed") and g.get("id") not in REC_EXCLUDE:
            return g
    return None


def _get_weakness_game(games: list[dict], weakness: str) -> Optional[dict]:
    """Legacy axis-based lookup — kept for ui/journey_banner.py."""
    axis_tag = "horizontal" if weakness == "x" else "vertical"
    for g in games:
        if (g.get("is_installed") and axis_tag in (g.get("body_parts") or [])
                and g.get("id") not in REC_EXCLUDE):
            return g
    return _get_easiest_game(games)


def _detect_weakness(sm: SessionManager) -> Optional[str]:
    """Axis-level weakness ('x'|'y'|None) derived from directional ability."""
    ab = ability(sm)
    weakest = ab.get("weakest")
    if not weakest:
        return None
    return "x" if weakest in ("pronation", "supination") else "y"


# ── Per-game adaptive difficulty ──────────────────────────────────────────────

def _current_phase(sm: SessionManager) -> int:
    return sm.get_journey().get("phase", 1)


def _start_difficulty(sm: SessionManager | None = None) -> float:
    """
    Fresh-game starting difficulty (§2/§3): seeded from the ASSESSMENT's overall
    ability minus a tremor penalty, clamped to the current phase ceiling.
    Falls back to warmup ability, then the global setting.
    """
    if sm is not None:
        overall = ability(sm).get("overall")
        tremor = (sm.get_baseline_rom() or {}).get("tremor")
        phase = _current_phase(sm)
        if overall is not None:
            return tp.seed_start_difficulty(overall, tremor, phase)
    try:
        import json, os
        from core.paths import get_data_dir
        p = os.path.join(get_data_dir(), "global_settings.json")
        with open(p, "r", encoding="utf-8") as f:
            v = float(json.load(f).get("difficulty_multiplier", 0.25))
        return max(DIFF_MIN, min(0.6, v))
    except Exception:
        return 0.25


def get_game_difficulty(sm: SessionManager, game_id: str) -> float:
    stored = sm.get_game_difficulty(game_id)
    d = stored if stored is not None else _start_difficulty(sm)
    guard = sm.get_guardrails()
    # Gentle day after a painful session — cap whatever the game is stored at
    if guard.get("pain_caution", True) and sm.get_last_pain_report() == "pain":
        d = min(d, 0.4)
    # Therapist hard cap (§4B Tier 1)
    d = min(d, float(guard.get("max_difficulty", 1.0)))
    return round(d, 2)


def _adapt_game_difficulty(sm: SessionManager, session: dict) -> float:
    """
    Called after each session. Dynamic Difficulty Adjustment (Challenge Point
    Framework): compute a 0..1 session success signal, then nudge difficulty
    TOWARD the current phase's success band — up if coasting, down if
    struggling, hold if in the band. Clamped to the phase ceiling.
    """
    gid   = session.get("game_id")
    d     = get_game_difficulty(sm, gid)
    phase = _current_phase(sm)
    success = tp.session_success(session)
    d = tp.adapt_difficulty(d, success, phase)
    sm.set_game_difficulty(gid, d)
    return d


# ── Game scoring ──────────────────────────────────────────────────────────────

def _difficulty_fit(tag: str, overall: float) -> float:
    """How well a game's difficulty tag suits the patient's current ability."""
    table = {
        "beginner":     (1.00, 0.70, 0.35),   # ability <0.45 / 0.45-0.7 / >0.7
        "intermediate": (0.45, 1.00, 0.75),
        "advanced":     (0.10, 0.50, 1.00),
    }
    row = table.get(tag or "", (0.6, 0.6, 0.6))
    return row[0] if overall < 0.45 else row[1] if overall < 0.7 else row[2]


def _squeeze_deficit(sm: SessionManager) -> float:
    sq = (sm.get_baseline_rom() or {}).get("squeeze_max")
    if sq is None:
        return 0.5                       # unknown — neutral priority
    return round(max(0.0, 1.0 - min(1.0, sq / 0.6)), 3)


def score_games(sm: SessionManager, games: list[dict],
                phase: int) -> list[tuple[float, dict, dict]]:
    """
    Score every installed game. Returns [(score, game, factors)] best-first.
    factors carries the pieces used for human-readable reasons.
    """
    ab    = ability(sm)
    tr    = trends(sm)
    stats = game_stats(sm)
    last_pain = sm.get_last_pain_report()
    prate     = pain_rate(sm)
    overall   = ab.get("overall") if ab.get("overall") is not None else 0.4
    sq_def    = _squeeze_deficit(sm)
    excluded  = set(sm.get_guardrails().get("excluded_movements", []))

    scored = []
    for g in games:
        if not g.get("is_installed"):
            continue
        if g.get("id") in REC_EXCLUDE:      # never auto-recommend these
            continue
        dirs = _movement_directions(g)
        # Therapist guardrail: skip games that require a contraindicated
        # movement (§4B Tier 1). Hybrid games (all dirs) are allowed.
        if excluded and dirs != set(DIRECTIONS) and (dirs & excluded):
            continue

        # 1) need: worst deficit among the directions this game trains,
        #    with urgency boost when that direction is declining/plateaued
        need, need_dir = 0.0, None
        for d in dirs:
            if d == "squeeze":
                deficit = sq_def
            else:
                a = ab.get(d)
                deficit = 1.0 - min(1.0, a) if a is not None else 0.5
                cls = tr.get(d, {}).get("cls")
                if cls == "declining":
                    deficit = min(1.0, deficit + 0.15)
                elif cls == "plateau":
                    deficit = min(1.0, deficit + 0.05)
            if deficit > need:
                need, need_dir = deficit, d

        # 2) difficulty fit
        fit = _difficulty_fit(g.get("difficulty_tag"), overall)

        # 3) variety: don't hammer the same game
        st = stats.get(g["id"], {})
        variety = 1.0
        if st.get("last_idx") == 0:
            variety -= 0.45              # was literally the last game played
        if st.get("share", 0) > 0.5:
            variety -= 0.25              # majority of all sessions already
        variety = max(0.0, variety)

        # 4) pain guard + phase bias
        bias = 0.5
        if last_pain == "pain" or prate >= 0.4:
            bias = 1.0 if g.get("difficulty_tag") == "beginner" else 0.2
        elif phase <= 2:
            bias = 1.0 if g.get("difficulty_tag") == "beginner" else 0.4

        score = 0.45 * need + 0.25 * fit + 0.20 * variety + 0.10 * bias
        scored.append((round(score, 4), g,
                       {"need": round(need, 3), "need_dir": need_dir,
                        "fit": fit, "variety": variety, "bias": bias}))

    scored.sort(key=lambda t: t[0], reverse=True)
    return scored


def _reason_text(sm: SessionManager, game: dict, factors: dict,
                 phase: int) -> str:
    ab = ability(sm)
    tr = trends(sm)
    last_pain = sm.get_last_pain_report()

    if last_pain == "pain":
        return "You reported discomfort last time, so today stays gentle."

    d = factors.get("need_dir")
    if d == "squeeze":
        return f"Your grip strength has the most room to grow — {game['name']} trains your squeeze."
    if d and ab.get(d) is not None:
        pct = int(min(1.0, ab[d]) * 100)
        cls = tr.get(d, {}).get("cls", "unknown")
        word = {"improving": "and improving — keep it going",
                "plateau": "and has levelled off — time to push it",
                "declining": "and slipping — let's work on it today",
                "unknown": "— let's build some data on it"}[cls]
        return (f"Your {_DIR_LABEL.get(d, d)} is at {pct}% of reference "
                f"{word}. {game['name']} targets exactly that.")
    if phase <= 2:
        return "Let's start with something gentle and build confidence."
    return f"{game['name']} is the best overall match for you today."


# ── Journey seeding & phases ──────────────────────────────────────────────────

# ── Stage ladder ──────────────────────────────────────────────────────────────
# The journey is a sequence of STAGES. Each stage locks exactly ONE game and
# is played for SESSIONS_PER_STAGE sessions (difficulty adapting within it).
# On completion the weakness is re-evaluated and the NEXT single game is
# locked in — deliberately different, so variety happens across stages, not
# within one. This replaces the old "many games per phase" design.
SESSIONS_PER_STAGE = 4

TOTAL_GRADUATE_SESSIONS = 15   # minimum sessions before graduation is checked


def _axis_of(direction: str | None) -> str | None:
    if direction in ("pronation", "supination"):
        return "x"
    if direction in ("flexion", "extension"):
        return "y"
    return None


def _factors_for(sm, games, game_id, phase=3) -> dict:
    for _score, g, factors in score_games(sm, games, phase):
        if g["id"] == game_id:
            return factors
    return {}


def _pick_stage_game(sm, games, avoid_id=None):
    """Best single game for the patient right now, preferably not avoid_id."""
    ranked = score_games(sm, games, 3)
    for _score, g, factors in ranked:
        if g["id"] != avoid_id:
            return g, factors
    return (ranked[0][1], ranked[0][2]) if ranked else (None, {})


def _ensure_stage_game(sm, games):
    """Return this stage's LOCKED game, picking + storing one if needed.
    Re-picks if the locked game is now excluded from recommendations."""
    journey = sm.get_journey()
    gid = journey.get("stage_game_id")
    g = next((x for x in games
              if x["id"] == gid and x.get("is_installed")), None)
    if g and gid not in REC_EXCLUDE:
        return g
    picked, _ = _pick_stage_game(sm, games)
    if picked:
        sm.update_journey(stage_game_id=picked["id"])
    return picked


def seed_journey_from_baseline(sm: SessionManager):
    """After the AssessmentWizard: set the ENTRY PHASE from measured ability
    (Brunnstrom — don't assume phase 1) and target the weakest direction."""
    baseline = sm.get_baseline_rom() or {}
    if not baseline.get("deg"):
        return
    ab = ability(sm)
    weakest = ab.get("weakest")
    phase = tp.entry_phase(ab.get("overall"))
    sm.update_journey(phase=phase, in_band_streak=0, graduated=False,
                      stage_game_id=None,
                      target_direction=weakest, target_weakness=_axis_of(weakest),
                      sessions_in_phase=0)
    print(f"[SuggestionEngine] Seeded: entry phase={phase} "
          f"({tp.PHASES[phase]['name']}), ability={ab}, target={weakest}")


def _check_graduation(sm: SessionManager, total_sessions: int,
                      current_diff: float) -> bool:
    """Degrees-based graduation gate: real recovery, not normalised artifacts."""
    if total_sessions < TOTAL_GRADUATE_SESSIONS or current_diff < 0.8:
        return False
    ab  = ability(sm)
    imp = improvement_pct(sm)
    if ab.get("overall") is not None and ab["overall"] >= 0.85:
        return True
    for d in DIRECTIONS:
        if (imp.get(d) is not None and imp[d] >= 50
                and ab.get(d) is not None and ab[d] >= 0.7):
            return True
    return False


# ── Card builder (shared by update_journey & get_current_card) ────────────────

def _build_card(sm: SessionManager, games: list[dict]) -> dict:
    journey   = sm.get_journey()
    graduated = journey.get("graduated", False)
    phase     = journey.get("phase", 1)
    streak    = journey.get("in_band_streak", 0)

    rec = _ensure_stage_game(sm, games)
    if not rec:
        return {
            "phase": phase, "phase_name": "Getting started",
            "goal": "Install a game from the Library to begin.",
            "recommended_game_id": None, "recommended_game_name": None,
            "reason": "Install a game from the Library to begin.",
            "difficulty_suggestion": _start_difficulty(sm),
            "progress_pct": 0.0, "graduated": False,
        }

    diff = get_game_difficulty(sm, rec["id"])

    if graduated:
        return {
            "phase": 4, "phase_name": PHASE_NAMES[4], "goal": PHASE_GOALS[4],
            "recommended_game_id": rec["id"], "recommended_game_name": rec["name"],
            "reason": ("You've graduated! Your movement has genuinely "
                       "recovered. Keep playing to maintain your gains."),
            "difficulty_suggestion": diff,
            "progress_pct": 1.0, "graduated": True,
        }

    factors = _factors_for(sm, games, rec["id"])
    reason  = _reason_text(sm, rec, factors, phase)
    return {
        "phase": phase, "phase_name": PHASE_NAMES[phase],
        "goal": PHASE_GOALS[phase],
        "recommended_game_id": rec["id"], "recommended_game_name": rec["name"],
        "reason": reason,
        "difficulty_suggestion": diff,
        "progress_pct": tp.phase_progress_pct(phase, diff, streak),
        "graduated": False,
    }


# ── Main entry points ─────────────────────────────────────────────────────────

def update_journey(sm: SessionManager, session: dict, games: list[dict]) -> dict:
    """Called after every session (pain check-in already recorded)."""
    # 1) DDA: adapt this game's difficulty toward the phase's success band
    new_diff = _adapt_game_difficulty(sm, session)
    success  = tp.session_success(session)

    journey   = sm.get_journey()
    if journey.get("graduated", False):
        return _build_card(sm, games)

    phase     = journey.get("phase", 1)
    streak    = journey.get("in_band_streak", 0)
    last_pain = sm.get_last_pain_report()
    grad_ready = _check_graduation(sm, sm.get_total_sessions(), new_diff)

    # 2) Phase transition — performance-gated (Challenge Point + Brunnstrom)
    nphase, nstreak, ev = tp.phase_transition(
        phase, new_diff, success, streak, last_pain, grad_ready)

    if ev == "graduate":
        sm.update_journey(graduated=True, phase=tp.LAST_PHASE, in_band_streak=0)
    elif ev in ("advance", "regress"):
        ab = ability(sm)
        weakest = ab.get("weakest")
        # New phase → lock a fresh game (different from the current one)
        nxt, _ = _pick_stage_game(sm, games, avoid_id=journey.get("stage_game_id"))
        sm.update_journey(
            phase=nphase, in_band_streak=0,
            stage_game_id=(nxt["id"] if nxt else None),
            target_direction=weakest, target_weakness=_axis_of(weakest))
        print(f"[SuggestionEngine] {ev.upper()} → {tp.PHASES[nphase]['name']} "
              f"(target={weakest}, game={nxt['name'] if nxt else None})")
    else:
        # Same phase — update the band-hold streak. In Phase 3 (random practice)
        # rotate the game periodically for contextual interference / transfer.
        upd = {"in_band_streak": nstreak}
        sip = journey.get("sessions_in_phase", 0) + 1
        upd["sessions_in_phase"] = sip
        if phase == 3 and sip % 3 == 0:
            nxt, _ = _pick_stage_game(sm, games, avoid_id=journey.get("stage_game_id"))
            if nxt:
                upd["stage_game_id"] = nxt["id"]
        sm.update_journey(**upd)

    return _build_card(sm, games)


def get_current_card(sm: SessionManager, games: list[dict]) -> dict:
    """Current recommendation without advancing the plan."""
    return _build_card(sm, games)
