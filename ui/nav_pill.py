"""
NavPill: the main navigation.

Closed (at rest) it is a slim black tab hanging from the top edge of the window, the
same size and shape as the three-dot window tab on the right, but holding one small
coloured symbol per page (Play, Progress, Settings) instead of the dots.

When the mouse comes near, while the controller focus is on the bar, and briefly after a
tab changes by shortcut, the tab itself grows, the way the window tab does: wider and
taller, until it holds the profile avatar and the labelled tabs. When the mouse leaves it
shrinks back.

The tabs are painted here so they can fade as the tab grows; only the profile avatar is a
real child widget (it fades in with an opacity effect).
"""
from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import (Qt, QPointF, QRectF, QTimer, QVariantAnimation, QEasingCurve,
                          pyqtSignal)
from PyQt6.QtGui import QPainter, QPainterPath, QColor, QPen, QFont, QFontMetrics, QCursor
from PyQt6.QtWidgets import QWidget, QGraphicsOpacityEffect

from core import theme as _t
from core.i18n import t

_NAV_KEYS = ["nav_play", "nav_progress", "nav_settings"]
# One colour per page, as on the reference: purple, magenta, cyan.
_SYMBOL_COLOURS = ("#8B7CF6", "#E060D8", "#22B8D4")

# closed: the slim tab, sized like the window tab at rest
CLOSED_H = 28
CLOSED_FLARE = 16
CLOSED_CORNER = 14
CLOSED_PAD = 13
SYMBOL_BOX = 22
SYMBOL_GAP = 4
SYMBOL_PX = 13
# open: the grown tab
OPEN_H = 80
OPEN_FLARE = 22
OPEN_CORNER = 36
SIDE_PAD = 12
DIVIDER_GAP = 10
AVATAR = 46
TAB_H = 52
TAB_MIN_W = 128
TAB_PAD = 26
TAB_GAP = 4
CONTENT_CY = 45               # vertical centre of the avatar and the tab row, open
SHADOW_ROOM = 12
SIDE_MARGIN = OPEN_FLARE + 4
OPEN_MS, CLOSE_MS = 180, 240  # the same timing as the window tab
APPROACH_PX = 90              # mouse this close to the closed tab opens it (as the window tab)
RELEASE_PX = 150              # ...and this far from the open tab lets it close
POLL_MS = 40
FLASH_MS = 1800               # stays open this long after a tab changes by shortcut
SYMBOLS_FADE = 2.6            # the symbols are gone by reveal 1/SYMBOLS_FADE
CONTENT_FROM = 0.60           # reveal at which the labels and avatar start to show
CONTENT_FULL = 0.95           # ...and at which they are fully shown
TABS_FROM = 0.74              # the labelled tabs show a little after the avatar, so they never overlap it


@dataclass
class _Tab:
    key: str
    text: str = ""
    width: int = TAB_MIN_W


class NavPill(QWidget):
    tab_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("navPill")
        self.setMouseTracking(True)
        self.buttons: list[_Tab] = [_Tab(k) for k in _NAV_KEYS]      # one per tab
        self._active = 0
        self._focused = False                  # controller focus is on the bar
        self._flash = False                    # held open briefly after a shortcut
        self._hover_tab = -1
        self._reveal = 0.0
        self._near = False                     # mouse is close enough to hold the tab open
        self._avatar: QWidget | None = None
        self._avatar_fx: QGraphicsOpacityEffect | None = None

        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_reveal)
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.setInterval(FLASH_MS)
        self._flash_timer.timeout.connect(self._end_flash)
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._sync_open)
        self._poll.start()

        self._retext()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not getattr(self, "_shown_once", False):
            self._shown_once = True
            self.flash()                       # open for a moment when the window first appears

    # ── Public API (used by the main window) ─────────────────────────────────
    def set_leading_widget(self, widget: QWidget) -> None:
        """Place the profile avatar; it shows once the tab is grown."""
        self._avatar = widget
        widget.setParent(self)
        widget.adjustSize()
        self._avatar_fx = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(self._avatar_fx)
        widget.show()
        self._place_avatar()

    def set_active_tab(self, idx: int) -> None:
        if 0 <= idx < len(self.buttons) and idx != self._active:
            self._active = idx
            self.update()

    def set_focused(self, on: bool) -> None:
        """Controller focus on the bar: stay open and ring the active tab."""
        if on != self._focused:
            self._focused = on
            self._sync_open()
            self.update()

    def flash(self) -> None:
        """Open for a moment (after a tab changes by shortcut, and at start-up)."""
        self._flash = True
        self._flash_timer.start()
        self._sync_open()

    def refresh_theme(self) -> None:
        self.update()

    def refresh_language(self) -> None:
        self._retext()

    # ── Measuring ────────────────────────────────────────────────────────────
    def _font(self) -> QFont:
        font = QFont(_t.FONT_DISPLAY)
        font.setPixelSize(17)
        font.setBold(True)
        return font

    def _retext(self) -> None:
        metrics = QFontMetrics(self._font())
        for tab in self.buttons:
            tab.text = t(tab.key)
            tab.width = max(TAB_MIN_W, metrics.horizontalAdvance(tab.text) + 2 * TAB_PAD)
        self.setFixedSize(int(self._open_width()) + 2 * SIDE_MARGIN, OPEN_H + SHADOW_ROOM)
        self.updateGeometry()
        self._place_avatar()
        self.update()

    def _open_width(self) -> float:
        tabs = sum(tab.width for tab in self.buttons) + TAB_GAP * (len(self.buttons) - 1)
        return SIDE_PAD + AVATAR + DIVIDER_GAP + 1 + DIVIDER_GAP + tabs + SIDE_PAD

    def _closed_width(self) -> float:
        symbols = len(self.buttons) * SYMBOL_BOX + SYMBOL_GAP * (len(self.buttons) - 1)
        return CLOSED_PAD + symbols + CLOSED_PAD

    def _lerp(self, closed: float, opened: float) -> float:
        return closed + (opened - closed) * self._reveal

    def _island(self) -> QRectF:
        """The tab's body for the current reveal: centred, hanging from the top edge."""
        w = self._lerp(self._closed_width(), self._open_width())
        h = self._lerp(CLOSED_H, OPEN_H)
        return QRectF((self.width() - w) / 2, 0, w, h)

    def _closed_rect(self) -> QRectF:
        w = self._closed_width()
        return QRectF((self.width() - w) / 2, 0, w, CLOSED_H)

    def _content_left(self) -> float:
        """Left edge of the open layout. It does not move while the tab grows (the tab
        grows around the same centre), so the labels are uncovered from the middle outward."""
        return (self.width() - self._open_width()) / 2

    def _tab_rects(self, island: QRectF | None = None) -> list[QRectF]:
        x = self._content_left() + SIDE_PAD + AVATAR + DIVIDER_GAP + 1 + DIVIDER_GAP
        rects = []
        for tab in self.buttons:
            rects.append(QRectF(x, CONTENT_CY - TAB_H / 2, tab.width, TAB_H))
            x += tab.width + TAB_GAP
        return rects

    def _symbol_rects(self) -> list[QRectF]:
        closed = self._closed_rect()
        x = closed.left() + CLOSED_PAD
        top = (CLOSED_H - SYMBOL_BOX) / 2 - 1
        rects = []
        for _ in self.buttons:
            rects.append(QRectF(x, top, SYMBOL_BOX, SYMBOL_BOX))
            x += SYMBOL_BOX + SYMBOL_GAP
        return rects

    # ── Opening and closing ──────────────────────────────────────────────────
    def _want_open(self) -> bool:
        return self._focused or self._flash or self._mouse_near()

    @staticmethod
    def _distance_to(rect: QRectF, pos: QPointF) -> float:
        dx = max(rect.left() - pos.x(), 0.0, pos.x() - rect.right())
        dy = max(rect.top() - pos.y(), 0.0, pos.y() - rect.bottom())
        return (dx * dx + dy * dy) ** 0.5

    def _mouse_near(self) -> bool:
        """Open when the mouse is within APPROACH_PX of the tab, and stay open until it is
        more than RELEASE_PX away (the gap stops it flickering), as the window tab does."""
        win = self.window()
        if not self.isVisible() or win is None or not win.isActiveWindow():
            return self._near
        pos = QPointF(self.mapFromGlobal(QCursor.pos()))
        if self._near:                                       # open: measured from the grown tab
            w = self._open_width()
            rect = QRectF((self.width() - w) / 2, 0, w, OPEN_H)
        else:                                                # closed: measured from the slim tab
            rect = self._closed_rect()
        distance = self._distance_to(rect, pos)
        if distance <= APPROACH_PX:
            self._near = True
        elif distance > RELEASE_PX:
            self._near = False
        return self._near

    def _end_flash(self) -> None:
        self._flash = False
        self._sync_open()

    def _sync_open(self) -> None:
        target = 1.0 if self._want_open() else 0.0
        if self._anim.state() == QVariantAnimation.State.Running:
            if float(self._anim.endValue()) == target:
                return
        elif abs(self._reveal - target) < 1e-3:
            return
        self._anim.stop()
        self._anim.setStartValue(self._reveal)
        self._anim.setEndValue(target)
        self._anim.setDuration(OPEN_MS if target > self._reveal else CLOSE_MS)
        self._anim.start()

    def _on_reveal(self, value) -> None:
        self._reveal = float(value)
        self._place_avatar()
        self.update()

    def _content_alpha(self) -> float:
        return max(0.0, min(1.0, (self._reveal - CONTENT_FROM) / (CONTENT_FULL - CONTENT_FROM)))

    def _place_avatar(self) -> None:
        if self._avatar is None:
            return
        # The avatar rides with the growing tab's left edge (a widget cannot be clipped to the
        # tab), landing on its place in the layout when the tab is fully open.
        self._avatar.move(round(self._island().left() + SIDE_PAD), round(CONTENT_CY - AVATAR / 2))
        alpha = self._content_alpha()
        if self._avatar_fx is not None:
            self._avatar_fx.setOpacity(alpha)
        self._avatar.setVisible(alpha > 0.01)
        self._avatar.raise_()

    # ── Painting ─────────────────────────────────────────────────────────────
    def _outline(self, body: QRectF) -> QPainterPath:
        x0, x1, h = body.left(), body.right(), body.height()
        corner = min(h / 2, self._lerp(CLOSED_CORNER, OPEN_CORNER))
        flare = min(self._lerp(CLOSED_FLARE, OPEN_FLARE), h - corner)
        path = QPainterPath(QPointF(x0 - flare, 0))
        path.quadTo(QPointF(x0, 0), QPointF(x0, flare))                # flare into the left side
        path.lineTo(x0, h - corner)
        path.arcTo(QRectF(x0, h - 2 * corner, 2 * corner, 2 * corner), 180, 90)
        path.lineTo(x1 - corner, h)
        path.arcTo(QRectF(x1 - 2 * corner, h - 2 * corner, 2 * corner, 2 * corner), 270, 90)
        path.lineTo(x1, flare)
        path.quadTo(QPointF(x1, 0), QPointF(x1 + flare, 0))            # flare out to the edge
        path.closeSubpath()
        return path

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        island = self._island()
        outline = self._outline(island)
        p.setPen(Qt.PenStyle.NoPen)
        for dy, a in ((7, 10), (5, 14), (3, 18), (1, 24)):
            p.setBrush(QColor(60, 40, 20, a))
            p.drawPath(outline.translated(0, dy))
        p.setBrush(QColor(_t.PRIMARY))
        p.drawPath(outline)

        ink = QColor(_t.ON_PRIMARY)
        symbols_alpha = max(0.0, 1.0 - self._reveal * SYMBOLS_FADE)
        if symbols_alpha > 0:
            self._paint_symbols(p, ink, symbols_alpha)
        content_alpha = self._content_alpha()
        if content_alpha > 0:
            p.setClipPath(outline)               # labels never spill outside the tab while it grows
            tabs_alpha = max(0.0, min(1.0, (self._reveal - TABS_FROM) / (CONTENT_FULL - TABS_FROM)))
            self._paint_tabs(p, island, ink, content_alpha, tabs_alpha)
        p.end()

    def _paint_symbols(self, p: QPainter, ink: QColor, alpha: float) -> None:
        p.setOpacity(alpha)
        for i, (rect, colour) in enumerate(zip(self._symbol_rects(), _SYMBOL_COLOURS)):
            active = i == self._active
            if active:                                  # soft disc behind the current page
                disc = QColor(ink)
                disc.setAlphaF(0.16)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(disc)
                p.drawEllipse(rect)
            glyph = QColor(colour)
            glyph.setAlphaF(1.0 if active else 0.72)
            self._paint_symbol(p, i, rect.center(), glyph)
        p.setOpacity(1.0)

    def _paint_symbol(self, p: QPainter, index: int, centre: QPointF, colour: QColor) -> None:
        s = float(SYMBOL_PX)
        p.save()
        p.translate(centre)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour)
        if index == 0:                                  # Play: a rounded play triangle
            tri = QPainterPath()
            tri.moveTo(-0.30 * s, -0.46 * s)
            tri.lineTo(0.48 * s, 0)
            tri.lineTo(-0.30 * s, 0.46 * s)
            tri.closeSubpath()
            pen = QPen(colour, 0.22 * s)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPath(tri)
        elif index == 1:                                # Progress: three rising bars
            bar_w = 0.26 * s
            for n, height in enumerate((0.50, 0.80, 1.10)):
                x = (n - 1) * 0.40 * s - bar_w / 2
                p.drawRoundedRect(QRectF(x, 0.55 * s - height * s, bar_w, height * s),
                                  bar_w / 2.4, bar_w / 2.4)
        else:                                           # Settings: a gear
            for n in range(8):
                p.save()
                p.rotate(n * 45)
                p.drawRoundedRect(QRectF(-0.11 * s, -0.56 * s, 0.22 * s, 0.30 * s), 0.05 * s, 0.05 * s)
                p.restore()
            ring = QPainterPath()
            ring.setFillRule(Qt.FillRule.OddEvenFill)
            ring.addEllipse(QPointF(0, 0), 0.40 * s, 0.40 * s)
            ring.addEllipse(QPointF(0, 0), 0.16 * s, 0.16 * s)
            p.drawPath(ring)
        p.restore()

    def _paint_tabs(self, p: QPainter, island: QRectF, ink: QColor, divider_alpha: float,
                    alpha: float) -> None:
        line = QColor(ink)
        line.setAlphaF(divider_alpha * 0.22)       # hairline between the avatar and the tabs
        dx = self._content_left() + SIDE_PAD + AVATAR + DIVIDER_GAP
        p.setPen(QPen(line, 1))
        p.drawLine(QPointF(dx + 0.5, CONTENT_CY - 14), QPointF(dx + 0.5, CONTENT_CY + 14))
        p.setFont(self._font())
        for i, (tab, rect) in enumerate(zip(self.buttons, self._tab_rects(island))):
            active = i == self._active
            radius = TAB_H / 2
            if active:
                fill = QColor(ink)
                fill.setAlphaF(alpha)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(fill)
                p.drawRoundedRect(rect, radius, radius)
                if self._focused:                       # controller focus ring
                    ring = QColor(_t.PRIMARY_CONTAINER)
                    ring.setAlphaF(alpha)
                    p.setPen(QPen(ring, 3))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), radius + 2, radius + 2)
                text = QColor(_t.PRIMARY)
                text.setAlphaF(alpha)
            else:
                if i == self._hover_tab:
                    wash = QColor(ink)
                    wash.setAlphaF(alpha * 0.14)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(wash)
                    p.drawRoundedRect(rect, radius, radius)
                text = QColor(ink)
                text.setAlphaF(alpha * (0.95 if i == self._hover_tab else 0.62))
            p.setPen(text)
            p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), tab.text)

    # ── Mouse ────────────────────────────────────────────────────────────────
    def _tab_at(self, pos) -> int:
        point = QPointF(pos)
        if self._reveal >= 0.7:                         # the grown tab's labelled tabs
            for i, rect in enumerate(self._tab_rects()):
                if rect.contains(point):
                    return i
        elif self._reveal <= 0.3:                       # the slim tab's symbols
            for i, rect in enumerate(self._symbol_rects()):
                if rect.contains(point):
                    return i
        return -1

    def mouseMoveEvent(self, event) -> None:
        idx = self._tab_at(event.position().toPoint())
        if idx != self._hover_tab:
            self._hover_tab = idx
            self.setCursor(Qt.CursorShape.PointingHandCursor if idx >= 0
                           else Qt.CursorShape.ArrowCursor)
            self.update()
        event.ignore()

    def leaveEvent(self, event) -> None:
        if self._hover_tab != -1:
            self._hover_tab = -1
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        idx = self._tab_at(event.position().toPoint())
        if idx < 0:
            event.ignore()                              # not on a tab: the bar behind may drag the window
            return
        self.set_active_tab(idx)
        self.tab_changed.emit(idx)
        event.accept()
