"""
LibraryPage — browse and download rehabilitation games.
Shows games not yet installed, with body-part filters and Coming Soon cards.
"""
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import (
    QColor, QPainter, QPainterPath, QLinearGradient, QBrush, QFont, QPixmap
)

from core.theme import (
    FONT_DISPLAY, FONT_BODY, ON_SURFACE, ON_SURFACE_VAR,
    PRIMARY_CONTAINER, PRIMARY_FIXED, SURFACE_CON_LOW, SURFACE_DIM,
    OUTLINE_VARIANT, ON_PRIMARY_FIXED_VARIANT, BACKGROUND
)
from core.game_manager import GameManager
from core.i18n import get_game_desc
from core.theme import PRIMARY, ON_PRIMARY
from ui import glass as _g

# Accent colour as an "r,g,b" triple for translucent tints (lighter on dark).
_ACC = "255,154,77" if _g.is_dark() else "194,72,10"

FILTERS = ["All", "Arm", "Wrist", "Vertical", "Horizontal", "Balance"]

FILTER_TAG_MAP = {
    "Arm":        "arm",
    "Wrist":      "wrist",
    "Vertical":   "vertical",
    "Horizontal": "horizontal",
    "Balance":    "balance",
}

# Coming-soon placeholder games (not in games_db.json yet)
COMING_SOON = [
    {
        "name":       "Balloon Pop",
        "emoji":      "🎈",
        "desc":       "Pop balloons to train large arm movement and tracking.",
        "body_parts": ["arm", "horizontal"],
        "eta":        "Coming Soon",
    },
    {
        "name":       "Fruit Ninja",
        "emoji":      "🍉",
        "desc":       "Slice fruit flying across the screen — trains speed and tracking.",
        "body_parts": ["arm", "wrist"],
        "eta":        "Coming Soon",
    },
    {
        "name":       "Stroky Painter",
        "emoji":      "🎨",
        "desc":       "Paint strokes on canvas using the Solace controller — ideal for fine motor recovery.",
        "body_parts": ["wrist", "vertical", "horizontal"],
        "eta":        "Coming Soon",
    },
    {
        "name":       "Maze Navigator",
        "emoji":      "🧩",
        "desc":       "Guide a ball through a maze — trains precise fine motor control.",
        "body_parts": ["wrist", "balance"],
        "eta":        "Coming Soon",
    },
]


class _FilterPill(QPushButton):
    def __init__(self, label: str, active: bool = False, parent=None):
        super().__init__(label, parent)
        self.setCheckable(True)
        self.setChecked(active)
        self.setFixedHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()
        # Note: _update_style is called explicitly by LibraryPage._on_filter
        # after state changes — do NOT connect toggled here to avoid double-firing.

    def _update_style(self):
        if self.isChecked():
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {PRIMARY};
                    color: {ON_PRIMARY};
                    border: none;
                    border-radius: 23px;
                    padding: 0 26px;
                    font-family: '{FONT_DISPLAY}';
                    font-size: 16px;
                    font-weight: bold;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {_g.pane_bg(0.72)};
                    color: {ON_SURFACE_VAR};
                    border: 1px solid {OUTLINE_VARIANT};
                    border-radius: 23px;
                    padding: 0 26px;
                    font-family: '{FONT_DISPLAY}';
                    font-size: 16px;
                }}
                QPushButton:hover {{
                    background: {SURFACE_DIM};
                    color: {ON_SURFACE};
                }}
            """)


# ── Genre palette for placeholder covers ──────────────────────────────────────
_GENRE_PALETTE = {
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


class _GameCover(QWidget):
    """
    Top section of a game card: real poster image (cover-fill) when available,
    otherwise a genre-tinted gradient with a large emoji.
    Draws with rounded top corners to match the card's border-radius.
    """

    def __init__(self, game: dict, height: int = 168, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        art = game.get("art_url", "")
        self._pix = QPixmap()
        if art and os.path.exists(str(art)):
            self._pix = QPixmap(str(art))

        self._emoji = game.get("emoji", "🎮")
        self._genre = game.get("genre", "")
        pal = _GENRE_PALETTE.get(self._genre, ("#EFECE5", "#DDD8CC"))
        self._c1 = QColor(pal[0])
        self._c2 = QColor(pal[1])
        # short genre label for the badge
        self._badge = self._genre.split("/")[0].upper() if self._genre else ""

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        W, H, R = self.width(), self.height(), 28

        # Clip: rounded on top, flat on bottom
        clip = QPainterPath()
        clip.moveTo(R, 0)
        clip.lineTo(W - R, 0)
        clip.quadTo(W, 0, W, R)
        clip.lineTo(W, H)
        clip.lineTo(0, H)
        clip.lineTo(0, R)
        clip.quadTo(0, 0, R, 0)
        p.setClipPath(clip)

        if not self._pix.isNull():
            # Cover-fill: scale to fill, crop center
            scaled = self._pix.scaled(
                W, H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            ox = (scaled.width() - W) // 2
            oy = (scaled.height() - H) // 2
            p.drawPixmap(0, 0, scaled, ox, oy, W, H)
            # Bottom-fade for text contrast
            fade = QLinearGradient(0, H * 0.4, 0, H)
            fade.setColorAt(0, QColor(0, 0, 0, 0))
            fade.setColorAt(1, QColor(0, 0, 0, 160))
            p.fillRect(0, 0, W, H, QBrush(fade))
        else:
            # Genre gradient background
            grad = QLinearGradient(0, 0, W, H)
            grad.setColorAt(0, self._c1)
            grad.setColorAt(1, self._c2)
            p.fillRect(0, 0, W, H, QBrush(grad))
            # Large emoji
            p.setFont(QFont("Segoe UI Emoji", 60))
            p.setPen(QColor(255, 255, 255, 180))
            p.drawText(QRectF(0, -8, W, H), Qt.AlignmentFlag.AlignCenter, self._emoji)

        # Genre badge (top-right)
        if self._badge:
            p.setClipping(False)
            p.setFont(QFont("Schibsted Grotesk", 9, QFont.Weight.Bold))
            fm = p.fontMetrics()
            bw = fm.horizontalAdvance(self._badge) + 16
            bh = 26
            bx, by = W - bw - 14, 14
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 220))
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 13, 13)
            p.setPen(QColor(20, 19, 15))
            p.drawText(QRectF(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, self._badge)

        p.end()


class _StoreCard(QFrame):
    """A single game card — cover image on top, info + button below."""
    download_clicked = pyqtSignal(str)   # game_id

    def __init__(self, game: dict, is_installed: bool, coming_soon: bool = False,
                 is_downloading: bool = False, is_failed: bool = False, parent=None):
        super().__init__(parent)
        self._game_id = game.get("id", "")
        self.setObjectName("storeCard")
        self.setStyleSheet(f"""
            QFrame#storeCard {{
                background: {SURFACE_CON_LOW};
                border-radius: 28px;
                border: 1px solid {_g.pane_edge()};
            }}
        """)
        self.setFixedHeight(372)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Cover image / gradient ──────────────────────────────────────────────
        layout.addWidget(_GameCover(game, height=190))

        # ── Content ────────────────────────────────────────────────────────────
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(24, 18, 24, 22)
        cl.setSpacing(5)

        name = QLabel(game.get("name", "Game"))
        name.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 20px; font-weight: bold; background: transparent;"
        )
        name.setWordWrap(True)

        desc_en = game.get("desc") or game.get("description", "")
        desc = QLabel(get_game_desc(game.get("id", ""), fallback_en=desc_en))
        desc.setStyleSheet(
            f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; "
            f"font-size: 14px; background: transparent;"
        )
        desc.setWordWrap(True)
        desc.setMaximumHeight(42)

        # Body-part tags
        tags_row = QHBoxLayout()
        tags_row.setSpacing(5)
        for tag in (game.get("body_parts") or [])[:3]:
            tl = QLabel(tag.capitalize())
            tl.setStyleSheet(
                f"color: {PRIMARY_CONTAINER}; background: rgba({_ACC},0.10); "
                f"border: 1px solid rgba({_ACC},0.28); border-radius: 12px; "
                f"padding: 3px 12px; font-family: '{FONT_BODY}'; font-size: 13px; "
                f"font-weight: bold;"
            )
            tags_row.addWidget(tl)
        tags_row.addStretch()

        cl.addWidget(name)
        cl.addWidget(desc)
        cl.addLayout(tags_row)
        cl.addStretch()

        # ── Action button ────────────────────────────────────────────────────────
        if coming_soon:
            btn = QPushButton(game.get("eta", "Coming Soon"))
            btn.setEnabled(False)
            btn.setFixedHeight(46)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {SURFACE_DIM};
                    color: {ON_SURFACE_VAR};
                    border: none; border-radius: 23px;
                    font-family: '{FONT_DISPLAY}'; font-size: 15px;
                }}
            """)
        elif is_downloading:
            btn = QPushButton("⏳  Downloading…")
            btn.setFixedHeight(46)
            btn.setEnabled(False)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba({_ACC},0.10); color: {PRIMARY_CONTAINER};
                    border: 1px solid {PRIMARY_CONTAINER}; border-radius: 23px;
                    font-family: '{FONT_DISPLAY}'; font-size: 15px; font-weight: bold;
                }}
            """)
            self._dot_count = 0
            self._dl_btn = btn
            from PyQt6.QtCore import QTimer as _QT
            self._dot_timer = _QT(self)
            self._dot_timer.timeout.connect(self._tick_dots)
            self._dot_timer.start(500)
        elif is_failed:
            btn = QPushButton("⚠️  Download failed — Retry ↺")
            btn.setFixedHeight(46)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(230,80,70,0.10); color: #C93A32;
                    border: 1px solid #C93A32; border-radius: 23px;
                    font-family: '{FONT_DISPLAY}'; font-size: 15px; font-weight: bold;
                }}
                QPushButton:hover {{ background: rgba(255,95,86,0.20); }}
            """)
            gid = self._game_id
            btn.clicked.connect(lambda _, g=gid: self.download_clicked.emit(g))
        elif is_installed:
            btn = QPushButton("▶  Play Now")
            btn.setFixedHeight(46)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {PRIMARY};
                    color: {ON_PRIMARY};
                    border: none; border-radius: 23px;
                    font-family: '{FONT_DISPLAY}'; font-size: 15px; font-weight: bold;
                }}
                QPushButton:hover {{
                    background: {_g.hover_ink()};
                    color: {ON_PRIMARY};
                }}
            """)
            btn.clicked.connect(lambda: self._find_library_page_and_launch())
        else:
            btn = QPushButton("⬇  Download")
            btn.setFixedHeight(46)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba({_ACC},0.10);
                    color: {PRIMARY_CONTAINER};
                    border: 1px solid rgba({_ACC},0.30);
                    border-radius: 23px;
                    font-family: '{FONT_DISPLAY}'; font-size: 15px; font-weight: bold;
                }}
                QPushButton:hover {{
                    background: rgba(194,72,10,0.20);
                    border-color: {PRIMARY_CONTAINER};
                }}
            """)
            gid = self._game_id
            btn.clicked.connect(lambda _, g=gid: self.download_clicked.emit(g))

        cl.addWidget(btn)
        layout.addWidget(content)

    def _tick_dots(self):
        dots = ["○○○", "●○○", "○●○", "○○●"]
        self._dot_count = (self._dot_count + 1) % len(dots)
        try:
            self._dl_btn.setText(f"⏳  Downloading {dots[self._dot_count]}")
        except RuntimeError:
            self._dot_timer.stop()

    def _find_library_page_and_navigate(self):
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, LibraryPage):
                parent.go_to_home.emit()
                return
            parent = parent.parent()

    def _find_library_page_and_launch(self):
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, LibraryPage):
                parent.launch_requested.emit(self._game_id)
                return
            parent = parent.parent()


class LibraryPage(QScrollArea):
    download_requested = pyqtSignal(str)   # game_id
    go_to_home         = pyqtSignal()      # B1: emitted when user clicks "go to Library"
    launch_requested   = pyqtSignal(str)   # game_id — launch directly from store

    def __init__(self, game_manager: GameManager, parent=None):
        super().__init__(parent)
        self._gm             = game_manager
        self._active_filter  = "All"

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self.setWidget(self._container)

        self._root = QVBoxLayout(self._container)
        self._root.setContentsMargins(48, 0, 48, 120)
        self._root.setSpacing(24)

        # ── Header ──────────────────────────────────────────────────────────
        title = QLabel("Library")
        title.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 40px; font-weight: bold;"
        )
        desc = QLabel("Download new rehabilitation games for your Solace controller.")
        desc.setStyleSheet(
            f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; font-size: 18px;"
        )
        self._root.addWidget(title)
        self._root.addWidget(desc)

        # ── Filter bar ───────────────────────────────────────────────────────
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self._filter_pills = {}
        for f in FILTERS:
            pill = _FilterPill(f, active=(f == "All"))
            pill.toggled.connect(lambda checked, lbl=f: self._on_filter(lbl, checked))
            filter_row.addWidget(pill)
            self._filter_pills[f] = pill
        filter_row.addStretch()
        self._root.addLayout(filter_row)

        # ── Game grids ────────────────────────────────────────────────────────
        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet("background: transparent;")
        self._grid = QVBoxLayout(self._grid_widget)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(16)
        self._root.addWidget(self._grid_widget)

        self._root.addStretch()
        self._rebuild_grid()

    # ── Filter logic ──────────────────────────────────────────────────────────

    def _on_filter(self, label: str, checked: bool):
        if not checked:
            return
        # Uncheck all others and explicitly update their style
        for lbl, pill in self._filter_pills.items():
            if lbl != label:
                pill.blockSignals(True)
                pill.setChecked(False)
                pill.blockSignals(False)
            pill._update_style()   # always refresh — toggled signal no longer auto-fires this
        self._active_filter = label
        self._rebuild_grid()

    def _clear_layout(self, layout):
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                else:
                    self._clear_layout(item.layout())
                    
    def _rebuild_grid(self):
        # Clear existing grid
        self._clear_layout(self._grid)

        tag_filter = FILTER_TAG_MAP.get(self._active_filter)

        all_games   = self._gm.get_games()
        installed   = {g["id"] for g in all_games if g.get("is_installed")}
        # Show ALL games (installed shown as installed, uninstalled as downloadable)
        shown_games = all_games

        combined = []
        for g in shown_games:
            if tag_filter and tag_filter not in (g.get("body_parts") or []):
                continue
            g_with_emoji = dict(g)
            g_with_emoji.setdefault("emoji", "🎮")
            combined.append(("real", g_with_emoji, g["id"] in installed))

        # Add coming-soon
        for cs in COMING_SOON:
            if tag_filter and tag_filter not in cs.get("body_parts", []):
                continue
            combined.append(("soon", cs, False))
            
        combined.sort(key=lambda item: (
            0 if item[2] else 1,
            0 if item[0] == "real" else 1,
            item[1].get("name", "")
        ))

        installed_items = [c for c in combined if c[2] == True]
        available_items = [c for c in combined if c[2] == False and c[0] == "real"]
        soon_items = [c for c in combined if c[0] == "soon"]

        def add_section(title, items):
            if not items:
                return
            lbl = QLabel(title)
            lbl.setStyleSheet(f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; font-size: 24px; font-weight: bold; margin-top: 24px; margin-bottom: 8px; background: transparent;")
            self._grid.addWidget(lbl)

            grid = QGridLayout()
            grid.setSpacing(20)
            downloading = getattr(self, '_downloading', set())
            failed      = getattr(self, '_failed', set())
            for i, (kind, game, is_inst) in enumerate(items):
                gid = game.get("id", "")
                card = _StoreCard(
                    game,
                    is_installed=is_inst,
                    coming_soon=(kind == "soon"),
                    is_downloading=(gid in downloading),
                    is_failed=(gid in failed),
                )
                card.download_clicked.connect(self.download_requested.emit)
                grid.addWidget(card, i // 3, i % 3)
            self._grid.addLayout(grid)

        add_section("My Downloaded Games", installed_items)
        add_section("Available to Download", available_items)
        add_section("Coming Soon", soon_items)

    def mark_installed(self, game_id: str):
        """Called when a download completes — rebuild grid to show installed badge."""
        getattr(self, '_downloading', set()).discard(game_id)
        getattr(self, '_failed', set()).discard(game_id)
        self._rebuild_grid()

    def mark_downloading(self, game_id: str):
        """U1: Show animated downloading state on the matching card."""
        # We store active download IDs; cards read this on rebuild
        if not hasattr(self, '_downloading'):
            self._downloading: set = set()
        self._downloading.add(game_id)
        self._rebuild_grid()

    def mark_failed(self, game_id: str):
        """U1: Show retry state when a download fails."""
        if hasattr(self, '_downloading'):
            self._downloading.discard(game_id)
        if not hasattr(self, '_failed'):
            self._failed: set = set()
        self._failed.add(game_id)
        self._rebuild_grid()

    def refresh_language(self):
        """Rebuild all game cards so descriptions render in the active language."""
        self._rebuild_grid()

    def refresh_theme(self):
        pass
