"""
ProfileOverlay: the whole "Who's Playing?" page as a panel over the app.

Opened from the avatar in the navigation tab. The window dims and the panel grows out of
the tab the way the tab itself grows: a slim card below the tab widens and deepens into the
full panel (same 180 ms open, 240 ms close and easing as the nav tab and the window tab),
and its contents are uncovered from the middle outward. Closing shrinks it back.

Inside: every profile as a tile plus an add tile. Picking one switches to it. Close with
the Close button, Escape, or a click outside the panel. Controller: left and right move
along the tiles, select picks one, up closes.

It reuses ProfileTile, AddTile and NewProfileDialog from ui.profile_screen.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF, QVariantAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QColor, QKeyEvent, QPen, QRegion
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                             QPushButton, QScrollArea, QMessageBox, QGraphicsOpacityEffect)

from core import theme as _t
from core.profile_manager import load_profiles, delete_profile
from ui import glass as _g
from ui.glass import paint_card_shadow
from ui.profile_screen import ProfileTile, AddTile, NewProfileDialog, TILE_SIZE

PANEL_MAX_WIDTH = 940
PANEL_SIDE_MARGIN = 40          # least gap between the panel and the window edge
PANEL_TOP = 100                 # just under the top bar
PANEL_RADIUS = 36
PANEL_PAD = 40
TILE_SPACING = 24
TILE_CELL_W = TILE_SIZE + 20     # ProfileTile and AddTile are this wide
PANEL_CHROME = 172               # panel height that is not the tile area (header, spacing, padding)
SCRIM_LIGHT, SCRIM_DARK = 95, 150
OPEN_MS, CLOSE_MS = 180, 240     # the same timing as the nav tab and the window tab
# the slim card the panel grows from (just under the nav tab)
START_W, START_H, START_RADIUS = 150, 30, 15
START_TOP = 88
CONTENT_FROM, CONTENT_FULL = 0.55, 0.95     # reveal at which the contents fade in


class _OverlayTile(ProfileTile):
    """A profile tile that only offers delete for profiles that may be deleted."""

    def __init__(self, profile: dict, deletable: bool, parent=None):
        super().__init__(profile, parent)
        self._deletable = deletable

    def enterEvent(self, event) -> None:
        if self._deletable:
            self._del.show()
        self.update()


class ProfileOverlay(QWidget):
    profile_chosen = pyqtSignal(dict)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._active_id: str | None = None
        self._tiles: list[_OverlayTile] = []
        self._add_tile: AddTile | None = None
        self._index = 0
        self._reveal = 0.0
        self._closing = False

        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_reveal)
        self._anim.finished.connect(self._on_anim_done)

        # The panel's contents live in _panel, laid out at their final size. The card behind
        # them is painted by the overlay (so it can grow). _clip is a plain, transparent layer
        # over the whole overlay that is masked to the growing card, so the contents never
        # show outside it (a mask on a widget that has an opacity effect does not clip).
        self._clip = QWidget(self)
        self._panel = QWidget(self._clip)
        self._panel.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(self._panel)
        lay.setContentsMargins(PANEL_PAD, PANEL_PAD - 6, PANEL_PAD, PANEL_PAD)
        lay.setSpacing(26)

        head = QHBoxLayout()
        self._title = QLabel("Who's Playing?")
        self._title.setStyleSheet(
            f"color: {_t.ON_SURFACE}; font-family: '{_t.FONT_DISPLAY}'; font-size: 38px;"
            f" font-weight: 800; letter-spacing: -1px; background: transparent;")
        head.addWidget(self._title)
        head.addStretch()
        self._close = QPushButton("Close")
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._close.setFixedHeight(44)
        self._close.setStyleSheet(
            f"QPushButton {{ background: {_g.tint(0.06)}; color: {_t.ON_SURFACE};"
            f" border: none; border-radius: 22px; padding: 0 26px;"
            f" font-family: '{_t.FONT_DISPLAY}'; font-size: 16px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {_g.tint(0.12)}; }}")
        self._close.clicked.connect(self.close_overlay)
        head.addWidget(self._close)
        lay.addLayout(head)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._holder = QWidget()
        self._holder.setStyleSheet("background: transparent;")
        outer = QHBoxLayout(self._holder)
        outer.setContentsMargins(0, 24, 0, 8)     # room for the selected tile's ring
        outer.addStretch(1)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(TILE_SPACING)
        self._grid.setVerticalSpacing(8)
        outer.addLayout(self._grid)
        outer.addStretch(1)
        self._scroll.setWidget(self._holder)
        lay.addWidget(self._scroll)

        self.hide()

    # ── Open and close ───────────────────────────────────────────────────────
    def open(self, active_id: str | None) -> None:
        self._active_id = active_id
        self._build_tiles(select_id=active_id)
        parent = self.parentWidget()
        if parent is not None:                     # a hidden widget has no size yet
            self.setGeometry(parent.rect())
        self._place_panel()
        self._closing = False
        self.show()
        self.raise_()
        self.setFocus()
        self._run(1.0, OPEN_MS)

    def is_open(self) -> bool:
        """True while shown and not on its way out."""
        return self.isVisible() and not self._closing

    def close_overlay(self) -> None:
        """Shrink back into the tab, then hide."""
        if not self.isVisible():
            return
        self._closing = True
        self._run(0.0, CLOSE_MS)

    def _run(self, end: float, ms: int) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._reveal)
        self._anim.setEndValue(end)
        self._anim.setDuration(ms)
        self._anim.start()

    def _on_reveal(self, value) -> None:
        self._reveal = float(value)
        self._apply_reveal()
        self.update()

    def _on_anim_done(self) -> None:
        if self._closing and self._reveal <= 0.001:
            self._closing = False
            self.hide()

    # ── The growing card ─────────────────────────────────────────────────────
    def _final_rect(self) -> QRectF:
        return QRectF(self._panel.geometry())

    def _card_rect(self) -> QRectF:
        """The card for the current reveal: a slim shape under the tab growing into the panel."""
        final = self._final_rect()
        r = self._reveal
        w = START_W + (final.width() - START_W) * r
        h = START_H + (final.height() - START_H) * r
        top = START_TOP + (final.top() - START_TOP) * r
        return QRectF(final.center().x() - w / 2, top, w, h)

    def _card_radius(self) -> float:
        return START_RADIUS + (PANEL_RADIUS - START_RADIUS) * self._reveal

    def _content_alpha(self) -> float:
        return max(0.0, min(1.0, (self._reveal - CONTENT_FROM) / (CONTENT_FULL - CONTENT_FROM)))

    def _apply_reveal(self) -> None:
        """Fade the contents in and keep them clipped to the growing card."""
        if self._reveal >= 0.999:
            self._panel.setGraphicsEffect(None)            # crisp text once fully open
            self._clip.clearMask()
            return
        effect = self._panel.graphicsEffect()
        if effect is None:
            effect = QGraphicsOpacityEffect(self._panel)
            self._panel.setGraphicsEffect(effect)
        effect.setOpacity(self._content_alpha())
        path = QPainterPath()
        path.addRoundedRect(self._card_rect(), self._card_radius(), self._card_radius())
        self._clip.setMask(QRegion(path.toFillPolygon().toPolygon()))

    # ── Tiles ────────────────────────────────────────────────────────────────
    def _build_tiles(self, select_id: str | None = None) -> None:
        for widget in [*self._tiles, self._add_tile]:
            if widget is not None:
                self._grid.removeWidget(widget)
                widget.setParent(None)              # vanish now; deleteLater alone keeps painting
                widget.deleteLater()
        self._tiles.clear()

        profiles = load_profiles()
        for profile in profiles:
            deletable = len(profiles) > 1 and profile.get("id") != self._active_id
            tile = _OverlayTile(profile, deletable)
            tile.clicked.connect(self._on_tile_clicked)
            tile.delete_requested.connect(self._confirm_delete)
            self._tiles.append(tile)
        self._add_tile = AddTile()
        self._add_tile.clicked.connect(self._new_profile)
        self._flow_tiles(self._columns())

        self._index = 0
        for i, tile in enumerate(self._tiles):
            if select_id and tile.profile.get("id") == select_id:
                self._index = i
        self._refresh_selection()

    def _columns(self) -> int:
        inner = self._panel.width() - 2 * PANEL_PAD
        return max(1, (inner + TILE_SPACING) // (TILE_CELL_W + TILE_SPACING))

    def _flow_tiles(self, columns: int) -> None:
        """Lay the tiles (and the add tile) out in rows of `columns`."""
        for widget in [*self._tiles, self._add_tile]:
            if widget is not None:
                self._grid.removeWidget(widget)
        for i, widget in enumerate([*self._tiles, self._add_tile]):
            if widget is not None:
                self._grid.addWidget(widget, i // columns, i % columns)
                widget.show()          # new tiles are otherwise hidden until the next event-loop turn,
                                       # and a hidden tile does not count towards the panel's height

    def _refresh_selection(self) -> None:
        for i, tile in enumerate(self._tiles):
            tile.set_selected(i == self._index)

    def _on_tile_clicked(self, profile: dict) -> None:
        self.close_overlay()
        self.profile_chosen.emit(profile)

    def _confirm_delete(self, profile_id: str) -> None:
        name = next((t.profile.get("name", "this profile") for t in self._tiles
                     if t.profile.get("id") == profile_id), "this profile")
        answer = QMessageBox.question(
            self.window(), "Delete profile",
            f"Delete {name}? Their saved progress goes with it, and this cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            delete_profile(profile_id)
            self._build_tiles(select_id=self._active_id)
            self._place_panel()

    def _new_profile(self) -> None:
        dialog = NewProfileDialog(self.window())
        created: list[dict] = []
        dialog.profile_created.connect(created.append)
        dialog.exec()
        if created:
            self._build_tiles(select_id=created[0].get("id"))
            self._place_panel()

    # ── Layout and painting ──────────────────────────────────────────────────
    def _place_panel(self) -> None:
        """Size the contents for the full panel and put them in their final place."""
        self._clip.setGeometry(self.rect())
        width = max(360, min(PANEL_MAX_WIDTH, self.width() - 2 * PANEL_SIDE_MARGIN))
        self._panel.setFixedWidth(width)
        self._flow_tiles(self._columns())
        self._holder.layout().activate()
        room = max(TILE_SIZE + 80, self.height() - PANEL_TOP - PANEL_CHROME - 40)
        self._scroll.setFixedHeight(min(self._holder.sizeHint().height(), room))
        self._panel.adjustSize()
        self._panel.move((self.width() - self._panel.width()) // 2, PANEL_TOP)
        self._apply_reveal()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isVisible():
            self._place_panel()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = SCRIM_DARK if _g.is_dark() else SCRIM_LIGHT
        p.fillRect(self.rect(), QColor(0, 0, 0, int(base * min(1.0, self._reveal * 1.4))))
        card = self._card_rect()
        radius = self._card_radius()
        paint_card_shadow(p, card, radius, min(1.0, self._reveal * 1.5))
        p.setBrush(QColor(_g.solid_pane()))
        if _g.is_dark():
            p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        else:
            p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(card, radius, radius)
        p.end()

    def mousePressEvent(self, event) -> None:
        if not self._final_rect().contains(event.position()):
            self.close_overlay()
        event.accept()

    # ── Keyboard and controller ──────────────────────────────────────────────
    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close_overlay()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.nav_action("left")
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.nav_action("right")
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.nav_action("action")
        else:
            super().keyPressEvent(event)

    def nav_action(self, action: str) -> None:
        if action == "left":
            self._index = max(0, self._index - 1)
        elif action == "right":
            self._index = min(len(self._tiles) - 1, self._index + 1)
        elif action == "action":
            if self._tiles:
                self._on_tile_clicked(self._tiles[self._index].profile)
            return
        elif action == "up":
            self.close_overlay()
            return
        self._refresh_selection()
        if self._tiles:
            self._scroll.ensureWidgetVisible(self._tiles[self._index], 40, 0)
