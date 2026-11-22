"""
movement_prompts — the ONE place patient-facing movement instructions live.

Both the daily warmup (CalibrationWarmup) and the first-launch assessment
(AssessmentWizard) read from here, so the icon and the sentence for a given
movement are always identical everywhere in the app.

Translations come from core/i18n (M5 fix) — English + Hindi.

Mirroring (M4 fix): when the patient's axis is flipped (left-hand grip), a
movement's physical direction is exactly its PARTNER movement's direction
(flexion↔extension, pronation↔supination) — so mirrored words are simply the
partner's words. This works in every language with zero string surgery.

Axis convention (firmware v5+): Y+ = flexion, Y- = extension,
                                X+ = pronation, X- = supination.
NOTE: direction words verified against the real device 2026-07-06.
"""
from core.i18n import t

_ICONS = {
    "flexion": "↺", "extension": "↻",
    "pronation": "➡️", "supination": "⬅️",
    "neutral": "⭕",
}

_MIRROR_MOVE = {
    "flexion": "extension", "extension": "flexion",
    "pronation": "supination", "supination": "pronation",
    "neutral": "neutral",
}

# which flip setting mirrors which movement
MOVEMENT_FLIP_AXIS = {
    "flexion": "y", "extension": "y",
    "pronation": "x", "supination": "x",
    "neutral": None,
}

# warmup axis-direction names -> movement
DIRECTION_TO_MOVEMENT = {
    "down": "flexion", "up": "extension",
    "right": "pronation", "left": "supination",
    "neutral": "neutral",
}

# Legacy compat: static English prompts (module-level consumers only use
# this for lengths/defaults; live UI goes through icon()/two_line()).
PROMPTS = {
    m: (_ICONS[m], t(f"mp_{m}_main"), t(f"mp_{m}_hint"))
    for m in _ICONS
}


def _effective(movement: str, mirrored: bool) -> str:
    return _MIRROR_MOVE[movement] if mirrored else movement


def icon(movement: str, mirrored: bool = False) -> str:
    return _ICONS[_effective(movement, mirrored)]


def two_line(movement: str, mirrored: bool = False) -> str:
    """'Twist the handle to the LEFT\\n(like turning a key)' — translated."""
    eff = _effective(movement, mirrored)
    return f"{t(f'mp_{eff}_main')}\n({t(f'mp_{movement}_hint')})"


def is_mirrored(movement: str, processor) -> bool:
    """Whether this movement's words should mirror for the given profile."""
    if processor is None:
        return False
    axis = MOVEMENT_FLIP_AXIS.get(movement)
    if axis == "x":
        return bool(getattr(processor, "flip_x", False))
    if axis == "y":
        return bool(getattr(processor, "flip_y", False))
    return False
