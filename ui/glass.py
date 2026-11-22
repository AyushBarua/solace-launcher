"""
Solace Glass — shared widget kit for the redesigned UI.

Look: warm paper background with a soft colour haze, white frosted cards with
large radii, round black action buttons, big numerals. Every colour is read
from core.theme at paint time, so a live theme switch still works.

Widgets
    GlassBackground  painted background with the colour haze
    GlassCard        rounded frosted card with soft shadow and a focus ring
    RoundArrowButton round black button with a drawn arrow
    PillButton       black (or light) pill button
    IconBubble       circular icon holder
    Chip             small rounded label
    ArcGauge         tick-mark semicircle gauge with a needle
    DotRow           row of small dots (e.g. the last 7 days)
    StatTile         GlassCard with icon, label and a big number
"""
from __future__ import annotations

import math

from PyQt6.QtCore import Qt, QRectF, QPointF, QSize, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QRadialGradient, QPen, QBrush,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QPushButton, QLabel, QHBoxLayout, QVBoxLayout, QSizePolicy,
)

from core import theme as _t

CARD_RADIUS = 28
HAZE_BLOBS = (
    # (x, y, radius as share of width, (r, g, b, alpha))
    (0.58, 0.18, 0.34, (255, 150, 70, 150)),    # orange
    (0.42, 0.06, 0.26, (255, 214, 110, 140)),   # yellow
    (0.90, 0.55, 0.30, (130, 175, 255, 110)),   # blue
    (0.10, 0.80, 0.28, (255, 170, 160, 90)),    # peach
)


def _is_dark() -> bool:
    return QColor(_t.BACKGROUND).lightness() < 100


# Theme-aware colour helpers. In the light theme each returns exactly the value
# that used to be hardcoded; in the dark theme it returns the dark equivalent.
def is_dark() -> bool:
    return _is_dark()


def pane_bg(alpha: float = 0.80) -> str:
    """Translucent fill for pills and panes sitting on the haze."""
    return f"rgba(46,43,39,{alpha})" if _is_dark() else f"rgba(255,255,255,{alpha})"


def pane_edge() -> str:
    return "rgba(255,255,255,0.10)" if _is_dark() else "rgba(255,255,255,0.95)"


def solid_pane() -> str:
    """Opaque panel colour (was a hardcoded white)."""
    return _t.SURFACE_CON if _is_dark() else "#FFFFFF"


def hover_ink() -> str:
    """Hover colour for primary (ink) buttons."""
    return "#FFFFFF" if _is_dark() else "#2B2A27"


def hover_pane() -> str:
    return _t.SURFACE_CON_HIGH if _is_dark() else "#FFFFFF"


def tint(alpha: float) -> str:
    """Faint overlay that darkens (light theme) or lightens (dark theme)."""
    return f"rgba(255,255,255,{alpha + 0.02})" if _is_dark() else f"rgba(20,19,15,{alpha})"


def on_accent() -> str:
    """Text colour on an orange (accent) fill."""
    return "#14130F" if _is_dark() else "#FFFFFF"


class GlassBackground(QWidget):
    """Paper base colour with large, soft colour blobs painted over it."""

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(_t.BACKGROUND))
        strength = 0.35 if _is_dark() else 1.0
        for fx, fy, fr, (r, g, b, a) in HAZE_BLOBS:
            radius = fr * max(w, h)
            grad = QRadialGradient(QPointF(fx * w, fy * h), radius)
            grad.setColorAt(0.0, QColor(r, g, b, int(a * strength)))
            grad.setColorAt(0.45, QColor(r, g, b, int(a * strength * 0.42)))
            grad.setColorAt(1.0, QColor(r, g, b, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawEllipse(QPointF(fx * w, fy * h), radius, radius)
        p.end()


SHADOW_PAD = 14        # room around the card for the painted shadow
SHADOW_TOP = 10        # less room above than below: the shadow falls downward
SHADOW_BOTTOM = 18
SHADOW_STEPS = 7


def paint_card_shadow(p: QPainter, card: QRectF, radius: float, fade: float = 1.0) -> None:
    """Soft downward shadow around `card`, painted in the SHADOW_* margins."""
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(SHADOW_STEPS, 0, -1):
        grow = i * (SHADOW_PAD - 2) / SHADOW_STEPS
        shade = QColor(0, 0, 0, int(22 * fade)) if _is_dark() else QColor(60, 40, 20, int(7 * fade))
        p.setBrush(shade)
        p.drawRoundedRect(card.adjusted(-grow, -grow * 0.4 + 5, grow, grow + 6),
                          radius + grow, radius + grow)


class GlassCard(QFrame):
    """Frosted rounded card. Set selected=True to draw the focus ring.

    The soft shadow is painted by the card itself inside its own margins
    (QGraphicsDropShadowEffect rendered clipped inside the scaled, scrolling
    view). The widget is therefore SHADOW_PAD larger than the visible card on
    each side; layouts inside it are already inset by that margin.
    """

    def __init__(self, radius: int = CARD_RADIUS, alpha: int = 205,
                 shadow: bool = True, parent=None):
        super().__init__(parent)
        self._radius = radius
        self._alpha = alpha
        self._shadow = shadow
        self._selected = False
        self._faded = False
        self._fill: str | None = None          # None = the theme's card colour
        if shadow:
            self.setContentsMargins(SHADOW_PAD, SHADOW_TOP, SHADOW_PAD, SHADOW_BOTTOM)

    def set_fill(self, colour: str | None, alpha: int | None = None) -> None:
        """Paint the card in `colour` (e.g. an inverted dark card) instead of the default."""
        self._fill = colour
        if alpha is not None:
            self._alpha = alpha
        self.update()

    def card_rect(self) -> QRectF:
        """The visible card, inside the shadow margins."""
        if not self._shadow:
            return QRectF(self.rect())
        return QRectF(self.rect()).adjusted(SHADOW_PAD, SHADOW_TOP,
                                            -SHADOW_PAD, -SHADOW_BOTTOM)

    def set_selected(self, on: bool):
        if on != self._selected:
            self._selected = on
            self.update()

    def set_faded(self, on: bool):
        if on != self._faded:
            self._faded = on
            self.update()

    def _paint_shadow(self, p: QPainter, card: QRectF):
        paint_card_shadow(p, card, self._radius, 0.55 if self._faded else 1.0)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = self.card_rect()
        if self._shadow:
            self._paint_shadow(p, card)
        rect = card.adjusted(1, 1, -1, -1)
        base = QColor(self._fill or _t.SURFACE_CON_LOW)
        base.setAlpha(int(self._alpha * (0.55 if self._faded else 1.0)))
        p.setBrush(base)
        edge = QColor(255, 255, 255, 190) if not _is_dark() else QColor(255, 255, 255, 25)
        p.setPen(QPen(edge, 1.2))
        p.drawRoundedRect(rect, self._radius, self._radius)
        if self._selected:
            ring = QColor(_t.PRIMARY)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(ring, 3))
            p.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5),
                              self._radius - 1, self._radius - 1)
        p.end()


class RoundArrowButton(QPushButton):
    """Round action button with a drawn up-right arrow."""

    def __init__(self, size: int = 52, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)

    def sizeHint(self):
        return QSize(self._size, self._size)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        fill = QColor(_t.PRIMARY)
        if not enabled:
            fill = QColor(_t.OUTLINE_VARIANT)
        elif self.underMouse() or self.hasFocus():
            fill = QColor(_t.PRIMARY).lighter(150)
        if self.isDown():
            fill = QColor(_t.PRIMARY_CONTAINER)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))

        arrow = QColor(_t.ON_PRIMARY) if enabled else QColor(_t.OUTLINE)
        pen = QPen(arrow, max(2.0, self._size * 0.05),
                   Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        c = self._size / 2.0
        d = self._size * 0.16
        p.drawLine(QPointF(c - d, c + d), QPointF(c + d, c - d))
        p.drawLine(QPointF(c - d * 0.1, c - d), QPointF(c + d, c - d))
        p.drawLine(QPointF(c + d, c - d), QPointF(c + d, c + d * 0.1))
        p.end()


class PillButton(QPushButton):
    """Black pill button; kind='light' gives a white pill with dark text."""

    def __init__(self, text: str = "", kind: str = "dark", height: int = 54,
                 parent=None):
        super().__init__(text, parent)
        self._kind = kind
        self.setFixedHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restyle()

    def restyle(self):
        r = self.height() // 2
        if self._kind == "dark":
            bg, fg, hover = _t.PRIMARY, _t.ON_PRIMARY, hover_ink()
            border = "none"
        else:
            bg, fg = solid_pane(), _t.ON_SURFACE
            hover = _t.SURFACE_CON_HIGH2 if _is_dark() else "#F4F1EA"
            border = f"1px solid {_t.OUTLINE_VARIANT}"
        self.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg}; border: {border};"
            f" border-radius: {r}px; padding: 0 28px;"
            f" font-family: '{_t.FONT_DISPLAY}'; font-size: 17px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
            f"QPushButton:pressed {{ background: {_t.PRIMARY_CONTAINER}; color: {on_accent()}; }}"
            f"QPushButton:disabled {{ background: {_t.SURFACE_DIM}; color: {_t.OUTLINE};"
            f" border: 1px solid {_t.OUTLINE_VARIANT}; }}"
        )


class IconBubble(QLabel):
    """Circular holder for an emoji or short glyph."""

    def __init__(self, glyph: str = "", size: int = 56, parent=None):
        super().__init__(glyph, parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background: {tint(0.06)}; border-radius: {size // 2}px;"
            f" font-size: {int(size * 0.46)}px; color: {_t.ON_SURFACE};"
        )


class Chip(QFrame):
    """Small rounded label. tone='accent' tints it with the orange accent."""

    def __init__(self, text: str, glyph: str = "", tone: str = "neutral",
                 parent=None):
        super().__init__(parent)
        accent = tone == "accent"
        if _is_dark():
            bg = "rgba(255,154,77,0.18)" if accent else pane_bg(0.72)
            border = "rgba(255,154,77,0.45)" if accent else "rgba(255,255,255,0.12)"
        else:
            bg = "rgba(255,178,107,0.28)" if accent else "rgba(255,255,255,0.72)"
            border = "rgba(194,72,10,0.35)" if accent else "rgba(20,19,15,0.10)"
        fg = _t.PRIMARY_CONTAINER if accent else _t.ON_SURFACE
        self.setObjectName("chip")
        self.setStyleSheet(
            f"QFrame#chip {{ background: {bg}; border: 1px solid {border};"
            f" border-radius: 16px; }}"       # under half the chip height, or Qt draws square corners
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 8, 18, 8)
        row.setSpacing(8)
        if glyph:
            g = QLabel(glyph)
            g.setStyleSheet("font-size: 16px; background: transparent; border: none;")
            row.addWidget(g)
        self.label = QLabel(text)
        self.label.setStyleSheet(
            f"color: {fg}; font-family: '{_t.FONT_DISPLAY}'; font-size: 15px;"
            f" font-weight: bold; background: transparent; border: none;"
        )
        row.addWidget(self.label)

    def set_text(self, text: str):
        self.label.setText(text)


class ArcGauge(QWidget):
    """Tick-mark semicircle gauge with a needle. value is 0.0 to 1.0."""

    START_DEG = 210.0     # lower left
    SWEEP_DEG = 240.0     # clockwise over the top to lower right
    TICKS = 44

    def __init__(self, value: float = 0.0, parent=None):
        super().__init__(parent)
        self._value = max(0.0, min(1.0, value))
        self.setMinimumSize(220, 150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_value(self, value: float):
        self._value = max(0.0, min(1.0, value))
        self.update()

    @staticmethod
    def _point(cx, cy, radius, deg):
        rad = math.radians(deg)
        return QPointF(cx + radius * math.cos(rad), cy - radius * math.sin(rad))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        radius = min(w / 2.0, h * 0.92) - 6
        cx, cy = w / 2.0, radius + 6
        dark = QColor(_t.PRIMARY)
        light = QColor(_t.OUTLINE_VARIANT)
        accent = QColor(_t.PRIMARY_CONTAINER)
        for i in range(self.TICKS + 1):
            frac = i / self.TICKS
            deg = self.START_DEG - self.SWEEP_DEG * frac
            filled = frac <= self._value and self._value > 0
            p.setPen(QPen(dark if filled else light, 3.0,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(self._point(cx, cy, radius * 0.84, deg),
                       self._point(cx, cy, radius * 0.97, deg))
        needle_deg = self.START_DEG - self.SWEEP_DEG * self._value
        p.setPen(QPen(accent, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(self._point(cx, cy, radius * 0.30, needle_deg),
                   self._point(cx, cy, radius * 0.68, needle_deg))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawEllipse(self._point(cx, cy, radius * 0.72, needle_deg), 6, 6)
        p.end()


class DotRow(QWidget):
    """Row of small dots, e.g. active days this week. True = filled."""

    def __init__(self, flags: list[bool], dot: int = 12, gap: int = 9, parent=None):
        super().__init__(parent)
        self._flags = list(flags)
        self._dot, self._gap = dot, gap
        n = len(self._flags)
        self.setFixedSize(n * dot + max(0, n - 1) * gap + 2, dot + 2)

    def set_flags(self, flags: list[bool]):
        self._flags = list(flags)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, on in enumerate(self._flags):
            x = 1 + i * (self._dot + self._gap)
            rect = QRectF(x, 1, self._dot, self._dot)
            if on:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(_t.PRIMARY))
            else:
                p.setPen(QPen(QColor(_t.OUTLINE), 1.6))
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(rect)
        p.end()


class StatTile(GlassCard):
    """Icon bubble, label and a big number. Optional round arrow button."""

    clicked = pyqtSignal()

    def __init__(self, label: str, value: str, glyph: str = "",
                 unit: str = "", dots: list[bool] | None = None,
                 with_arrow: bool = False, parent=None):
        super().__init__(parent=parent)
        self.setMinimumHeight(190)
        col = QVBoxLayout(self)
        col.setContentsMargins(26, 24, 26, 22)
        col.setSpacing(0)

        top = QHBoxLayout()
        top.setSpacing(0)
        top.addWidget(IconBubble(glyph, 48))
        top.addStretch()
        if with_arrow:
            arrow = RoundArrowButton(46)
            arrow.clicked.connect(self.clicked.emit)
            top.addWidget(arrow)
        col.addLayout(top)
        col.addStretch()

        self.label = QLabel(label)
        self.label.setStyleSheet(
            f"color: {_t.ON_SURFACE_VAR}; font-family: '{_t.FONT_BODY}';"
            f" font-size: 17px; font-weight: bold; background: transparent;"
        )
        col.addWidget(self.label)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.value = QLabel(value)
        self.value.setStyleSheet(
            f"color: {_t.ON_SURFACE}; font-family: '{_t.FONT_DISPLAY}';"
            f" font-size: 58px; font-weight: 800; letter-spacing: -1px;"
            f" background: transparent;"
        )
        bottom.addWidget(self.value, alignment=Qt.AlignmentFlag.AlignBottom)
        if unit:
            u = QLabel(unit)
            u.setStyleSheet(
                f"color: {_t.ON_SURFACE_VAR}; font-family: '{_t.FONT_BODY}';"
                f" font-size: 20px; font-weight: bold; background: transparent;"
            )
            bottom.addWidget(u, alignment=Qt.AlignmentFlag.AlignBottom)
        bottom.addStretch()
        self.dots = DotRow(dots) if dots else None
        if self.dots:
            bottom.addWidget(self.dots, alignment=Qt.AlignmentFlag.AlignBottom)
        col.addLayout(bottom)

    def set_value(self, value: str):
        self.value.setText(value)

    def set_dots(self, flags: list[bool]):
        if self.dots:
            self.dots.set_flags(flags)
