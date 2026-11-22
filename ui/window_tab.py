"""
WindowTab — a small dark tab hanging from the top edge of the window.

At rest it is a slim tab with three dots, just enough to say "controls are
here". When the mouse comes near it grows into the full tab holding the
minimise, maximise and close symbols (line icons, no labels), and shrinks
again once the mouse moves away. Close turns red on hover; the maximise symbol
becomes two stacked squares while the window is maximised.
"""
from __future__ import annotations

from PyQt6.QtCore import (
    Qt, QRectF, QPointF, QPoint, QSize, QTimer, QPropertyAnimation, QEasingCurve,
    pyqtProperty,
)
from PyQt6.QtGui import QPainter, QPainterPath, QColor, QPen, QPolygonF, QCursor
from PyQt6.QtWidgets import QWidget, QAbstractButton

from core import theme as _t

TAB_HEIGHT = 48
BUTTON_SIZE = 34
BUTTON_GAP = 6
TAB_PAD = 20                  # space between the tab's side and the first/last symbol
FLARE = 16                    # radius of the concave curves where the tab meets the edge
CORNER = 22                   # radius of the tab's lower corners
SHADOW_ROOM = 8
GLYPH_WIDTH = 2.4
GLYPH_HALF = 5.5              # half the size of a symbol
CLOSE_HOVER = "#FF5F56"
CLOSE_HOVER_INK = "#3A0A06"
BODY_WIDTH = 3 * BUTTON_SIZE + 2 * BUTTON_GAP + 2 * TAB_PAD
TOTAL_WIDTH = BODY_WIDTH + 2 * FLARE
TOTAL_HEIGHT = TAB_HEIGHT + SHADOW_ROOM

REST_WIDTH = 78               # the slim tab at rest
REST_HEIGHT = 24
DOT_RADIUS = 3.0
DOT_GAP = 13
APPROACH_PX = 90              # the tab opens when the mouse is this close
RELEASE_PX = 150              # and closes again beyond this distance
POLL_MS = 40
OPEN_MS, CLOSE_MS = 180, 240
SHOW_SYMBOLS_FROM = 0.7       # reveal amount at which the symbols appear
DOTS_FADE = 2.6               # the dots are gone by reveal = 1 / DOTS_FADE


class _SymbolButton(QAbstractButton):
    """One window symbol: 'min', 'max' or 'close'."""

    def __init__(self, kind: str, label: str, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._hover = False
        self.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self.setToolTip(label)
        self.setAccessibleName(label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def sizeHint(self) -> QSize:
        return QSize(BUTTON_SIZE, BUTTON_SIZE)

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = QColor(_t.ON_PRIMARY)
        if self._hover:
            if self._kind == "close":
                fill, ink = QColor(CLOSE_HOVER), QColor(CLOSE_HOVER_INK)
            else:
                fill = QColor(ink)
                fill.setAlphaF(0.16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        pen = QPen(ink, GLYPH_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        c = QPointF(self.width() / 2, self.height() / 2)
        {"min": self._draw_minimise, "max": self._draw_maximise,
         "close": self._draw_close}[self._kind](p, c)
        p.end()

    @staticmethod
    def _draw_minimise(p: QPainter, c: QPointF) -> None:
        p.drawLine(QPointF(c.x() - GLYPH_HALF, c.y() + 2), QPointF(c.x() + GLYPH_HALF, c.y() + 2))

    def _draw_maximise(self, p: QPainter, c: QPointF) -> None:
        h = GLYPH_HALF
        win = self.window()
        if win is not None and win.isMaximized():             # restore symbol: two squares
            p.drawRoundedRect(QRectF(c.x() - h, c.y() - h + 3, 2 * h - 3, 2 * h - 3), 2.5, 2.5)
            back = QPolygonF([QPointF(c.x() - h + 3, c.y() - h + 3), QPointF(c.x() - h + 3, c.y() - h),
                              QPointF(c.x() + h, c.y() - h), QPointF(c.x() + h, c.y() + h - 3),
                              QPointF(c.x() + h - 3, c.y() + h - 3)])
            p.drawPolyline(back)
        else:
            p.drawRoundedRect(QRectF(c.x() - h, c.y() - h, 2 * h, 2 * h), 3, 3)

    @staticmethod
    def _draw_close(p: QPainter, c: QPointF) -> None:
        h = GLYPH_HALF - 0.5
        p.drawLine(QPointF(c.x() - h, c.y() - h), QPointF(c.x() + h, c.y() + h))
        p.drawLine(QPointF(c.x() - h, c.y() + h), QPointF(c.x() + h, c.y() - h))


class WindowTab(QWidget):
    def __init__(self, on_minimize, on_maximize, on_close, parent=None):
        super().__init__(parent)
        self.setFixedSize(TOTAL_WIDTH, TOTAL_HEIGHT)
        self._reveal = 0.0
        self._open = False

        specs = (("min", "Minimise", on_minimize), ("max", "Maximise", on_maximize),
                 ("close", "Close", on_close))
        self._buttons: list[_SymbolButton] = []
        for kind, label, handler in specs:
            btn = _SymbolButton(kind, label, self)
            btn.clicked.connect(handler)
            self._buttons.append(btn)

        self._anim = QPropertyAnimation(self, b"reveal", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._poller = QTimer(self)
        self._poller.setInterval(POLL_MS)
        self._poller.timeout.connect(self._follow_mouse)
        self._poller.start()
        self._apply_reveal()

    # ── growing and shrinking ────────────────────────────────────────────────
    def _get_reveal(self) -> float:
        return self._reveal

    def _set_reveal(self, value: float) -> None:
        self._reveal = value
        self._apply_reveal()
        self.update()

    reveal = pyqtProperty(float, _get_reveal, _set_reveal)

    def set_open(self, on: bool) -> None:
        """Grow into the full tab (True) or shrink back to the slim one (False)."""
        if on == self._open:
            return
        self._open = on
        self._anim.stop()
        self._anim.setDuration(OPEN_MS if on else CLOSE_MS)
        self._anim.setStartValue(self._reveal)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def is_open(self) -> bool:
        return self._open

    def _distance_to_mouse(self) -> float:
        """How far the mouse is from the full-size tab, in pixels (0 when over it)."""
        top_left = self.mapToGlobal(QPoint(FLARE, 0))
        pos = QCursor.pos()
        dx = max(top_left.x() - pos.x(), 0, pos.x() - (top_left.x() + BODY_WIDTH))
        dy = max(top_left.y() - pos.y(), 0, pos.y() - (top_left.y() + TAB_HEIGHT))
        return (dx * dx + dy * dy) ** 0.5

    def _follow_mouse(self) -> None:
        win = self.window()
        if not self.isVisible() or win is None or not win.isActiveWindow():
            return
        distance = self._distance_to_mouse()
        if distance <= APPROACH_PX:
            self.set_open(True)
        elif distance > RELEASE_PX:
            self.set_open(False)

    # ── geometry ─────────────────────────────────────────────────────────────
    def _body_rect(self) -> QRectF:
        r = self._reveal
        w = REST_WIDTH + (BODY_WIDTH - REST_WIDTH) * r
        h = REST_HEIGHT + (TAB_HEIGHT - REST_HEIGHT) * r
        return QRectF(FLARE + (BODY_WIDTH - w) / 2, 0, w, h)

    def _apply_reveal(self) -> None:
        body = self._body_rect()
        total = len(self._buttons) * BUTTON_SIZE + (len(self._buttons) - 1) * BUTTON_GAP
        x = body.left() + (body.width() - total) / 2
        y = (body.height() - BUTTON_SIZE) / 2
        shown = self._reveal >= SHOW_SYMBOLS_FROM
        for btn in self._buttons:
            btn.move(round(x), round(y))
            btn.setVisible(shown)
            x += BUTTON_SIZE + BUTTON_GAP
        # While slim, the tab lets clicks fall through to the bar behind it.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not shown)

    def _outline(self, body: QRectF) -> QPainterPath:
        x0, x1, h = body.left(), body.right(), body.height()
        corner = min(CORNER, h / 2)
        flare = min(FLARE, h - corner)
        path = QPainterPath(QPointF(x0 - flare, 0))
        path.quadTo(QPointF(x0, 0), QPointF(x0, flare))               # flare into the left side
        path.lineTo(x0, h - corner)
        path.arcTo(QRectF(x0, h - 2 * corner, 2 * corner, 2 * corner), 180, 90)
        path.lineTo(x1 - corner, h)
        path.arcTo(QRectF(x1 - 2 * corner, h - 2 * corner, 2 * corner, 2 * corner), 270, 90)
        path.lineTo(x1, flare)
        path.quadTo(QPointF(x1, 0), QPointF(x1 + flare, 0))           # flare out to the edge
        path.closeSubpath()
        return path

    # ── painting ─────────────────────────────────────────────────────────────
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = self._body_rect()
        outline = self._outline(body)
        p.setPen(Qt.PenStyle.NoPen)
        for dy, alpha in ((5, 14), (3, 18), (1, 22)):
            p.setBrush(QColor(60, 40, 20, alpha))
            p.drawPath(outline.translated(0, dy))
        p.setBrush(QColor(_t.PRIMARY))
        p.drawPath(outline)
        self._paint_dots(p, body)
        p.end()

    def _paint_dots(self, p: QPainter, body: QRectF) -> None:
        """The three dots of the slim tab; they fade out as the tab grows."""
        alpha = max(0.0, 1.0 - self._reveal * DOTS_FADE)
        if alpha <= 0:
            return
        ink = QColor(_t.ON_PRIMARY)
        ink.setAlphaF(alpha * 0.85)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        centre = QPointF(body.center().x(), body.height() / 2 + 1)
        for step in (-1, 0, 1):
            p.drawEllipse(QPointF(centre.x() + step * DOT_GAP, centre.y()), DOT_RADIUS, DOT_RADIUS)

    def refresh_state(self) -> None:
        """Repaint the symbols, e.g. after the window is maximised or restored."""
        for btn in self._buttons:
            btn.update()
