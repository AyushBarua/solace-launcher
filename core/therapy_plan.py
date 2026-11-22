"""
therapy_plan — evidence-based phase model + dynamic difficulty (DDA to a
success band). Pure functions, no Qt, so it's unit-testable in isolation.

Grounded in (see SOLACE_IMPROVEMENT_PLAN.md §1):
  • Fitts & Posner — 3 stages of motor learning (Cognitive→Associative→Autonomous)
  • Challenge Point Framework — learning peaks at an OPTIMAL challenge, matched
    to ability; difficulty tracks a target SUCCESS RATE, it does not climb forever
  • Kleim & Jones — neuroplasticity principles (specificity, repetition,
    intensity, salience, transference, interference)
  • Brunnstrom — recovery is non-linear; entry stage set by assessment; can regress
  • DDA / flow — hold the patient in a success band (~65–85%) for engagement + reps

Core idea: PROGRESS = sustaining the success band while task DEMAND rises.
Each phase caps how hard the demand can get; difficulty is nudged toward the
phase's success band; the patient advances when they hold the band at the phase
ceiling, and regresses on sustained failure or pain.
"""

DIFF_MIN, DIFF_MAX = 0.15, 1.0
ADVANCE_SUSTAIN = 2          # sessions in-band at the ceiling before advancing (D3)

# ── Phase definitions ─────────────────────────────────────────────────────────
# success_band : DDA target (Challenge Point) for this phase
# ceiling      : max difficulty demand in this phase (defines "top of phase")
# practice     : blocked (one movement) → random (mixed) as skill grows
PHASES = {
    1: {
        "key": "foundation", "name": "Find Your Movement",
        "stage": "Cognitive", "practice": "blocked",
        "success_band": (0.75, 0.85), "ceiling": 0.40,
        "goal": "Getting comfortable with the movement — slow and steady, "
                "building confidence.",
    },
    2: {
        "key": "build", "name": "Build Strength",
        "stage": "Associative", "practice": "focused",
        "success_band": (0.68, 0.78), "ceiling": 0.65,
        "goal": "Strengthening your weakest movement with focused repetition.",
    },
    3: {
        "key": "sharpen", "name": "Sharpen & Combine",
        "stage": "Associative→Autonomous", "practice": "random",
        "success_band": (0.62, 0.72), "ceiling": 0.90,
        "goal": "Mixing movements and games so your gains carry into daily life.",
    },
    4: {
        "key": "mastery", "name": "Mastery",
        "stage": "Autonomous", "practice": "varied",
        "success_band": (0.60, 0.80), "ceiling": 1.00,
        "goal": "You've recovered — keep playing to maintain and enjoy it.",
    },
}
FIRST_PHASE, LAST_PHASE = 1, 4


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ── Entry phase & starting difficulty (from the assessment) ───────────────────

def entry_phase(overall_ability: float | None) -> int:
    """Brunnstrom: don't assume stage 1 — set entry from measured ability."""
    if overall_ability is None:
        return 1
    if overall_ability < 0.35:
        return 1
    if overall_ability < 0.60:
        return 2
    return 3            # able patients start at Sharpen, never skip to Mastery


def seed_start_difficulty(overall_ability: float | None,
                          tremor: float | None, phase: int) -> float:
    """
    Fresh-game starting difficulty from the assessment (§2/§3):
      start = 0.15 + ability×0.50, minus a tremor penalty, clamped to the
      phase ceiling so a phase-1 patient never starts above phase-1 demand.
    """
    a = overall_ability if overall_ability is not None else 0.2
    start = 0.15 + a * 0.50
    if tremor is not None:
        start -= 0.05 if tremor >= 0.05 else 0.0
        start -= 0.05 if tremor >= 0.10 else 0.0
    ceiling = PHASES[phase]["ceiling"]
    return round(_clamp(start, DIFF_MIN, min(0.60, ceiling)), 2)


# ── Per-session success signal (0..1) ─────────────────────────────────────────

def session_success(session: dict, target_seconds: int = 180) -> float:
    """
    v1 success signal from what the launcher actually knows (D2): pain check-in
    (primary), engagement via play duration, and completion. In-game score can
    replace/augment this later when games are instrumented.
      pain        → 0.15 (clear signal it was too much)
      else        → 0.40 + 0.50 × min(1, duration/target); 'tired' −0.10
    """
    pain = session.get("pain_report")
    if pain == "pain":
        return 0.15
    dur = session.get("duration_seconds", 0) or 0
    engagement = _clamp(dur / max(1, target_seconds), 0.0, 1.0)
    score = 0.40 + 0.50 * engagement
    if pain == "tired":
        score -= 0.10
    return round(_clamp(score, 0.0, 1.0), 3)


# ── Dynamic difficulty: nudge toward the phase's success band ─────────────────

def adapt_difficulty(cur_diff: float, success: float, phase: int) -> float:
    """
    Challenge Point Framework as an algorithm: move difficulty toward keeping
    the patient in the phase's success band, NOT upward without limit.
      above band → harder (they're coasting)
      in band    → hold (bank reps at the optimal challenge)
      below band → easier
    Clamped to the phase ceiling so difficulty stays within the phase.
    """
    lo, hi = PHASES[phase]["success_band"]
    if success > hi:
        cur_diff += 0.08
    elif success < lo:
        cur_diff -= 0.10
    ceiling = PHASES[phase]["ceiling"]
    return round(_clamp(cur_diff, DIFF_MIN, ceiling), 2)


def _in_band(success: float, phase: int) -> bool:
    lo, hi = PHASES[phase]["success_band"]
    return lo <= success <= hi


def _at_ceiling(diff: float, phase: int) -> bool:
    return diff >= PHASES[phase]["ceiling"] - 1e-6


# ── Phase progression (performance-gated) ─────────────────────────────────────

def phase_transition(phase: int, diff: float, success: float,
                     in_band_streak: int, last_pain: str | None,
                     graduated_ready: bool) -> tuple[int, int, str]:
    """
    Decide the next phase from performance (not a raw session count).
    Returns (new_phase, new_in_band_streak, event) where event ∈
    {"", "advance", "regress", "graduate"}.

    Advance: at the phase ceiling AND holding the band for ADVANCE_SUSTAIN
             sessions → next phase (harder demand, lower band).
    Regress: pain, or bottomed-out difficulty while still failing the band.
    """
    # Regression first — safety.
    if last_pain == "pain" and phase > FIRST_PHASE:
        return phase - 1, 0, "regress"
    if (success < PHASES[phase]["success_band"][0]
            and diff <= DIFF_MIN + 1e-6 and phase > FIRST_PHASE):
        return phase - 1, 0, "regress"

    # Progress toward advancing: at the phase ceiling, succeeding AT OR ABOVE
    # the band means the phase is mastered (difficulty is capped, so they can't
    # be pulled down INTO the band — above it is the signal to move up).
    lo = PHASES[phase]["success_band"][0]
    streak = in_band_streak + 1 if (_at_ceiling(diff, phase)
                                    and success >= lo) else 0

    if phase < LAST_PHASE and streak >= ADVANCE_SUSTAIN:
        # Graduation only checked when clinically ready (degrees-based, elsewhere)
        if phase == 3 and not graduated_ready:
            return phase, streak, ""      # stay in Sharpen until truly recovered
        return phase + 1, 0, ("graduate" if phase == 3 else "advance")

    return phase, streak, ""


def phase_progress_pct(phase: int, diff: float, in_band_streak: int) -> float:
    """0..1 progress through the CURRENT phase (demand climb + band-hold)."""
    ceiling = PHASES[phase]["ceiling"]
    demand = _clamp((diff - DIFF_MIN) / max(1e-6, ceiling - DIFF_MIN), 0, 1)
    hold = _clamp(in_band_streak / ADVANCE_SUSTAIN, 0, 1)
    # demand climb is 70% of the bar, holding the band at the top the last 30%
    return round(_clamp(0.7 * demand + 0.3 * hold, 0, 1), 3)
