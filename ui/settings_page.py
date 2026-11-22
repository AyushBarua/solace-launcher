"""
SettingsPage - Two-level panel navigation.
Visual hierarchy:
  • Panel (context):  subtle left accent bar — "you're somewhere here"
  • Control (action): entire row glows gold — impossible to miss
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QHBoxLayout,
                             QScrollArea, QFrame, QGraphicsDropShadowEffect, QPushButton)
from PyQt6.QtCore import Qt, QPropertyAnimation, pyqtProperty, QRectF, QTimer
from PyQt6.QtGui import QPainter, QLinearGradient, QColor, QPainterPath, QPen
import sys

from core import app_flags
from ui import glass as _g
from ui.floating_scrollbar import FloatingScrollBar
from ui.glass import (GlassCard, is_dark as _is_dark_theme, pane_edge as _pane_edge,
                      SHADOW_PAD)
from core.theme import (FONT_DISPLAY, ON_SURFACE, PRIMARY_CONTAINER,
                        ON_SURFACE_VAR, PRIMARY_FIXED, ON_PRIMARY_FIXED_VARIANT,
                        SURFACE_DIM, OUTLINE_VARIANT, SURFACE_VARIANT, FONT_BODY, OUTLINE,
                        SURFACE_CON_LOW, SURFACE_CON)

PAGE_EDGE = 40                          # where the visible cards start, from the window edge
PAGE_MARGIN = PAGE_EDGE - SHADOW_PAD    # cards carry their own shadow margin
MAX_CONTENT_WIDTH = 1240
PANEL_RADIUS = 36
ROW_RADIUS = 26

# Short names for the quick-jump chips under the page title.
_JUMP_NAMES = {
    "Controller Calibration": "Controller", "Game Difficulty": "Difficulty",
    "Display Parameters": "Display", "Audio Output": "Audio",
}


def _row_qss(active: bool) -> str:
    """Soft tile for one setting; the focused one glows in the accent colour."""
    import core.theme as _t
    from core.theme import hex_rgba
    if active:
        return (f"QFrame#controlRow {{ background: {hex_rgba(_t.PRIMARY_CONTAINER, 0.12)};"
                f" border: 2px solid {_t.PRIMARY_CONTAINER}; border-radius: {ROW_RADIUS}px; }}")
    return (f"QFrame#controlRow {{ background: {_g.tint(0.04)};"
            f" border: 2px solid transparent; border-radius: {ROW_RADIUS}px; }}")


def _title_qss() -> str:
    import core.theme as _t
    return (f"color:{_t.ON_SURFACE}; font-family:'{_t.FONT_DISPLAY}'; "
            f"font-size:22px; font-weight:bold; background:transparent; border:none;")


def _desc_qss() -> str:
    import core.theme as _t
    return (f"color:{_t.ON_SURFACE_VAR}; font-family:'{_t.FONT_BODY}'; "
            f"font-size:16px; background:transparent; border:none;")


def _chip_qss() -> str:
    """The value readout (ON / 1.0x / 85%) shown beside a control."""
    import core.theme as _t
    return (f"color:{_t.PRIMARY_CONTAINER}; background:{_g.tint(0.08)}; border:none; "
            f"padding:6px 18px; border-radius:16px; font-weight:bold; "
            f"font-family:'{_t.FONT_DISPLAY}'; font-size:17px; min-width:34px;")


def _pill_button_qss() -> str:
    import core.theme as _t
    return (f"QPushButton {{ background-color:{_t.PRIMARY}; color:{_t.ON_PRIMARY};"
            f" font-family:'{_t.FONT_DISPLAY}'; font-size:16px; font-weight:bold;"
            f" border-radius:24px; border:none; padding:0 22px; }}"
            f"QPushButton:hover {{ background-color:{_g.hover_ink()}; }}")


def _danger_button_qss() -> str:
    """Red pill for buttons that destroy data."""
    import core.theme as _t
    fill, hover = ("#E5574C", "#F06E63") if _is_dark_theme() else ("#C93A32", "#B02F28")
    return (f"QPushButton {{ background-color:{fill}; color:#FFFFFF;"
            f" font-family:'{_t.FONT_DISPLAY}'; font-size:16px; font-weight:bold;"
            f" border-radius:24px; border:none; padding:0 22px; }}"
            f"QPushButton:hover {{ background-color:{hover}; }}")


def _new_row(title: str, desc: str, vertical: bool = False):
    """A setting row: returns (frame, controls layout, title label, description label).

    Horizontal rows put the control at the right of the text; vertical rows (sliders)
    put a header line (text + readout) above a full-width control.
    """
    inner = QFrame()
    inner.setObjectName("controlRow")
    inner.setStyleSheet(_row_qss(False))
    t = QLabel(title)
    t.setStyleSheet(_title_qss())
    d = QLabel(desc)
    d.setStyleSheet(_desc_qss())
    d.setWordWrap(True)
    text = QVBoxLayout()
    text.setSpacing(3)
    text.addWidget(t)
    text.addWidget(d)
    if vertical:
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 18, 24, 14)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(16)
        head.addLayout(text, 1)
        lay.addLayout(head)
        return inner, head, t, d
    lay = QHBoxLayout(inner)
    lay.setContentsMargins(24, 18, 24, 18)
    lay.setSpacing(16)
    lay.addLayout(text, 1)
    return inner, lay, t, d


def _install_selection(inner, control, t, d, chip=None):
    """Give a row the select / action hooks the page's navigation expects."""
    inner.control = control
    inner._active = False

    def set_selected(active, _inner=inner, _control=control, _t=t, _d=d, _chip=chip):
        _inner._active = active
        _inner.setStyleSheet(_row_qss(active))
        _t.setStyleSheet(_title_qss())
        _d.setStyleSheet(_desc_qss())
        if _chip is not None:
            _chip.setStyleSheet(_chip_qss())
        if hasattr(_control, "set_selected"):
            _control.set_selected(active)

    inner.set_selected = set_selected
    inner.action = control.action if hasattr(control, "action") else (lambda: None)


# ─────────────────────────────────────────────────────────────────────────────
# ToggleSwitch
# ─────────────────────────────────────────────────────────────────────────────
TOGGLE_W, TOGGLE_H, TOGGLE_KNOB = 100, 52, 44
TOGGLE_OFF_X = 4
TOGGLE_ON_X = TOGGLE_W - TOGGLE_KNOB - 4


class ToggleSwitch(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(TOGGLE_W, TOGGLE_H)
        self._is_on = False
        self._knob_pos = TOGGLE_OFF_X
        self._animation = QPropertyAnimation(self, b"knobPos")
        self._animation.setDuration(250)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.is_selected = False

    def set_selected(self, selected):
        self.is_selected = selected
        self.update()

    def action(self):
        self._is_on = not self._is_on
        self._animation.setEndValue(TOGGLE_ON_X if self._is_on else TOGGLE_OFF_X)
        self._animation.start()
        if hasattr(self, 'toggled_cb'):
            self.toggled_cb(self._is_on)

    @pyqtProperty(int)
    def knobPos(self): return self._knob_pos

    @knobPos.setter
    def knobPos(self, pos):
        self._knob_pos = pos
        self.update()

    def mousePressEvent(self, e):
        # Accept the press so Qt delivers the matching release to this widget;
        # without this a real mouse click never reached mouseReleaseEvent.
        e.accept()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.action()

    def paintEvent(self, e):
        import core.theme as _t
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(Qt.PenStyle.NoPen)
        dark = _is_dark_theme()
        on_col = _t.PRIMARY_CONTAINER if dark else _t.PRIMARY      # off-white would hide the white knob
        off_col = _t.SURFACE_CON_HIGH2 if dark else "#D9D5CB"
        p.setBrush(QColor(on_col) if self._is_on else QColor(off_col))
        p.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        if self.is_selected:                       # focus ring for keyboard / controller
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(_t.PRIMARY_CONTAINER), 3))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1),
                              TOGGLE_H / 2 - 1, TOGGLE_H / 2 - 1)
        kr = QRectF(float(self._knob_pos), 4.0, TOGGLE_KNOB, TOGGLE_KNOB)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawEllipse(kr.translated(0, 2))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(kr)


# ─────────────────────────────────────────────────────────────────────────────
# CustomSlider
# ─────────────────────────────────────────────────────────────────────────────
class CustomSlider(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(64)
        self._value = 0.66
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.is_selected = False

    def set_selected(self, selected):
        self.is_selected = selected
        self.update()

    def action(self):
        val = self._value + 0.25
        if val > 1.05: val = 0.0
        if getattr(self, 'is_difficulty', False):
            if self._value < 0.25:   val = 0.5
            elif self._value < 0.75: val = 1.0
            else:                    val = 0.0
        self._value = val
        self.update()
        if hasattr(self, 'value_changed_cb'):
            self.value_changed_cb(self._value)

    def paintEvent(self, e):
        import core.theme as _t
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        ty, th, kd = 26.0, 12.0, 40.0
        p.setPen(Qt.PenStyle.NoPen)
        dark = _is_dark_theme()
        accent = _t.PRIMARY_CONTAINER if dark else _t.PRIMARY
        p.setBrush(QColor(_t.SURFACE_CON_HIGH2 if dark else "#E3DFD5"))
        p.drawRoundedRect(QRectF(0, ty, w, th), th / 2, th / 2)
        fw = w * self._value
        p.setBrush(QColor(accent))
        p.drawRoundedRect(QRectF(0, ty, max(fw, th), th), th / 2, th / 2)

        tx = max(0.0, min(fw - kd / 2, w - kd))
        knob = QRectF(tx, ty + th / 2 - kd / 2, kd, kd)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawEllipse(knob.translated(0, 2))
        ring = QColor(_t.PRIMARY_CONTAINER) if self.is_selected else QColor(accent)
        p.setBrush(QColor("#FFFFFF"))
        p.setPen(QPen(ring, 4 if self.is_selected else 3))
        p.drawEllipse(knob.adjusted(1.5, 1.5, -1.5, -1.5))

    def mousePressEvent(self, e): self._set(e.position().x())
    def mouseMoveEvent(self, e):  self._set(e.position().x())
    def _set(self, x):
        self._value = max(0.0, min(1.0, x/self.width()))
        self.update()
        if hasattr(self, 'value_changed_cb'):
            self.value_changed_cb(self._value)


# ─────────────────────────────────────────────────────────────────────────────
# SettingsPanel — frosted card; its accent bar lights while the controller is inside
# ─────────────────────────────────────────────────────────────────────────────
class SettingsPanel(GlassCard):
    """A frosted card holding one group of settings (the `icon` argument is ignored)."""

    def __init__(self, title: str, icon: str = "", parent=None):
        super().__init__(radius=PANEL_RADIUS, alpha=225, parent=parent)
        self.title = title
        self.controls: list = []   # row frames with set_selected() / action()

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(34, 28, 34, 24)
        self._layout.setSpacing(10)

        hdr = QHBoxLayout()
        self._accent_bar = QLabel()               # lights up while the controller is in this card
        self._accent_bar.setFixedSize(5, 30)
        self._accent_bar.setStyleSheet("background: transparent; border-radius: 2px;")
        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet(self._title_qss())
        hdr.addWidget(self._accent_bar)
        hdr.addSpacing(12)
        hdr.addWidget(self._title_lbl)
        hdr.addStretch()
        self._layout.addLayout(hdr)
        self._layout.addSpacing(4)

    @staticmethod
    def _title_qss() -> str:
        import core.theme as _t
        return (f"color:{_t.ON_SURFACE}; font-family:'{_t.FONT_DISPLAY}'; "
                f"font-size:30px; font-weight:800; letter-spacing:-0.01em; "
                f"background:transparent; border:none;")

    def content_layout(self): return self._layout

    def set_panel_active(self, active: bool):
        import core.theme as _t
        self._accent_bar.setStyleSheet(
            f"background: {_t.PRIMARY_CONTAINER}; border-radius: 2px;"
            if active else
            "background: transparent; border-radius: 2px;"
        )

    def refresh_theme(self):
        """Re-apply colours with the current theme globals."""
        self._title_lbl.setStyleSheet(self._title_qss())
        self.update()


# ─────────────────────────────────────────────────────────────────────────────
# Main Settings Page
# ─────────────────────────────────────────────────────────────────────────────
class SettingsPage(QScrollArea):
    def __init__(self, processor=None, parent=None):
        super().__init__(parent)
        self._processor = processor
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._floating_bar = FloatingScrollBar(self)       # slim thumb over the edge, not a native bar

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self.setWidget(container)

        outer = QHBoxLayout(container)
        outer.setContentsMargins(PAGE_MARGIN, 10, PAGE_MARGIN, 80)
        outer.addStretch(1)
        content = QWidget()
        content.setMaximumWidth(MAX_CONTENT_WIDTH)
        outer.addWidget(content, 100)
        outer.addStretch(1)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        head = QVBoxLayout()
        head.setContentsMargins(SHADOW_PAD, 0, SHADOW_PAD, 0)
        head.setSpacing(6)
        self._eyebrow_lbl = QLabel("PREFERENCES")
        self._title_lbl = QLabel("Settings")
        self._desc_lbl = QLabel("Adjust interface and accessibility options to fit your needs.")
        head.addWidget(self._eyebrow_lbl)
        head.addWidget(self._title_lbl)
        head.addWidget(self._desc_lbl)
        layout.addLayout(head)
        self._style_header()
        self._jump_row = QHBoxLayout()            # filled once the panels exist
        self._jump_row.setContentsMargins(SHADOW_PAD, 18, SHADOW_PAD, 8)
        self._jump_row.setSpacing(10)
        layout.addLayout(self._jump_row)

        self._panels: list[SettingsPanel] = []
        self._panel_idx   = 0
        self._control_idx = 0

        self._build_calibration_panel(layout)
        self._build_difficulty_panel(layout)
        self._build_accessibility_panel(layout)
        self._build_language_panel(layout)
        self._build_display_panel(layout)
        self._build_audio_panel(layout)
        self._build_account_panel(layout)   # F1
        self._build_therapist_panel(layout)
        self._build_developer_panel(layout)

        layout.addStretch()
        self._build_jump_chips()
        if self._panels:
            self._apply_focus()

    # ── Header ────────────────────────────────────────────────────────────────

    def _style_header(self):
        import core.theme as _t
        self._eyebrow_lbl.setStyleSheet(
            f"color:{_t.ON_SURFACE_VAR}; font-family:'{_t.FONT_DISPLAY}'; font-size:15px;"
            f" font-weight:700; letter-spacing:0.14em; background:transparent;")
        self._title_lbl.setStyleSheet(
            f"color:{_t.ON_SURFACE}; font-family:'{_t.FONT_DISPLAY}'; font-size:56px;"
            f" font-weight:800; letter-spacing:-0.02em; background:transparent;")
        self._desc_lbl.setStyleSheet(
            f"color:{_t.ON_SURFACE_VAR}; font-family:'{_t.FONT_BODY}'; font-size:19px;"
            f" background:transparent;")

    @staticmethod
    def _jump_chip_qss() -> str:
        import core.theme as _t
        return (f"QPushButton {{ background:{_g.pane_bg(0.8)}; color:{_t.ON_SURFACE};"
                f" border:1px solid {_g.pane_edge()}; border-radius:20px; padding:0 20px;"
                f" font-family:'{_t.FONT_DISPLAY}'; font-size:16px; font-weight:bold; }}"
                f"QPushButton:hover {{ background:{_g.hover_pane()}; }}")

    def _build_jump_chips(self):
        """A row of pills under the title that scroll straight to a panel."""
        self._jump_btns = []
        for i, panel in enumerate(self._panels):
            btn = QPushButton(_JUMP_NAMES.get(panel.title, panel.title))
            btn.setFixedHeight(40)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(self._jump_chip_qss())
            btn.clicked.connect(lambda _=False, idx=i: self._jump_to(idx))
            self._jump_row.addWidget(btn)
            self._jump_btns.append(btn)
        self._jump_row.addStretch()

    def _jump_to(self, panel_index: int):
        self._panel_idx = panel_index
        self._control_idx = 0
        self._apply_focus()

    # ── Navigation API ────────────────────────────────────────────────────────

    def navigate(self, direction: int):
        panel = self._panels[self._panel_idx]
        new_ctrl = self._control_idx + direction

        if 0 <= new_ctrl < len(panel.controls):
            self._control_idx = new_ctrl
        else:
            new_panel = self._panel_idx + direction
            if 0 <= new_panel < len(self._panels):
                self._panel_idx = new_panel
                n = len(self._panels[new_panel].controls)
                self._control_idx = 0 if direction == 1 else max(0, n-1)
        self._apply_focus()

    def activate_selected(self):
        panel = self._panels[self._panel_idx]
        if 0 <= self._control_idx < len(panel.controls):
            panel.controls[self._control_idx].action()

    # Backward compat
    @property
    def items(self):
        return [c for p in self._panels for c in p.controls]

    @property
    def selected_idx(self):
        return sum(len(p.controls) for p in self._panels[:self._panel_idx]) + self._control_idx

    def set_selected_index(self, flat_idx: int):
        idx = 0
        for pi, panel in enumerate(self._panels):
            for ci in range(len(panel.controls)):
                if idx == flat_idx:
                    self._panel_idx = pi; self._control_idx = ci
                    self._apply_focus(); return
                idx += 1

    def get_selected_item(self):
        panel = self._panels[self._panel_idx]
        if 0 <= self._control_idx < len(panel.controls):
            return panel.controls[self._control_idx]
        return None

    def handle_gamepad_action(self, action: str):
        if action == 'up':    self.navigate(-1)
        elif action == 'down': self.navigate(1)
        elif action in ('action','enter'): self.activate_selected()

    # ── Focus rendering ───────────────────────────────────────────────────────

    def _apply_focus(self):
        for pi, panel in enumerate(self._panels):
            panel_active = (pi == self._panel_idx)
            panel.set_panel_active(panel_active)
            for ci, ctrl in enumerate(panel.controls):
                ctrl.set_selected(panel_active and ci == self._control_idx)
        self.ensureWidgetVisible(self._panels[self._panel_idx], 0, 60)

    def refresh_theme(self):
        """Re-apply all theme colours to every panel and control row."""
        from core.theme import (ON_SURFACE, ON_SURFACE_VAR, FONT_DISPLAY,
                                 FONT_BODY, PRIMARY_CONTAINER, SURFACE_DIM,
                                 OUTLINE_VARIANT)
        # Refresh panel backgrounds
        for panel in self._panels:
            panel.refresh_theme()
        # Re-apply focus (which calls set_panel_active / set_selected with fresh colors)
        if self._panels:
            self._apply_focus()
        self._style_header()
        for btn in getattr(self, '_jump_btns', []):
            btn.setStyleSheet(self._jump_chip_qss())

        # Force repaint of widgets that draw with live theme colors
        for widget in self.widget().findChildren(__import__('PyQt6.QtWidgets', fromlist=['QWidget']).QWidget):
            if type(widget).__name__ in ('ToggleSwitch', 'CustomSlider'):
                widget.update()

    # ── Panel / row builders ──────────────────────────────────────────────────

    def _add_panel(self, title, icon, parent_layout) -> SettingsPanel:
        p = SettingsPanel(title, icon)
        self._panels.append(p)
        parent_layout.addWidget(p)
        return p

    def _add_slider_row(self, panel: SettingsPanel, title: str, desc: str,
                        value_text: str, slider: CustomSlider) -> QLabel:
        """Header line (text and readout chip) above a full-width slider."""
        inner, head, t, d = _new_row(title, desc, vertical=True)
        val_lbl = QLabel(value_text)
        val_lbl.setStyleSheet(_chip_qss())
        head.addWidget(val_lbl, 0, Qt.AlignmentFlag.AlignTop)
        inner.layout().addWidget(slider)
        _install_selection(inner, slider, t, d, val_lbl)
        panel.content_layout().addWidget(inner)
        panel.controls.append(inner)
        return val_lbl

    def _add_toggle_row(self, panel: SettingsPanel, title: str, desc: str,
                        default_on: bool = False) -> ToggleSwitch:
        toggle = ToggleSwitch()
        if default_on:
            toggle._is_on = True
            toggle._knob_pos = TOGGLE_ON_X

        val_lbl = QLabel("ON" if default_on else "OFF")
        val_lbl.setStyleSheet(_chip_qss())
        orig_action = toggle.action

        def _action(_t=toggle, _l=val_lbl, _orig=orig_action):
            _orig()
            _l.setText("ON" if _t._is_on else "OFF")
        toggle.action = _action

        inner, lay, t, d = _new_row(title, desc)
        lay.addWidget(val_lbl)
        lay.addWidget(toggle)
        _install_selection(inner, toggle, t, d, val_lbl)
        panel.content_layout().addWidget(inner)
        panel.controls.append(inner)
        return toggle

    def _add_button_row(self, panel: SettingsPanel, title: str, desc: str,
                        btn_label: str, action_fn):
        btn = QPushButton(btn_label)
        btn.setFixedHeight(48)
        btn.setMinimumWidth(150)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(_pill_button_qss())
        btn.clicked.connect(action_fn)

        inner, lay, t, d = _new_row(title, desc)
        lay.addWidget(btn)
        _install_selection(inner, btn, t, d)
        inner.action = action_fn
        panel.content_layout().addWidget(inner)
        panel.controls.append(inner)
        return btn

    def _build_calibration_panel(self, layout):
        if not self._processor:
            # P2: Show a clear placeholder instead of silent blank space
            p = self._add_panel("Controller Calibration", "🎮", layout)
            placeholder = QWidget()
            ph_layout = QVBoxLayout(placeholder)
            ph_layout.setContentsMargins(16, 20, 16, 20)
            ph_layout.setSpacing(10)
            ph_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            msg = QLabel(
                "No controller detected.\n"
                "Plug in your Solace sensor or hand controller,\n"
                "then restart the app or click Refresh."
            )
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setWordWrap(True)
            msg.setStyleSheet(
                f"color:{ON_SURFACE_VAR}; font-family:'{FONT_BODY}'; "
                f"font-size:17px; background:transparent; border:none;"
            )

            refresh_btn = QPushButton("Refresh")
            refresh_btn.setFixedSize(160, 44)
            refresh_btn.setStyleSheet(
                f"QPushButton {{ background:{PRIMARY_CONTAINER}; color:#0d0b09; "
                f"border:none; border-radius:22px; font-size:14px; font-weight:bold; }}"
                f"QPushButton:hover {{ background:{PRIMARY_FIXED}; }}"
            )

            def _refresh():
                from PyQt6.QtWidgets import QApplication
                import importlib
                # Try to late-import the processor — works when controller plugged in after launch
                try:
                    from core.input_processor import InputProcessor
                    proc = InputProcessor()
                    from core.controller import GamepadThread
                    # Check if controller is now available
                    test = GamepadThread(proc, None)
                    test.start()
                    import time; time.sleep(0.4)
                    if test.is_running():
                        msg.setText("Controller detected! Restart Solace to enable calibration.")
                        test.quit()
                    else:
                        msg.setText("Still no controller found. Check USB connection and try again.")
                        test.quit()
                except Exception as ex:
                    msg.setText(f"Could not detect controller: {ex}")

            refresh_btn.clicked.connect(_refresh)

            ph_layout.addWidget(msg)
            ph_layout.addWidget(refresh_btn, alignment=Qt.AlignmentFlag.AlignCenter)
            p.content_layout().addWidget(placeholder)
            return

        p = self._add_panel("Controller Calibration", "🎮", layout)
        
        from ui.input_settings_card import InputSettingsCard
        self.input_card = InputSettingsCard(self._processor)
        self.input_card.hide_interactive_controls()
        # The panel is already a card: flatten the nested one and drop its duplicate title.
        self.input_card.setStyleSheet("QFrame#inputCard { background: transparent; border: none; }")
        self.input_card.layout().setContentsMargins(4, 4, 4, 4)
        for lbl in self.input_card.findChildren(QLabel):
            if lbl.text() == "Controller Input":
                lbl.hide()
        p.content_layout().addWidget(self.input_card)
        
        self._add_button_row(
            p, "Calibrate Neutral Position", "Captures current sensor reading as the zero / neutral point.",
            "Calibrate", lambda: self._processor.calibrate(*self.input_card._last_raw)
        )
        
        def set_flip(is_x, val):
            if is_x:
                self._processor.flip_x = val
            else:
                self._processor.flip_y = val
            self._processor.save()
            
        t_x = self._add_toggle_row(p, "Flip X-axis", "Invert the horizontal axis.", default_on=self._processor.flip_x)
        t_x.toggled_cb = lambda v: set_flip(True, v)
        
        t_y = self._add_toggle_row(p, "Flip Y-axis", "Invert the vertical axis.", default_on=self._processor.flip_y)
        t_y.toggled_cb = lambda v: set_flip(False, v)
        
        s_sens = CustomSlider()
        s_sens._value = min(1.0, max(0.0, (self._processor.sensitivity - 0.5) / 2.5))
        lbl_sens = self._add_slider_row(p, "Sensitivity", "How much a small tilt moves the cursor.", "1.0x", s_sens)
        def on_sens(val):
            real_val = 0.5 + (val * 2.5)
            self._processor.sensitivity = real_val
            self._processor.save()
            lbl_sens.setText(f"{real_val:.1f}x")
        s_sens.value_changed_cb = on_sens
        on_sens(s_sens._value)
        
        s_dead = CustomSlider()
        s_dead._value = min(1.0, max(0.0, self._processor.inner_dead_zone / 0.6))
        lbl_dead = self._add_slider_row(p, "Dead-zone", "Ignore tilt smaller than this threshold.", "15%", s_dead)
        def on_dead(val):
            real_val = val * 0.6
            self._processor.inner_dead_zone = real_val
            self._processor.save()
            lbl_dead.setText(f"{int(real_val * 100)}%")
        s_dead.value_changed_cb = on_dead
        on_dead(s_dead._value)

    # ── Specific panels ───────────────────────────────────────────────────────

    def _build_difficulty_panel(self, parent_layout):
        import os, json
        panel = self._add_panel("Game Difficulty", "🎮", parent_layout)
        s = CustomSlider(); s.is_difficulty = True

        val_lbl = self._add_slider_row(panel,
            "Global Speed Multiplier",
            "Adjust the speed of games (0.25x Slow · 0.5x Medium · 1.0x Fast).",
            "1.0x", s)

        from core.paths import get_data_dir
        sp = os.path.join(get_data_dir(), "global_settings.json")

        def save(v):
            if v < 0.25:   mult, s._value = 0.25, 0.0
            elif v < 0.75: mult, s._value = 0.5, 0.5
            else:          mult, s._value = 1.0, 1.0
            try:
                # Read-modify-write to preserve all other settings keys
                existing = {}
                try:
                    with open(sp, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                except Exception:
                    pass
                existing["difficulty_multiplier"] = mult
                tmp = sp + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(existing, f, indent=2)
                import os as _os; _os.replace(tmp, sp)
            except Exception:
                pass
            val_lbl.setText(f"{mult:.2f}x" if mult == 0.25 else f"{mult:.1f}x")
            s.update()

        try:
            with open(sp) as f:
                mult = json.load(f).get("difficulty_multiplier", 1.0)
                s._value = 0.0 if mult<=0.25 else 0.5 if mult<=0.5 else 1.0
                val_lbl.setText(f"{mult:.2f}x" if mult==0.25 else f"{mult:.1f}x")
        except: s._value = 1.0
        s.value_changed_cb = save

    def _build_accessibility_panel(self, parent_layout):
        from core.theme import save_theme, get_active_theme_name
        import subprocess, sys, os

        panel = self._add_panel("Accessibility", "✨", parent_layout)

        is_dark = get_active_theme_name() == "dark"
        t = self._add_toggle_row(panel, "High Contrast Mode",
            "ON = dark theme · OFF = light theme (default).",
            default_on=is_dark)

        def on_contrast_toggled(is_on):
            from core.theme import save_theme, switch_theme_live
            theme_name = "dark" if is_on else "light"
            save_theme(theme_name)
            switch_theme_live(theme_name)

            # Find main window and do a live in-process cross-fade
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            for w in app.topLevelWidgets():
                if hasattr(w, 'apply_theme_live'):
                    w.apply_theme_live(theme_name)
                    break



        t.toggled_cb = on_contrast_toggled

        self._add_toggle_row(panel, "Screen Reader Output",
            "Enables tactile and auditory feedback for interface navigation.")

    def _build_display_panel(self, parent_layout):
        from core.theme import save_ui_scale, get_ui_scale

        panel = self._add_panel("Display Parameters", "🖥️", parent_layout)
        s = CustomSlider()

        # Map saved scale (1.0–1.5) → slider value (0.0–1.0)
        current_scale = get_ui_scale()
        s._value = max(0.0, min(1.0, (current_scale - 1.0) / 0.5))
        current_pct = int(round(current_scale * 100))

        val_lbl = self._add_slider_row(
            panel, "Interface Scale",
            "Scales all UI elements in real time.",
            f"{current_pct}%", s
        )

        def on_scale(v):
            scale = 1.0 + v * 0.5          # 0–1 → 1.0–1.5
            val_lbl.setText(f"{int(round(scale * 100))}%")
            save_ui_scale(scale)
            # Real-time: update main window scale without restart
            from PyQt6.QtWidgets import QApplication
            for win in QApplication.instance().topLevelWidgets():
                if hasattr(win, 'set_ui_scale'):
                    win.set_ui_scale(scale)
                    break

        s.value_changed_cb = on_scale


    def _build_language_panel(self, parent_layout):
        """Language / भाषा: English / Hindi switcher."""
        from core.i18n import set_language, get_language

        panel = self._add_panel("Language / भाषा", "", parent_layout)
        inner, inner_layout, t_lbl, d_lbl = _new_row(
            "Interface language", "Choose the interface language.  /  इंटरफ़ेस की भाषा चुनें।")

        langs = [("en", "English"), ("hi", "हिंदी")]
        self._lang_btns = {}

        def _btn_qss(active: bool) -> str:
            import core.theme as _t
            if active:
                return (f"QPushButton {{ background:{_t.PRIMARY}; color:{_t.ON_PRIMARY};"
                        f" border:none; border-radius:22px; font-size:17px; font-weight:bold; }}")
            return (f"QPushButton {{ background:{_g.tint(0.07)}; color:{_t.ON_SURFACE_VAR};"
                    f" border:none; border-radius:22px; font-size:17px; font-weight:bold; }}"
                    f"QPushButton:hover {{ background:{_g.tint(0.12)}; color:{_t.ON_SURFACE}; }}")

        current = get_language()
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        for code, label in langs:
            btn = QPushButton(label)
            btn.setFixedSize(130, 46)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_btn_qss(code == current))
            self._lang_btns[code] = btn

            def _on_click(_checked=False, _code=code):
                set_language(_code, save=True)
                for c, b in self._lang_btns.items():
                    b.setStyleSheet(_btn_qss(c == _code))

            btn.clicked.connect(_on_click)
            btn_row.addWidget(btn)
        inner_layout.addLayout(btn_row)

        inner.control = self._lang_btns.get("en")
        inner._active = False

        def _set_selected(active, _inner=inner, _t=t_lbl, _d=d_lbl):
            _inner._active = active
            _inner.setStyleSheet(_row_qss(active))
            _t.setStyleSheet(_title_qss())
            _d.setStyleSheet(_desc_qss())

        inner.set_selected = _set_selected
        inner.action = lambda: None

        panel.content_layout().addWidget(inner)
        panel.controls.append(inner)

    def _build_audio_panel(self, parent_layout):
        panel = self._add_panel("Audio Output", "🔊", parent_layout)
        s = CustomSlider(); s._value = 0.85
        self._add_slider_row(panel, "Master Volume", "Global system audio level.", "85%", s)

    def _build_account_panel(self, parent_layout):
        """F1: Password change and account management."""
        panel = self._add_panel("Account", "🔐", parent_layout)

        # Status label — shared between all button actions
        self._acct_status = QLabel("")
        self._acct_status.setStyleSheet(
            f"color:{PRIMARY_CONTAINER}; font-family:'{FONT_BODY}'; "
            f"font-size:14px; background:transparent;"
        )
        self._acct_status.setWordWrap(True)
        self._acct_status.setVisible(False)
        panel.content_layout().addWidget(self._acct_status)

        needs_login = app_flags.REQUIRE_LOGIN
        if needs_login:
            self._add_button_row(
                panel,
                "Change Password",
                "Update your login password. You’ll need your current password.",
                "Change",
                self._open_change_password_dialog,
            )

        self._add_button_row(
            panel,
            "Log Out" if needs_login else "Switch Profile",
            "Switch to a different profile or sign out of this one." if needs_login
            else "Go back to the profile chooser and pick who is playing.",
            "Log Out" if needs_login else "Switch",
            self._do_logout,
        )

        self._add_button_row(
            panel,
            "Profile Lock (PIN)",
            "Optional. A 4-digit PIN keeps this profile private on a shared home "
            "device. Off by default.",
            "Set PIN",
            self._set_profile_pin,
        )

        delete_btn = self._add_button_row(
            panel,
            "Delete Account" if needs_login else "Delete Profile",
            "Permanently erase this profile — login, sessions, baseline and "
            "settings. This cannot be undone." if needs_login else
            "Permanently erase this profile — sessions, baseline and "
            "settings. This cannot be undone.",
            "Delete",
            self._confirm_delete_account,
        )
        delete_btn.setStyleSheet(_danger_button_qss())

    def _set_profile_pin(self):
        from PyQt6.QtWidgets import QInputDialog
        from core.profile_manager import get_active_profile, set_profile_pin
        prof = get_active_profile() or {}
        if not prof.get("id"):
            return
        parent = self._get_main_window()
        cur = prof.get("pin")
        if cur:
            val, ok = QInputDialog.getText(parent, "Profile PIN", "Enter current PIN:")
            if not ok or val != cur:
                return
        new, ok = QInputDialog.getText(
            parent, "Profile PIN",
            "New 4-digit PIN (blank removes the lock):")
        if not ok:
            return
        new = new.strip()
        if new and (not new.isdigit() or len(new) != 4):
            return
        set_profile_pin(prof["id"], new or None)

    def _show_cloud_status(self):
        from core.cloud_sync import status
        from core.profile_manager import get_active_profile
        prof = get_active_profile() or {}
        acct = prof.get("auth_id") or prof.get("id")
        self._confirm(self, "Cloud Backup", status(acct))

    @staticmethod
    def _get_main_window():
        """The settings page lives inside a QGraphicsProxyWidget (UI scaler),
        so self.window() does NOT reach the real MainWindow — find it via
        the application's top-level widgets instead."""
        from PyQt6.QtWidgets import QApplication
        for w in QApplication.topLevelWidgets():
            if hasattr(w, "_switch_profile") and hasattr(w, "gamepad"):
                return w
        return None

    @classmethod
    def _confirm(cls, parent, title: str, text: str, danger: bool = False) -> bool:
        """Theme-styled confirmation dialog.

        IMPORTANT: parented to the real MainWindow, NOT the settings page —
        the settings page lives inside a QGraphicsProxyWidget (UI scaler),
        and a dialog parented to a proxied widget renders as a blank window.
        """
        from PyQt6.QtWidgets import QMessageBox
        real_parent = cls._get_main_window()
        m = QMessageBox(real_parent)
        m.setWindowTitle(title)
        m.setText(text)
        m.setStandardButtons(QMessageBox.StandardButton.Yes
                             | QMessageBox.StandardButton.Cancel)
        m.setDefaultButton(QMessageBox.StandardButton.Cancel)
        accent = "#c0392b" if danger else "#8a7f4f"
        m.setStyleSheet(f"""
            QMessageBox {{ background: #1e1c17; }}
            QMessageBox QLabel {{ color: #e8e4da; font-size: 14px; }}
            QPushButton {{
                background: #2a2822; color: #e8e4da;
                border: 1px solid #4a463c; border-radius: 8px;
                padding: 8px 20px; min-width: 90px; font-size: 13px;
            }}
            QPushButton:hover {{ background: {accent}; color: #ffffff; }}
        """)
        return m.exec() == QMessageBox.StandardButton.Yes

    def _do_logout(self):
        mw = self._get_main_window()
        if mw is not None:
            mw._switch_profile()
        else:
            print("[Settings] Log out: main window not found")

    def _build_therapist_panel(self, parent_layout):
        """§4B Tier 1 — clinician guardrails (PIN-gated)."""
        panel = self._add_panel("Therapist", "🩺", parent_layout)
        self._add_button_row(
            panel,
            "Therapist Settings",
            "Clinician-only: set a difficulty ceiling, exclude movements that "
            "aren't ready, and manage the pain rule. PIN protected.",
            "Open",
            self._open_therapist_settings,
        )

    def _active_sm(self):
        mw = self._get_main_window()
        return getattr(mw, "_session_manager", None) if mw else None

    def _open_therapist_settings(self):
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                     QLineEdit, QPushButton, QCheckBox, QSlider)
        from PyQt6.QtCore import Qt
        sm = self._active_sm()
        if sm is None:
            return
        guard = sm.get_guardrails()

        # PIN gate: if a PIN is set, require it; else let them set one now.
        existing_pin = guard.get("pin")
        parent = self._get_main_window()
        if existing_pin:
            dlg = QDialog(parent); dlg.setWindowTitle("Therapist PIN")
            dlg.setStyleSheet("QDialog{background:#1e1c17;} QLabel{color:#e8e4da;}")
            vl = QVBoxLayout(dlg)
            vl.addWidget(QLabel("Enter therapist PIN:"))
            pin_in = QLineEdit(); pin_in.setEchoMode(QLineEdit.EchoMode.Password)
            pin_in.setStyleSheet("background:#2b2b24;color:#fff;padding:6px;border-radius:6px;")
            vl.addWidget(pin_in)
            ok = QPushButton("Unlock"); vl.addWidget(ok)
            ok.clicked.connect(dlg.accept)
            if dlg.exec() != QDialog.DialogCode.Accepted or pin_in.text() != existing_pin:
                return

        dlg = QDialog(parent)
        dlg.setWindowTitle("Therapist Settings")
        dlg.setFixedWidth(460)
        dlg.setStyleSheet("QDialog{background:#1e1c17;} QLabel{color:#e8e4da;} "
                          "QCheckBox{color:#e8e4da;}")
        vl = QVBoxLayout(dlg); vl.setSpacing(14); vl.setContentsMargins(24,24,24,24)

        vl.addWidget(QLabel("<b>Difficulty ceiling</b> — caps how hard games get."))
        cap_lbl = QLabel(f"{int(guard['max_difficulty']*100)}%")
        cap = QSlider(Qt.Orientation.Horizontal); cap.setRange(20,100)
        cap.setValue(int(guard["max_difficulty"]*100))
        cap.valueChanged.connect(lambda v: cap_lbl.setText(f"{v}%"))
        row = QHBoxLayout(); row.addWidget(cap); row.addWidget(cap_lbl); vl.addLayout(row)

        vl.addWidget(QLabel("<b>Exclude movements</b> not ready for loading:"))
        boxes = {}
        excl = set(guard.get("excluded_movements", []))
        for m in ("flexion","extension","pronation","supination"):
            cb = QCheckBox(m.capitalize()); cb.setChecked(m in excl)
            boxes[m] = cb; vl.addWidget(cb)

        pain_cb = QCheckBox("Extra gentle after a painful session")
        pain_cb.setChecked(guard.get("pain_caution", True)); vl.addWidget(pain_cb)

        # SAFETY §1.1 — dose limits
        vl.addWidget(QLabel("<b>Safe dose limits</b> (prevent overexertion):"))
        sess_lbl = QLabel(f"Per-session goal: {guard.get('max_session_min',20)} min")
        sess = QSlider(Qt.Orientation.Horizontal); sess.setRange(5,45)
        sess.setValue(int(guard.get("max_session_min",20)))
        sess.valueChanged.connect(lambda v: sess_lbl.setText(f"Per-session goal: {v} min"))
        vl.addWidget(sess_lbl); vl.addWidget(sess)
        day_lbl = QLabel(f"Daily goal: {guard.get('max_daily_min',45)} min")
        day = QSlider(Qt.Orientation.Horizontal); day.setRange(10,120)
        day.setValue(int(guard.get("max_daily_min",45)))
        day.valueChanged.connect(lambda v: day_lbl.setText(f"Daily goal: {v} min"))
        vl.addWidget(day_lbl); vl.addWidget(day)
        rest_cb = QCheckBox("Suggest a rest break after a long session")
        rest_cb.setChecked(guard.get("rest_reminder", True)); vl.addWidget(rest_cb)

        vl.addWidget(QLabel("<b>Set / change PIN</b> (blank = keep current):"))
        new_pin = QLineEdit(); new_pin.setEchoMode(QLineEdit.EchoMode.Password)
        new_pin.setStyleSheet("background:#2b2b24;color:#fff;padding:6px;border-radius:6px;")
        vl.addWidget(new_pin)

        save = QPushButton("Save"); vl.addWidget(save)
        def _save():
            sm.set_guardrails(
                max_difficulty=cap.value()/100.0,
                excluded_movements=[m for m,cb in boxes.items() if cb.isChecked()],
                pain_caution=pain_cb.isChecked(),
                max_session_min=sess.value(),
                max_daily_min=day.value(),
                rest_reminder=rest_cb.isChecked(),
                pin=(new_pin.text() if new_pin.text() else guard.get("pin")))
            dlg.accept()
        save.clicked.connect(_save)
        dlg.exec()

    def _build_developer_panel(self, parent_layout):
        """Developer-only options."""
        panel = self._add_panel("Developer", "🛠️", parent_layout)
        self._add_button_row(
            panel,
            "Cloud Sync (diagnostic)",
            "Backup is automatic. This just shows the current sync state. "
            "(Simulated until the cloud backend launches.)",
            "Status",
            self._show_cloud_status,
        )
        reset_btn = self._add_button_row(
            panel,
            "Factory Reset",
            "Erase ALL data — profiles, sessions, baselines, milestones and "
            "settings — and restart the app as if freshly installed.",
            "Reset",
            self._confirm_factory_reset,
        )
        reset_btn.setStyleSheet(_danger_button_qss())

    def _confirm_delete_account(self):
        from core.profile_manager import get_active_profile
        profile = get_active_profile() or {}
        name = profile.get("name", "this profile")
        if not profile.get("id"):
            return
        noun = "account" if app_flags.REQUIRE_LOGIN else "profile"
        if not self._confirm(
                self, f"Delete {noun.title()}",
                f"Permanently delete {name}'s {noun}?\n\nAll sessions, the "
                "baseline, milestones and settings will be erased. There is "
                "no undo.", danger=True):
            return
        if self._confirm(
                self, "Are you absolutely sure?",
                f"Final confirmation — {name}'s data will be gone forever.",
                danger=True):
            self._do_delete_account(profile)

    def _do_delete_account(self, profile: dict):
        from core.profile_manager import delete_profile_completely
        from core.session_store import clear_session

        removed = delete_profile_completely(profile["id"])

        # Also remove the linked login credentials (local accounts)
        auth_id = (removed or profile).get("auth_id")
        if auth_id:
            try:
                from core.auth_manager import delete_user
                delete_user(auth_id)
            except Exception as exc:
                print(f"[Settings] auth deletion: {exc}")

        clear_session()
        # Back to the profile/login screen
        mw = self._get_main_window()
        if mw is not None:
            mw._switch_profile()

    def _confirm_factory_reset(self):
        if not self._confirm(
                self, "Factory Reset",
                "This erases EVERY profile, session, baseline and setting on "
                "this machine.\n\nThere is no undo. Continue?", danger=True):
            return
        if self._confirm(
                self, "Are you absolutely sure?",
                "Final confirmation — all patient data will be permanently "
                "deleted and the app will restart empty.", danger=True):
            self._do_factory_reset()

    def _do_factory_reset(self):
        import os, sys, glob, shutil, subprocess, traceback
        from PyQt6.QtWidgets import QApplication
        from core.paths import get_data_dir

        try:
            # 0) Stop background threads FIRST — quitting with the gamepad
            #    QThread still running hard-crashes Qt on teardown.
            mw = self._get_main_window()
            if mw is not None and hasattr(mw, "gamepad"):
                try:
                    mw.gamepad.stop()
                except Exception as exc:
                    print(f"[FactoryReset] gamepad stop: {exc}")

            # 1) Wipe the data directory (profiles, session logs, settings…)
            data_dir = get_data_dir()
            for path in glob.glob(os.path.join(data_dir, "*")):
                try:
                    shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
                except Exception as exc:
                    print(f"[FactoryReset] could not remove {path}: {exc}")

            # 2) Wipe the input calibration config (lives next to the app code)
            try:
                from core import input_processor as _ip
                cfg = os.path.normpath(_ip._CONFIG_PATH)
                if os.path.exists(cfg):
                    os.remove(cfg)
            except Exception as exc:
                print(f"[FactoryReset] input config: {exc}")

            print("[FactoryReset] complete — restarting")
            # 3) Relaunch fresh, then exit this process
            try:
                if getattr(sys, 'frozen', False):
                    subprocess.Popen([sys.executable])
                else:
                    subprocess.Popen([sys.executable] + sys.argv)
            except Exception as exc:
                print(f"[FactoryReset] relaunch failed: {exc}")
        except Exception:
            traceback.print_exc()
        QApplication.instance().quit()

    def _open_change_password_dialog(self):
        """F1: Open a simple inline dialog for password change."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QLabel, QPushButton, QHBoxLayout
        from PyQt6.QtCore import Qt
        from core.profile_manager import get_active_profile

        profile = get_active_profile() or {}
        identifier = profile.get("identifier") or profile.get("id", "")
        if not identifier or profile.get("provider", "local") != "local":
            self._show_acct_status(
                "Password change is only available for email/password accounts.", error=True
            )
            return

        # Parent to the real MainWindow — a dialog parented to this proxied
        # widget renders blank (same bug as the Factory Reset confirms).
        dlg = QDialog(self._get_main_window())
        dlg.setWindowTitle("Change Password")
        dlg.setFixedWidth(420)
        dlg.setStyleSheet("QDialog { background: #1a1a16; border-radius: 12px; }")

        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(28, 24, 28, 24)
        vl.setSpacing(12)

        title = QLabel("Change Password")
        title.setStyleSheet(
            f"color:{ON_SURFACE}; font-family:'{FONT_DISPLAY}'; font-size:24px; font-weight:bold;"
        )
        vl.addWidget(title)

        INPUT_SS = (
            "QLineEdit { background:#2b2b24; border:1px solid #444; border-radius:6px; "
            f"padding:0 12px; color:{ON_SURFACE}; font-family:'{FONT_BODY}'; font-size:14px; height:38px; }}"
            f"QLineEdit:focus {{ border:1px solid {PRIMARY_CONTAINER}; }}"
        )
        fields = {}
        for label_text, attr, placeholder in [
            ("Current password",    "old",     "Enter current password"),
            ("New password",         "new",     "Minimum 6 characters"),
            ("Confirm new password", "confirm", "Repeat new password"),
        ]:
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"color:{ON_SURFACE_VAR}; font-size:13px; background:transparent;")
            vl.addWidget(lbl)
            field = QLineEdit()
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setFixedHeight(40)
            field.setPlaceholderText(placeholder)
            field.setStyleSheet(INPUT_SS)
            vl.addWidget(field)
            fields[attr] = field

        err_lbl = QLabel("")
        err_lbl.setStyleSheet("color:#ff5f56; background:transparent; font-size:13px;")
        err_lbl.setWordWrap(True)
        err_lbl.setVisible(False)
        vl.addWidget(err_lbl)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background:{SURFACE_DIM}; color:{ON_SURFACE_VAR}; "
            f"border:none; border-radius:6px; font-size:14px; }}"
            f"QPushButton:hover {{ background:{OUTLINE_VARIANT}; }}"
        )
        cancel_btn.clicked.connect(dlg.reject)

        save_btn = QPushButton("Update Password")
        save_btn.setFixedHeight(40)
        save_btn.setStyleSheet(
            f"QPushButton {{ background:{PRIMARY_CONTAINER}; color:#0d0b09; "
            f"border:none; border-radius:6px; font-size:14px; font-weight:bold; }}"
            f"QPushButton:hover {{ background:{PRIMARY_FIXED}; }}"
        )

        def _on_save():
            old_pwd = fields["old"].text()
            new_pwd = fields["new"].text()
            con_pwd = fields["confirm"].text()
            err_lbl.setVisible(False)

            if not old_pwd:
                err_lbl.setText("Please enter your current password.")
                err_lbl.setVisible(True); return
            if len(new_pwd) < 6:
                err_lbl.setText("New password must be at least 6 characters.")
                err_lbl.setVisible(True); return
            if new_pwd != con_pwd:
                err_lbl.setText("New passwords don’t match.")
                err_lbl.setVisible(True); return

            try:
                from core.auth_manager import LocalAuthProvider
                LocalAuthProvider().change_password(identifier, old_pwd, new_pwd)
                dlg.accept()
                self._show_acct_status("Password changed successfully!", error=False)
            except RuntimeError as e:
                err_lbl.setText(str(e))
                err_lbl.setVisible(True)

        save_btn.clicked.connect(_on_save)
        fields["confirm"].returnPressed.connect(_on_save)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        vl.addLayout(btn_row)

        dlg.exec()

    def _show_acct_status(self, msg: str, error: bool = False):
        """Show a status message under the Account panel."""
        color = "#ff5f56" if error else PRIMARY_CONTAINER
        self._acct_status.setStyleSheet(
            f"color:{color}; font-family:'{FONT_BODY}'; font-size:14px; background:transparent;"
        )
        self._acct_status.setText(msg)
        self._acct_status.setVisible(True)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(5000, lambda: self._acct_status.setVisible(False))
