"""
JourneyPanel — Today's Journey as a grid of glass tiles.

A wide hero tile (today's warmup) on top, then one tile per recommended game.
Each tile: icon bubble, small tag, name, a short description and either a round
arrow button (start), a "Redo" pill (done) or a disabled button (locked).
The whole tile is clickable. Keyboard and controller navigation moves a
selection ring through the tiles in order.
"""
from __future__ import annotations

import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QSizePolicy,
)
from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QPixmap

from core import theme as _t
from ui.glass import GlassCard, IconBubble, Chip, RoundArrowButton, PillButton

BODY_MAX_CHARS = 96


# ── Journey step data ─────────────────────────────────────────────────────────

def build_journey_steps(sm, games: list[dict]) -> list[dict]:
    """
    TODAY'S JOURNEY — a daily agenda derived from the plan (not the whole
    roadmap). Two panels: (1) today's warmup, (2) today's single recommended
    game for the current phase, with the engine's reason + phase progress.
    See SOLACE_IMPROVEMENT_PLAN.md §1.0-A.
    """
    journey = sm.get_journey()
    phase   = journey.get("phase", 1)
    has_rom = sm.get_daily_rom() is not None      # today's warmup done?

    from core.suggestion_engine import get_current_card
    card = get_current_card(sm, games)
    rec  = next((g for g in games
                 if g.get("id") == card.get("recommended_game_id")), None) or {}

    art = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       "..", "assets", "warmup_art.png"))
    graduated = card.get("graduated")

    steps = [{
        "id": "warmup", "game_id": None, "is_warmup": True, "emoji": "",
        "name": "Warmup",
        "art_url": art if os.path.exists(art) else "",
        "tag": "TODAY · STEP 1",
        "body": ("Measure your movement range for today — this personalises "
                 "your session." if not has_rom
                 else "Today's measurement is done. Nice."),
        "state": "done" if has_rom else "current",
        "done": 1 if has_rom else 0, "needed": 1,
    }]

    if graduated:
        steps.append({
            "id": rec.get("id", "graduated"), "game_id": rec.get("id"),
            "is_warmup": False, "emoji": "🎓",
            "name": "You've graduated! 🎓",
            "art_url": rec.get("art_url", ""),
            "tag": "MAINTENANCE",
            "body": ("Your movement has genuinely recovered — incredible work. "
                     "Keep playing to maintain your gains."
                     + (f"\nToday's pick: {rec.get('name')}" if rec else "")),
            "state": "current", "done": 1, "needed": 1,
        })
        return steps

    # Today's games for the current phase — the SAME recommended set, but each
    # game now gets its OWN card (up to 4) instead of being grouped into one.
    prog   = card.get("progress_pct", 0.0)
    pct    = int(round(prog * 100))
    phase  = card.get("phase", 1)
    rec_id = card.get("recommended_game_id")

    from core.suggestion_engine import score_games
    scored = score_games(sm, games, phase)   # installed, best-first, excl. REC_EXCLUDE

    # The engine's recommendation leads; fill the rest from the next best
    # scorers, capped at 4 cards total.
    ordered, seen = [], set()
    rec_game = next((g for _s, g, _f in scored if g.get("id") == rec_id), None)
    if rec_game is None and scored:
        rec_game = scored[0][1]
    if rec_game:
        ordered.append(rec_game)
        seen.add(rec_game["id"])
    for _s, g, _f in scored:
        if len(ordered) >= 4:
            break
        if g["id"] not in seen:
            ordered.append(g)
            seen.add(g["id"])

    for g in ordered:
        primary = rec_game is not None and g.get("id") == rec_game.get("id")
        if primary:
            tag = f"TODAY · {card.get('phase_name', '')}"
            body = card.get("reason") or g.get("description", "")
            done, needed = pct, 100
        else:
            tag = "ALSO TODAY"
            body = g.get("description", "") or "Another way to train today's movement."
            done, needed = 0, 0
        steps.append({
            "id": g.get("id", ""), "game_id": g.get("id"),
            "is_warmup": False, "emoji": g.get("emoji") or "🎮",
            "name": g.get("name", "Your game"),
            "art_url": g.get("art_url", ""),
            "tag": tag,
            "body": body,
            "state": "locked" if not has_rom else "current",   # warmup first
            "done": done, "needed": needed,
        })
    return steps


# ── Tiles ─────────────────────────────────────────────────────────────────────

def _short(text: str) -> str:
    first = text.split("\n")[0].strip()
    if len(first) <= BODY_MAX_CHARS:
        return first
    return first[:BODY_MAX_CHARS].rsplit(" ", 1)[0] + "…"


def _label(text: str, size: int, color: str, bold: bool = False,
           wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(wrap)
    lbl.setStyleSheet(
        f"color: {color}; font-family: '{_t.FONT_DISPLAY}'; font-size: {size}px;"
        f" font-weight: {'bold' if bold else 'normal'}; background: transparent;"
    )
    return lbl


class _StepTile(GlassCard):
    action_clicked = pyqtSignal(dict)

    def __init__(self, step: dict, parent=None):
        super().__init__(parent=parent)
        self._step = step
        self._hero = bool(step.get("is_warmup"))
        self._state = step["state"]
        self._art = None
        art = step.get("art_url", "")
        if self._hero and art and os.path.exists(art):
            pm = QPixmap(art)
            if not pm.isNull():
                self._art = pm

        self.setMinimumHeight(290 if self._hero else 250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.set_faded(self._state == "locked")
        if self._state != "locked":
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(32, 28, 32, 28)
        outer.setSpacing(0)

        col = QVBoxLayout()
        col.setSpacing(6)
        outer.addLayout(col, 3 if self._hero else 1)
        if self._hero:
            outer.addStretch(2)      # the artwork is painted into this space

        col.addLayout(self._top_row())
        col.addSpacing(10)
        col.addWidget(_label(self._step["tag"].title(), 15, _t.PRIMARY_CONTAINER, True))
        col.addWidget(_label(self._step["name"], 40 if self._hero else 27,
                             _t.ON_SURFACE if self._state != "locked" else _t.ON_SURFACE_VAR,
                             True, wrap=True))
        body = _short(self._step["body"])
        col.addWidget(_label(body, 18 if self._hero else 16, _t.ON_SURFACE_VAR, wrap=True))
        col.addStretch()
        col.addLayout(self._action_row())

    def _top_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(0)
        glyph = self._step.get("emoji") or "🌅"
        row.addWidget(IconBubble(glyph, 60))
        row.addStretch()
        if self._state == "done":
            row.addWidget(Chip("Done today", "✓", tone="accent"))
        elif self._state == "locked":
            row.addWidget(Chip("Locked", "🔒"))
        return row

    def _action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)
        step = self._step
        if self._state == "locked":
            row.addWidget(_label("Finish the warmup first", 15, _t.ON_SURFACE_VAR, True))
            row.addStretch()
            arrow = RoundArrowButton(56)
            arrow.setEnabled(False)
            row.addWidget(arrow)
        elif self._hero:
            label = "Redo warmup" if self._state == "done" else "Begin warmup"
            btn = PillButton(label, "light" if self._state == "done" else "dark", 58)
            btn.clicked.connect(lambda: self.action_clicked.emit(step))
            row.addWidget(btn)
            row.addStretch()
        else:
            if self._state == "done":
                redo = PillButton("Redo", "light", 52)
                redo.clicked.connect(lambda: self.action_clicked.emit(step))
                row.addWidget(redo)
            row.addStretch()
            arrow = RoundArrowButton(56)
            arrow.clicked.connect(lambda: self.action_clicked.emit(step))
            row.addWidget(arrow)
        return row

    # ── Interaction and painting ──────────────────────────────────────────────

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self._state != "locked"
                and self.rect().contains(event.position().toPoint())):
            self.action_clicked.emit(self._step)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._art:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        card = self.card_rect()
        inset = 16
        target = QRectF(card.left() + card.width() * 0.60, card.top() + inset,
                        card.width() * 0.40 - inset, card.height() - 2 * inset)
        clip = QPainterPath()
        clip.addRoundedRect(target, 22, 22)
        p.setClipPath(clip)
        pm = self._art
        scale = max(target.width() / pm.width(), target.height() / pm.height())
        sw, sh = target.width() / scale, target.height() / scale
        src = QRectF((pm.width() - sw) / 2, (pm.height() - sh) / 2, sw, sh)
        p.drawPixmap(target, pm, src)
        p.end()


# ── Journey panel ─────────────────────────────────────────────────────────────

class JourneyPanel(QWidget):
    warmup_requested     = pyqtSignal()
    game_requested       = pyqtSignal(str)
    assessment_requested = pyqtSignal()

    COLUMNS = 2

    def __init__(self, session_manager, game_manager, parent=None):
        super().__init__(parent)
        self._sm = session_manager
        self._gm = game_manager
        self._cards: list[_StepTile] = []
        self._sel = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(0)      # the cards' shadow margins already space them
        for c in range(self.COLUMNS):
            self._grid.setColumnStretch(c, 1)
        self._build()

    def _build(self):
        steps = build_journey_steps(self._sm, self._gm.get_games())
        self._cards = []
        slot = 0
        for step in steps:
            tile = _StepTile(step)
            tile.action_clicked.connect(self._on_action)
            if step.get("is_warmup"):
                self._grid.addWidget(tile, 0, 0, 1, self.COLUMNS)
            else:
                self._grid.addWidget(tile, 1 + slot // self.COLUMNS, slot % self.COLUMNS)
                slot += 1
            self._cards.append(tile)

        # Default selection: the first actionable tile
        self._sel = next((i for i, c in enumerate(self._cards)
                          if c._step.get("state") == "current"), 0)
        self._apply_selection()

    # ── Keyboard / controller navigation ──────────────────────────────────────

    def _apply_selection(self):
        for i, tile in enumerate(self._cards):
            tile.set_selected(i == self._sel)

    def navigate(self, direction: int):
        if not self._cards:
            return
        self._sel = max(0, min(len(self._cards) - 1, self._sel + direction))
        self._apply_selection()

    def activate_selected(self):
        if 0 <= self._sel < len(self._cards):
            self._on_action(self._cards[self._sel]._step)

    def _on_action(self, step: dict):
        if step.get("is_assessment"):
            self.assessment_requested.emit()
        elif step.get("is_warmup"):
            self.warmup_requested.emit()
        elif step.get("game_id"):
            self.game_requested.emit(step["game_id"])

    def set_session_manager(self, sm):
        """C1 fix: rebind to the new profile's data on profile switch."""
        self._sm = sm
        self.refresh()

    def refresh(self):
        # setParent(None) detaches immediately; deleteLater() alone is async and
        # would let _build() run while the old tiles still exist.
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._build()
        self.update()
