"""
PlayPage — the single place to pick a game.

Layout (learned from console launchers, not their look). The whole page scrolls.

  Featured section   full-bleed, edge to edge and behind the floating top bar like
                     a TV launcher: the focused game enlarged (cover, title, blurb,
                     Play button) with today's recommended games as a "Featured"
                     strip along its bottom. The banner and the strip are one
                     section, so nothing is shown twice.
  Your other games   the remaining installed games, one row.
  Get more games     games ready to download, then coming-soon placeholders.

A game appears in exactly one section. Moving the focus anywhere changes the
featured card, so it always describes what is highlighted.

Navigation (keyboard or controller): left/right move along a row, up/down move
between rows, select activates. Pressing up on the featured strip hands focus
back to the launcher, which uses it for the tab bar. Mouse: click a tile to
focus it, click it again (or the Play button) to play or download.
"""
from __future__ import annotations

from dataclasses import dataclass

import time

from PyQt6.QtCore import Qt, QRectF, QPoint, QTimer, QVariantAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QPainterPath, QPen, QPixmap, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QPushButton,
    QGraphicsOpacityEffect,
)

from core import theme as _t
from core.i18n import t
from ui.calibration_banner import CalibrationBanner
from ui.top_bar import TOP_BAR_HEIGHT
from ui.floating_scrollbar import FloatingScrollBar
from ui.glass import (
    Chip, GlassCard, paint_card_shadow, SHADOW_PAD, SHADOW_TOP, SHADOW_BOTTOM,
)
from ui.play_tiles import (
    GameTile, load_cover, paint_cover, EMOJI_FONT, CELL_SIZE, TILE_MARGIN,
)

PAGE_EDGE = 40                 # where the visible cards start, from the window edge
PAGE_MARGIN = PAGE_EDGE - SHADOW_PAD     # the cards carry their own shadow margin
SECTION_PAD_SIDE, SECTION_PAD_TOP, SECTION_PAD_BOTTOM = 22, 18, 10
SECTION_RADIUS = 34
PAGE_TOP_MARGIN = 2
MAX_CONTENT_WIDTH = 1800
PAGE_BOTTOM_PAD = 56           # a little air under the last section; snapping a row to the top stops at the page end
SECTION_GAP = 18
HERO_TEXT_MIN = 210            # least height of the text area above the tile strip
HERO_GAP = 14                  # space between the text area and the strip
NEXT_SECTION_PEEK = 56         # how much of the next section shows under the featured section
HERO_PAD_TOP = TOP_BAR_HEIGHT + 20     # the art runs behind the top bar; text starts below it
HERO_PAD_BOTTOM, HERO_PAD_SIDE = 22, 64
ROTATE_S = 7.0                 # the featured art moves to the next game after this long
TICK_MS = 50                   # clock and pager refresh rate
ART_FADE_MS = 650              # the new cover fades in (and eases in from a slight zoom)
ART_ZOOM = 0.06                # how much larger the incoming cover starts
TEXT_OUT_MS, TEXT_IN_MS = 150, 350

HERO_TEXT_SHARE = 0.5          # share of the width used by the text column
HERO_SHADE_END = 0.62          # the dark text-side gradient fades out by here
HERO_FLOOR_SHARE = 0.55        # the dark floor behind the strip covers this much of the height
HERO_SCRIM_HEIGHT = TOP_BAR_HEIGHT + 70   # soft dark band so the top bar stays readable
TITLE_PX_SHORT, TITLE_PX_MEDIUM, TITLE_PX_LONG = 76, 60, 46   # by name length
TITLE_MEDIUM_FROM, TITLE_LONG_FROM = 19, 25
BLURB_MAX_CHARS = 150
FEATURED_COUNT = 5
HEADING_PX = 26
ROW_HEIGHT = CELL_SIZE.height() + 4
STRIP_HEADING_H = HEADING_PX + 14
HERO_MIN_HEIGHT = (HERO_PAD_TOP + HERO_TEXT_MIN + HERO_GAP + STRIP_HEADING_H + ROW_HEIGHT
                   + HERO_PAD_BOTTOM)
ON_ART = "#FFFFFF"             # text on the banner's dark gradient
ON_ART_SOFT = "rgba(255,255,255,0.88)"
ON_ART_TAG = "#FFB26B"

# Placeholder games shown at the end until they exist.
COMING_SOON = [
    {"id": "soon_balloon", "name": "Balloon Pop", "emoji": "🎈",
     "description": "Pop balloons to train large arm movement and tracking.",
     "body_parts": ["arm", "horizontal"], "genre": "Casual/Skill"},
    {"id": "soon_fruit", "name": "Fruit Ninja", "emoji": "🍉",
     "description": "Slice fruit flying across the screen — trains speed and tracking.",
     "body_parts": ["arm", "wrist"], "genre": "Arcade/Catch"},
    {"id": "soon_painter", "name": "Stroky Painter", "emoji": "🎨",
     "description": "Paint strokes on canvas using the Solace controller — ideal for fine motor recovery.",
     "body_parts": ["wrist", "vertical", "horizontal"], "genre": "Puzzle"},
    {"id": "soon_maze", "name": "Maze Navigator", "emoji": "🧩",
     "description": "Guide a ball through a maze — trains precise fine motor control.",
     "body_parts": ["wrist", "balance"], "genre": "Puzzle/Aim"},
]


@dataclass(frozen=True)
class Entry:
    """One tile's data: the game, how it can be used, and whether it leads."""
    game: dict
    kind: str                 # 'installed' | 'download' | 'soon'
    recommended: bool = False

    @property
    def game_id(self) -> str:
        return self.game.get("id", "")


def _short(text: str, limit: int = BLURB_MAX_CHARS) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


# ── Rows ──────────────────────────────────────────────────────────────────────

class _RowScroll(QScrollArea):
    """Horizontal strip of tiles. Vertical wheel movement goes to the page."""

    def wheelEvent(self, event) -> None:
        dx = event.angleDelta().x()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if dx or shift:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - (dx or event.angleDelta().y()))
            event.accept()
        else:
            event.ignore()


class _Row(QWidget):
    """A horizontally scrolling row of tiles, with an optional heading."""

    def __init__(self, title: str = "", ink: str | None = None, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        if title:
            heading = QLabel(title)
            heading.setContentsMargins(TILE_MARGIN, 0, 0, 0)     # lines up with the tile edge
            heading.setStyleSheet(
                f"color: {ink or _t.ON_SURFACE}; font-family: '{_t.FONT_DISPLAY}';"
                f" font-size: {HEADING_PX}px; font-weight: bold; background: transparent;")
            col.addWidget(heading)

        self.scroll = _RowScroll()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(ROW_HEIGHT)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        strip = QWidget()
        strip.setStyleSheet("background: transparent;")
        self._strip = QHBoxLayout(strip)
        self._strip.setContentsMargins(0, 0, 0, 0)
        self._strip.setSpacing(8)
        self._strip.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.scroll.setWidget(strip)
        col.addWidget(self.scroll)
        self.tiles: list[GameTile] = []

    def add_tile(self, tile: GameTile) -> None:
        self.tiles.append(tile)
        self._strip.addWidget(tile)


class _Section(GlassCard):
    """A frosted card holding one titled row of tiles."""

    def __init__(self, title: str, parent=None):
        super().__init__(radius=SECTION_RADIUS, alpha=215, parent=parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SECTION_PAD_SIDE, SECTION_PAD_TOP,
                               SECTION_PAD_SIDE, SECTION_PAD_BOTTOM)
        self.row = _Row(title)
        self.row.pane = self
        lay.addWidget(self.row)


# ── Featured section ──────────────────────────────────────────────────────────

class _Hero(QWidget):
    """The focused game enlarged, with the recommended strip along its bottom."""

    action_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._game: dict = {}
        self._pix = QPixmap()
        self._prev_game: dict = {}                 # the cover being faded out, if any
        self._prev_pix = QPixmap()
        self._art_t = 1.0                          # 0..1 progress of the cover crossfade
        self._pending: tuple | None = None         # text waiting for the old text to fade out
        self._art_anim = QVariantAnimation(self)
        self._art_anim.setStartValue(0.0)
        self._art_anim.setEndValue(1.0)
        self._art_anim.setDuration(ART_FADE_MS)
        self._art_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._art_anim.valueChanged.connect(self._on_art_step)
        self._art_anim.finished.connect(self._on_art_done)
        self._text_anim = QVariantAnimation(self)
        self._text_anim.valueChanged.connect(self._on_text_step)
        self._text_anim.finished.connect(self._on_text_done)
        self._text_fading_out = False
        self.setFixedHeight(HERO_MIN_HEIGHT)       # PlayPage grows it to fill the screen

        outer = QVBoxLayout(self)
        # The tiles carry their own cell margin, so the text and the strip line up.
        outer.setContentsMargins(HERO_PAD_SIDE - TILE_MARGIN, HERO_PAD_TOP,
                                 HERO_PAD_SIDE - TILE_MARGIN, HERO_PAD_BOTTOM)
        outer.setSpacing(HERO_GAP)

        self._text = QWidget()
        self._text.setStyleSheet("background: transparent;")
        col = QVBoxLayout(self._text)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        self._tag = QLabel()
        self._title = QLabel()
        self._title.setWordWrap(True)
        self._blurb = QLabel()
        self._blurb.setWordWrap(True)
        self._chips = QHBoxLayout()
        self._chips.setSpacing(10)
        self._button = QPushButton()
        self._button.setFixedHeight(60)
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.clicked.connect(self.action_clicked.emit)
        col.addStretch(1)                         # the text block sits in the middle of the card
        col.addWidget(self._tag)
        col.addWidget(self._title)
        col.addWidget(self._blurb)
        col.addLayout(self._chips)
        col.addSpacing(10)
        col.addWidget(self._button, 0, Qt.AlignmentFlag.AlignLeft)
        col.addStretch(1)

        text_row = QHBoxLayout()
        text_row.setContentsMargins(TILE_MARGIN, 0, 0, 0)
        text_row.addWidget(self._text)
        text_row.addStretch()
        outer.addLayout(text_row, 1)              # takes all the extra height

        self.strip = _Row(t("play_row_featured"), ink=ON_ART)   # today's recommended games
        outer.addWidget(self.strip)
        self._style_static()

    def _style_static(self) -> None:
        self._tag.setStyleSheet(
            f"color: {ON_ART_TAG}; font-family: '{_t.FONT_DISPLAY}'; font-size: 14px;"
            f" font-weight: bold; letter-spacing: 2px; background: transparent;")
        self._blurb.setStyleSheet(
            f"color: {ON_ART_SOFT}; font-family: '{_t.FONT_BODY}'; font-size: 21px;"
            f" background: transparent;")
        self._button.setStyleSheet(
            f"QPushButton {{ background: #FFFFFF; color: #14130F; border: none;"
            f" border-radius: 30px; padding: 0 40px; font-family: '{_t.FONT_DISPLAY}';"
            f" font-size: 18px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: #F1EEE7; }}"
            f"QPushButton:disabled {{ background: rgba(255,255,255,0.30);"
            f" color: rgba(255,255,255,0.85); }}")

    def show_entry(self, entry: Entry, tag: str, blurb: str, button: str,
                   button_enabled: bool) -> None:
        args = (entry, tag, blurb, button, button_enabled)
        if self._pending is not None:              # mid-swap: the new text waits its turn
            self._pending = args
            self._swap_art(entry)
            return
        changed = bool(self._game) and self._game.get("id") != entry.game.get("id")
        if not changed or not self.isVisible():
            self._apply_art(entry)
            self._apply_text(*args)
            return
        self._swap_art(entry)
        self._pending = args
        self._set_text_opacity(1.0)
        self._text_fading_out = True
        self._run_text_anim(1.0, 0.0, TEXT_OUT_MS)

    # ── Crossfade ────────────────────────────────────────────────────────────
    def _apply_art(self, entry: Entry) -> None:
        self._game = entry.game
        self._pix = load_cover(entry.game)

    def _swap_art(self, entry: Entry) -> None:
        """Fade the new cover in over the old one, with a slight zoom-in."""
        if self._game.get("id") == entry.game.get("id"):
            return
        if self._art_anim.state() != QVariantAnimation.State.Running:
            self._prev_game, self._prev_pix = self._game, self._pix
        self._apply_art(entry)
        self._art_t = 0.0
        self._art_anim.stop()
        self._art_anim.start()

    def _on_art_step(self, value) -> None:
        self._art_t = float(value)
        self.update()

    def _on_art_done(self) -> None:
        self._art_t = 1.0
        self._prev_game, self._prev_pix = {}, QPixmap()
        self.update()

    def _run_text_anim(self, start: float, end: float, ms: int) -> None:
        self._text_anim.stop()
        self._text_anim.setStartValue(start)
        self._text_anim.setEndValue(end)
        self._text_anim.setDuration(ms)
        self._text_anim.start()

    def _set_text_opacity(self, value: float) -> None:
        effect = self._text.graphicsEffect()
        if effect is None:
            effect = QGraphicsOpacityEffect(self._text)
            self._text.setGraphicsEffect(effect)
        effect.setOpacity(value)

    def _on_text_step(self, value) -> None:
        self._set_text_opacity(float(value))

    def _on_text_done(self) -> None:
        if self._text_fading_out:                  # old text is gone: swap, then fade the new in
            self._text_fading_out = False
            args, self._pending = self._pending, None
            if args is not None:
                self._apply_text(*args)
            self._run_text_anim(0.0, 1.0, TEXT_IN_MS)
        else:
            self._text.setGraphicsEffect(None)     # back to plain, crisp text

    def _apply_text(self, entry: Entry, tag: str, blurb: str, button: str,
                    button_enabled: bool) -> None:
        self._tag.setText(tag)
        self._tag.setVisible(bool(tag))
        name = entry.game.get("name", "")
        self._title.setText(name)
        px = (TITLE_PX_LONG if len(name) >= TITLE_LONG_FROM
              else TITLE_PX_MEDIUM if len(name) >= TITLE_MEDIUM_FROM else TITLE_PX_SHORT)
        self._title.setStyleSheet(
            f"color: {ON_ART}; font-family: '{_t.FONT_DISPLAY}'; font-size: {px}px;"
            f" font-weight: 800; letter-spacing: -2px; background: transparent;")
        self._blurb.setText(_short(blurb))
        self._button.setText(button)
        self._button.setEnabled(button_enabled)
        self._set_chips(entry.game)
        self.update()

    def _set_chips(self, game: dict) -> None:
        while self._chips.count():
            widget = self._chips.takeAt(0).widget()
            if widget:
                widget.setParent(None)            # vanish now; deleteLater alone keeps painting
                widget.deleteLater()
        labels = [game.get("genre", "").split("/")[0],
                  ", ".join(p.capitalize() for p in (game.get("body_parts") or [])[:3]),
                  (game.get("difficulty_tag") or "").capitalize()]
        for text in (x for x in labels if x):
            self._chips.addWidget(Chip(text))
        self._chips.addStretch()

    def resizeEvent(self, event) -> None:
        self._text.setFixedWidth(int(self.width() * HERO_TEXT_SHARE))
        super().resizeEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        self._paint_art(p)
        p.end()

    def _paint_art(self, p: QPainter) -> None:
        p.setRenderHints(QPainter.RenderHint.Antialiasing
                         | QPainter.RenderHint.SmoothPixmapTransform
                         | QPainter.RenderHint.TextAntialiasing)
        card = QRectF(self.rect())                      # edge to edge, no card, no rounding
        if self._prev_game and self._art_t < 1.0:
            self._paint_cover(p, card, self._prev_game, self._prev_pix)
            grow = ART_ZOOM * (1.0 - self._art_t)       # the new cover settles in from a slight zoom
            dx, dy = card.width() * grow / 2, card.height() * grow / 2
            p.setOpacity(self._art_t)
            self._paint_cover(p, card.adjusted(-dx, -dy, dx, dy), self._game, self._pix)
            p.setOpacity(1.0)
        elif self._game:
            self._paint_cover(p, card, self._game, self._pix)
        shade = QLinearGradient(card.left(), 0, card.left() + card.width() * HERO_SHADE_END, 0)
        shade.setColorAt(0, QColor(0, 0, 0, 205))
        shade.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(card, shade)
        floor_top = card.bottom() - card.height() * HERO_FLOOR_SHARE
        floor = QLinearGradient(0, floor_top, 0, card.bottom())
        floor.setColorAt(0, QColor(0, 0, 0, 0))
        floor.setColorAt(1, QColor(0, 0, 0, 190))
        p.fillRect(QRectF(card.left(), floor_top, card.width(), card.bottom() - floor_top), floor)
        scrim = QLinearGradient(0, 0, 0, HERO_SCRIM_HEIGHT)
        scrim.setColorAt(0, QColor(0, 0, 0, 150))
        scrim.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, 0, card.width(), HERO_SCRIM_HEIGHT), scrim)

    def _paint_cover(self, p: QPainter, rect: QRectF, game: dict, pix: QPixmap) -> None:
        paint_cover(p, rect, game, pix, 0, emoji_px=0)
        if pix.isNull():
            self._paint_emoji(p, rect)

    def _paint_emoji(self, p: QPainter, card: QRectF) -> None:
        text_h = (card.height() - HERO_PAD_TOP - HERO_GAP - STRIP_HEADING_H
                  - ROW_HEIGHT - HERO_PAD_BOTTOM)
        font = QFont(EMOJI_FONT)
        font.setPixelSize(int(text_h * 0.6))
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 215))
        area = QRectF(card.left() + card.width() * 0.55, card.top() + HERO_PAD_TOP,
                      card.width() * 0.45, text_h)
        p.drawText(area, Qt.AlignmentFlag.AlignCenter, self._game.get("emoji") or "🎮")


# ── Page ──────────────────────────────────────────────────────────────────────

class PlayPage(QScrollArea):
    game_launch_requested = pyqtSignal(str)    # play an installed game
    download_requested    = pyqtSignal(str)    # download a game that is not installed
    art_state_changed     = pyqtSignal(bool)   # the top bar is over the featured art (True) or not

    def __init__(self, game_manager, session_manager, parent=None):
        super().__init__(parent)
        self.game_manager = game_manager
        self.session_manager = session_manager
        self._rows: list[_Row] = []          # row 0 is the featured strip
        self._entries: list[list[Entry]] = []
        self._sel = (0, 0)
        self._row_col: dict[int, int] = {}
        self._downloading: set[str] = set()
        self._failed: set[str] = set()
        self._reason = ""
        self._over_art = True

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._floating_bar = FloatingScrollBar(self)       # replaces the native bar: art runs edge to edge
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self.setWidget(container)

        page = QVBoxLayout(container)             # the featured art first, edge to edge
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)
        self._hero = _Hero()
        self._hero.action_clicked.connect(self.activate_selected)
        page.addWidget(self._hero)

        body = QWidget()                          # the rest of the page keeps its side margins
        body.setStyleSheet("background: transparent;")
        outer = QHBoxLayout(body)
        outer.setContentsMargins(PAGE_MARGIN, SECTION_GAP, PAGE_MARGIN, PAGE_BOTTOM_PAD)
        outer.addStretch(1)
        content = QWidget()
        content.setMaximumWidth(MAX_CONTENT_WIDTH)
        outer.addWidget(content, 100)
        outer.addStretch(1)
        page.addWidget(body, 1)

        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SECTION_GAP)
        # The calibration nudge sits just under the featured art, so the art gets the whole screen.
        self._banner = CalibrationBanner(session_manager)
        self._banner.layout().setContentsMargins(SHADOW_PAD, 0, SHADOW_PAD, 0)
        root.addWidget(self._banner)
        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(SECTION_GAP)
        root.addLayout(self._rows_box)
        root.addStretch()

        # The featured art steps through the recommended games on its own, TV-launcher
        # style, but only while nobody is using the page. The current tile's bottom edge
        # fills up to show when the next game is coming.
        self._elapsed = 0.0                       # seconds the current game has been up
        self._last_tick = time.monotonic()

        self._rebuild()
        self._banner.refresh()
        self.verticalScrollBar().valueChanged.connect(self._check_art_state)

        self._ticker = QTimer(self)
        self._ticker.setInterval(TICK_MS)
        self._ticker.timeout.connect(self._tick)
        self._ticker.start()

    # ── Rotation ──────────────────────────────────────────────────────────────
    def _may_rotate(self) -> bool:
        """True while the featured art is idle and in view, so the clock may run."""
        r, c = self._sel
        win = self.window()
        entries = self._entries[0] if self._entries else []
        return not (r != 0 or len(entries) < 2 or not self.isVisible() or not self.over_art()
                    or entries[c].game_id in self._downloading
                    or (win is not None and not win.isActiveWindow()))

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(now - self._last_tick, 0.25)     # a stalled UI must not skip ahead
        self._last_tick = now
        if not self._may_rotate():
            return
        self._elapsed += dt
        if self._elapsed >= ROTATE_S:
            self._advance()
        self._update_progress()

    def _advance(self) -> None:
        """Move the featured art on to the next recommended game."""
        self._select(0, (self._sel[1] + 1) % len(self._entries[0]), scroll=False)

    def _update_progress(self) -> None:
        """The current featured tile shows the countdown to the next game along its foot."""
        r, c = self._sel
        show = r == 0 and len(self._entries[0]) > 1 if self._entries else False
        fraction = min(1.0, self._elapsed / ROTATE_S)
        for i, tile in enumerate(self._rows[0].tiles if self._rows else []):
            tile.set_progress(fraction if show and i == c else None)

    # ── Sizing ────────────────────────────────────────────────────────────────
    def _fit_hero(self) -> None:
        """Make the featured art fill the visible page (the top bar floats over it),
        leaving just a peek of the next section so it is clear there is more below."""
        self._hero.setFixedHeight(max(HERO_MIN_HEIGHT,
                                      self.viewport().height() - NEXT_SECTION_PEEK))
        self._check_art_state()

    def over_art(self) -> bool:
        """True while the floating top bar still sits over the featured art."""
        # Done once the Featured tiles reach the bar, so tiles never slide under bare text.
        strip_h = HERO_PAD_BOTTOM + ROW_HEIGHT + STRIP_HEADING_H
        return self.verticalScrollBar().value() < self._hero.height() - strip_h - TOP_BAR_HEIGHT

    def _check_art_state(self, *_args) -> None:
        state = self.over_art()
        if state != self._over_art:
            self._over_art = state
            self.art_state_changed.emit(state)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_hero()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_hero()

    # ── Data ──────────────────────────────────────────────────────────────────
    def _installed_best_first(self, installed: list[dict]) -> list[dict]:
        """Installed games, today's lead first, then the engine's best-fit order."""
        self._reason = ""
        try:
            from core.suggestion_engine import get_current_card, score_games
            games = self.game_manager.get_games()
            card = get_current_card(self.session_manager, games)
            scored = [g for _s, g, _f in score_games(
                self.session_manager, games, card.get("phase", 1))]
            lead_id = card.get("recommended_game_id")
            lead = next((g for g in scored if g.get("id") == lead_id), None)
            ordered = ([lead] if lead else []) + [g for g in scored if g is not lead]
            if lead:
                self._reason = card.get("reason", "")
        except Exception as exc:                       # never leave the page empty
            print(f"[Play] recommendation unavailable: {exc}")
            ordered = []
        rest = [g for g in installed if g not in ordered]   # e.g. excluded from recommendations
        return ordered + sorted(rest, key=lambda g: g.get("name", ""))

    def _build_sections(self) -> list[tuple[str, list[Entry]]]:
        """[(title, entries)], featured strip first (its title is unused).
        Every game is in exactly one section."""
        games = self.game_manager.get_games()
        installed = self._installed_best_first([g for g in games if g.get("is_installed")])
        featured = [Entry(g, "installed", recommended=(i == 0 and bool(self._reason)))
                    for i, g in enumerate(installed[:FEATURED_COUNT])]
        others = [Entry(g, "installed") for g in sorted(
            installed[FEATURED_COUNT:], key=lambda g: g.get("name", ""))]
        more = [Entry(g, "download") for g in games if not g.get("is_installed")]
        more += [Entry(g, "soon") for g in COMING_SOON]
        if not featured:                               # nothing installed yet: feature downloads
            featured, more = more[:FEATURED_COUNT], more[FEATURED_COUNT:]
        on_this_pc = [Entry(g, "installed") for g in self.game_manager.get_detected_games()]
        sections = [("", featured), (t("play_row_mine"), others),
                    (t("play_row_pc"), on_this_pc), (t("play_row_more"), more)]
        return [(title, entries) for title, entries in sections if entries]

    def _rebuild(self, keep_id: str | None = None) -> None:
        old = self._current_entry()
        keep_id = keep_id or (old.game_id if old else None)
        for row in self._rows[1:]:                     # row 0 lives inside the banner
            pane = row.pane
            pane.setParent(None)
            pane.deleteLater()
        for tile in (self._rows[0].tiles if self._rows else []):
            tile.setParent(None)
            tile.deleteLater()
        self._rows, self._entries = [], []
        strip = self._hero.strip
        strip.tiles.clear()

        for n, (title, entries) in enumerate(self._build_sections()):
            section = None if n == 0 else _Section(title)
            row = strip if section is None else section.row
            for entry in entries:
                tile = GameTile(entry.game, entry.kind, entry.recommended)
                tile.set_state(entry.game_id in self._downloading,
                               entry.game_id in self._failed)
                tile.clicked.connect(self._on_tile_clicked)
                row.add_tile(tile)
            if section is not None:
                self._rows_box.addWidget(section)
            self._rows.append(row)
            self._entries.append(entries)
        self._row_col = {}
        self._sel = (-1, 0)
        r, c = self._locate(keep_id) or (0, 0)
        self._select(r, c, scroll=False)

    def _locate(self, game_id: str | None) -> tuple[int, int] | None:
        for r, entries in enumerate(self._entries):
            for c, entry in enumerate(entries):
                if game_id and entry.game_id == game_id:
                    return (r, c)
        return None

    # ── Selection ─────────────────────────────────────────────────────────────
    def _current_entry(self) -> Entry | None:
        r, c = self._sel
        if 0 <= r < len(self._entries) and 0 <= c < len(self._entries[r]):
            return self._entries[r][c]
        return None

    def _select(self, r: int, c: int, scroll: bool = True) -> None:
        if not self._rows:
            self._hero.setVisible(False)
            return
        pr, pc = self._sel
        if 0 <= pr < len(self._rows) and 0 <= pc < len(self._rows[pr].tiles):
            self._rows[pr].tiles[pc].set_selected(False)
        self._sel = (r, c)
        self._row_col[r] = c
        self._elapsed = 0.0                            # any new game up restarts the clock
        tile = self._rows[r].tiles[c]
        tile.set_selected(True)
        tile.raise_()                                  # the swollen tile sits above its neighbours
        self._sync_hero()
        self._update_progress()
        if scroll:
            self._rows[r].scroll.ensureWidgetVisible(tile, 40, 0)
            self._scroll_to_row(r)

    def _scroll_to_row(self, r: int) -> None:
        """Whole-page scroll: the featured section for row 0, else snap the row near the top."""
        bar = self.verticalScrollBar()
        if r == 0:
            bar.setValue(0)
        else:
            top = self._rows[r].pane.mapTo(self.widget(), QPoint(0, 0)).y()
            bar.setValue(max(0, top + SHADOW_TOP - TOP_BAR_HEIGHT - 12))   # clear of the floating bar

    def _sync_hero(self) -> None:
        entry = self._current_entry()
        if entry is None:
            return
        self._hero.setVisible(True)
        gid = entry.game_id
        if gid in self._downloading:
            button, enabled = t("play_btn_downloading"), False
        elif gid in self._failed:
            button, enabled = t("play_btn_retry"), True
        elif entry.kind == "installed":
            button, enabled = t("play_btn_play"), True
        elif entry.kind == "download":
            button, enabled = t("play_btn_download"), True
        else:
            button, enabled = t("play_btn_soon"), False
        lead = entry.recommended and bool(self._reason)
        tag = {"installed": t("play_tag_rec") if lead else "",
               "download": t("play_tag_download"),
               "soon": t("play_tag_soon")}[entry.kind]
        blurb = self._reason if lead else entry.game.get("description", "")
        self._hero.show_entry(entry, tag, blurb, button, enabled)

    def _on_tile_clicked(self, tile: GameTile) -> None:
        for r, row in enumerate(self._rows):
            if tile in row.tiles:
                c = row.tiles.index(tile)
                if (r, c) == self._sel:
                    self.activate_selected()
                else:
                    self._select(r, c)
                return

    # ── Keyboard / controller ─────────────────────────────────────────────────
    def handle_action(self, action: str) -> bool:
        """Returns False when the move leaves the page (up from the featured strip)."""
        if not self._rows:
            return action != "up"
        r, c = self._sel
        if action == "left":
            if c > 0:
                self._select(r, c - 1)
            return True
        if action == "right":
            if c < len(self._rows[r].tiles) - 1:
                self._select(r, c + 1)
            return True
        if action in ("up", "down"):
            nr = r + (-1 if action == "up" else 1)
            if nr < 0:
                return False
            if nr < len(self._rows):
                nc = min(self._row_col.get(nr, 0), len(self._rows[nr].tiles) - 1)
                self._select(nr, nc)
            return True
        if action == "action":
            self.activate_selected()
            return True
        return False

    def activate_selected(self) -> None:
        entry = self._current_entry()
        if entry is None or entry.game_id in self._downloading:
            return
        if entry.kind == "installed":
            self.game_launch_requested.emit(entry.game_id)
        elif entry.kind == "download":
            self.download_requested.emit(entry.game_id)

    # ── State pushed in by the launcher ───────────────────────────────────────
    def _refresh_tiles_for(self, game_id: str) -> None:
        for row in self._rows:
            for tile in row.tiles:
                if tile.game.get("id") == game_id:
                    tile.set_state(game_id in self._downloading, game_id in self._failed)
        self._sync_hero()

    def mark_downloading(self, game_id: str) -> None:
        self._failed.discard(game_id)
        self._downloading.add(game_id)
        self._refresh_tiles_for(game_id)

    def mark_failed(self, game_id: str) -> None:
        self._downloading.discard(game_id)
        self._failed.add(game_id)
        self._refresh_tiles_for(game_id)

    def mark_installed(self, game_id: str) -> None:
        self._downloading.discard(game_id)
        self._failed.discard(game_id)
        self._rebuild(keep_id=game_id)

    def refresh(self) -> None:
        """Re-read the games and recommendation (after a session or profile change)."""
        self.game_manager.refresh_detected()     # pick up newly installed games
        self._rebuild()
        self._banner.refresh()

    def set_session_manager(self, sm) -> None:
        self.session_manager = sm
        self._banner.set_session_manager(sm)
        self.refresh()

    def refresh_language(self) -> None:
        self._rebuild()

    def refresh_theme(self) -> None:
        pass
