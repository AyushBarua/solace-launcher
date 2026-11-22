"""
Game cover painting and the focusable row tile used by the Play page.

A tile is a rounded cover (real art when the game has some, otherwise a
genre-tinted gradient with a big emoji) with the game name along the bottom and
a small badge in the corner. The selected tile is larger and gets a ring, so
the focus is obvious from across the room.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPixmap, QPainterPath, QLinearGradient, QFont, QPen, QBrush,
)
from PyQt6.QtWidgets import QWidget

from core import theme as _t

# Pastel gradient per genre for games without cover art.
GENRE_PALETTE = {
    "Arcade":             ("#FFE9D6", "#FFC9A3"),
    "Racing":             ("#FFE3D1", "#FFB78A"),
    "Puzzle":             ("#EADFFF", "#CDB8FF"),
    "Sports/Arcade":      ("#DDF3E2", "#B4E3C1"),
    "Sports/Skill":       ("#FFF0CF", "#FFD98A"),
    "Cognitive/Sequence": ("#DCEBFF", "#B3D2FF"),
    "Casual/Skill":       ("#D9F3EA", "#A9E2CF"),
    "Puzzle/Aim":         ("#E3E6FF", "#BFC6FF"),
    "Arcade/Breakout":    ("#FFDFE6", "#FFB5C6"),
    "Arcade/Catch":       ("#EAF5D3", "#CDE79B"),
}
_FALLBACK_PALETTE = ("#EFECE5", "#DDD8CC")

TILE_SIZE = QSize(236, 150)
TILE_MARGIN = 12         # room around the card for the focus pop and ring
SELECT_GROW = 8          # the focused tile swells by this much on every side
CELL_SIZE = QSize(TILE_SIZE.width() + 2 * TILE_MARGIN,
                  TILE_SIZE.height() + 2 * TILE_MARGIN)
TILE_RADIUS = 24
PROGRESS_WASH, PROGRESS_GLOW, PROGRESS_FEATHER = 46, 60, 54   # rotation sweep: wash alpha, extra alpha at the edge, edge softness (px)
EMOJI_FONT = "Segoe UI Emoji"


def _is_dark() -> bool:
    return QColor(_t.BACKGROUND).lightness() < 100


def load_cover(game: dict) -> QPixmap:
    """The game's art as a pixmap, or a null pixmap when it has none."""
    art = game.get("art_url", "")
    if art and os.path.exists(str(art)):
        return QPixmap(str(art))
    return QPixmap()


def paint_cover(p: QPainter, rect: QRectF, game: dict, pix: QPixmap,
                radius: float, emoji_px: int) -> None:
    """Fill `rect` with the cover: art cropped to fill, or gradient plus emoji."""
    p.save()
    clip = QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
    if not pix.isNull():
        scaled = pix.scaled(int(rect.width()), int(rect.height()),
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
        ox = (scaled.width() - rect.width()) / 2
        oy = (scaled.height() - rect.height()) / 2
        p.drawPixmap(rect.toRect(), scaled,
                     QRectF(ox, oy, rect.width(), rect.height()).toRect())
    else:
        c1, c2 = GENRE_PALETTE.get(game.get("genre", ""), _FALLBACK_PALETTE)
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0, QColor(c1))
        grad.setColorAt(1, QColor(c2))
        p.fillRect(rect, QBrush(grad))
        if emoji_px > 0:                       # the banner draws its own emoji
            font = QFont(EMOJI_FONT)
            font.setPixelSize(emoji_px)
            p.setFont(font)
            p.setPen(QColor(255, 255, 255, 200))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, game.get("emoji") or "🎮")
    p.restore()


class GameTile(QWidget):
    """One game in a row. kind is 'installed', 'download' or 'soon'."""

    clicked = pyqtSignal(object)          # emits the tile itself

    def __init__(self, game: dict, kind: str, recommended: bool = False, parent=None):
        super().__init__(parent)
        self.game = game
        self.kind = kind
        self.recommended = recommended
        self.downloading = False
        self.failed = False
        self._selected = False
        self._progress: float | None = None     # rotation countdown along the tile's foot
        self._pix = load_cover(game)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_size()

    # ── state ────────────────────────────────────────────────────────────────
    @property
    def selected(self) -> bool:
        return self._selected

    def set_selected(self, on: bool) -> None:
        if on != self._selected:
            self._selected = on
            self._apply_size()
            self.update()

    def set_progress(self, fraction: float | None) -> None:
        """Show how far through its time on the featured art this game is (None: hide)."""
        if fraction is None and self._progress is None:
            return
        if (fraction is not None and self._progress is not None
                and abs(fraction - self._progress) < 0.004):
            return
        self._progress = fraction
        self.update()

    def set_state(self, downloading: bool = False, failed: bool = False) -> None:
        self.downloading, self.failed = downloading, failed
        self.update()

    def _apply_size(self) -> None:
        self.setFixedSize(CELL_SIZE)           # fixed cell: the focus pop is painted in the margin

    def sizeHint(self) -> QSize:
        return self.size()

    # ── painting ─────────────────────────────────────────────────────────────
    def _badge_text(self) -> str:
        if self.downloading:
            return "DOWNLOADING…"
        if self.failed:
            return "RETRY"
        if self.kind == "download":
            return "DOWNLOAD"
        if self.kind == "soon":
            return "SOON"
        return "FOR YOU" if self.recommended else ""

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing
                         | QPainter.RenderHint.SmoothPixmapTransform
                         | QPainter.RenderHint.TextAntialiasing)
        inset = TILE_MARGIN - (SELECT_GROW if self._selected else 0)
        card = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        self._paint_shadow(p, card)
        paint_cover(p, card, self.game, self._pix, TILE_RADIUS,
                    emoji_px=int(card.height() * 0.42))
        if self.kind == "soon":                       # dim what can't be played yet
            p.setBrush(QColor(0, 0, 0, 90) if _is_dark() else QColor(255, 255, 255, 70))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(card, TILE_RADIUS, TILE_RADIUS)
        self._paint_progress(p, card)                 # under the name and badge, which stay crisp
        self._paint_name_strip(p, card)
        self._paint_badge(p, card)
        if self._selected:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(_t.PRIMARY), 3.5))
            p.drawRoundedRect(card.adjusted(-1, -1, 1, 1), TILE_RADIUS + 1, TILE_RADIUS + 1)
        p.end()

    def _paint_shadow(self, p: QPainter, card: QRectF) -> None:
        """A soft drop shadow inside the cell margin, so tiles lift off the page."""
        p.setPen(Qt.PenStyle.NoPen)
        shade = QColor(0, 0, 0, 34) if _is_dark() else QColor(60, 40, 20, 14)
        for i in range(4, 0, -1):
            grow = i * 2.0
            p.setBrush(shade)
            p.drawRoundedRect(card.adjusted(-grow, -grow * 0.3 + 2, grow, grow + 3),
                              TILE_RADIUS + grow, TILE_RADIUS + grow)

    def _paint_name_strip(self, p: QPainter, card: QRectF) -> None:
        strip_h = card.height() * 0.5
        fade = QLinearGradient(0, card.bottom() - strip_h, 0, card.bottom())
        fade.setColorAt(0, QColor(0, 0, 0, 0))
        fade.setColorAt(1, QColor(0, 0, 0, 185))
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(card, TILE_RADIUS, TILE_RADIUS)
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        p.fillRect(QRectF(card.left(), card.bottom() - strip_h, card.width(), strip_h),
                   QBrush(fade))
        p.restore()
        font = QFont(_t.FONT_DISPLAY)
        font.setPixelSize(19 if self._selected else 17)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))
        text_rect = card.adjusted(16, 0, -16, -12)
        name = p.fontMetrics().elidedText(self.game.get("name", "Game"),
                                          Qt.TextElideMode.ElideRight,
                                          int(text_rect.width()))
        p.drawText(text_rect, int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft), name)

    def _paint_progress(self, p: QPainter, card: QRectF) -> None:
        """A soft light wash that sweeps across the whole tile, left to right, until the
        next game comes up. Kept faint, with a feathered leading edge."""
        if self._progress is None:
            return
        edge_x = card.left() + card.width() * max(0.0, min(1.0, self._progress))
        feather = min(PROGRESS_FEATHER, card.width() * 0.5)
        wash = QLinearGradient(edge_x - feather, 0, edge_x, 0)     # solid behind the edge, clear at it
        wash.setColorAt(0.0, QColor(255, 255, 255, PROGRESS_WASH))
        wash.setColorAt(0.85, QColor(255, 255, 255, PROGRESS_WASH + PROGRESS_GLOW))
        wash.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(card, TILE_RADIUS, TILE_RADIUS)
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        body = QRectF(card.left(), card.top(), max(0.0, edge_x - feather - card.left()), card.height())
        p.fillRect(body, QColor(255, 255, 255, PROGRESS_WASH))
        p.fillRect(QRectF(edge_x - feather, card.top(), feather, card.height()), QBrush(wash))
        p.restore()

    def _paint_badge(self, p: QPainter, card: QRectF) -> None:
        text = self._badge_text()
        if not text:
            return
        font = QFont(_t.FONT_DISPLAY)
        font.setPixelSize(12)
        font.setBold(True)
        p.setFont(font)
        w = p.fontMetrics().horizontalAdvance(text) + 20
        box = QRectF(card.right() - w - 12, card.top() + 12, w, 26)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 230))
        p.drawRoundedRect(box, 13, 13)
        p.setPen(QColor(20, 19, 15))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self)
