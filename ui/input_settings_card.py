"""
InputSettingsCard — live axis preview + configuration controls for the
custom controller / Arduino IMU. Inserted as the first card on SettingsPage.

Controls:
  • Live axis bars   — real-time X/Y visualisation
  • Calibrate button — zeroes the neutral position
  • Flip X / Flip Y  — toggle axis inversion
  • Sensitivity      — slider 0.5× → 3.0×
  • Dead-zone        — slider 0 % → 60 %
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QRectF, QPropertyAnimation, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QPainter, QLinearGradient, QColor, QPainterPath

from core.theme import (
    FONT_DISPLAY, FONT_BODY, FONT_MONO,
    ON_SURFACE, ON_SURFACE_VAR, PRIMARY, ON_PRIMARY,
    PRIMARY_CONTAINER, ON_PRIMARY_FIXED_VARIANT, PRIMARY_FIXED,
    SURFACE_DIM, OUTLINE_VARIANT, SURFACE_VARIANT, OUTLINE,
    SURFACE_CON_HIGH, SURFACE_CON_LOW,
)
try:
    from ui.controller_3d_view import Controller3DView as _Controller3D
    _WEB_VIEW = True
except Exception as _webengine_err:
    import traceback, os as _os, sys as _sys
    try:
        _exe_dir = _os.path.dirname(_sys.executable) if getattr(_sys, 'frozen', False) \
                   else _os.path.dirname(_os.path.abspath(__file__))
        _log_path = _os.path.join(_exe_dir, 'webengine_error.log')
        with open(_log_path, 'w') as _lf:
            _lf.write(traceback.format_exc())
    except Exception:
        pass
    from ui.controller_3d_widget import Controller3DWidget as _Controller3D
    _WEB_VIEW = False


# ── small reusable widgets ────────────────────────────────────────────────────

class _AxisBar(QWidget):
    """Single animated bar showing a normalised value in [-1, 1]."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._value = 0.0
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, v: float):
        self._value = max(-1.0, min(1.0, v))
        self.update()

    def paintEvent(self, _event):
        import core.theme as _t
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Track
        track_rect = QRectF(0, 14, w, 20)
        path = QPainterPath()
        path.addRoundedRect(track_rect, 10, 10)
        p.fillPath(path, QColor(_t.SURFACE_DIM))

        # Filled portion (from centre)
        cx = w / 2
        bar_x = cx
        bar_w = self._value * cx
        if bar_w < 0:
            bar_x = cx + bar_w
            bar_w = abs(bar_w)

        if bar_w > 0:
            fill_rect = QRectF(bar_x, 16, bar_w, 16)
            grad = QLinearGradient(fill_rect.left(), 0, fill_rect.right(), 0)
            grad.setColorAt(0, QColor(_t.PRIMARY_CONTAINER))
            grad.setColorAt(1, QColor(_t.PRIMARY))
            fill_path = QPainterPath()
            fill_path.addRoundedRect(fill_rect, 8, 8)
            p.fillPath(fill_path, grad)

        # Centre tick
        p.setPen(QColor(_t.OUTLINE_VARIANT))
        p.drawLine(int(cx), 12, int(cx), 36)

        # Label
        p.setPen(QColor(_t.ON_SURFACE_VAR))
        p.setFont(p.font())
        p.drawText(0, 0, 32, 48, Qt.AlignmentFlag.AlignVCenter, self._label)


class _MiniToggle(QWidget):
    """Small 64×32 toggle switch with animated knob."""
    toggled_signal = pyqtSignal(bool)

    def __init__(self, initial=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 32)
        self._is_on = initial
        self._knob_pos = 34 if initial else 2
        self._anim = QPropertyAnimation(self, b"knobPos")
        self._anim.setDuration(200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @pyqtProperty(int)
    def knobPos(self):
        return self._knob_pos

    @knobPos.setter
    def knobPos(self, v):
        self._knob_pos = v
        self.update()

    def mouseReleaseEvent(self, _event):
        self._is_on = not self._is_on
        self._anim.setEndValue(34 if self._is_on else 2)
        self._anim.start()
        self.toggled_signal.emit(self._is_on)

    def paintEvent(self, _event):
        import core.theme as _t
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 16, 16)
        p.fillPath(path, QColor(_t.PRIMARY_CONTAINER if self._is_on else _t.SURFACE_DIM))
        knob = QRectF(self._knob_pos, 2, 28, 28)
        p.setBrush(QColor(_t.PRIMARY if self._is_on else _t.SURFACE_VARIANT))
        p.setPen(QColor(_t.OUTLINE_VARIANT))
        p.drawEllipse(knob)


class _Slider(QWidget):
    """Horizontal slider: maps to [min_val, max_val]."""
    value_changed = pyqtSignal(float)

    def __init__(self, min_val=0.0, max_val=1.0, initial=0.5, parent=None):
        super().__init__(parent)
        self._min = min_val
        self._max = max_val
        self._value = initial
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def value(self):
        return self._value

    def _norm(self):
        return (self._value - self._min) / (self._max - self._min)

    def _set_from_x(self, x):
        t = max(0.0, min(1.0, x / self.width()))
        self._value = self._min + t * (self._max - self._min)
        self.update()
        self.value_changed.emit(self._value)

    def mousePressEvent(self, e):
        self._set_from_x(e.position().x())

    def mouseMoveEvent(self, e):
        self._set_from_x(e.position().x())

    def paintEvent(self, _event):
        import core.theme as _t
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        track_rect = QRectF(0, 18, w, 12)
        path = QPainterPath()
        path.addRoundedRect(track_rect, 6, 6)
        p.fillPath(path, QColor(_t.SURFACE_DIM))

        fill_w = w * self._norm()
        if fill_w > 0:
            fill_rect = QRectF(0, 18, fill_w, 12)
            grad = QLinearGradient(0, 18, fill_w, 30)
            grad.setColorAt(0, QColor(_t.PRIMARY_CONTAINER))
            grad.setColorAt(1, QColor(_t.PRIMARY))
            fp = QPainterPath()
            fp.addRoundedRect(fill_rect, 6, 6)
            p.fillPath(fp, grad)

        # Thumb
        tx = fill_w - 18
        tx = max(0, min(w - 36, tx))
        t_grad = QLinearGradient(tx, 6, tx + 36, 42)
        t_grad.setColorAt(0, QColor(_t.PRIMARY_FIXED))
        t_grad.setColorAt(1, QColor(_t.ON_PRIMARY_FIXED_VARIANT))
        p.setBrush(t_grad)
        p.setPen(QColor(_t.ON_PRIMARY_FIXED_VARIANT))
        p.drawEllipse(QRectF(tx, 6, 36, 36))


# ── main card ─────────────────────────────────────────────────────────────────

class InputSettingsCard(QFrame):

    assessment_requested = pyqtSignal()   # therapist wants to redo the baseline
    """
    Settings card for the custom controller / Arduino IMU.
    Connect the GamepadThread.raw_axes signal to update_raw_axes().
    """

    def __init__(self, processor, parent=None):
        super().__init__(parent)
        self._processor = processor
        self._last_raw = (0.0, 0.0)

        self.setObjectName("inputCard")
        self.setStyleSheet(f"""
            QFrame#inputCard {{
                background-color: {SURFACE_CON_LOW};
                border-top: 1px solid {OUTLINE_VARIANT};
                border-radius: 24px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(32)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Controller Input")
        title.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 24px; font-weight: bold; background: transparent;"
        )
        hdr.addWidget(title)
        hdr.addStretch()
        root.addLayout(hdr)

        # ── Live 3D Preview ───────────────────────────────────────────────────
        prev_lbl = QLabel("Live Controller Preview")
        prev_lbl.setStyleSheet(
            f"color: {ON_SURFACE_VAR}; font-family: '{FONT_MONO}'; "
            f"font-size: 13px; letter-spacing: 2px; background: transparent;"
        )
        root.addWidget(prev_lbl)

        self._3d_widget = _Controller3D()
        self._3d_widget.setFixedHeight(380 if _WEB_VIEW else 190)
        root.addWidget(self._3d_widget)

        # ── Live Axis Bars ────────────────────────────────────────────────────
        axis_lbl = QLabel("Raw Axes")
        axis_lbl.setStyleSheet(
            f"color: {ON_SURFACE_VAR}; font-family: '{FONT_MONO}'; "
            f"font-size: 13px; letter-spacing: 2px; background: transparent;"
        )
        root.addWidget(axis_lbl)

        self._bar_x = _AxisBar("X")
        self._bar_y = _AxisBar("Y")
        root.addWidget(self._bar_x)
        root.addWidget(self._bar_y)

        # ── Calibrate button ──────────────────────────────────────────────────
        cal_row = QHBoxLayout()
        cal_desc = QVBoxLayout()
        cal_title = QLabel("Calibrate Neutral Position")
        cal_title.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 20px; font-weight: bold; background: transparent;"
        )
        cal_sub = QLabel("Captures current sensor reading as the zero/neutral point.")
        cal_sub.setStyleSheet(
            f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; "
            f"font-size: 15px; background: transparent;"
        )
        cal_desc.addWidget(cal_title)
        cal_desc.addWidget(cal_sub)
        cal_row.addLayout(cal_desc)
        cal_row.addStretch()

        self._cal_btn = QPushButton("Calibrate")
        self._cal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cal_btn.setFixedSize(160, 48)
        self._cal_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {PRIMARY};
                color: {ON_PRIMARY};
                font-family: '{FONT_MONO}';
                font-size: 14px;
                font-weight: bold;
                border-radius: 24px;
                border: none;
            }}
            QPushButton:hover {{ background-color: {PRIMARY_FIXED}; }}
        """)
        self._cal_btn.clicked.connect(self._do_calibrate)
        cal_row.addWidget(self._cal_btn)

        # Re-centre: hardware tare over serial ('T') — resets the firmware's
        # neutral pose + FSR baseline. Use when the gyro has drifted mid-session.
        self._retare_btn = QPushButton("Re-centre")
        self._retare_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._retare_btn.setFixedSize(160, 48)
        self._retare_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {ON_SURFACE};
                font-family: '{FONT_MONO}';
                font-size: 14px;
                font-weight: bold;
                border-radius: 24px;
                border: 1px solid {OUTLINE_VARIANT};
            }}
            QPushButton:hover {{ background: {SURFACE_DIM}; }}
        """)
        self._retare_btn.clicked.connect(self._do_retare)
        cal_row.addWidget(self._retare_btn)

        # Redo the first-launch movement assessment (new baseline)
        self._assess_btn = QPushButton("Redo assessment")
        self._assess_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._assess_btn.setFixedSize(180, 48)
        self._assess_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {ON_SURFACE};
                font-family: '{FONT_MONO}';
                font-size: 14px;
                font-weight: bold;
                border-radius: 24px;
                border: 1px solid {OUTLINE_VARIANT};
            }}
            QPushButton:hover {{ background: {SURFACE_DIM}; }}
        """)
        self._assess_btn.clicked.connect(self.assessment_requested.emit)
        cal_row.addWidget(self._assess_btn)
        root.addLayout(cal_row)

        root.addWidget(self._separator())

        # ── Axis Flip ─────────────────────────────────────────────────────────
        flip_row = QHBoxLayout()
        flip_row.setSpacing(40)

        flip_x_lbl = QLabel("Flip X-axis")
        flip_x_lbl.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 20px; font-weight: bold; background: transparent;"
        )
        self._flip_x = _MiniToggle(initial=processor.flip_x)
        self._flip_x.toggled_signal.connect(self._on_flip_x)

        flip_y_lbl = QLabel("Flip Y-axis")
        flip_y_lbl.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 20px; font-weight: bold; background: transparent;"
        )
        self._flip_y = _MiniToggle(initial=processor.flip_y)
        self._flip_y.toggled_signal.connect(self._on_flip_y)

        flip_row.addWidget(flip_x_lbl)
        flip_row.addWidget(self._flip_x)
        flip_row.addSpacing(24)
        flip_row.addWidget(flip_y_lbl)
        flip_row.addWidget(self._flip_y)
        flip_row.addStretch()
        root.addLayout(flip_row)

        root.addWidget(self._separator())

        # ── Sensitivity slider ─────────────────────────────────────────────────
        root.addLayout(self._slider_row(
            "Sensitivity",
            "How much a small tilt moves the cursor.",
            min_val=0.5, max_val=3.0,
            initial=processor.sensitivity,
            fmt=lambda v: f"{v:.1f}×",
            on_change=self._on_sensitivity,
        ))

        root.addWidget(self._separator())

        # ── Navigation effort slider ──────────────────────────────────────────
        root.addLayout(self._slider_row(
            "Navigation effort",
            "How far to move before the menu reacts. Lower = easier, higher = steadier.",
            min_val=0.2, max_val=0.9,
            initial=processor.nav_threshold,
            fmt=lambda v: f"{int(v * 100)}%",
            on_change=self._on_nav_threshold,
        ))

        root.addWidget(self._separator())

        # ── Dead-zone slider ───────────────────────────────────────────────────
        root.addLayout(self._slider_row(
            "Dead-zone",
            "Ignore tilt smaller than this threshold.",
            min_val=0.0, max_val=0.6,
            initial=processor.inner_dead_zone,
            fmt=lambda v: f"{int(v * 100)}%",
            on_change=self._on_dead_zone,
        ))

    # ── helpers ───────────────────────────────────────────────────────────────

    def _separator(self):
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {OUTLINE_VARIANT};")
        return line

    def _slider_row(self, title, desc, min_val, max_val, initial, fmt, on_change):
        layout = QVBoxLayout()
        layout.setSpacing(12)

        header = QHBoxLayout()
        txt = QVBoxLayout()
        lbl_t = QLabel(title)
        lbl_t.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 20px; font-weight: bold; background: transparent;"
        )
        lbl_d = QLabel(desc)
        lbl_d.setStyleSheet(
            f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; "
            f"font-size: 15px; background: transparent;"
        )
        txt.addWidget(lbl_t)
        txt.addWidget(lbl_d)
        header.addLayout(txt)
        header.addStretch()

        val_lbl = QLabel(fmt(initial))
        val_lbl.setStyleSheet(
            f"color: {PRIMARY_CONTAINER}; background-color: {SURFACE_DIM}; "
            f"padding: 6px 14px; border-radius: 8px; border: 1px solid {OUTLINE_VARIANT}; "
            f"font-weight: bold; font-family: '{FONT_MONO}';"
        )
        header.addWidget(val_lbl)
        layout.addLayout(header)

        slider = _Slider(min_val, max_val, initial)

        def _changed(v):
            val_lbl.setText(fmt(v))
            on_change(v)

        slider.value_changed.connect(_changed)
        layout.addWidget(slider)
        return layout

    # ── slots ─────────────────────────────────────────────────────────────────

    def update_raw_axes(self, x: float, y: float):
        """Connect this to GamepadThread.raw_axes."""
        self._last_raw = (x, y)
        nx, ny, _ = self._processor.process(x, y)
        self._bar_x.set_value(nx)
        self._bar_y.set_value(ny)
        # 3D preview mirrors the physical device: apply the calibration offset
        # (so the Calibrate button re-centres the model) but keep it raw
        # otherwise — no flips/deadzone, those are game-input concerns.
        cx = max(-1.0, min(1.0, x - self._processor.cal_x))
        cy = max(-1.0, min(1.0, y - self._processor.cal_y))
        self._3d_widget.update_axes(cx, cy)

    def _do_calibrate(self):
        x, y = self._last_raw
        self._processor.calibrate(x, y)
        self._cal_btn.setText("Calibrated!")
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self._cal_btn.setText("Calibrate"))

    def _do_retare(self):
        """Hardware tare: device must be resting in NEUTRAL when pressed."""
        from core.device_link import send_retare
        from PyQt6.QtCore import QTimer
        ok = send_retare()
        self._retare_btn.setText("Re-centred!" if ok else "No device")
        QTimer.singleShot(2000, lambda: self._retare_btn.setText("Re-centre"))

    def _on_flip_x(self, state: bool):
        self._processor.flip_x = state
        self._processor.save()

    def _on_flip_y(self, state: bool):
        self._processor.flip_y = state
        self._processor.save()

    def _on_sensitivity(self, v: float):
        self._processor.sensitivity = v
        self._processor.save()

    def _on_nav_threshold(self, v: float):
        self._processor.nav_threshold = v
        self._processor.save()

    def _on_dead_zone(self, v: float):
        self._processor.inner_dead_zone = v
        self._processor.save()

    def hide_interactive_controls(self):
        """Called by CalibrationPage — show ONLY the live axis bars (no duplicate controls)."""
        # Walk child widgets and hide everything after the axis bars
        hiding = False
        for i in range(self.layout().count()):
            item = self.layout().itemAt(i)
            if item and item.widget():
                w = item.widget()
                # The axis bars are _AxisBar instances; everything after the second bar is hidden
                if hasattr(self, '_bar_y') and w is self._bar_y:
                    hiding = True
                    continue
                if hiding:
                    w.hide()
            elif item and item.layout() and hiding:
                # hide widgets inside sub-layouts
                def _hide_layout(l):
                    for j in range(l.count()):
                        it = l.itemAt(j)
                        if it and it.widget():
                            it.widget().hide()
                        elif it and it.layout():
                            _hide_layout(it.layout())
                _hide_layout(item.layout())

    def refresh_theme(self):
        """Update live colors when theme changes."""
        import core.theme as _t
        self.setStyleSheet(f"""
            QFrame#inputCard {{
                background-color: {_t.SURFACE_CON_LOW};
                border-top: 1px solid {_t.OUTLINE_VARIANT};
                border-radius: 24px;
            }}
        """)
        if hasattr(self, '_bar_x'): self._bar_x.update()
        if hasattr(self, '_bar_y'): self._bar_y.update()
        
        from PyQt6.QtWidgets import QLabel
        for lbl in self.findChildren(QLabel):
            ss = lbl.styleSheet()
            if 'font-size: 24px' in ss or 'font-size:24px' in ss:
                lbl.setStyleSheet(f"color: {_t.ON_SURFACE}; font-family: '{_t.FONT_DISPLAY}'; font-size: 24px; font-weight: bold; background: transparent;")
            elif 'letter-spacing: 2px' in ss:
                lbl.setStyleSheet(f"color: {_t.ON_SURFACE_VAR}; font-family: '{_t.FONT_MONO}'; font-size: 13px; letter-spacing: 2px; background: transparent;")
            elif 'font-size: 20px' in ss or 'font-size:20px' in ss:
                lbl.setStyleSheet(f"color: {_t.ON_SURFACE}; font-family: '{_t.FONT_DISPLAY}'; font-size: 20px; font-weight: bold; background: transparent;")
            elif 'font-size: 15px' in ss or 'font-size:15px' in ss:
                lbl.setStyleSheet(f"color: {_t.ON_SURFACE_VAR}; font-family: '{_t.FONT_BODY}'; font-size: 15px; background: transparent;")
            elif 'padding: 6px 14px' in ss or 'padding:6px 14px' in ss:
                lbl.setStyleSheet(f"color: {_t.PRIMARY_CONTAINER}; background-color: {_t.SURFACE_DIM}; padding: 6px 14px; border-radius: 8px; border: 1px solid {_t.OUTLINE_VARIANT}; font-weight: bold; font-family: '{_t.FONT_MONO}';")


