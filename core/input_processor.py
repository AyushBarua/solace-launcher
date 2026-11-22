"""
InputProcessor — pure data transformation layer between raw axis values
(from any device) and normalised direction events.

Pipeline per poll tick:
  raw (x, y)
    → subtract calibration offset
    → apply sensitivity scale
    → apply dead-zone (inner + outer)
    → flip axes if configured
    → map to direction string | None
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_HERE, "..", "input_config.json")

_DEFAULTS = {
    "inner_dead_zone": 0.08,   # ignore movement smaller than this (analog cleanliness)
    "outer_dead_zone": 0.95,   # clamp anything beyond this to ±1
    "sensitivity": 1.0,        # multiplier applied before dead-zone
    "nav_threshold": 0.5,      # deflection needed to trigger MENU NAVIGATION.
                               # Separate from dead-zone: nav needs a confident
                               # push, not the first twitch past the dead-zone.
    "flip_x": False,           # invert left/right
    "flip_y": False,           # invert up/down
    "cal_x": 0.0,              # calibration offset X
    "cal_y": 0.0,              # calibration offset Y
}


class InputProcessor:
    """Stateless processing of raw joystick/IMU axis values.

    Config is PER-PROFILE (H3 fix): flips (left/right hand!), sensitivity,
    nav threshold, dead-zone and calibration belong to a patient, not the
    machine. Files live in the data dir as input_config_<profile>.json;
    a missing per-profile file is seeded from the legacy global config.
    """

    def __init__(self, profile_id: str | None = None):
        self._profile_id = profile_id or "default"
        self._cfg: dict = dict(_DEFAULTS)
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _profile_path(self) -> str:
        from core.paths import get_data_dir
        safe = "".join(c for c in self._profile_id if c.isalnum() or c in "-_")
        return os.path.join(get_data_dir(), f"input_config_{safe or 'default'}.json")

    def set_profile(self, profile_id: str):
        """Switch to another patient's input settings (profile change)."""
        self._profile_id = profile_id or "default"
        self._cfg = dict(_DEFAULTS)
        self._load()
        print(f"[InputProcessor] Loaded input config for profile {self._profile_id}")

    def _load(self):
        path = self._profile_path()
        if not os.path.exists(path) and os.path.exists(_CONFIG_PATH):
            path = _CONFIG_PATH          # seed from legacy global config
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    saved = json.load(fh)
                self._cfg.update(saved)
            except Exception as exc:
                print(f"[InputProcessor] Could not load config: {exc}")

    def save(self):
        try:
            with open(self._profile_path(), "w", encoding="utf-8") as fh:
                json.dump(self._cfg, fh, indent=2)
        except Exception as exc:
            print(f"[InputProcessor] Could not save config: {exc}")

    # ── property accessors (used by Settings UI) ──────────────────────────────

    @property
    def inner_dead_zone(self) -> float:
        return self._cfg["inner_dead_zone"]

    @inner_dead_zone.setter
    def inner_dead_zone(self, v: float):
        self._cfg["inner_dead_zone"] = max(0.0, min(0.9, v))

    @property
    def sensitivity(self) -> float:
        return self._cfg["sensitivity"]

    @sensitivity.setter
    def sensitivity(self, v: float):
        self._cfg["sensitivity"] = max(0.1, min(3.0, v))

    @property
    def nav_threshold(self) -> float:
        return self._cfg["nav_threshold"]

    @nav_threshold.setter
    def nav_threshold(self, v: float):
        self._cfg["nav_threshold"] = max(0.15, min(0.9, v))

    @property
    def flip_x(self) -> bool:
        return self._cfg["flip_x"]

    @flip_x.setter
    def flip_x(self, v: bool):
        self._cfg["flip_x"] = bool(v)

    @property
    def flip_y(self) -> bool:
        return self._cfg["flip_y"]

    @flip_y.setter
    def flip_y(self, v: bool):
        self._cfg["flip_y"] = bool(v)

    @property
    def cal_x(self) -> float:
        return self._cfg["cal_x"]

    @property
    def cal_y(self) -> float:
        return self._cfg["cal_y"]

    # ── calibration ───────────────────────────────────────────────────────────

    def calibrate(self, raw_x: float, raw_y: float):
        """Capture current raw position as the new neutral (zero) point."""
        self._cfg["cal_x"] = raw_x
        self._cfg["cal_y"] = raw_y
        self.save()
        print(f"[InputProcessor] Calibrated neutral: ({raw_x:.3f}, {raw_y:.3f})")

    def reset_calibration(self):
        self._cfg["cal_x"] = 0.0
        self._cfg["cal_y"] = 0.0
        self.save()

    # ── core processing ───────────────────────────────────────────────────────

    def process(self, raw_x: float, raw_y: float, apply_deadzone: bool = True) -> tuple[float, float, str | None]:
        """
        Transform raw axis values into (norm_x, norm_y, direction | None).

        norm_x/norm_y are post-processed values in [-1, 1] for live preview.
        direction is 'up' | 'down' | 'left' | 'right' | None.
        """
        # 1. Subtract calibration offset
        x = raw_x - self._cfg["cal_x"]
        y = raw_y - self._cfg["cal_y"]

        # 2. Apply sensitivity
        x *= self._cfg["sensitivity"]
        y *= self._cfg["sensitivity"]

        # 3. Clamp to [-1, 1]
        x = max(-1.0, min(1.0, x))
        y = max(-1.0, min(1.0, y))

        # 4. Apply axis flips
        if self._cfg["flip_x"]:
            x = -x
        if self._cfg["flip_y"]:
            y = -y

        # 5. Dead-zone (optional for continuous gameplay)
        if apply_deadzone:
            idz = self._cfg["inner_dead_zone"]
            odz = self._cfg["outer_dead_zone"]
            
            def _dz(v):
                av = abs(v)
                if av < idz:
                    return 0.0
                if av > odz:
                    return 1.0 if v > 0 else -1.0
                # Rescale from [idz, odz] → [0, 1]
                return ((av - idz) / (odz - idz)) * (1.0 if v > 0 else -1.0)
                
            nx = _dz(x)
            ny = _dz(y)
        else:
            nx = x
            ny = y

        # 6. Map to direction (dominant axis wins). Navigation requires a
        #    CONFIDENT deflection (nav_threshold), not just crossing the
        #    dead-zone — fixes hair-trigger menu navigation.
        thr = self._cfg["nav_threshold"]
        direction = None
        if abs(nx) >= thr or abs(ny) >= thr:
            if abs(nx) >= abs(ny):
                direction = "right" if nx > 0 else "left"
            else:
                direction = "down" if ny > 0 else "up"

        return nx, ny, direction
