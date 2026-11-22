"""
patient_model — computes the patient's current state from recorded data.

Everything the recommendation engine needs, derived fresh from the
SessionManager log each time it's asked:

  ability(sm)        per-direction ability ratio vs the healthy reference
                     (median of the last 3 warmup readings, so one bad or
                     lucky day doesn't swing recommendations)
  trends(sm)         per-direction improvement slope (deg/session) over the
                     recent warmups + classification:
                     "improving" | "plateau" | "declining" | "unknown"
  improvement_pct(sm) per-direction % change vs the assessment baseline
  pain_rate(sm)      fraction of recent sessions reporting pain
  tremor_latest(sm)  most recent hand-shake RMS (and baseline value)
  game_stats(sm)     per-game: plays, last-played session index, avg duration

All angles are DEGREES via the per-record "deg" blocks (units-safe across
firmware limit changes). Legacy records without "deg" are converted assuming
healthy limits — correct for data captured before per-patient limits existed.
"""
from typing import Optional
from core.units import FIRMWARE_LIMITS as HEALTHY

DIRECTIONS = ("flexion", "extension", "pronation", "supination")

# legacy normalised keys -> direction (sign conventions of old records)
_LEGACY = {"flexion": "max_down", "extension": "max_up",
           "pronation": "max_right", "supination": "max_left"}


def _deg_from_record(rom: dict) -> Optional[dict]:
    """Extract a per-direction degrees dict from a rom record (any era)."""
    if not rom:
        return None
    deg = rom.get("deg")
    if deg:
        return {d: float(deg.get(d, 0.0) or 0.0) for d in DIRECTIONS}
    # Legacy: normalised values, assume healthy limits
    return {d: abs(rom.get(_LEGACY[d], 0.0) or 0.0) * HEALTHY[d]
            for d in DIRECTIONS}


def direction_series(sm) -> dict:
    """{direction: [deg, deg, …]} in session order (baseline first if present)."""
    series = {d: [] for d in DIRECTIONS}
    baseline = _deg_from_record(sm.get_baseline_rom() or {})
    if baseline and any(baseline.values()):
        for d in DIRECTIONS:
            series[d].append(baseline[d])
    for s in sm.get_all_sessions():
        deg = _deg_from_record(s.get("rom"))
        if deg and any(deg.values()):
            for d in DIRECTIONS:
                series[d].append(deg[d])
    return series


def _median(vals):
    v = sorted(vals)
    n = len(v)
    if n == 0:
        return 0.0
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def ability(sm) -> dict:
    """
    Per-direction ability ratio 0..1+ vs the healthy reference, from the
    median of the last 3 readings. Also returns "overall" (mean) and
    "weakest"/"strongest" direction names. Directions with no data get None.
    """
    series = direction_series(sm)
    out = {}
    vals = []
    for d in DIRECTIONS:
        pts = series[d][-3:]
        if pts:
            r = _median(pts) / HEALTHY[d]
            out[d] = round(r, 3)
            vals.append(r)
        else:
            out[d] = None
    out["overall"] = round(sum(vals) / len(vals), 3) if vals else None
    known = {d: out[d] for d in DIRECTIONS if out[d] is not None}
    out["weakest"]   = min(known, key=known.get) if known else None
    out["strongest"] = max(known, key=known.get) if known else None
    return out


def _slope(points: list) -> float:
    """Least-squares slope of points vs their index (units per session)."""
    n = len(points)
    if n < 3:
        return 0.0
    xs = range(n)
    mx = (n - 1) / 2
    my = sum(points) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, points))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


def trends(sm, window: int = 8) -> dict:
    """
    Per-direction: {"slope": deg/session, "cls": improving|plateau|declining|unknown}
    over the last `window` readings. Thresholds relative to the healthy
    reference so 0.3%/session of the reference counts as real movement.
    """
    series = direction_series(sm)
    out = {}
    for d in DIRECTIONS:
        pts = series[d][-window:]
        if len(pts) < 3:
            out[d] = {"slope": 0.0, "cls": "unknown", "n": len(pts)}
            continue
        sl = _slope(pts)
        thresh = HEALTHY[d] * 0.003          # 0.3% of reference per session
        cls = ("improving" if sl > thresh else
               "declining" if sl < -thresh else "plateau")
        out[d] = {"slope": round(sl, 3), "cls": cls, "n": len(pts)}
    return out


def improvement_pct(sm) -> dict:
    """Per-direction % change of current ability vs the baseline reading."""
    series = direction_series(sm)
    baseline = _deg_from_record(sm.get_baseline_rom() or {})
    out = {}
    for d in DIRECTIONS:
        pts = series[d][-3:]
        if not baseline or not pts or baseline[d] <= 0:
            out[d] = None
            continue
        out[d] = round((_median(pts) - baseline[d]) / baseline[d] * 100, 1)
    return out


def pain_rate(sm, last_n: int = 5) -> float:
    """Fraction of the last N sessions that reported pain."""
    sessions = sm.get_all_sessions()[-last_n:]
    if not sessions:
        return 0.0
    painful = sum(1 for s in sessions if s.get("pain_report") == "pain")
    return round(painful / len(sessions), 2)


def tremor_latest(sm) -> dict:
    """{"latest": rms | None, "baseline": rms | None}"""
    latest = None
    for s in reversed(sm.get_all_sessions()):
        t = (s.get("rom") or {}).get("tremor")
        if t is not None:
            latest = t
            break
    base = (sm.get_baseline_rom() or {}).get("tremor")
    return {"latest": latest, "baseline": base}


def game_stats(sm) -> dict:
    """
    {game_id: {"plays": int, "last_idx": int, "avg_duration": s, "share": 0..1}}
    last_idx counts back from the most recent session (0 = last played).
    """
    sessions = sm.get_all_sessions()
    total = len(sessions)
    out: dict = {}
    for i, s in enumerate(sessions):
        gid = s.get("game_id")
        if not gid:
            continue
        st = out.setdefault(gid, {"plays": 0, "durations": [], "last_idx": None})
        st["plays"] += 1
        st["durations"].append(s.get("duration_seconds", 0))
        st["last_idx"] = total - 1 - i
    for gid, st in out.items():
        st["avg_duration"] = (sum(st["durations"]) // len(st["durations"])
                              if st["durations"] else 0)
        st["share"] = round(st["plays"] / total, 3) if total else 0.0
        del st["durations"]
    return out
