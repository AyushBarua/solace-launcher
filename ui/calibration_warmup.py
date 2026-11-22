"""
CalibrationWarmup — pre-session warmup + daily ROM capture.

Shown automatically before every game launch. Guides the patient through
5 directional movements, recording the maximum range on each axis.
Data is stored on the active session object via SessionManager.

The flow takes ~45 seconds. A skip option appears after 10 seconds.
"""
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QProgressBar, QApplication
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor

from core.theme import (
    FONT_DISPLAY, FONT_BODY, ON_SURFACE, ON_SURFACE_VAR,
    PRIMARY_CONTAINER, SURFACE_DIM, OUTLINE_VARIANT,
    SURFACE_CON_LOW, BACKGROUND, PRIMARY_FIXED,
    ON_PRIMARY_FIXED_VARIANT
)
try:
    from ui.controller_3d_view import Controller3DView as _Controller3D
    _WEB_VIEW = True
except ImportError:
    from ui.controller_3d_widget import Controller3DWidget as _Controller3D
    _WEB_VIEW = False


# Prompts come from ui/movement_prompts.py — the SAME icon and wording the
# AssessmentWizard uses, in the SAME order (flexion → extension → pronation →
# supination → neutral). The 3D model demonstrates each movement first.
from ui.movement_prompts import PROMPTS as _P, DIRECTION_TO_MOVEMENT as _D2M

def _seq_entry(direction: str):
    m = _D2M[direction]
    return (_P[m][0], f"{_P[m][1]}\n({_P[m][2]})", direction)

# Neutral comes FIRST: the device is re-tared while the patient holds still
# (H2 fix), and the tremor sample is collected at the same time.
# Default sequence — instances rebuild it with per-profile mirroring (M4).
SEQUENCE = [
    _seq_entry("neutral"),
    _seq_entry("down"),     # flexion
    _seq_entry("up"),       # extension
    _seq_entry("right"),    # pronation
    _seq_entry("left"),     # supination
]


def build_sequence(processor):
    """Per-profile sequence: words/arrows mirror when axes are flipped (M4)."""
    from ui.movement_prompts import icon, two_line, is_mirrored
    seq = []
    for _, _, direction in SEQUENCE:
        m = _D2M[direction]
        mir = is_mirrored(m, processor)
        seq.append((icon(m, mir), two_line(m, mir), direction))
    return seq

HOLD_FRAMES = 50   # ~2.5s at 20fps poll


def _tremor_rms(samples: list) -> float:
    """RMS deviation from the mean position — the hand-shake factor."""
    import math
    if len(samples) < 10:
        return 0.0
    mx = sum(s[0] for s in samples) / len(samples)
    my = sum(s[1] for s in samples) / len(samples)
    return round(math.sqrt(sum((x - mx) ** 2 + (y - my) ** 2
                               for x, y in samples) / len(samples)), 4)


class CalibrationWarmup(QDialog):
    """
    Call .exec() before launching a game.
    If accepted → read .rom_data for (max_left, max_right, max_up, max_down).
    """

    def __init__(self, processor=None, parent=None):
        super().__init__(parent)
        self._processor = processor   # InputProcessor — used to apply cal offset
        # M4: per-profile prompt wording (mirrors with axis flips)
        self._sequence = build_sequence(processor)
        self.rom_data = (0.0, 0.0, 0.0, 0.0)   # populated on completion
        self.completed = False   # True only via _finish (NOT _skip). Distinguishes
                                 # a real warmup — even a zero-ROM one for an impaired
                                 # hand — from a skip, so the daily gate unlocks.
        self._raw = (0.0, 0.0)
        self._step = 0
        self._hold = 0
        self._elapsed = 0               # frames spent on the current step
        self._closing = False           # guards teardown against late signals
        self._readings = {"left": 0.0, "right": 0.0, "up": 0.0, "down": 0.0}
        self._skip_unlocked = False
        self._tremor_samples: list = []   # (x, y) collected in the neutral step
        self.tremor_level = 0.0           # RMS hand-shake, populated on finish

        self.setWindowTitle("Solace — Warmup")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        screen = QApplication.primaryScreen().availableGeometry()
        self.setFixedSize(screen.width(), screen.height())
        self.setStyleSheet(f"background: {BACKGROUND};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top label ─────────────────────────────────────────────────────────
        top_bar = QWidget()
        top_bar.setFixedHeight(56)
        top_bar.setStyleSheet(f"background: {SURFACE_CON_LOW};")
        top_l = QHBoxLayout(top_bar)
        top_l.setContentsMargins(48, 0, 48, 0)
        top_lbl = QLabel("Daily Warmup & Measurement")
        top_lbl.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 18px; font-weight: bold; background: transparent;"
        )
        top_l.addWidget(top_lbl)
        top_l.addStretch()
        root.addWidget(top_bar)

        # ── Centre content ─────────────────────────────────────────────────────
        centre = QWidget()
        centre_l = QVBoxLayout(centre)
        centre_l.setContentsMargins(0, 0, 0, 0)
        centre_l.setSpacing(0)

        # Step counter dots
        dots_row = QHBoxLayout()
        dots_row.setSpacing(10)
        dots_row.addStretch()
        self._dots = []
        for _ in SEQUENCE:
            d = QFrame()
            d.setFixedSize(12, 12)
            d.setStyleSheet(f"background: {OUTLINE_VARIANT}; border-radius: 6px;")
            self._dots.append(d)
            dots_row.addWidget(d)
        dots_row.addStretch()

        # Main card — selector scoped so the border doesn't cascade onto labels
        self._card = QFrame()
        self._card.setObjectName("warmupCard")
        self._card.setFixedWidth(860)
        self._card.setFixedHeight(260)
        self._card.setStyleSheet(f"""
            QFrame#warmupCard {{
                background: {SURFACE_CON_LOW}; border-radius: 28px;
                border: 1px solid {OUTLINE_VARIANT};
            }}
            QFrame#warmupCard QLabel {{ border: none; background: transparent; }}
        """)
        card_l = QVBoxLayout(self._card)
        card_l.setContentsMargins(40, 32, 40, 32)
        card_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_l.setSpacing(12)

        self._icon_lbl = QLabel("⬅️")
        self._icon_lbl.setStyleSheet("font-size: 64px; background: transparent;")
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._inst_lbl = QLabel()
        self._inst_lbl.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 26px; font-weight: bold; background: transparent;"
        )
        self._inst_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._inst_lbl.setWordWrap(True)

        self._hold_bar = QProgressBar()
        self._hold_bar.setRange(0, HOLD_FRAMES)
        self._hold_bar.setValue(0)
        self._hold_bar.setFixedHeight(12)
        self._hold_bar.setTextVisible(False)
        self._hold_bar.setStyleSheet(f"""
            QProgressBar {{ background: {SURFACE_DIM}; border-radius: 6px; border: none; }}
            QProgressBar::chunk {{ background: {PRIMARY_CONTAINER}; border-radius: 6px; }}
        """)

        card_l.addWidget(self._icon_lbl)
        card_l.addWidget(self._inst_lbl)
        card_l.addSpacing(8)
        card_l.addWidget(self._hold_bar)

        card_wrapper = QHBoxLayout()
        card_wrapper.addStretch()
        card_wrapper.addWidget(self._card)
        card_wrapper.addStretch()

        # Skip button (hidden for first 10 seconds)
        self._skip_btn = QPushButton("Skip warmup")
        self._skip_btn.setFixedHeight(48)
        self._skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip_btn.setVisible(False)
        self._skip_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {ON_SURFACE_VAR};
                border: 1px solid {OUTLINE_VARIANT};
                border-radius: 12px;
                padding: 0 28px;
                font-family: '{FONT_DISPLAY}';
                font-size: 15px;
            }}
            QPushButton:hover {{ background: {SURFACE_DIM}; }}
        """)
        self._skip_btn.clicked.connect(self._skip)
        skip_row = QHBoxLayout()
        skip_row.addStretch()
        skip_row.addWidget(self._skip_btn)
        skip_row.addStretch()

        # 3D controller preview — big enough to actually follow the demo
        self._3d_widget = _Controller3D()
        self._3d_widget.setFixedHeight(340 if _WEB_VIEW else 200)
        self._3d_widget.setFixedWidth(860)

        preview_wrapper = QHBoxLayout()
        preview_wrapper.addStretch()
        preview_wrapper.addWidget(self._3d_widget)
        preview_wrapper.addStretch()

        centre_l.addStretch()
        centre_l.addLayout(dots_row)
        centre_l.addSpacing(12)
        centre_l.addLayout(preview_wrapper)
        centre_l.addSpacing(12)
        centre_l.addLayout(card_wrapper)
        centre_l.addSpacing(24)
        centre_l.addLayout(skip_row)
        centre_l.addStretch()

        root.addWidget(centre, stretch=1)

        # ── Timers ─────────────────────────────────────────────────────────────
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(50)  # 20fps

        # Unlock skip after 4 seconds (was 10 — patients who can't reach a
        # direction shouldn't be trapped for long)
        QTimer.singleShot(4000, self._unlock_skip)

        self._update_card()

    def update_raw_axes(self, x: float, y: float):
        """Feed live controller data in. Applies calibration offset if processor is set."""
        if self._closing:
            return
        if self._processor is not None:
            x = x - self._processor.cal_x
            y = y - self._processor.cal_y
        self._raw = (x, y)
        self._3d_widget.update_axes(x, y)

    def _update_card(self):
        icon, text, direction = self._sequence[self._step]
        self._icon_lbl.setText(icon)
        self._inst_lbl.setText(text)
        self._hold_bar.setValue(0)
        self._hold = 0
        # 3D model demonstrates the movement so the direction is unmistakable.
        # Capture and the step timer wait until the demo finishes.
        if direction != "neutral" and hasattr(self._3d_widget, "play_demo"):
            self._demo_wait = 52          # 2.6 s at 20 fps
            self._3d_widget.play_demo(direction, 2.6)
        else:
            self._demo_wait = 0
            # H2 fix: hardware tare while the patient holds still in neutral
            import threading
            def _tare():
                try:
                    from core.device_link import send_retare
                    send_retare()
                except Exception as exc:
                    print(f"[Warmup] tare failed: {exc}")
            threading.Thread(target=_tare, daemon=True).start()
        for i, dot in enumerate(self._dots):
            if i == self._step:
                dot.setStyleSheet(f"background: {PRIMARY_CONTAINER}; border-radius: 6px;")
            elif i < self._step:
                dot.setStyleSheet("background: #27c93f; border-radius: 6px;")
            else:
                dot.setStyleSheet(f"background: {OUTLINE_VARIANT}; border-radius: 6px;")

    def _poll(self):
        if self._closing:
            return
        # Wait for the 3D demonstration before capturing / timing the step
        if getattr(self, "_demo_wait", 0) > 0:
            self._demo_wait -= 1
            return
        x, y = self._raw
        direction = self._sequence[self._step][2]

        # Small floor so sensor noise at neutral can't auto-complete a step,
        # but ANY genuine effort past it counts — a patient does NOT need to
        # reach some fixed large angle. Their own reachable max is the target.
        MOVE_FLOOR = 0.04
        self._elapsed += 1

        # value in the step's direction (positive = moving the right way)
        if direction == "left":
            val = -x
        elif direction == "right":
            val = x
        elif direction == "up":
            val = -y
        elif direction == "down":
            val = y
        else:               # neutral
            val = 0.0

        if direction != "neutral":
            key = direction
            if val > self._readings[key]:
                self._readings[key] = val            # record peak reached
            peak = self._readings[key]
            # "Holding at their limit" = at/above the floor AND within 75% of
            # the best they've shown this step. Works for weak ROM patients
            # whose limit is well below the old 0.15 threshold.
            holding = peak >= MOVE_FLOOR and val >= min(peak * 0.75, peak - 0.02)
        else:
            holding = abs(x) < 0.10 and abs(y) < 0.10
            self._tremor_samples.append((x, y))   # measure shake while "still"

        if holding:
            self._hold += 1
        else:
            self._hold = max(0, self._hold - 1)      # decay if they drift off
        self._hold_bar.setValue(self._hold)

        # Advance when held long enough OR after a hard per-step timeout so the
        # flow can NEVER get stuck (captures whatever peak was reached).
        STEP_TIMEOUT = 240   # ~12 s at 20 fps
        if self._hold >= HOLD_FRAMES or self._elapsed >= STEP_TIMEOUT:
            self._advance_step()

    def _advance_step(self):
        self._step += 1
        self._elapsed = 0
        if self._step >= len(SEQUENCE):
            self._finish()
        else:
            self._update_card()

    def _finish(self):
        self._closing = True
        self.completed = True
        self._poll_timer.stop()
        self.tremor_level = _tremor_rms(self._tremor_samples)
        r = self._readings
        self.rom_data = (
            -r["left"],   # max_left  (negative X)
             r["right"],  # max_right (positive X)
            -r["up"],     # max_up    (negative Y)
             r["down"],   # max_down  (positive Y)
        )

        # Brief success flash
        self._card.setStyleSheet(
            "background: rgba(39,201,63,0.12); border-radius: 28px; "
            "border: 1px solid #27c93f;"
        )
        self._icon_lbl.setText("")
        self._inst_lbl.setText("Warmup complete!\nLet's play!")
        QTimer.singleShot(1200, self.accept)

    def _skip(self):
        # Guard against late gamepad signals hitting a tearing-down dialog.
        self._closing = True
        self._poll_timer.stop()
        self.rom_data = (0.0, 0.0, 0.0, 0.0)
        self.accept()

    def _unlock_skip(self):
        if self._closing:
            return
        self._skip_btn.setVisible(True)
