"""
AssessmentWizard — first-launch movement assessment (per profile).

Measures the patient's real range of motion in DEGREES for all four mapped
movements (flexion, extension, pronation, supination — 2 repetitions each,
best kept) plus analog squeeze (firmware v6 Z axis), and hands the result
back as the clinical baseline that seeds the therapy journey and the
per-patient controller range limits.

Usage (from the launcher):
    wiz = AssessmentWizard(parent)
    gamepad.raw_axes.connect(wiz.update_raw_axes)
    gamepad.raw_squeeze.connect(wiz.update_squeeze)
    if wiz.exec():                     # accepted
        wiz.baseline_deg               # {"flexion":…, …} degrees
        wiz.squeeze_max                # 0..1 or None (no v6 firmware)
        wiz.hand                       # "left" | "right"

The wizard resets the controller to HEALTHY range limits before measuring
(otherwise a redo would be clipped by the patient's previous limits).
"""
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QProgressBar, QApplication, QGridLayout
)
from PyQt6.QtCore import Qt, QTimer
from core.theme import (
    FONT_DISPLAY, FONT_BODY, ON_SURFACE, ON_SURFACE_VAR,
    PRIMARY_CONTAINER, SURFACE_DIM, OUTLINE_VARIANT,
    SURFACE_CON_LOW, BACKGROUND, PRIMARY_FIXED,
)
try:
    from ui.controller_3d_view import Controller3DView as _Controller3D
    _WEB_VIEW = True
except ImportError:
    from ui.controller_3d_widget import Controller3DWidget as _Controller3D
    _WEB_VIEW = False


# Movement metadata: key, axis, sign, icon, patient-facing instruction.
# Icons and wording come from ui/movement_prompts.py — identical to the
# daily warmup. The 3D model demonstrates each movement first.
from ui.movement_prompts import icon as _icon, two_line as _text

MOVEMENTS = [
    ("flexion",    "y", +1, _icon("flexion"),    _text("flexion")),
    ("extension",  "y", -1, _icon("extension"),  _text("extension")),
    ("pronation",  "x", +1, _icon("pronation"),  _text("pronation")),
    ("supination", "x", -1, _icon("supination"), _text("supination")),
]

CAPTURE_SECS = 6.0     # per repetition
REST_SECS    = 2.5
DEMO_SECS    = 2.6     # 3D model demonstrates first; capture starts after
REPS         = 2
POLL_MS      = 50


class AssessmentWizard(QDialog):

    def __init__(self, parent=None, processor=None):
        super().__init__(parent)
        # Results
        self.baseline_deg: dict = {}
        self.squeeze_max: float | None = None
        self.hand: str = "right"

        # M4: per-profile prompt wording — words/arrows mirror with axis flips
        from ui.movement_prompts import icon as _pic, two_line as _ptl, is_mirrored
        self._movements = [
            (key, axis, sign,
             _pic(key, is_mirrored(key, processor)),
             _ptl(key, is_mirrored(key, processor)))
            for key, axis, sign, _i, _t in MOVEMENTS
        ]

        self._raw = (0.0, 0.0)
        self._squeeze = 0.0
        self._squeeze_seen = False
        self._closing = False
        self._peaks = {m[0]: [0.0] * REPS for m in self._movements}   # axis units
        self._squeeze_peaks = [0.0] * REPS
        self._tremor_samples: list = []   # collected during the neutral hold
        self.tremor_level = 0.0

        # Reset controller to healthy limits so measurement isn't clipped
        import threading
        def _reset():
            try:
                from core.device_link import apply_patient_limits
                apply_patient_limits(None)
            except Exception as exc:
                print(f"[AssessmentWizard] limit reset failed: {exc}")
        threading.Thread(target=_reset, daemon=True).start()

        # Build the phase list
        self._phases = [("hand", None, 0), ("neutral", None, 0)]
        for m in self._movements:
            for rep in range(REPS):
                self._phases.append(("capture", m, rep))
                self._phases.append(("rest", m, rep))
        for rep in range(REPS):
            self._phases.append(("squeeze", None, rep))
            self._phases.append(("rest", None, rep))
        self._phases.append(("summary", None, 0))
        self._phase_idx = 0
        self._phase_elapsed = 0.0
        self._hold_ticks = 0

        # ── Window ────────────────────────────────────────────────────────────
        self.setWindowTitle("Solace — Movement Assessment")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        screen = QApplication.primaryScreen().availableGeometry()
        self.setFixedSize(screen.width(), screen.height())
        self.setStyleSheet(f"background: {BACKGROUND};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        top_bar = QWidget()
        top_bar.setFixedHeight(56)
        top_bar.setStyleSheet(f"background: {SURFACE_CON_LOW};")
        tl = QHBoxLayout(top_bar)
        tl.setContentsMargins(48, 0, 48, 0)
        t = QLabel("Movement Assessment — your personal baseline")
        t.setStyleSheet(f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
                        f"font-size: 18px; font-weight: bold; background: transparent;")
        tl.addWidget(t)
        tl.addStretch()
        root.addWidget(top_bar)

        centre = QWidget()
        cl = QVBoxLayout(centre)
        cl.addStretch()

        # 3D preview — big enough to actually follow the demo
        self._3d = _Controller3D()
        self._3d.setFixedSize(860, 340 if _WEB_VIEW else 200)
        row3d = QHBoxLayout(); row3d.addStretch(); row3d.addWidget(self._3d); row3d.addStretch()
        cl.addLayout(row3d)
        cl.addSpacing(14)

        # Card — selector scoped to the frame itself so the border does NOT
        # cascade onto child labels (was drawing a box around every label)
        self._card = QFrame()
        self._card.setObjectName("assessCard")
        self._card.setFixedSize(860, 300)
        self._card.setStyleSheet(f"""
            QFrame#assessCard {{
                background: {SURFACE_CON_LOW}; border-radius: 28px;
                border: 1px solid {OUTLINE_VARIANT};
            }}
            QFrame#assessCard QLabel {{ border: none; background: transparent; }}
        """)
        cardl = QVBoxLayout(self._card)
        cardl.setContentsMargins(40, 28, 40, 28)
        cardl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cardl.setSpacing(10)

        self._icon = QLabel("🖐️")
        self._icon.setStyleSheet("font-size: 56px; background: transparent;")
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title = QLabel()
        self._title.setStyleSheet(f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
                                  f"font-size: 24px; font-weight: bold; background: transparent;")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        self._sub = QLabel()
        self._sub.setStyleSheet(f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; "
                                f"font-size: 16px; background: transparent;")
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub.setWordWrap(True)

        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setValue(0)
        self._bar.setFixedHeight(12)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet(f"""
            QProgressBar {{ background: {SURFACE_DIM}; border-radius: 6px; border: none; }}
            QProgressBar::chunk {{ background: {PRIMARY_CONTAINER}; border-radius: 6px; }}
        """)

        # Hand-pick buttons (only visible in the hand phase)
        self._hand_row = QHBoxLayout()
        from core.i18n import t as _t
        self._btn_left  = self._hand_btn(_t("aw_left_hand"))
        self._btn_right = self._hand_btn(_t("aw_right_hand"))
        self._btn_left.clicked.connect(lambda: self._pick_hand("left"))
        self._btn_right.clicked.connect(lambda: self._pick_hand("right"))
        self._hand_row.addStretch()
        self._hand_row.addWidget(self._btn_left)
        self._hand_row.addSpacing(20)
        self._hand_row.addWidget(self._btn_right)
        self._hand_row.addStretch()

        # Summary grid + finish (built lazily)
        self._summary_widget = None
        self._finish_btn = None

        cardl.addWidget(self._icon)
        cardl.addWidget(self._title)
        cardl.addWidget(self._sub)
        cardl.addLayout(self._hand_row)
        cardl.addSpacing(6)
        cardl.addWidget(self._bar)
        self._cardl = cardl

        cardrow = QHBoxLayout(); cardrow.addStretch(); cardrow.addWidget(self._card); cardrow.addStretch()
        cl.addLayout(cardrow)
        cl.addSpacing(18)

        # Skip
        self._skip = QPushButton(_t("aw_skip"))
        self._skip.setFixedHeight(44)
        self._skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {ON_SURFACE_VAR};
                border: 1px solid {OUTLINE_VARIANT}; border-radius: 12px;
                padding: 0 26px; font-family: '{FONT_DISPLAY}'; font-size: 14px; }}
            QPushButton:hover {{ background: {SURFACE_DIM}; }}
        """)
        self._skip.clicked.connect(self._do_skip)
        sr = QHBoxLayout(); sr.addStretch(); sr.addWidget(self._skip); sr.addStretch()
        cl.addLayout(sr)
        cl.addStretch()
        root.addWidget(centre, stretch=1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_MS)
        self._show_phase()

    # ── external feeds ─────────────────────────────────────────────────────────

    def update_raw_axes(self, x: float, y: float):
        if self._closing:
            return
        self._raw = (x, y)
        self._3d.update_axes(x, y)

    def update_squeeze(self, v: float):
        if self._closing:
            return
        self._squeeze = v
        self._squeeze_seen = True

    # ── ui helpers ─────────────────────────────────────────────────────────────

    def _hand_btn(self, text):
        b = QPushButton(text)
        b.setFixedSize(220, 64)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(f"""
            QPushButton {{ background: {SURFACE_DIM}; color: {ON_SURFACE};
                border: 1px solid {OUTLINE_VARIANT}; border-radius: 16px;
                font-family: '{FONT_DISPLAY}'; font-size: 18px; font-weight: bold; }}
            QPushButton:hover {{ background: {PRIMARY_CONTAINER}; color: #0d0b09; }}
        """)
        return b

    def _pick_hand(self, hand: str):
        self.hand = hand
        self._advance()

    def _do_skip(self):
        self._closing = True
        self._timer.stop()
        self.reject()

    # ── phase machine ──────────────────────────────────────────────────────────

    def _show_phase(self):
        kind, move, rep = self._phases[self._phase_idx]
        self._phase_elapsed = 0.0
        self._bar.setValue(0)
        self._btn_left.setVisible(kind == "hand")
        self._btn_right.setVisible(kind == "hand")
        self._bar.setVisible(kind in ("neutral", "capture", "rest", "squeeze"))

        from core.i18n import t
        if kind == "hand":
            self._icon.setText("🙌")
            self._title.setText(t("aw_hand_title"))
            self._sub.setText(t("aw_hand_sub"))
        elif kind == "neutral":
            self._icon.setText("⭕")
            self._title.setText(t("aw_neutral_title"))
            self._sub.setText(t("aw_neutral_sub"))
            # H2 fix: hardware tare NOW, while the patient is holding neutral —
            # otherwise a device booted off-neutral skews every measurement.
            import threading
            def _tare():
                try:
                    from core.device_link import send_retare
                    send_retare()
                except Exception as exc:
                    print(f"[AssessmentWizard] tare failed: {exc}")
            threading.Thread(target=_tare, daemon=True).start()
        elif kind == "capture":
            key, axis, sign, icon, inst = move
            self._icon.setText(icon)
            self._title.setText(inst)
            self._sub.setText(t("aw_capture_sub", n=rep + 1, t=REPS))
            self._demo_left = DEMO_SECS          # capture waits for the demo
            if hasattr(self._3d, "play_demo"):
                self._3d.play_demo(key, DEMO_SECS)
        elif kind == "rest":
            self._icon.setText("😌")
            self._title.setText(t("aw_rest_title"))
            self._sub.setText(t("aw_rest_sub"))
        elif kind == "squeeze":
            self._icon.setText("✊")
            self._title.setText(t("aw_squeeze_title"))
            self._sub.setText(f"Attempt {rep + 1} of {REPS}."
                              + ("" if self._squeeze_seen else
                                 "  (No squeeze signal detected yet — needs firmware v6.)"))
        elif kind == "summary":
            self._finish()

    # capture only advances when the patient actually moves and HOLDS near
    # their own peak — an idle user can no longer "complete" an assessment
    MOVE_FLOOR   = 0.04    # below this = noise, not movement
    HOLD_TICKS   = 30      # ~1.5 s at 50 ms holding near the peak
    TIMEOUT_SECS = 12.0    # absolute backstop so the flow can never hang

    def _poll(self):
        kind, move, rep = self._phases[self._phase_idx]
        if kind in ("hand", "summary"):
            return
        # Demonstration first: capture starts AFTER the model finishes
        if kind == "capture" and getattr(self, "_demo_left", 0) > 0:
            self._demo_left -= POLL_MS / 1000.0
            self._bar.setValue(0)
            return
        self._phase_elapsed += POLL_MS / 1000.0

        if kind in ("neutral", "rest"):
            dur = 3.0 if kind == "neutral" else REST_SECS
            self._bar.setValue(min(1000, int(self._phase_elapsed / dur * 1000)))
            if kind == "neutral":
                self._tremor_samples.append(self._raw)
            if self._phase_elapsed >= dur:
                self._advance()
            return

        # capture / squeeze: hold-at-peak driven, not timer driven
        if kind == "capture":
            key, axis, sign, icon, inst = move
            v = (self._raw[0] if axis == "x" else self._raw[1]) * sign
            if v > self._peaks[key][rep]:
                self._peaks[key][rep] = min(1.0, v)
            peak = self._peaks[key][rep]
        else:  # squeeze
            v = self._squeeze
            if v > self._squeeze_peaks[rep]:
                self._squeeze_peaks[rep] = min(1.0, v)
            peak = self._squeeze_peaks[rep]

        holding = (peak >= self.MOVE_FLOOR
                   and v >= min(peak * 0.75, peak - 0.02))
        self._hold_ticks = (self._hold_ticks + 1) if holding else \
                           max(0, getattr(self, "_hold_ticks", 0) - 1)
        self._bar.setValue(min(1000, int(self._hold_ticks / self.HOLD_TICKS * 1000)))

        if (self._hold_ticks >= self.HOLD_TICKS
                or self._phase_elapsed >= self.TIMEOUT_SECS):
            self._hold_ticks = 0
            self._advance()

    def _advance(self):
        self._phase_idx += 1
        self._phase_elapsed = 0.0
        self._hold_ticks = 0
        if self._phase_idx < len(self._phases):
            self._show_phase()

    # ── summary ────────────────────────────────────────────────────────────────

    def _finish(self):
        self._closing = True
        self._timer.stop()
        from ui.calibration_warmup import _tremor_rms
        self.tremor_level = _tremor_rms(self._tremor_samples)
        from core.units import get_active_limits
        limits = get_active_limits()   # healthy defaults (reset at start)

        self.baseline_deg = {
            key: round(max(peaks) * limits[key], 1)
            for key, peaks in self._peaks.items()
        }
        self.squeeze_max = (round(max(self._squeeze_peaks), 3)
                            if self._squeeze_seen else None)

        # Swap card content for the summary
        from core.i18n import t
        self._icon.setText("")
        self._title.setText(t("aw_summary_title"))
        self._sub.setVisible(False)
        self._bar.setVisible(False)

        grid = QGridLayout()
        grid.setHorizontalSpacing(36)
        grid.setVerticalSpacing(6)
        rows = [("Flexion", "flexion"), ("Extension", "extension"),
                ("Pronation", "pronation"), ("Supination", "supination")]
        for i, (label, key) in enumerate(rows):
            l1 = QLabel(label)
            l1.setStyleSheet(f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; "
                             f"font-size: 16px; background: transparent;")
            pct = self.baseline_deg[key] / limits[key] * 100 if limits[key] else 0
            l2 = QLabel(f"{self.baseline_deg[key]:.0f}°  ({pct:.0f}% of reference)")
            l2.setStyleSheet(f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
                             f"font-size: 16px; font-weight: bold; background: transparent;")
            grid.addWidget(l1, i, 0)
            grid.addWidget(l2, i, 1)
        sq = QLabel("Squeeze")
        sq.setStyleSheet(f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; "
                         f"font-size: 16px; background: transparent;")
        sqv = QLabel("not measured" if self.squeeze_max is None
                     else f"{self.squeeze_max * 100:.0f}% of scale")
        sqv.setStyleSheet(f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
                          f"font-size: 16px; font-weight: bold; background: transparent;")
        grid.addWidget(sq, len(rows), 0)
        grid.addWidget(sqv, len(rows), 1)
        self._cardl.addLayout(grid)

        self._finish_btn = QPushButton(t("aw_save"))
        self._finish_btn.setFixedSize(240, 52)
        self._finish_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._finish_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 {PRIMARY_FIXED}, stop:1 {PRIMARY_CONTAINER});
                color: #0d0b09; border: none; border-radius: 14px;
                font-family: '{FONT_DISPLAY}'; font-size: 16px; font-weight: bold;
            }}
        """)
        self._finish_btn.clicked.connect(self.accept)
        fr = QHBoxLayout(); fr.addStretch(); fr.addWidget(self._finish_btn); fr.addStretch()
        self._cardl.addLayout(fr)
        self._card.setFixedHeight(430)
        self._skip.setText("Discard")
