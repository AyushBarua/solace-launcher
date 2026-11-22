"""
SessionManager — the data backbone for Solace Phase 2.

Handles per-profile session logging, daily ROM capture, streak tracking,
pain check-in storage, milestone logging, and therapy journey state.

All data is stored locally in session_log.json next to the active profile.
Nothing leaves the device unless the user explicitly exports a report.
"""
import os
import sys
import json
from datetime import datetime, date, timedelta
from typing import Optional


def get_settings_path():
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), "global_settings.json")


def _get_log_path(profile_id: str) -> str:
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), f"session_log_{profile_id}.json")


def _load_log(profile_id: str) -> dict:
    path = _get_log_path(profile_id)
    bak  = path + ".bak"

    # Try primary file first
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return _migrate_log(data)
        except Exception as e:
            print(f"[SessionManager] Primary log corrupt ({e}), trying backup…")

    # Primary missing or corrupt — try .bak
    if os.path.exists(bak):
        try:
            with open(bak, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"[SessionManager] Recovered session data from backup for {profile_id}")
            return _migrate_log(data)
        except Exception as e:
            print(f"[SessionManager] Backup also corrupt ({e}), starting fresh.")

    return _empty_log(profile_id)


def _save_log(profile_id: str, log: dict):
    path = _get_log_path(profile_id)
    bak  = path + ".bak"
    tmp  = path + ".tmp"
    try:
        # Write new data to .tmp first
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2, ensure_ascii=False)
        # Promote the current good file to .bak before replacing
        if os.path.exists(path):
            try:
                import shutil
                shutil.copy2(path, bak)
            except Exception:
                pass  # non-fatal — proceed with the save anyway
        # Atomic replace: tmp → primary
        os.replace(tmp, path)
    except Exception as e:
        print(f"[SessionManager] Could not save log: {e}")


def _empty_log(profile_id: str) -> dict:
    return {
        "schema_version":  1,
        "profile_id":      profile_id,
        "baseline_rom":    None,
        "sessions":        [],
        "milestones":      [],
        "journey": {
            "phase":             1,
            "target_weakness":   None,
            "sessions_in_phase": 0,
            "phase_start_date":  None,
        },
        "streak": {
            "current":           0,
            "longest":           0,
            "last_session_date": None,
        },
    }


def _migrate_log(log: dict) -> dict:
    """Idempotent migration: upgrades log to the current schema version in-place."""
    version = log.get("schema_version", 0)

    if version < 1:
        # v0 → v1: ensure all required top-level keys exist
        log.setdefault("baseline_rom", None)
        log.setdefault("sessions", [])
        log.setdefault("milestones", [])
        log.setdefault("journey", {
            "phase": 1, "target_weakness": None,
            "sessions_in_phase": 0, "phase_start_date": None,
        })
        log.setdefault("streak", {
            "current": 0, "longest": 0, "last_session_date": None,
        })
        log["schema_version"] = 1

    # Add future migrations here as elif version < N: …

    return log


# ── Public API ────────────────────────────────────────────────────────────────

class SessionManager:
    """
    Manages the full lifecycle of a patient's session data.
    One instance per active profile — create with SessionManager(profile_id).
    """

    def __init__(self, profile_id: str):
        self.profile_id = profile_id
        self._log = _load_log(profile_id)

    def _save(self):
        _save_log(self.profile_id, self._log)

    # ── Baseline ROM (onboarding) ─────────────────────────────────────────────

    def save_baseline_rom(self, max_left: float, max_right: float,
                          max_up: float, max_down: float):
        """Fallback baseline from a plain warmup (no hand/squeeze data).
        Marked provisional — the AssessmentWizard remains on offer."""
        from core.units import rom_record_from_axes
        self._log["baseline_rom"] = {
            "source": "warmup",
            "max_left":  round(max_left,  3),
            "max_right": round(max_right, 3),
            "max_up":    round(max_up,    3),
            "max_down":  round(max_down,  3),
            "date":      date.today().isoformat(),
            # Degrees record — clinical source of truth (flaw #1/#4 fix).
            # Carries its own firmware limits so it survives firmware changes.
            "deg": {k: (round(v, 1) if isinstance(v, float) else v)
                    for k, v in rom_record_from_axes(
                        max_left, max_right, max_up, max_down).items()},
        }
        self._save()

    def save_assessment_baseline(self, deg: dict, squeeze_max: float | None,
                                 hand: str, tremor: float | None = None):
        """
        Save the first-launch assessment as the clinical baseline.

        deg:         {"flexion":…, "extension":…, "pronation":…, "supination":…}
                     in DEGREES (measured with healthy limits loaded).
        squeeze_max: peak analog squeeze 0..1 (None if firmware lacks Z axis).
        hand:        "left" | "right".
        """
        from core.units import FIRMWARE_LIMITS, ROM_UNITS_VERSION
        # Legacy-compatible normalised fields (vs healthy reference)
        norm = {k: round(min(1.0, deg.get(a, 0.0) / FIRMWARE_LIMITS[a]), 3)
                for k, a in (("max_right", "pronation"), ("max_left", "supination"),
                             ("max_down", "flexion"),    ("max_up", "extension"))}
        self._log["baseline_rom"] = {
            **norm,
            "max_left": -norm["max_left"],   # legacy sign convention
            "max_up":   -norm["max_up"],
            "date": date.today().isoformat(),
            "hand": hand,
            "squeeze_max": round(squeeze_max, 3) if squeeze_max is not None else None,
            "tremor": round(tremor, 4) if tremor is not None else None,
            "source": "assessment_wizard",
            "deg": {
                "units": ROM_UNITS_VERSION,
                "firmware_limits": dict(FIRMWARE_LIMITS),
                **{k: round(float(deg.get(k, 0.0)), 1)
                   for k in ("flexion", "extension", "pronation", "supination")},
            },
        }
        self._save()

    def has_baseline(self) -> bool:
        return self._log["baseline_rom"] is not None

    def get_baseline_rom(self) -> Optional[dict]:
        return self._log.get("baseline_rom")

    # ── Therapist guardrails (§4B Tier 1) ─────────────────────────────────────

    _GUARDRAIL_DEFAULTS = {
        "max_difficulty":     1.0,     # cap on adaptive difficulty
        "excluded_movements": [],      # e.g. ["pronation"] — games needing these hidden
        "pain_caution":       True,    # extra gentle after pain
        "pin":                None,     # clinician PIN (None = not set)
        # Patient-safety dose limits (SAFETY §1.1) — prevent overexertion.
        "max_session_min":    20,      # suggest stopping after this per game
        "max_daily_min":      45,      # total across the day before a firm rest
        "rest_reminder":      True,    # nudge a break after a long session
    }

    def get_guardrails(self) -> dict:
        g = dict(self._GUARDRAIL_DEFAULTS)
        g.update(self._log.get("guardrails", {}))
        return g

    def set_guardrails(self, **kwargs):
        g = self._log.setdefault("guardrails", {})
        for k, v in kwargs.items():
            if k in self._GUARDRAIL_DEFAULTS:
                g[k] = v
        self._save()

    # ── Daily ROM (one warmup per day, shared by all sessions that day) ───────

    def save_daily_rom(self, max_left: float, max_right: float,
                       max_up: float, max_down: float,
                       tremor: float | None = None):
        from core.units import rom_record_from_axes
        rec = {
            "max_left":  round(max_left,  3),
            "max_right": round(max_right, 3),
            "max_up":    round(max_up,    3),
            "max_down":  round(max_down,  3),
            "tremor":    round(tremor, 4) if tremor is not None else None,
            "deg": {k: (round(v, 1) if isinstance(v, float) else v)
                    for k, v in rom_record_from_axes(
                        max_left, max_right, max_up, max_down).items()},
        }
        daily = self._log.setdefault("daily_rom", {})
        daily[date.today().isoformat()] = rec
        # Cap history at ~1 year of entries
        if len(daily) > 370:
            for k in sorted(daily)[:-370]:
                del daily[k]
        self._save()

    def get_daily_rom(self, day: str | None = None) -> Optional[dict]:
        """Today's warmup measurement (standalone or from a session)."""
        day = day or date.today().isoformat()
        rec = self._log.get("daily_rom", {}).get(day)
        if rec:
            return rec
        for s in reversed(self._log["sessions"]):
            if s.get("date") == day and s.get("rom"):
                return s["rom"]
        return None

    # ── Per-game adaptive difficulty ──────────────────────────────────────────

    def get_game_difficulty(self, game_id: str):
        return self._log.setdefault("game_difficulty", {}).get(game_id)

    def set_game_difficulty(self, game_id: str, value: float):
        self._log.setdefault("game_difficulty", {})[game_id] = round(value, 2)
        self._save()

    def mark_onboarding_done(self):
        """Call after onboarding is completed OR skipped so it never shows again."""
        self._log["onboarding_done"] = True
        self._save()

    def onboarding_done(self) -> bool:
        return self._log.get("onboarding_done", False)

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def start_session(self, game_id: str, difficulty: float,
                      actual_difficulty: float | None = None) -> dict:
        """
        Call when a game is about to launch.
        Returns a session dict — pass it to end_session() when done.

        Args:
            difficulty:        The difficulty the SuggestionEngine recommended.
            actual_difficulty: The difficulty written to game_config.json and
                               actually read by the game. Pass this whenever
                               available so the engine doesn't feed its own
                               suggestions as inputs (A9 fix).
        """
        session = {
            "id":                  datetime.now().isoformat(),
            "date":                date.today().isoformat(),
            "game_id":             game_id,
            "suggested_difficulty": difficulty,          # engine recommendation
            "difficulty":          actual_difficulty     # what the game received
                                   if actual_difficulty is not None
                                   else difficulty,     # fallback for callers
                                                        # not yet passing actual
            "started_at":          datetime.now().isoformat(),
            "ended_at":            None,
            "duration_seconds":    0,
            "rom":                 None,   # Filled by warmup calibration
            "pain_report":         None,   # Filled by post-session check-in
            "milestones_hit":      [],
        }
        return session

    def end_session(self, session: dict):
        """
        Call when the game subprocess exits and the launcher is restored.
        Calculates duration, updates streak, saves to log.
        """
        now = datetime.now()
        session["ended_at"] = now.isoformat()
        started = datetime.fromisoformat(session["started_at"])
        session["duration_seconds"] = int((now - started).total_seconds())

        self._log["sessions"].append(session)
        self._update_streak(session["date"])
        self._save()

    # ── Daily ROM capture (warmup) ────────────────────────────────────────────

    def record_warmup_rom(self, session: dict,
                          max_left: float, max_right: float,
                          max_up: float, max_down: float,
                          tremor: float | None = None):
        """Called after the warmup calibration flow completes."""
        from core.units import rom_record_from_axes
        session["rom"] = {
            "max_left":  round(max_left,  3),
            "max_right": round(max_right, 3),
            "max_up":    round(max_up,    3),
            "max_down":  round(max_down,  3),
            # Hand-shake factor (RMS during the neutral hold)
            "tremor":    round(tremor, 4) if tremor is not None else None,
            # Degrees record — clinical source of truth (flaw #1/#4 fix).
            "deg": {k: (round(v, 1) if isinstance(v, float) else v)
                    for k, v in rom_record_from_axes(
                        max_left, max_right, max_up, max_down).items()},
        }

    # ── Pain check-in ─────────────────────────────────────────────────────────

    def record_pain(self, session: dict, result: str):
        """
        result: "good" | "tired" | "pain"
        Called after the post-session pain check-in screen.
        """
        session["pain_report"] = result

    # ── Streak ────────────────────────────────────────────────────────────────

    def _update_streak(self, session_date_str: str):
        streak = self._log["streak"]
        today = date.today()
        last_str = streak.get("last_session_date")

        if last_str is None:
            streak["current"] = 1
        else:
            last = date.fromisoformat(last_str)
            diff = (today - last).days
            if diff == 1:
                streak["current"] += 1
            elif diff == 0:
                pass  # Multiple sessions same day — no change
            else:
                streak["current"] = 1  # Streak broken

        streak["longest"] = max(streak["longest"], streak["current"])
        streak["last_session_date"] = session_date_str

    def get_streak(self) -> int:
        return self._log["streak"]["current"]

    def get_longest_streak(self) -> int:
        return self._log["streak"]["longest"]

    # ── Today's stats ─────────────────────────────────────────────────────────

    def get_today_duration_seconds(self) -> int:
        """Total seconds played today across all sessions."""
        today = date.today().isoformat()
        return sum(
            s.get("duration_seconds", 0)
            for s in self._log["sessions"]
            if s.get("date") == today
        )

    def get_total_sessions(self) -> int:
        return len(self._log["sessions"])

    def get_all_sessions(self) -> list:
        return list(self._log["sessions"])

    # ── Last pain report ─────────────────────────────────────────────────────

    def get_last_pain_report(self) -> Optional[str]:
        sessions = self._log["sessions"]
        for s in reversed(sessions):
            if s.get("pain_report"):
                return s["pain_report"]
        return None

    # ── ROM trend ─────────────────────────────────────────────────────────────

    def get_rom_history(self) -> list[dict]:
        """Returns list of {date, max_left, max_right, max_up, max_down} for all sessions that have ROM data."""
        result = []
        for s in self._log["sessions"]:
            if s.get("rom"):
                result.append({"date": s["date"], **s["rom"]})
        return result

    def get_latest_rom(self) -> Optional[dict]:
        for s in reversed(self._log["sessions"]):
            if s.get("rom"):
                return s["rom"]
        return None

    # axis name -> anatomical direction in the "deg" record
    _AXIS_TO_ANATOMY = {
        "right": "pronation",  "left": "supination",
        "down":  "flexion",    "up":   "extension",
    }

    def get_rom_improvement_pct(self, axis: str) -> Optional[float]:
        """
        Returns % improvement on a given axis vs baseline.
        axis: "right" | "left" | "up" | "down"
        Returns None if insufficient data.

        Compares DEGREES when both records carry a "deg" block (flaw #12 fix):
        normalised values are relative to whatever range limits the controller
        had loaded at capture time, so they aren't comparable across sessions
        once per-patient limits are in use. Degrees always are.
        """
        baseline = self._log.get("baseline_rom")
        latest = self.get_latest_rom()
        if not baseline or not latest:
            return None

        anatomy = self._AXIS_TO_ANATOMY[axis]
        b_deg = (baseline.get("deg") or {}).get(anatomy)
        c_deg = (latest.get("deg")   or {}).get(anatomy)
        if b_deg and c_deg is not None:
            if b_deg == 0:
                return None
            return round(((c_deg - b_deg) / b_deg) * 100, 1)

        # Fallback for old logs without degree records (pre-deg_v1) —
        # only valid while both were captured under the same limits.
        key = f"max_{axis}"
        b = abs(baseline.get(key, 0))
        c = abs(latest.get(key, 0))
        if b == 0:
            return None
        return round(((c - b) / b) * 100, 1)

    # ── Milestones ───────────────────────────────────────────────────────────

    def has_milestone(self, milestone_id: str) -> bool:
        return milestone_id in self._log["milestones"]

    def award_milestone(self, milestone_id: str, session: dict):
        if milestone_id not in self._log["milestones"]:
            self._log["milestones"].append(milestone_id)
            session["milestones_hit"].append(milestone_id)
            self._save()

    def get_milestones(self) -> list[str]:
        return list(self._log["milestones"])

    # ── Journey state ─────────────────────────────────────────────────────────

    def get_journey(self) -> dict:
        return dict(self._log["journey"])

    def update_journey(self, **kwargs):
        """Update journey state fields. E.g. update_journey(phase=2, target_weakness="y")"""
        self._log["journey"].update(kwargs)
        self._save()

    # ── Consent flag ─────────────────────────────────────────────────────────

    @staticmethod
    def is_consented() -> bool:
        from core.paths import get_data_dir
        path = os.path.join(get_data_dir(), "global_settings.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("consented", False)
        except Exception:
            return False

    @staticmethod
    def save_consent():
        from core.paths import get_data_dir
        path = os.path.join(get_data_dir(), "global_settings.json")
        settings = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except Exception:
            pass
        settings["consented"] = True
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
