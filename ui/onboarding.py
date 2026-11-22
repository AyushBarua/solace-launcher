"""
OnboardingFlow — shown once per new profile immediately after creation.

4-step sequence:
  Step 1: Welcome
  Step 2: Device connection (optional — patient can skip)
  Step 3: Learn your device (only if connected)
  Step 4: Baseline calibration / ROM capture (only if connected)

If device is skipped → patient lands on Home Screen with a soft banner.
Steps 3 & 4 auto-unlock the moment a device is detected (even mid-flow).
"""
import os
import sys
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QStackedWidget, QApplication,
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal, QThread
)
from PyQt6.QtGui import QColor, QFont

from core.theme import (
    FONT_DISPLAY, FONT_BODY, ON_SURFACE, ON_SURFACE_VAR,
    PRIMARY_CONTAINER, PRIMARY_FIXED, SURFACE_DIM, OUTLINE_VARIANT,
    ON_PRIMARY_FIXED_VARIANT, SURFACE_CON, SURFACE_CON_LOW, BACKGROUND
)
from core.session_manager import SessionManager
from core.i18n import t, set_language, get_language, i18n as _i18n_hub
from core.theme import PRIMARY, ON_PRIMARY
from ui import glass as _g


# ── Helpers ───────────────────────────────────────────────────────────────────

def _btn_primary(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedHeight(54)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: {PRIMARY};
            color: {ON_PRIMARY};
            border: none;
            border-radius: 27px;
            padding: 0 40px;
            font-family: '{FONT_DISPLAY}';
            font-size: 17px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background: {_g.hover_ink()};
        }}
    """)
    return btn


def _btn_secondary(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedHeight(54)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: transparent;
            color: {ON_SURFACE_VAR};
            border: 1px solid {OUTLINE_VARIANT};
            border-radius: 27px;
            padding: 0 32px;
            font-family: '{FONT_DISPLAY}';
            font-size: 16px;
        }}
        QPushButton:hover {{
            background: {SURFACE_DIM};
            color: {ON_SURFACE};
            border-color: {ON_SURFACE_VAR};
        }}
    """)
    return btn


def _label(text: str, size: int = 18, bold: bool = False,
           color: str = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    col = color or ON_SURFACE
    weight = "bold" if bold else "normal"
    lbl.setStyleSheet(
        f"color: {col}; font-family: '{FONT_DISPLAY}'; "
        f"font-size: {size}px; font-weight: {weight}; background: transparent;"
    )
    if wrap:
        lbl.setWordWrap(True)
    return lbl


# ── Step 0: Language Selection ──────────────────────────────────────────────────────────

class _StepLanguage(QWidget):
    """Full-bleed language picker — shown once, before Welcome."""
    proceed = pyqtSignal()

    _LANGS = [
        ("en", "English", "\U0001f1ec\U0001f1e7", "Continue →"),
        ("hi", "\u0939\u093f\u0902\u0926\u0940",  "\U0001f1ee\U0001f1f3", "\u091c\u093e\u0930\u0940 \u0930\u0916\u0947\u0902 \u2192"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected = get_language()   # pre-select saved language
        self._cards    = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch()

        # Heading
        globe = QLabel("\U0001f310")
        globe.setStyleSheet("font-size:64px; background:transparent;")
        globe.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(globe)
        layout.addSpacing(20)

        title = QLabel("Choose Your Language  /  \u0905\u092a\u0928\u0940 \u092d\u093e\u0937\u093e \u091a\u0941\u0928\u0947\u0902")
        title.setStyleSheet(
            f"color:{ON_SURFACE}; font-family:'{FONT_DISPLAY}'; "
            "font-size:28px; font-weight:bold; background:transparent;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)
        layout.addSpacing(12)

        sub = QLabel("You can change this later in Settings  /  \u0906\u092a \u0907\u0938\u0947 \u0938\u0947\u091f\u093f\u0902\u0917\u094d\u0938 \u092e\u0947\u0902 \u092c\u093e\u0926 \u092e\u0947\u0902 \u092c\u0926\u0932 \u0938\u0915\u0924\u0947 \u0939\u0948\u0902")
        sub.setStyleSheet(
            f"color:{ON_SURFACE_VAR}; font-family:'{FONT_DISPLAY}'; "
            "font-size:15px; background:transparent;"
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        layout.addWidget(sub)
        layout.addSpacing(40)

        # Two language cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(24)
        cards_row.addStretch()

        for code, label, flag, _ in self._LANGS:
            card = QFrame()
            card.setObjectName("langCard")
            card.setFixedSize(220, 180)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            self._cards[code] = card

            card_layout = QVBoxLayout(card)
            card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.setSpacing(10)

            flag_lbl = QLabel(flag)
            flag_lbl.setStyleSheet("font-size:52px; background:transparent;")
            flag_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            name_lbl = QLabel(label)
            name_lbl.setStyleSheet(
                f"color:{ON_SURFACE}; font-size:22px; font-weight:bold; background:transparent;"
            )
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            card_layout.addWidget(flag_lbl)
            card_layout.addWidget(name_lbl)

            # Click selects this card
            card.mousePressEvent = lambda _, c=code: self._select(c)
            cards_row.addWidget(card)

        cards_row.addStretch()
        layout.addLayout(cards_row)
        layout.addSpacing(40)

        # Continue button
        self._btn = _btn_primary("Continue \u2192")
        self._btn.setFixedWidth(280)
        self._btn.clicked.connect(self._on_continue)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

        # Apply initial selection style
        self._select(self._selected)

    def _select(self, code: str):
        self._selected = code
        for c, card in self._cards.items():
            if c == code:
                card.setStyleSheet(
                    f"QFrame#langCard {{ background:rgba(210,168,87,0.12); "
                    f"border:2px solid {PRIMARY_CONTAINER}; border-radius:20px; }}"
                )
            else:
                card.setStyleSheet(
                    f"QFrame#langCard {{ background:{SURFACE_DIM}; "
                    f"border:2px solid {OUTLINE_VARIANT}; border-radius:20px; }}"
                )
        # Update continue button label to chosen language
        for c, label, _, btn_label in self._LANGS:
            if c == code:
                self._btn.setText(btn_label)
                break

    def _on_continue(self):
        set_language(self._selected, save=True)
        self.proceed.emit()


# ── Step 1: Welcome ───────────────────────────────────────────────────────────────────────

class _StepWelcome(QWidget):
    proceed = pyqtSignal()

    def __init__(self, profile_name: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addStretch()

        greeting = _label(f"Welcome, {profile_name}!", 42, bold=True)
        greeting.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(greeting)
        layout.addSpacing(16)

        desc = _label(
            "Solace uses fun games to help you regain movement in your\n"
            "arm and hand. Your progress is tracked so your therapist\n"
            "can see how you're improving week by week.",
            18, color=ON_SURFACE_VAR, wrap=True
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)
        layout.addSpacing(48)

        btn = _btn_primary("  Let's get started  →")
        btn.setFixedWidth(320)
        btn.clicked.connect(self.proceed.emit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()


# ── Step 2: Device Connection ─────────────────────────────────────────────────

class _DevicePoller(QThread):
    """Polls pygame joystick in background and signals connect/disconnect."""
    device_connected = pyqtSignal(str)   # name
    device_lost      = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._was_connected = False

    def run(self):
        import pygame
        # initialize just the joystick module
        pygame.joystick.init()
        while self._running:
            # Quit and re-init is safer than event.pump() in a background thread 
            # without initializing display, which causes a hard crash.
            pygame.joystick.quit()
            pygame.joystick.init()
            count = pygame.joystick.get_count()
            
            if count > 0 and not self._was_connected:
                j = pygame.joystick.Joystick(0)
                j.init()
                name = j.get_name()
                if name == "ESP32S3_DEV":
                    name = "Solace controller"
                self.device_connected.emit(name)
                self._was_connected = True
            elif count == 0 and self._was_connected:
                self.device_lost.emit()
                self._was_connected = False
            self.msleep(500)

    def stop(self):
        self._running = False
        self.wait()


class _StepDevice(QWidget):
    device_detected = pyqtSignal(str)
    skipped         = pyqtSignal()

    def __init__(self, parent=None, external_gamepad=None, initial_name=None):
        super().__init__(parent)
        self._poller = None
        self._external = external_gamepad
        self._initial_name = initial_name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch()

        title = _label("Connect Your Solace Controller", 36, bold=True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(12)

        self._status_lbl = _label(
            "Looking for your device…", 17, color=ON_SURFACE_VAR
        )
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_lbl)
        layout.addSpacing(40)

        # Status card
        self._card = QFrame()
        self._card.setFixedWidth(480)
        self._card.setObjectName("devCard")   # scoped: a bare rule would box every child label
        self._card.setStyleSheet(
            f"QFrame#devCard {{ background: {SURFACE_CON_LOW}; border-radius: 20px; "
            f"border: 1px solid {OUTLINE_VARIANT}; }}"
            f"QFrame#devCard QLabel {{ border: none; background: transparent; }}"
        )
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(32, 24, 32, 24)
        card_layout.setSpacing(8)

        self._conn_lbl = QLabel("Waiting for Solace controller…")
        self._conn_lbl.setStyleSheet(
            f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; "
            f"font-size: 16px; background: transparent;"
        )
        self._conn_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._conn_lbl)

        card_row = QHBoxLayout()
        card_row.addStretch()
        card_row.addWidget(self._card)
        card_row.addStretch()
        layout.addLayout(card_row)
        layout.addSpacing(32)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)
        skip = _btn_secondary("Skip for now — I'll connect later")
        skip.clicked.connect(self.skipped.emit)
        btn_row.addStretch()
        btn_row.addWidget(skip)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

        # Device detection: at RUNTIME the main GamepadThread already owns
        # pygame — starting our own poller (which quit()/init()s the joystick
        # subsystem) yanks its handles away and hard-crashes the app. Use its
        # signals instead. Only at app-startup (no gamepad thread yet) do we
        # run the private poller.
        if self._external is not None:
            self._external.controller_state.connect(self._on_external_state)
            # NOTE: don't fire _on_detected here — wait for showEvent so we don't
            # skip steps that haven't been shown yet (e.g. Language picker).
        else:
            self._poller = _DevicePoller()
            self._poller.device_connected.connect(self._on_detected)
            self._poller.device_lost.connect(self._on_lost)
            self._poller.start()

    def showEvent(self, event):
        super().showEvent(event)
        # If controller was already connected before this step was displayed,
        # trigger detection now (safe — we're actually visible).
        if self._external is not None and self._initial_name:
            QTimer.singleShot(300, lambda: self._on_detected(self._initial_name))

    def _on_external_state(self, connected: bool, name: str):
        if connected:
            self._on_detected(name)
        else:
            self._on_lost()

    def _on_detected(self, name: str):
        self._conn_lbl.setText(f"{name} connected!")
        self._conn_lbl.setStyleSheet(
            f"color: #1E9E4A; font-family: '{FONT_BODY}'; "
            f"font-size: 17px; font-weight: bold; background: transparent;"
        )
        self._card.setStyleSheet(
            f"QFrame#devCard {{ background: rgba(39,201,63,0.08); border-radius: 20px; "
            f"border: 1px solid #27c93f; }}"
            f"QFrame#devCard QLabel {{ border: none; background: transparent; }}"
        )
        # Brief pause so user can see the green tick, then auto-advance
        QTimer.singleShot(800, lambda: self.device_detected.emit(name))

    def _on_lost(self):
        self._conn_lbl.setText("Waiting for Solace controller…")
        self._conn_lbl.setStyleSheet(
            f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; "
            f"font-size: 16px; background: transparent;"
        )

    def stop_poller(self):
        if self._poller:
            self._poller.stop()
        if self._external is not None:
            try:
                self._external.controller_state.disconnect(self._on_external_state)
            except TypeError:
                pass
            self._external = None


# ── Step 3: Learn Your Device ─────────────────────────────────────────────────

class _StepLearn(QWidget):
    proceed = pyqtSignal()

    # Device-centric movements from the shared prompt module — identical
    # wording to the warmup and the assessment, with the 3D model
    # demonstrating each one.
    MOVEMENT_ORDER = ["neutral", "flexion", "extension", "pronation", "supination"]

    @property
    def DIRECTIONS(self):
        from ui.movement_prompts import PROMPTS
        return [(PROMPTS[m][0], PROMPTS[m][1], PROMPTS[m][2])
                for m in self.MOVEMENT_ORDER]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._step_idx = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch()

        title = _label("Let's learn how it works", 36, bold=True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(8)

        sub = _label("Watch the model demonstrate each movement", 17, color=ON_SURFACE_VAR)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)
        layout.addSpacing(16)

        # 3D controller — demonstrates each movement
        try:
            from ui.controller_3d_view import Controller3DView as _C3D
            self._3d = _C3D()
            self._3d.setFixedSize(620, 260)
        except ImportError:
            from ui.controller_3d_widget import Controller3DWidget as _C3D
            self._3d = _C3D()
            self._3d.setFixedSize(620, 180)
        row3d = QHBoxLayout()
        row3d.addStretch(); row3d.addWidget(self._3d); row3d.addStretch()
        layout.addLayout(row3d)
        layout.addSpacing(16)

        # Instruction card — selector scoped so the border doesn't cascade
        # onto the child labels (boxed-label bug)
        self._card = QFrame()
        self._card.setObjectName("learnCard")
        self._card.setFixedWidth(620)
        self._card.setFixedHeight(180)
        self._card.setStyleSheet(f"""
            QFrame#learnCard {{
                background: {SURFACE_CON_LOW}; border-radius: 24px;
                border: 1px solid {OUTLINE_VARIANT};
            }}
            QFrame#learnCard QLabel {{ border: none; background: transparent; }}
        """)
        card_l = QVBoxLayout(self._card)
        card_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_l.setSpacing(8)

        self._inst_icon = QLabel("⬅️")
        self._inst_icon.setStyleSheet("font-size: 52px; background: transparent;")
        self._inst_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._inst_title = _label("Tilt LEFT", 26, bold=True)
        self._inst_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._inst_desc = _label("See the cursor move left", 15, color=ON_SURFACE_VAR)
        self._inst_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card_l.addWidget(self._inst_icon)
        card_l.addWidget(self._inst_title)
        card_l.addWidget(self._inst_desc)

        card_row = QHBoxLayout()
        card_row.addStretch()
        card_row.addWidget(self._card)
        card_row.addStretch()
        layout.addLayout(card_row)
        layout.addSpacing(24)

        # Progress dots
        self._dots_layout = QHBoxLayout()
        self._dots_layout.setSpacing(8)
        self._dots_layout.addStretch()
        self._dots = []
        for _ in self.DIRECTIONS:
            dot = QFrame()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background: {OUTLINE_VARIANT}; border-radius: 5px;")
            self._dots.append(dot)
            self._dots_layout.addWidget(dot)
        self._dots_layout.addStretch()
        layout.addLayout(self._dots_layout)
        layout.addSpacing(32)

        # Auto advance every 3 seconds — but ONLY start when this step is shown
        self._timer = QTimer()
        self._timer.timeout.connect(self._next_step)
        # Timer is started in showEvent, stopped in hideEvent

        self._btn_row = QHBoxLayout()
        self._skip_btn = _btn_secondary("Got it — skip tutorial")
        self._skip_btn.clicked.connect(self.proceed.emit)
        self._btn_row.addStretch()
        self._btn_row.addWidget(self._skip_btn)
        self._btn_row.addStretch()
        layout.addLayout(self._btn_row)
        layout.addStretch()

        self._update_card()

    def showEvent(self, event):
        super().showEvent(event)
        self._step_idx = 0
        self._update_card()
        self._timer.start(3600)   # demo (2.6 s) + a beat to absorb it

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def _update_card(self):
        icon, title, desc = self.DIRECTIONS[self._step_idx]
        self._inst_icon.setText(icon)
        self._inst_title.setText(title)
        self._inst_desc.setText(f"({desc})")
        # 3D model performs the movement being described
        movement = self.MOVEMENT_ORDER[self._step_idx]
        if movement != "neutral" and hasattr(self._3d, "play_demo"):
            self._3d.play_demo(movement, 2.6)
        for i, dot in enumerate(self._dots):
            if i == self._step_idx:
                dot.setStyleSheet(f"background: {PRIMARY_CONTAINER}; border-radius: 5px;")
            else:
                dot.setStyleSheet(f"background: {OUTLINE_VARIANT}; border-radius: 5px;")

    def _next_step(self):
        self._step_idx += 1
        if self._step_idx >= len(self.DIRECTIONS):
            self._timer.stop()
            self.proceed.emit()
        else:
            self._update_card()


# ── Step 4: Baseline Calibration ─────────────────────────────────────────────

class _StepCalibration(QWidget):
    completed = pyqtSignal(float, float, float, float)  # max_left, max_right, max_up, max_down

    SEQUENCE = [
        ("⬅️", "Move as far LEFT as comfortable…", "left"),
        ("➡️", "Now as far RIGHT…", "right"),
        ("⬆️", "Now as far UP…", "up"),
        ("⬇️", "Now as far DOWN…", "down"),
        ("⭕", "Return to neutral and hold…", "neutral"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._step_idx = 0
        self._readings = {"left": 0.0, "right": 0.0, "up": 0.0, "down": 0.0}
        self._hold_count = 0
        self._hold_target = 40  # ~2 seconds at 60fps
        self._last_raw = (0.0, 0.0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch()

        title = _label("Let's measure your range", 36, bold=True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(8)

        sub = _label(
            "Move in each direction as far as comfortable.\n"
            "Hold for 2 seconds when you reach your limit.",
            17, color=ON_SURFACE_VAR, wrap=True
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)
        layout.addSpacing(40)

        # Instruction card
        self._card = QFrame()
        self._card.setFixedWidth(520)
        self._card.setFixedHeight(200)
        self._card.setObjectName("calCard")   # scoped: a bare rule would box every child label
        self._card.setStyleSheet(
            f"QFrame#calCard {{ background: {SURFACE_CON_LOW}; border-radius: 24px; "
            f"border: 1px solid {OUTLINE_VARIANT}; }}"
            f"QFrame#calCard QLabel {{ border: none; background: transparent; }}"
        )
        card_l = QVBoxLayout(self._card)
        card_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_l.setSpacing(10)

        self._cal_icon = QLabel("⬅️")
        self._cal_icon.setStyleSheet("font-size: 52px; background: transparent;")
        self._cal_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cal_lbl = _label("Move as far LEFT as comfortable…", 22, bold=True)
        self._cal_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Hold progress bar
        from PyQt6.QtWidgets import QProgressBar
        self._hold_bar = QProgressBar()
        self._hold_bar.setRange(0, self._hold_target)
        self._hold_bar.setValue(0)
        self._hold_bar.setFixedHeight(10)
        self._hold_bar.setTextVisible(False)
        self._hold_bar.setStyleSheet(f"""
            QProgressBar {{ background: {SURFACE_DIM}; border-radius: 5px; border: none; }}
            QProgressBar::chunk {{ background: {PRIMARY_CONTAINER}; border-radius: 5px; }}
        """)

        card_l.addWidget(self._cal_icon)
        card_l.addWidget(self._cal_lbl)
        card_l.addWidget(self._hold_bar)

        card_row = QHBoxLayout()
        card_row.addStretch()
        card_row.addWidget(self._card)
        card_row.addStretch()
        layout.addLayout(card_row)
        layout.addSpacing(32)

        # Skip button
        skip = _btn_secondary("Skip baseline calibration")
        skip.clicked.connect(self._skip)
        skip_row = QHBoxLayout()
        skip_row.addStretch()
        skip_row.addWidget(skip)
        skip_row.addStretch()
        layout.addLayout(skip_row)
        layout.addStretch()

        # Poll timer to capture max ROM — ONLY starts when this step is shown
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll)
        # Started in showEvent to prevent auto-advancing while on earlier steps
        self._update_card()

    def showEvent(self, event):
        super().showEvent(event)
        # Reset state each time this step becomes visible
        self._step_idx = 0
        self._readings = {"left": 0.0, "right": 0.0, "up": 0.0, "down": 0.0}
        self._hold_count = 0
        self._last_raw = (0.0, 0.0)
        self._update_card()
        self._poll_timer.start(16)  # ~60fps

    def hideEvent(self, event):
        super().hideEvent(event)
        self._poll_timer.stop()

    def update_raw_axes(self, x: float, y: float):
        """Called externally with live axis data."""
        self._last_raw = (x, y)

    def _update_card(self):
        icon, text, _ = self.SEQUENCE[self._step_idx]
        self._cal_icon.setText(icon)
        self._cal_lbl.setText(text)
        self._hold_bar.setValue(0)
        self._hold_count = 0

    def _poll(self):
        x, y = self._last_raw
        _, direction = self.SEQUENCE[self._step_idx][0], self.SEQUENCE[self._step_idx][2]
        MOVE_THRESHOLD = 0.15  # must exceed dead-zone to count as real movement

        moving = False
        if direction == "neutral":
            moving = abs(x) < MOVE_THRESHOLD and abs(y) < MOVE_THRESHOLD
        elif direction == "left":
            self._readings["left"] = max(self._readings.get("left", 0), abs(x))
            moving = x < -MOVE_THRESHOLD
        elif direction == "right":
            self._readings["right"] = max(self._readings.get("right", 0), abs(x))
            moving = x > MOVE_THRESHOLD
        elif direction == "up":
            self._readings["up"] = max(self._readings.get("up", 0), abs(y))
            moving = y < -MOVE_THRESHOLD
        elif direction == "down":
            self._readings["down"] = max(self._readings.get("down", 0), abs(y))
            moving = y > MOVE_THRESHOLD

        if moving:
            self._hold_count += 1
        self._hold_bar.setValue(self._hold_count)

        if self._hold_count >= self._hold_target:
            self._step_idx += 1
            if self._step_idx >= len(self.SEQUENCE):
                self._poll_timer.stop()
                self.completed.emit(
                    -self._readings.get("left", 0.0),
                     self._readings.get("right", 0.0),
                    -self._readings.get("up", 0.0),
                     self._readings.get("down", 0.0),
                )
            else:
                self._update_card()

    def _skip(self):
        self._poll_timer.stop()
        self.completed.emit(0.0, 0.0, 0.0, 0.0)


# ── Main Onboarding Dialog ────────────────────────────────────────────────────

class OnboardingFlow(QDialog):
    """
    Full-screen onboarding flow — call .exec() and check result.
    """
    onboarding_complete = pyqtSignal()

    def __init__(self, profile: dict, session_manager: SessionManager,
                 parent=None, gamepad=None, connected_name=None):
        super().__init__(parent)
        self._profile = profile
        self._sm = session_manager
        self._device_name = None
        self._gamepad = gamepad             # runtime: reuse the main thread's
        self._connected_name = connected_name   # pygame instead of a poller

        self.setWindowTitle("Solace — Welcome")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )

        screen = QApplication.primaryScreen().availableGeometry()
        self.setFixedSize(screen.width(), screen.height())
        self.setStyleSheet(f"background: {BACKGROUND};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Step indicator bar ─────────────────────────────────────────────────
        bar = QWidget()
        bar.setFixedHeight(56)
        bar.setStyleSheet(f"background: {SURFACE_CON_LOW};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(48, 0, 48, 0)
        bar_layout.setSpacing(0)

        logo = QLabel("Solace Setup")
        logo.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 18px; font-weight: bold; background: transparent;"
        )
        bar_layout.addWidget(logo)
        bar_layout.addStretch()

        self._step_lbl = QLabel("")   # blank during language picker; set from Step 1
        self._step_lbl.setStyleSheet(
            f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; "
            f"font-size: 14px; background: transparent;"
        )
        bar_layout.addWidget(self._step_lbl)
        root.addWidget(bar)

        # ── Centred content area ───────────────────────────────────────────────
        content_area = QWidget()
        content_layout = QVBoxLayout(content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # Max-width wrapper
        self._stack = QStackedWidget()
        self._stack.setFixedWidth(800)

        self._step_lang    = _StepLanguage()
        self._step_welcome = _StepWelcome(profile.get("name", "Friend"))
        self._step_device  = _StepDevice(external_gamepad=self._gamepad,
                                         initial_name=self._connected_name)
        self._step_cal     = _StepCalibration()

        self._stack.addWidget(self._step_lang)     # 0 — choose language FIRST
        self._stack.addWidget(self._step_welcome)  # 1
        self._stack.addWidget(self._step_device)   # 2
        self._stack.addWidget(self._step_cal)      # 3

        # Wire signals
        self._step_lang.proceed.connect(self._on_language_chosen)
        self._step_welcome.proceed.connect(lambda: self._go_to(2))
        self._step_device.device_detected.connect(self._on_device)
        self._step_device.skipped.connect(self._on_skip_device)
        self._step_cal.completed.connect(self._on_calibration_done)

        center_row = QHBoxLayout()
        center_row.addStretch()
        center_row.addWidget(self._stack)
        center_row.addStretch()
        content_layout.addStretch()
        content_layout.addLayout(center_row)
        content_layout.addStretch()

        root.addWidget(content_area, stretch=1)

        # Language is the unnumbered first screen; the 3 numbered steps follow.
        self._stack.setCurrentIndex(0)
        self._update_step_label(1, 3)

    def _on_language_chosen(self):
        # Re-translate the later steps into the chosen language, then continue.
        for w in (self._step_welcome, self._step_device, self._step_cal):
            if hasattr(w, "retranslate"):
                w.retranslate()
        self._go_to(1)   # → Welcome

    def _go_to(self, idx: int):
        self._stack.setCurrentIndex(idx)
        # idx 0 = language (unnumbered); numbered steps are welcome/device/cal.
        self._update_step_label(max(1, idx), 3)

    def _update_step_label(self, current: int, total: int):
        self._step_lbl.setText(f"Step {current} of {total}")

    def _on_device(self, name: str):
        self._device_name = name
        self._step_device.stop_poller()
        self._go_to(3)   # straight to Calibration (index 3 after adding language)

    def _on_skip_device(self):
        self._step_device.stop_poller()
        self._finish_onboarding()   # no device — just complete onboarding

    def _finish_onboarding(self):
        """End of onboarding — the AssessmentWizard takes over from here."""
        self._sm.mark_onboarding_done()
        self.accept()

    def _on_calibration_done(self, max_left, max_right, max_up, max_down):
        # Legacy path (step 4 no longer reachable) — kept for safety.
        self._sm.mark_onboarding_done()
        self.accept()


def should_show_onboarding(profile_id: str) -> bool:
    """Returns True if this profile has never completed onboarding."""
    sm = SessionManager(profile_id)
    return not sm.onboarding_done()
