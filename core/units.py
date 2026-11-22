"""
units — single source of truth for converting controller axis values to
anatomical angles in degrees.

The firmware (Solace_Gamepad_v5) normalises each movement direction to its
own measured healthy-ROM limit before sending it as a joystick axis, so a
raw axis value of +1.0 on Y means "at the flexion limit", not a fixed angle.
Everything that stores or displays clinical ROM must go through this module
so the numbers are always degrees, and always tagged with the limits they
were derived from.

IMPORTANT: these constants MUST match the firmware's per-direction limits.
If the firmware is re-captured/re-flashed with new limits, update them here
(and old stored baselines remain valid because they carry their own copy).
"""

# Per-direction limits (degrees) — the firmware's DEFAULTS (healthy reference).
FIRMWARE_LIMITS = {
    "flexion":    50.0,   # axis Y positive
    "extension":  43.0,   # axis Y negative
    "pronation":  63.0,   # axis X positive
    "supination": 72.0,   # axis X negative
}

# ACTIVE limits — what the controller is currently mapping full deflection to.
# Firmware v6 accepts per-patient limits at runtime ('L' serial command); when
# the launcher sends them it MUST also call set_active_limits() so every
# axis→degree conversion stays truthful.
_ACTIVE_LIMITS = dict(FIRMWARE_LIMITS)


def set_active_limits(limits: dict):
    """Update the limits used for conversion (after sending 'L' to firmware)."""
    global _ACTIVE_LIMITS
    _ACTIVE_LIMITS = {k: float(limits.get(k, FIRMWARE_LIMITS[k]))
                      for k in FIRMWARE_LIMITS}


def get_active_limits() -> dict:
    return dict(_ACTIVE_LIMITS)


def reset_active_limits():
    global _ACTIVE_LIMITS
    _ACTIVE_LIMITS = dict(FIRMWARE_LIMITS)


# Units/version tag written next to any stored ROM record.
ROM_UNITS_VERSION = "deg_v1"


def _clamp(v: float) -> float:
    return max(-1.0, min(1.0, v))


def axis_to_degrees(raw_x: float, raw_y: float) -> tuple[float, float]:
    """
    (raw_x, raw_y) in [-1, 1]  ->  (pronsup_deg, flex_deg)

    pronsup_deg: + = pronation, - = supination
    flex_deg   : + = flexion,   - = extension
    """
    x = _clamp(raw_x)
    y = _clamp(raw_y)
    pronsup_deg = x * (_ACTIVE_LIMITS["pronation"] if x >= 0
                       else _ACTIVE_LIMITS["supination"])
    flex_deg    = y * (_ACTIVE_LIMITS["flexion"] if y >= 0
                       else _ACTIVE_LIMITS["extension"])
    return pronsup_deg, flex_deg


def x_axis_to_degrees(raw_x: float) -> float:
    """Pronation(+)/supination(-) degrees from the X axis."""
    return axis_to_degrees(raw_x, 0.0)[0]


def y_axis_to_degrees(raw_y: float) -> float:
    """Flexion(+)/extension(-) degrees from the Y axis."""
    return axis_to_degrees(0.0, raw_y)[1]


def rom_record_from_axes(max_left: float, max_right: float,
                         max_up: float, max_down: float) -> dict:
    """
    Convert warmup-style normalised extremes (axis units, magnitudes 0..1)
    into a degrees-based anatomical ROM record.

    Axis convention (firmware v5): X+ = pronation, X- = supination,
                                   Y+ = flexion,   Y- = extension.
    'left/right/up/down' follow the launcher's reading of X/Y:
      right = X+, left = X-, down = Y+, up = Y-  (screen direction of Y+ is
      down in the launcher's navigation mapping).
    """
    return {
        "units": ROM_UNITS_VERSION,
        "firmware_limits": dict(_ACTIVE_LIMITS),
        "pronation":  abs(max_right) * _ACTIVE_LIMITS["pronation"],
        "supination": abs(max_left)  * _ACTIVE_LIMITS["supination"],
        "flexion":    abs(max_down)  * _ACTIVE_LIMITS["flexion"],
        "extension":  abs(max_up)    * _ACTIVE_LIMITS["extension"],
    }
