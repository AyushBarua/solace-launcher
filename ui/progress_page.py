"""
ProgressPage — Solace Glass design.

Frosted cards with painted shadows over the warm haze, big numerals, one dark
highlight card (the streak) and a PDF report button in the header. All
SessionManager data calls are unchanged; only the presentation is new.
"""
import math
from datetime import date, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QScrollArea, QFrame,
    QFileDialog, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QLinearGradient, QFont

from core.session_manager import SessionManager
from core.i18n import t

# ── Design tokens (Solace Glass) ──────────────────────────────────────────────
from core import theme as _theme
from core.theme import hex_rgba
from ui import glass as _g
from ui.floating_scrollbar import FloatingScrollBar
from ui.glass import GlassCard, Chip, PillButton, SHADOW_PAD

_CARD   = _theme.SURFACE_CON_LOW        # card fill
_INNER  = _theme.SURFACE_CON_HIGH       # nested panel fill
_BORDER = _theme.OUTLINE_VARIANT
_GOLD   = _theme.PRIMARY_CONTAINER      # accent (deep orange, readable on white)
_GOLD_D = "#FF8A3D"                     # bright accent for fills
_GOLD_L = _theme.PRIMARY_FIXED
_DARK = _g.is_dark()
_GREEN  = "#4CD07D" if _DARK else "#1E9E4A"     # light: readable on white
_TEXT   = _theme.ON_SURFACE
_TEXT2  = _theme.ON_SURFACE_VAR
_MUTED  = "#9A968C" if _DARK else "#6F6D66"     # caption grey, 4.9:1 on the card
_DIM    = _theme.OUTLINE_VARIANT
_REST   = "#3A3732" if _DARK else "#E7E3DA"     # heat-map "rest day" cell
_PARTIAL = "#2F6B45" if _DARK else "#8FD19E"    # heat-map "under 15 min" cell
_ON_ACCENT = "#14130F" if _DARK else "#FFFFFF"  # text on an accent-filled button
_TRACK  = "#4A463F" if _DARK else _INNER        # gauge background arc (dark: needs more contrast)
_ACCENT_ON_INK = "#C2480A" if _DARK else "#FF9A4D"   # accent numerals on the inverted card
_DISPLAY = _theme.FONT_DISPLAY

PAGE_EDGE = 40                          # where the visible cards start, from the window edge
PAGE_MARGIN = PAGE_EDGE - SHADOW_PAD    # cards carry their own shadow margin
PANEL_RADIUS = 34
STAT_MIN_HEIGHT = 222
DAILY_GOAL_MIN = 20


# ── PDF thread (unchanged) ────────────────────────────────────────────────────

class _PDFThread(QThread):
    done  = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, sm, profile, path, parent=None):
        super().__init__(parent)
        self._sm = sm
        self._profile = profile
        self._path = path

    def run(self):
        try:
            from core.report_generator import generate_report
            self.done.emit(generate_report(self._sm, self._profile, self._path))
        except Exception as e:
            self.error.emit(str(e))


def _label(text: str, size: int, colour: str, weight: int = 700, spacing: str = "",
           display: bool = False) -> QLabel:
    """A transparent text label; scoped to the label so it never boxes children."""
    lbl = QLabel(text)
    family = f"font-family:'{_DISPLAY}';" if display else ""
    lbl.setStyleSheet(
        f"color:{colour}; font-size:{size}px; font-weight:{weight}; {family}"
        f"{('letter-spacing:' + spacing + ';') if spacing else ''}"
        f"background:transparent; border:none;"
    )
    return lbl


# ── Daily-goal bar ────────────────────────────────────────────────────────────

class _GoalBar(QWidget):
    """Slim rounded progress bar: minutes played today against the daily goal."""

    def __init__(self, fraction: float = 0.0, on_ink: bool = False, parent=None):
        super().__init__(parent)
        self._fraction = max(0.0, min(1.0, fraction))
        self._on_ink = on_ink
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_fraction(self, fraction: float) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        track = QColor(255, 255, 255, 46) if self._on_ink and not _DARK else QColor(_TRACK)
        if self._on_ink and _DARK:
            track = QColor(0, 0, 0, 40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, 5, 5)
        if self._fraction > 0:
            fill = QRectF(r.left(), r.top(), max(10.0, r.width() * self._fraction), r.height())
            grad = QLinearGradient(fill.left(), 0, fill.right(), 0)
            grad.setColorAt(0, QColor(_GOLD_L))
            grad.setColorAt(1, QColor(_GOLD_D))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(fill, 5, 5)
        p.end()


# ── Stat card ─────────────────────────────────────────────────────────────────

class _StatCard(GlassCard):
    """Label, big numeral and a caption (no icons). dark=True inverts the card."""

    def __init__(self, label: str, value: str, unit: str = "",
                 hint: str = "", dark: bool = False, goal: float | None = None,
                 parent=None):
        super().__init__(radius=PANEL_RADIUS, alpha=225, parent=parent)
        self.setMinimumHeight(STAT_MIN_HEIGHT)
        ink = _theme.ON_PRIMARY if dark else _TEXT
        soft = hex_rgba(_theme.ON_PRIMARY, 0.72) if dark else _TEXT2
        if dark:
            self.set_fill(_theme.PRIMARY, 255)

        col = QVBoxLayout(self)
        col.setContentsMargins(26, 22, 26, 20)
        col.setSpacing(0)

        col.addWidget(_label(label, 18, soft, display=True))
        col.addStretch()

        row = QHBoxLayout()
        row.setSpacing(8)
        self.value = _label(value, 60, _ACCENT_ON_INK if dark else ink, 800, "-1px", True)
        row.addWidget(self.value, alignment=Qt.AlignmentFlag.AlignBottom)
        if unit:
            row.addWidget(_label(unit, 20, soft, display=True),
                          alignment=Qt.AlignmentFlag.AlignBottom)
        row.addStretch()
        col.addLayout(row)

        self.goal = None
        if goal is not None:
            self.goal = _GoalBar(goal, on_ink=dark)
            col.addSpacing(4)
            col.addWidget(self.goal)
        if goal is None:
            col.addSpacing(14)                 # same height as the goal bar, so labels line up
        if hint:
            col.addSpacing(6)
            col.addWidget(_label(hint, 15, soft, 600))

    def set_value(self, value: str) -> None:
        self.value.setText(value)


class _AxisCell(QFrame):
    """One movement direction and how many degrees it has changed since baseline."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("axisCell")
        self.setStyleSheet(
            f"QFrame#axisCell {{ background:{_g.tint(0.05)}; border-radius:20px; border:none; }}")
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 10, 16, 10)
        col.setSpacing(0)
        col.addWidget(_label(name, 14, _MUTED, 700))
        self.delta = _label("—", 26, _TEXT, 800, display=True)
        col.addWidget(self.delta)

    def set_delta(self, degrees: float | None) -> None:
        if degrees is None:
            self.delta.setText("—")
            colour = _MUTED
        else:
            sign = "+" if degrees >= 0 else ""
            self.delta.setText(f"{sign}{degrees:.0f}°")
            colour = _GREEN if degrees >= 0 else _GOLD
        self.delta.setStyleSheet(
            f"color:{colour}; font-size:26px; font-weight:800; font-family:'{_DISPLAY}';"
            f"background:transparent; border:none;")


class _RomCard(GlassCard):
    """Range-of-motion change per direction: a 2 x 2 grid of cells."""

    AXES = ("Flexion", "Extension", "Pronation", "Supination")

    def __init__(self, label: str, parent=None):
        super().__init__(radius=PANEL_RADIUS, alpha=225, parent=parent)
        self.setMinimumHeight(STAT_MIN_HEIGHT)
        col = QVBoxLayout(self)
        col.setContentsMargins(24, 20, 24, 18)
        col.setSpacing(10)

        col.addWidget(_label(label, 18, _TEXT2, display=True))

        grid = QGridLayout()
        grid.setSpacing(10)
        self._cells = {}
        for i, name in enumerate(self.AXES):
            cell = _AxisCell(name)
            self._cells[name] = cell
            grid.addWidget(cell, i // 2, i % 2)
        col.addLayout(grid)

        self._caption = _label("", 15, _MUTED, 600)
        self._caption.setWordWrap(True)
        col.addWidget(self._caption)
        col.addStretch()

    def set_axes(self, axes: dict, squeeze: int | None) -> None:
        """axes: {name: degrees}. Empty means no baseline or session yet."""
        for name, cell in self._cells.items():
            cell.set_delta(axes.get(name))
        if not axes:
            self._caption.setText("Calibrate to start tracking.")
        elif squeeze is not None:
            self._caption.setText(f"Grip strength baseline {squeeze}%")
        else:
            self._caption.setText("Change since your baseline calibration")


# ── Panel with a heading ──────────────────────────────────────────────────────

class _Panel(GlassCard):
    """Frosted panel: heading on the left, an optional chip on the right."""

    def __init__(self, title: str, right: QWidget | None = None, parent=None):
        super().__init__(radius=PANEL_RADIUS, alpha=225, parent=parent)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(30, 26, 30, 24)
        self.body.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(_label(title, 26, _TEXT, 800, "-0.01em", True))
        head.addStretch()
        if right is not None:
            head.addWidget(right)
        self.body.addLayout(head)


# ── Arc gauge widget ──────────────────────────────────────────────────────────

class _ArcGauge(QWidget):
    """
    Quarter-turn ROM gauge.
    Forearm points left; wrist rotates upward (CCW in screen).
      wrist 0°  = left  (Qt 180° = 9-o'clock)
      wrist 90° = up    (Qt 90°  = 12-o'clock)
    """
    def __init__(self, baseline_deg: float, current_deg: float,
                 target_deg: float = 90.0, parent=None):
        super().__init__(parent)
        self._base    = max(0.0, baseline_deg)
        self._current = max(0.0, current_deg)
        self._target  = max(0.0, target_deg)
        self.setFixedHeight(290)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _pt(self, cx: float, cy: float, r: float, wrist_deg: float):
        """Convert wrist angle → screen (x, y)."""
        rad = math.radians(180.0 - max(0.0, wrist_deg))
        return cx + r * math.cos(rad), cy - r * math.sin(rad)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h  = self.width(), self.height()
        cy    = h - 40.0
        r     = max(60.0, min(w / 2.0 - 90, cy - 36))
        cx    = w / 2.0 + 0.34 * r          # centre the arc's visible span in the card
        arc_w = 20
        max_r = 110   # max display angle

        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)

        # 1. Background arc (full range)
        p.setPen(QPen(QColor(_TRACK), arc_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(rect, 180 * 16, -int(max_r * 16))

        # 2. Gold fill arc (wrist 0° → current)
        clamp = min(self._current, max_r)
        if clamp > 0:
            g = QLinearGradient(cx - r, cy, cx + r, cy)
            g.setColorAt(0, QColor(_GOLD_L))
            g.setColorAt(1, QColor(_GOLD_D))
            p.setPen(QPen(QBrush(g), arc_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, 180 * 16, -int(clamp * 16))

        # 3. Green dashed gap (current → target)
        if self._target > self._current:
            dash_pen = QPen(QColor(_GREEN), 6, Qt.PenStyle.CustomDashLine, Qt.PenCapStyle.RoundCap)
            dash_pen.setDashPattern([5.0, 3.5])
            p.setPen(dash_pen)
            p.drawArc(rect, int((180 - clamp) * 16),
                      -int((min(self._target, max_r) - clamp) * 16))

        # 4. Forearm bar (horizontal, left of joint)
        arm = r - 8
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_BORDER))
        p.drawRoundedRect(int(cx - arm), int(cy - 7), int(arm), 14, 7, 7)

        # 5. Ghost arm — baseline (very faded)
        if self._base > 0:
            bx, by = self._pt(cx, cy, r - 8, self._base)
            ghost = QColor(255, 255, 255, 40) if _DARK else QColor(20, 19, 15, 28)
            p.setPen(QPen(ghost, 11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(int(cx), int(cy), int(bx), int(by))

        # 6. Current arm — accent
        ax, ay = self._pt(cx, cy, r - 8, self._current)
        p.setPen(QPen(QColor(_GOLD), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(int(cx), int(cy), int(ax), int(ay))

        # 7. Target tick
        if self._target > 0:
            tx1, ty1 = self._pt(cx, cy, r + 6, self._target)
            tx2, ty2 = self._pt(cx, cy, r + 20, self._target)
            p.setPen(QPen(QColor(_GREEN), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(int(tx1), int(ty1), int(tx2), int(ty2))

        # 8. Wrist joint circles
        p.setPen(QPen(QColor(_DIM), 2))
        p.setBrush(QColor(_INNER))
        p.drawEllipse(int(cx - 16), int(cy - 16), 32, 32)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_BORDER))
        p.drawEllipse(int(cx - 7), int(cy - 7), 14, 14)

        # 9. End dot on the arc tip
        ex, ey = self._pt(cx, cy, r, clamp)
        p.setPen(QPen(QColor(_CARD), 2.5))
        p.setBrush(QColor(_GOLD))
        p.drawEllipse(int(ex - 8), int(ey - 8), 16, 16)

        # 10. Labels
        p.setFont(QFont(_DISPLAY, 13, QFont.Weight.Bold))

        lx, ly = self._pt(cx, cy, r + 34, clamp)
        p.setPen(QColor(_GOLD))
        p.drawText(int(lx) - 18, int(ly) - 4, f"{self._current:.0f}°")

        if self._target > 0:
            tlx, tly = self._pt(cx, cy, r + 36, min(self._target, max_r))
            p.setPen(QColor(_GREEN))
            p.drawText(int(tlx) - 38, int(tly) - 4, f"{self._target:.0f}° target")

        if self._base > 0:                      # under the forearm, clear of the arms
            p.setPen(QColor(_MUTED))
            p.drawText(int(cx - r), int(cy + 34), f"{self._base:.0f}° baseline")

        p.end()


class _Metric(QFrame):
    """A small rounded readout under the gauge."""

    def __init__(self, label: str, value: str, colour: str, parent=None):
        super().__init__(parent)
        self.setObjectName("metric")
        self.setStyleSheet(
            f"QFrame#metric {{ background:{_g.tint(0.05)}; border-radius:22px; border:none; }}")
        col = QVBoxLayout(self)
        col.setContentsMargins(10, 12, 10, 12)
        col.setSpacing(2)
        v = _label(value, 26, colour, 800, display=True)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        n = _label(label, 13, _MUTED, 700, "0.08em")
        n.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(v)
        col.addWidget(n)


# ── Activity calendar ─────────────────────────────────────────────────────────

class _ActivityCalendar(QWidget):
    """
    28-day heatmap drawn with QPainter, uniform circles.

      future   → thin border outline
      rest day → soft filled circle
      <15 min  → mid-green solid
      15+ min  → bright green solid
      today    → accent circle with the date

    session_durations: {date: total_seconds_played}
    """
    _ROW_W = 64    # left column width for date labels
    _CELL  = 42    # each day cell (width = height)

    def __init__(self, session_durations: dict, parent=None):
        super().__init__(parent)
        self._durations = session_durations
        today = date.today()
        self._today  = today
        self._start  = today - timedelta(days=today.weekday()) - timedelta(weeks=3)
        hdr = 24
        self.setFixedHeight(hdr + 4 * self._CELL + 4)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        CELL  = self._CELL
        ROW_W = self._ROW_W
        HDR   = 24
        DAYS  = ["M", "T", "W", "T", "F", "S", "S"]
        avail = self.width() - ROW_W
        col_w = avail / 7.0
        DOT_R = CELL * 0.40

        # ── Day-name header ───────────────────────────────────────────────────
        p.setFont(QFont(_DISPLAY, 11, QFont.Weight.Bold))
        for i, day in enumerate(DAYS):
            p.setPen(QColor(_MUTED))
            p.drawText(QRectF(ROW_W + col_w * i, 0, col_w, HDR),
                       Qt.AlignmentFlag.AlignCenter, day)

        # ── Week rows ─────────────────────────────────────────────────────────
        for week in range(4):
            week_start = self._start + timedelta(weeks=week)
            row_y = HDR + week * CELL

            p.setFont(QFont(_DISPLAY, 11))
            p.setPen(QColor(_MUTED))
            p.drawText(QRectF(0, row_y, ROW_W - 10, CELL),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       week_start.strftime("%b ") + str(week_start.day))

            for day_off in range(7):
                d     = week_start + timedelta(days=day_off)
                secs  = self._durations.get(d, 0)
                future   = d > self._today
                is_today = d == self._today

                cx = ROW_W + col_w * day_off + col_w / 2.0
                cy = row_y + CELL / 2.0
                rect = QRectF(cx - DOT_R, cy - DOT_R, DOT_R * 2, DOT_R * 2)

                if is_today:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(_GOLD))
                    p.drawEllipse(rect)
                    p.setFont(QFont(_DISPLAY, 11, QFont.Weight.Bold))
                    p.setPen(QColor(_ON_ACCENT))
                    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(d.day))
                elif future:
                    p.setPen(QPen(QColor(_BORDER), 1.5))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(rect)
                elif secs >= 900:                        # 15+ min → full green
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(_GREEN))
                    p.drawEllipse(rect)
                elif secs > 0:                           # 1–14 min → mid green
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(_PARTIAL))
                    p.drawEllipse(rect)
                else:                                    # rest day
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(_REST))
                    p.drawEllipse(rect)

        p.end()


# ── Milestone timeline ────────────────────────────────────────────────────────

class _MilestoneTimeline(QWidget):
    """Horizontal node row: earned=accent, next=accent ring, locked=dim."""

    NODE = 56

    def __init__(self, achieved: list, all_milestones: list, parent=None):
        super().__init__(parent)
        self._achieved = set(achieved)
        self._all = all_milestones
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        node = self.NODE

        next_id = next(
            (m["id"] for m in self._all if m["id"] not in self._achieved), None
        )

        row = QHBoxLayout()
        row.setSpacing(0)

        for i, m in enumerate(self._all):
            earned  = m["id"] in self._achieved
            is_next = m["id"] == next_id

            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)            # so the connector lines up with the bubble
            col.setSpacing(8)
            col.setAlignment(Qt.AlignmentFlag.AlignHCenter)

            bubble = QLabel(m["emoji"] if (earned or is_next) else "🔒")
            bubble.setFixedSize(node, node)
            bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
            half = node // 2
            if earned:
                bubble.setStyleSheet(
                    f"background:{_GOLD}; border-radius:{half}px; font-size:21px; color:{_ON_ACCENT};")
            elif is_next:
                bubble.setStyleSheet(
                    f"background:transparent; border:3px solid {_GOLD}; "
                    f"border-radius:{half}px; font-size:21px; color:{_GOLD};")
            else:
                bubble.setStyleSheet(
                    f"background:{_g.tint(0.05)}; border:1.5px solid {_BORDER}; "
                    f"border-radius:{half}px; font-size:17px; color:{_MUTED};")

            name_lbl = QLabel(m["title"])
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            name_lbl.setWordWrap(True)
            name_lbl.setFixedWidth(84)
            name_lbl.setMinimumHeight(56)                 # room for three wrapped lines
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            name_lbl.setStyleSheet(
                f"color:{_GOLD if earned else (_TEXT2 if is_next else _MUTED)}; "
                f"font-size:14px; font-weight:700; background:transparent;")

            col.addWidget(bubble, alignment=Qt.AlignmentFlag.AlignHCenter)
            col.addWidget(name_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)

            node_w = QWidget()
            node_w.setLayout(col)
            row.addWidget(node_w, stretch=1)

            if i < len(self._all) - 1:
                line = QFrame()
                line.setFixedSize(14, 3)
                line.setStyleSheet(
                    f"background:{_GOLD if earned else _BORDER}; border-radius:1px;")
                link = QWidget()                          # puts the line level with the bubbles' middle
                link.setFixedWidth(14)
                ll = QVBoxLayout(link)
                ll.setContentsMargins(0, half - 1, 0, 0)
                ll.addWidget(line)
                ll.addStretch()
                row.addWidget(link)

        layout.addLayout(row)

        last = next(
            (m for m in reversed(self._all) if m["id"] in self._achieved), None
        )
        if last:
            layout.addWidget(self._trophy(last))

    @staticmethod
    def _trophy(last: dict) -> QFrame:
        """Banner for the most recently earned milestone."""
        trophy = QFrame()
        trophy.setObjectName("trophy")
        if _DARK:
            fill, edge = "rgba(255,154,77,0.14)", "rgba(255,154,77,0.40)"
        else:
            fill = ("qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #FFE3C4, stop:1 #FFD0A0)")
            edge = "rgba(194,72,10,0.25)"
        trophy.setStyleSheet(
            f"QFrame#trophy {{ background:{fill}; border:1px solid {edge}; border-radius:26px; }}")
        tr = QHBoxLayout(trophy)
        tr.setContentsMargins(22, 16, 22, 16)
        tr.setSpacing(16)

        info = QVBoxLayout()
        info.setSpacing(2)
        info.addWidget(_label(f"{last['title']}!", 17, _GOLD, 800, display=True))
        info.addWidget(_label(last.get("desc", ""), 15, _TEXT2, 500))
        tr.addLayout(info)
        tr.addStretch()

        badge = QLabel("EARNED")
        badge.setStyleSheet(
            f"color:{_GOLD}; background:rgba(194,72,10,0.10); "
            f"border:1px solid rgba(194,72,10,0.25); border-radius:12px; "
            f"font-size:13px; font-weight:700; padding:4px 12px;")
        tr.addWidget(badge)
        return trophy


# ── Main page ─────────────────────────────────────────────────────────────────

class ProgressPage(QScrollArea):
    def __init__(self, session_manager: SessionManager, profile: dict, parent=None):
        super().__init__(parent)
        self._sm         = session_manager
        self._profile    = profile
        self._pdf_thread = None

        self.setWidgetResizable(True)
        self.setStyleSheet(
            "QScrollArea { border:none; background:transparent; }"
            f"QScrollBar:vertical {{ background:transparent; width:6px; border-radius:3px; }}"
            f"QScrollBar::handle:vertical {{ background:{_DIM}; border-radius:3px; min-height:24px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }"
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._floating_bar = FloatingScrollBar(self)       # slim thumb over the edge, not a native bar

        container = QWidget()
        container.setStyleSheet("background:transparent;")
        self.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(PAGE_MARGIN, 16, PAGE_MARGIN, 120)
        root.setSpacing(0)

        root.addLayout(self._build_header())
        root.addSpacing(10)
        root.addLayout(self._build_stats_row())
        root.addLayout(self._build_pair_row())
        root.addWidget(self._build_milestones_panel())
        root.addStretch()

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setContentsMargins(SHADOW_PAD, 0, SHADOW_PAD, 0)

        titles = QVBoxLayout()
        titles.setSpacing(6)
        titles.addWidget(_label(
            f"YOUR PROGRESS · {date.today().strftime('%A %d %B').upper()}",
            15, _MUTED, 700, "0.14em"))
        self._title = _label(t("prog_title"), 56, _TEXT, 800, "-0.02em", True)
        titles.addWidget(self._title)
        head.addLayout(titles)
        head.addStretch()

        report = QVBoxLayout()
        report.setSpacing(6)
        self._report_btn = PillButton(t("prog_download"), "dark", 56)
        self._report_btn.clicked.connect(self._download_report)
        report.addStretch()
        report.addWidget(self._report_btn, alignment=Qt.AlignmentFlag.AlignRight)
        self._status_lbl = _label("", 15, _MUTED, 600)
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        report.addWidget(self._status_lbl)
        head.addLayout(report)
        return head

    # ── Stat cards ────────────────────────────────────────────────────────────

    def _today_minutes(self) -> int:
        # Round UP so even a 1-minute (or 40-second) session shows as activity
        return -(-self._sm.get_today_duration_seconds() // 60)

    def _build_stats_row(self) -> QHBoxLayout:
        total  = self._sm.get_total_sessions()
        streak = self._sm.get_streak()
        mins   = self._today_minutes()

        self._total_card = _StatCard(t("prog_total"), str(total),
                                     hint="sessions completed")
        self._streak_card = _StatCard(t("prog_streak"), str(streak),
                                      unit="days", hint="in a row", dark=True)
        self._today_card = _StatCard(t("prog_today"), str(mins), unit="min",
                                     hint=f"goal: {DAILY_GOAL_MIN} min / day",
                                     goal=mins / DAILY_GOAL_MIN)
        self._rom_card = _RomCard(t("prog_rom_imp"))
        axes, squeeze = self._rom_axes()
        self._rom_card.set_axes(axes, squeeze)

        row = QHBoxLayout()
        row.setSpacing(0)
        for card in (self._total_card, self._streak_card, self._today_card):
            row.addWidget(card, stretch=1)
        row.addWidget(self._rom_card, stretch=1)
        return row

    def _rom_axes(self):
        """
        Per-direction ROM change in DEGREES with anatomical names, plus the grip
        baseline (percent) when measured. Uses the 'deg' block when present;
        falls back to the normalised legacy values for pre-deg records.
        Returns ({}, None) when there is no baseline or session yet.
        """
        baseline = self._sm.get_baseline_rom() or {}
        rom_hist = self._sm.get_rom_history()
        latest   = rom_hist[-1] if rom_hist else None
        if not baseline or not latest:
            return {}, None

        b_deg = baseline.get("deg") or {}
        c_deg = latest.get("deg") or {}
        axes = {}
        for label, dkey, legacy in [
            ("Flexion",    "flexion",    "max_down"),
            ("Extension",  "extension",  "max_up"),
            ("Pronation",  "pronation",  "max_right"),
            ("Supination", "supination", "max_left"),
        ]:
            if b_deg and dkey in b_deg:
                base_val = b_deg.get(dkey, 0)
                curr_val = c_deg.get(dkey, base_val)
            else:
                base_val = abs(baseline.get(legacy, 0))
                curr_val = abs(latest.get(legacy, base_val))
            axes[label] = curr_val - base_val

        sq_base = baseline.get("squeeze_max")
        return axes, (int(sq_base * 100) if sq_base is not None else None)

    # ── Movement + activity ───────────────────────────────────────────────────

    def _build_pair_row(self) -> QHBoxLayout:
        pair = QHBoxLayout()
        pair.setSpacing(0)
        pair.addWidget(self._build_movement_panel(), stretch=11)
        pair.addWidget(self._build_calendar_panel(), stretch=10)
        return pair

    def _build_movement_panel(self) -> QWidget:
        panel = _Panel(t("prog_movement"))
        vl = panel.body

        baseline = self._sm.get_baseline_rom()
        rom_hist = self._sm.get_rom_history()
        latest   = rom_hist[-1] if rom_hist else None

        base_deg    = abs(baseline.get("max_right", 0.0)) if baseline else 0.0
        current_deg = abs(latest.get("max_right", base_deg)) if latest else base_deg
        target_deg  = max(90.0, base_deg + 25.0)

        if base_deg == 0.0 and current_deg == 0.0:
            vl.addWidget(_ArcGauge(0.0, 0.0, 90.0))
            hint = _label(t("prog_rom_empty"), 16, _MUTED, 500)
            hint.setWordWrap(True)
            vl.addWidget(hint)
            vl.addStretch()
            return panel

        vl.addWidget(_ArcGauge(base_deg, current_deg, target_deg))

        gain = current_deg - base_deg
        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        for lbl, val, col in [
            ("BASELINE",   f"{base_deg:.0f}°",    _TEXT2),
            ("TODAY",      f"{current_deg:.0f}°", _GOLD),
            ("TARGET",     f"{target_deg:.0f}°",  _GREEN),
            ("TOTAL GAIN", f"+{gain:.0f}°" if gain >= 0 else f"{gain:.0f}°", _GREEN),
        ]:
            metrics.addWidget(_Metric(lbl, val, col), stretch=1)
        vl.addLayout(metrics)
        vl.addStretch()
        return panel

    def _build_calendar_panel(self) -> QWidget:
        sessions = self._sm.get_all_sessions()
        durations: dict = {}
        for s in sessions:
            raw = s.get("date") or s.get("start_time", "")
            if raw:
                try:
                    d = date.fromisoformat(str(raw)[:10])
                    durations[d] = durations.get(d, 0) + s.get("duration_seconds", 0)
                except ValueError:
                    pass

        today = date.today()
        start = today - timedelta(days=today.weekday()) - timedelta(weeks=3)
        total_days = (today - start).days + 1
        in_range = sum(1 for d in durations if start <= d <= today)
        pct = int(in_range / max(total_days, 1) * 100)

        panel = _Panel(t("prog_activity"), Chip(f"{pct}% · 28 days", tone="accent"))
        vl = panel.body
        vl.addWidget(_ActivityCalendar(durations))
        vl.addStretch()

        secs_in_range = [s for d, s in durations.items() if start <= d <= today and s > 0]
        avg_min = round(sum(secs_in_range) / len(secs_in_range) / 60) if secs_in_range else 0
        best_min = round(max(secs_in_range) / 60) if secs_in_range else 0
        summary = QHBoxLayout()
        summary.setSpacing(12)
        for lbl, val, col in [("ACTIVE DAYS", str(in_range), _TEXT),
                              ("AVG / DAY", f"{avg_min} min", _GOLD),
                              ("BEST DAY", f"{best_min} min", _GREEN)]:
            summary.addWidget(_Metric(lbl, val, col), stretch=1)
        vl.addLayout(summary)

        legend = QHBoxLayout()
        legend.setSpacing(0)
        for color, txt in [(_GREEN, "15+ min"), (_PARTIAL, "< 15 min"),
                           (_REST, "Rest"), (_GOLD, "Today")]:
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(f"background:{color}; border-radius:6px; border:none;")
            legend.addWidget(swatch)
            legend.addSpacing(6)
            legend.addWidget(_label(txt, 14, _MUTED, 600))
            legend.addSpacing(18)
        legend.addStretch()
        vl.addLayout(legend)
        return panel

    # ── Milestones ────────────────────────────────────────────────────────────

    def _build_milestones_panel(self) -> QWidget:
        from core.milestone_manager import MILESTONES
        achieved = self._sm.get_milestones()
        done = sum(1 for m in MILESTONES if m["id"] in set(achieved))
        panel = _Panel(t("prog_milestones"),
                       Chip(f"{done} of {len(MILESTONES)} earned", tone="accent"))
        panel.body.addSpacing(6)
        panel.body.addWidget(_MilestoneTimeline(achieved, MILESTONES))
        return panel

    # ── Download handler ──────────────────────────────────────────────────────

    def _download_report(self):
        from datetime import datetime as _dt
        name    = self._profile.get("name", "Patient").replace(" ", "_")
        ts      = _dt.now().strftime("%Y-%m-%d_%H-%M-%S")
        default = f"Solace_Report_{name}_{ts}.pdf"
        path, _ = QFileDialog.getSaveFileName(None, "Save Report", default, "PDF Files (*.pdf)")
        self.window().update()
        if not path:
            return
        self._report_btn.setEnabled(False)
        self._report_btn.setText(t("prog_generating"))
        self._status_lbl.setText(t("prog_building"))
        self._pdf_thread = _PDFThread(self._sm, self._profile, path)
        self._pdf_thread.done.connect(self._on_report_done)
        self._pdf_thread.error.connect(self._on_report_error)
        self._pdf_thread.start()

    def _on_report_done(self, path: str):
        self._report_btn.setEnabled(True)
        self._report_btn.setText(t("prog_download"))
        self._status_lbl.setText(f"Saved to: {path}")

    def _on_report_error(self, msg: str):
        self._report_btn.setEnabled(True)
        self._report_btn.setText(t("prog_download"))
        self._status_lbl.setText(f"Could not save the report: {msg}")

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self):
        """Update the stat cards in place with the latest session data."""
        mins = self._today_minutes()
        self._total_card.set_value(str(self._sm.get_total_sessions()))
        self._streak_card.set_value(str(self._sm.get_streak()))
        self._today_card.set_value(str(mins))
        if self._today_card.goal is not None:
            self._today_card.goal.set_fraction(mins / DAILY_GOAL_MIN)
        axes, squeeze = self._rom_axes()
        self._rom_card.set_axes(axes, squeeze)

    def refresh_theme(self):
        pass

    # ── Keyboard / controller navigation (mirrors the Settings page) ──────────
    def navigate(self, direction: int):
        """Scroll the page; the Progress page is mostly a read-only display."""
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + direction * 120)

    def activate_selected(self):
        """The one action on this page is downloading the report."""
        if hasattr(self, "_report_btn") and self._report_btn.isEnabled():
            self._download_report()
