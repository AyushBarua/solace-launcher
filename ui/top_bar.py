"""
TopBar — fixed header, Solace Glass style.

Left: window controls and the wordmark. Centre: the navigation pill (inserted
by the main window via set_center_widget). Right: input-device pill and the
profile pill, which opens a dropdown for switching profiles.
"""
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QPushButton,
                              QGraphicsDropShadowEffect, QVBoxLayout, QFrame)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui import QColor, QPainter, QLinearGradient, QFont, QFontMetrics, QPen

from core import theme as _t
from core.theme import hex_rgba
from ui import glass as _g
from ui.window_tab import WindowTab, BODY_WIDTH, FLARE

WINDOW_TAB_X = 28              # left edge of the tab's body, from the window edge
TOP_BAR_HEIGHT = 92
PILL_HEIGHT = 48
AVATAR_SIZE = 46               # the round avatar; the nav pill's inside is 50 px high, so this leaves a margin


def _soft_shadow(owner, blur: int = 30, alpha: int = 34) -> QGraphicsDropShadowEffect:
    fx = QGraphicsDropShadowEffect(owner)
    fx.setBlurRadius(blur)
    fx.setOffset(0, 8)
    fx.setColor(QColor(60, 40, 20, alpha))
    return fx


# ──────────────────────────────────────────────────────────────────────────────
# The profile button (the round avatar)
# ──────────────────────────────────────────────────────────────────────────────
class _AvatarButton(QPushButton):
    """The round avatar, painted by hand so its edge stays smooth and is never clipped."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colour = QColor("#D2A857")
        self._glyph = ""
        self.setFlat(True)

    def set_look(self, glyph: str, colour: str) -> None:
        self._glyph, self._colour = glyph, QColor(colour)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ring = 2.0
        disc = QRectF(self.rect()).adjusted(ring / 2, ring / 2, -ring / 2, -ring / 2)
        fill = QColor(self._colour)
        fill.setAlpha(128 if self.underMouse() else 77)
        edge = QColor(self._colour)
        edge.setAlpha(166)
        p.setBrush(fill)
        p.setPen(QPen(edge, ring))
        p.drawEllipse(disc)
        font = QFont("Segoe UI Emoji")
        font.setPixelSize(int(AVATAR_SIZE * 0.5))
        p.setFont(font)
        p.setPen(QColor(_t.ON_SURFACE))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._glyph)
        p.end()


class ProfilePill(QWidget):
    switch_profile = pyqtSignal()         # the avatar was clicked: show the profile page

    def __init__(self, profile: dict = None, parent=None):
        super().__init__(parent)
        self._profile = profile

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._pill = _AvatarButton()
        self._pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pill.clicked.connect(self.switch_profile.emit)
        layout.addWidget(self._pill)
        self._refresh_style()

    def _refresh_style(self):
        p = self._profile
        name = p.get("name", "Player") if p else "Guest"
        avatar = p.get("avatar", "👤") if p else "👤"
        colour = p.get("color", "#D2A857") if p else "#D2A857"
        self._pill.set_look(avatar, colour)
        self._pill.setToolTip(name)
        self._pill.setAccessibleName(f"Profile: {name}")
        self._pill.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)

    def set_profile(self, profile: dict):
        self._profile = profile
        self._refresh_style()


# ──────────────────────────────────────────────────────────────────────────────
# Input-device status
# ──────────────────────────────────────────────────────────────────────────────
SHOW_INPUT_STATUS = False       # hidden for now; True brings the device readout back
STATUS_DOT = 9                  # px, the status light
STATUS_GAP = 10                 # px between the light and the words
STATUS_PX = 15                  # label size
STATUS_TAB_GAP = 44             # px between the status and the window tab's body (flare included)


class InputStatus(QWidget):
    """A quiet readout of the active input device: a small light and its name.

    It only reports, so it is plain text with no button shape. The light is green
    while a controller is connected and a soft neutral for the keyboard.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._text = ""
        self._ink = QColor("#000000")
        self._light = QColor("#888888")
        self._glow = False

    def set_state(self, text: str, ink: QColor, light: QColor, glow: bool) -> None:
        self._text, self._ink, self._light, self._glow = text, ink, light, glow
        metrics = QFontMetrics(self._font())
        self.setFixedSize(STATUS_DOT + STATUS_GAP + metrics.horizontalAdvance(text) + 2,
                          PILL_HEIGHT)
        self.update()

    def _font(self) -> QFont:
        font = QFont(_t.FONT_DISPLAY)
        font.setPixelSize(STATUS_PX)
        font.setBold(True)
        return font

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre_y = self.height() / 2
        dot_x = STATUS_DOT / 2
        p.setPen(Qt.PenStyle.NoPen)
        if self._glow:                                  # a soft halo while connected
            halo = QColor(self._light)
            halo.setAlpha(60)
            p.setBrush(halo)
            p.drawEllipse(QPointF(dot_x, centre_y), STATUS_DOT * 0.95, STATUS_DOT * 0.95)
        p.setBrush(self._light)
        p.drawEllipse(QPointF(dot_x, centre_y), STATUS_DOT / 2, STATUS_DOT / 2)
        p.setFont(self._font())
        p.setPen(self._ink)
        p.drawText(self.rect().adjusted(STATUS_DOT + STATUS_GAP, 0, 0, 0),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self._text)
        p.end()


# ──────────────────────────────────────────────────────────────────────────────
# Main TopBar
# ──────────────────────────────────────────────────────────────────────────────
class TopBar(QWidget):
    profile_clicked = pyqtSignal()         # the avatar was clicked: show the profile page

    def __init__(self, active_profile: dict = None, parent=None):
        super().__init__(parent)
        self._active_profile = active_profile
        self._ctrl_connected = False
        self._ctrl_name = "KEYBOARD"
        self.setFixedHeight(TOP_BAR_HEIGHT)
        self.setObjectName("topBar")
        self.setStyleSheet("QWidget#topBar { background: transparent; }")

        root = QHBoxLayout(self)
        root.setContentsMargins(28, 0, 28, 0)     # the nav island hangs from y=0, so no top margin
        root.setSpacing(0)

        # Left and right zones get equal stretch so the centre stays centred.
        left = QWidget()
        lh = QHBoxLayout(left)
        lh.setContentsMargins(0, 0, 0, 0)
        lh.setSpacing(22)
        self._profile_pill = ProfilePill(active_profile)
        self._profile_pill.switch_profile.connect(self.profile_clicked.emit)
        lh.addWidget(self._build_wordmark())      # the avatar lives inside the nav pill
        lh.addStretch()

        self._center = QWidget()
        self._center_layout = QHBoxLayout(self._center)
        self._center_layout.setContentsMargins(0, 0, 0, 0)

        right = QWidget()
        rh = QHBoxLayout(right)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(0)
        rh.addStretch()
        self.input_status = InputStatus()
        self._style_input_status(False)
        self.input_status.setVisible(SHOW_INPUT_STATUS)
        rh.addWidget(self.input_status)
        # The window tab hangs from the top edge at the right, outside the layout.
        self._window_tab = WindowTab(self._on_minimize, self._on_maximize, self._on_close, self)
        rh.addSpacing(BODY_WIDTH + STATUS_TAB_GAP)

        root.addWidget(left, 1)
        root.addWidget(self._center, 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(right, 1)

    # ── Building blocks ───────────────────────────────────────────────────────

    def _build_wordmark(self) -> QLabel:
        mark = QLabel(f"solace<span style='color:#FF8A3D;'>.</span>")
        mark.setTextFormat(Qt.TextFormat.RichText)
        self._wordmark = mark
        self._style_wordmark()
        return mark

    def paintEvent(self, _event) -> None:
        """Off the featured art, fade the page colour in behind the bar so content that
        scrolls up under it never collides with the pill, avatar and wordmark."""
        if getattr(self, "_on_art", False):
            return
        p = QPainter(self)
        base = QColor(_t.BACKGROUND)
        fade = QLinearGradient(0, 0, 0, self.height())
        base.setAlpha(246)
        fade.setColorAt(0.0, base)
        fade.setColorAt(0.7, base)
        clear = QColor(base)
        clear.setAlpha(0)
        fade.setColorAt(1.0, clear)
        p.fillRect(self.rect(), fade)
        p.end()

    def set_on_art(self, on: bool) -> None:
        """Light-on-dark text while the bar floats over the featured art."""
        on = bool(on)
        if on == getattr(self, "_on_art", False):
            return
        self._on_art = on
        self.update()
        self._style_wordmark()
        self._style_input_status(self._ctrl_connected, self._ctrl_name)

    def _style_wordmark(self):
        ink = "#FFFFFF" if getattr(self, "_on_art", False) else _t.ON_SURFACE
        self._wordmark.setStyleSheet(
            f"color: {ink}; font-family: '{_t.FONT_DISPLAY}';"
            f" font-size: 32px; font-weight: 800; letter-spacing: -1px;"
            f" background: transparent;"
        )

    def set_center_widget(self, widget: QWidget):
        """Place the navigation pill in the centre of the bar, with the profile avatar
        folded into its left end."""
        self._center_layout.addWidget(widget)
        if hasattr(widget, "set_leading_widget"):
            widget.set_leading_widget(self._profile_pill)

    # ── Window control & drag helpers ─────────────────────────────────────────

    def _on_close(self):
        if self.window():
            self.window().close()

    def _on_minimize(self):
        if self.window():
            self.window().showMinimized()

    def _on_maximize(self):
        if self.window():
            if self.window().isMaximized():
                self.window().showNormal()
            else:
                self.window().showMaximized()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._window_tab.move(self.width() - WINDOW_TAB_X - BODY_WIDTH - FLARE, 0)
        self._window_tab.raise_()
        self._window_tab.refresh_state()          # the maximise symbol follows the window state

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, '_drag_pos'):
            # Moving a maximized window restores it to normal size first
            if self.window().isMaximized():
                self.window().showNormal()
                self._drag_pos = event.globalPosition().toPoint()
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.window().move(self.window().pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
            event.accept()

    # ── Input-device status ───────────────────────────────────────────────────

    def _style_input_status(self, connected: bool, name: str = "KEYBOARD"):
        self._ctrl_connected = connected
        self._ctrl_name = name
        label = name.title() if name.isupper() else name
        on_art = getattr(self, "_on_art", False)
        if on_art:
            ink = QColor(255, 255, 255, 225)
        else:
            ink = QColor(_t.ON_SURFACE_VAR)
        if connected:
            light = QColor("#4BD58A") if (_g.is_dark() or on_art) else QColor("#1E9A55")
            text = f"{label} connected"
        else:
            light = QColor(255, 255, 255, 150) if on_art else QColor(_t.ON_SURFACE_VAR)
            text = label
        self.input_status.set_state(text, ink, light, glow=connected)

    def set_controller_connected(self, connected: bool, name: str = "KEYBOARD"):
        self._style_input_status(connected, name)

    def set_profile(self, profile: dict):
        """Refresh the pill after switching profiles."""
        self._active_profile = profile
        self._profile_pill.set_profile(profile)

    def refresh_theme(self):
        """Re-apply styles after a live theme switch."""
        self.setStyleSheet("QWidget#topBar { background: transparent; }")
        self._style_wordmark()
        self._style_input_status(self._ctrl_connected, self._ctrl_name)
        self._profile_pill._refresh_style()
        self._window_tab.update()
