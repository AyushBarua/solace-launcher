"""
FloatingScrollBar: a slim scrollbar thumb that floats over a scroll area's right edge.

The native bar is switched off, so the content (the featured art on Play) runs all the
way to the window edge. The thumb fades in while the page scrolls or when the mouse
goes to the right edge, and fades out about a second later. Drag it, or click the track
to page. Mouse wheel, keys and controller keep scrolling the area as before.
"""
from __future__ import annotations

from PyQt6.QtCore import (Qt, QEvent, QRect, QRectF, QTimer, QVariantAnimation,
                          QEasingCurve)
from PyQt6.QtGui import QPainter, QColor, QPen, QRegion, QCursor
from PyQt6.QtWidgets import QWidget, QScrollArea

TRACK_W = 18              # width of the column that catches the mouse
THUMB_W = 6               # resting thumb thickness
THUMB_W_ACTIVE = 9        # while hovered or dragged
EDGE_GAP = 5              # thumb distance from the window edge
TOP_GAP = 100             # starts below the top bar
BOTTOM_GAP = 14
MIN_THUMB = 40            # shortest the thumb gets
MAX_THUMB = 90            # longest it gets, however much of the page is showing
WAKE_PX = 30              # mouse within this many px of the right edge wakes the thumb
HOLD_MS = 1100            # stays visible this long after the last scroll
FADE_IN_MS, FADE_OUT_MS = 120, 380
POLL_MS = 120


class FloatingScrollBar(QWidget):
    def __init__(self, area: QScrollArea):
        super().__init__(area)
        self._area = area
        self._bar = area.verticalScrollBar()
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self._opacity = 0.0
        self._grab_offset: int | None = None       # where inside the thumb a drag started
        self._hover = False

        self._fade = QVariantAnimation(self)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.valueChanged.connect(self._on_fade)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(HOLD_MS)
        self._hold.timeout.connect(self._fade_out)
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._check_mouse)
        self._poll.start()

        self._bar.valueChanged.connect(self.wake)
        self._bar.rangeChanged.connect(self._on_range)
        area.installEventFilter(self)
        self._reposition()
        self.hide()

    # ── Geometry ─────────────────────────────────────────────────────────────
    def eventFilter(self, obj, event) -> bool:
        if obj is self._area and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._reposition()
        return False

    def _reposition(self) -> None:
        h = max(0, self._area.height() - TOP_GAP - BOTTOM_GAP)
        self.setGeometry(self._area.width() - TRACK_W, TOP_GAP, TRACK_W, h)
        self.raise_()
        self._update_mask()

    def _scrollable(self) -> bool:
        return self._bar.maximum() > 0

    def _thumb_rect(self) -> QRect:
        track_h = self.height()
        total = self._bar.maximum() + self._bar.pageStep()
        thumb_h = int(track_h * self._bar.pageStep() / max(1, total))
        thumb_h = min(max(MIN_THUMB, min(thumb_h, MAX_THUMB)), track_h)     # always a short pill
        span = max(1, track_h - thumb_h)
        top = int(span * self._bar.value() / max(1, self._bar.maximum()))
        width = THUMB_W_ACTIVE if (self._hover or self._grab_offset is not None) else THUMB_W
        return QRect(self.width() - EDGE_GAP - width, top, width, thumb_h)

    def _update_mask(self) -> None:
        """Only catch the mouse while the thumb is showing, so the page under it stays clickable."""
        if self._opacity > 0.05 and self._scrollable():
            self.setMask(QRegion(self.rect()))
        else:
            self.setMask(QRegion(QRect(0, 0, 0, 0)))

    # ── Showing and hiding ───────────────────────────────────────────────────
    def wake(self, *_args) -> None:
        if not self._scrollable():
            return
        self._hold.start()
        self.show()
        self.raise_()
        fading_in = (self._fade.state() == QVariantAnimation.State.Running
                     and self._fade.endValue() == 1.0)
        if self._opacity < 1.0 and not fading_in:
            self._run_fade(1.0, FADE_IN_MS)
        self.update()

    def _fade_out(self) -> None:
        if self._hover or self._grab_offset is not None:
            self._hold.start()                     # keep it while the mouse is on it
            return
        self._run_fade(0.0, FADE_OUT_MS)

    def _run_fade(self, end: float, ms: int) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._opacity)
        self._fade.setEndValue(end)
        self._fade.setDuration(ms)
        self._fade.start()

    def _on_fade(self, value) -> None:
        self._opacity = float(value)
        self._update_mask()
        if self._opacity <= 0.0 and self._fade.endValue() == 0.0:   # done fading out
            self.hide()
        self.update()

    def _on_range(self, *_args) -> None:
        if not self._scrollable():
            self._opacity = 0.0
            self.hide()
        self._update_mask()
        self.update()

    def _check_mouse(self) -> None:
        """Wake the thumb when the mouse goes to the right edge of the page."""
        if not self._area.isVisible() or not self._scrollable():
            return
        win = self._area.window()
        if win is not None and not win.isActiveWindow():
            return
        local = self._area.mapFromGlobal(QCursor.pos())
        if (self._area.rect().contains(local) and local.x() >= self._area.width() - WAKE_PX
                and local.y() >= TOP_GAP):
            self.wake()

    # ── Painting ─────────────────────────────────────────────────────────────
    def paintEvent(self, _event) -> None:
        if self._opacity <= 0.0 or not self._scrollable():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._opacity)
        thumb = QRectF(self._thumb_rect())
        radius = thumb.width() / 2
        p.setPen(QPen(QColor(0, 0, 0, 55), 1))              # a hairline so it reads on light and dark
        p.setBrush(QColor(255, 255, 255, 235))
        p.drawRoundedRect(thumb.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        p.end()

    # ── Mouse ────────────────────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        thumb = self._thumb_rect()
        y = int(event.position().y())
        if thumb.top() <= y <= thumb.bottom():
            self._grab_offset = y - thumb.top()
        else:                                              # click on the track pages up or down
            step = self._bar.pageStep()
            self._bar.setValue(self._bar.value() + (step if y > thumb.bottom() else -step))
        self.update()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._grab_offset is not None:
            thumb = self._thumb_rect()
            span = max(1, self.height() - thumb.height())
            top = int(event.position().y()) - self._grab_offset
            ratio = max(0.0, min(1.0, top / span))
            self._bar.setValue(int(round(ratio * self._bar.maximum())))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._grab_offset = None
        self._hold.start()
        self.update()
        event.accept()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.wake()

    def leaveEvent(self, event) -> None:
        self._hover = False
        self._hold.start()
        self.update()
