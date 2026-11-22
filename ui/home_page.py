"""
HomePage — Home tab, Solace Glass layout.

Header with the title and two chips, an optional calibration nudge, then two
columns: on the left a phase-progress gauge card and two stat tiles; on the
right today's journey as a grid of tiles.
"""
from datetime import date, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QPushButton
)
from PyQt6.QtCore import pyqtSignal, Qt

from core import theme as _t
from core.i18n import t
from core.suggestion_engine import get_current_card
from ui.glass import (GlassCard, IconBubble, Chip, ArcGauge, StatTile, PillButton,
                      SHADOW_PAD as CARD_INSET)
from ui.journey_banner import JourneyPanel

PAGE_MARGIN = 56
LEFT_COLUMN_WIDTH = 540
MAX_CONTENT_WIDTH = 1800


class HomePage(QScrollArea):
    """Home tab — progress summary on the left, today's journey on the right."""

    game_launch_requested = pyqtSignal(str)
    warmup_requested      = pyqtSignal()
    assessment_requested  = pyqtSignal()

    def __init__(self, game_manager, session_manager, parent=None):
        super().__init__(parent)
        self.game_manager    = game_manager
        self.session_manager = session_manager

        self.items    = []
        self.game_ids = []

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self.setWidget(container)

        outer = QHBoxLayout(container)
        outer.setContentsMargins(PAGE_MARGIN, 8, PAGE_MARGIN, 56)
        outer.addStretch(1)
        content = QWidget()
        content.setMaximumWidth(MAX_CONTENT_WIDTH)
        outer.addWidget(content, 100)
        outer.addStretch(1)

        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(24)

        root.addLayout(self._build_header())
        self._cal_banner = self._make_cal_banner()
        root.addWidget(self._cal_banner)
        self._refresh_cal_banner()

        body = QHBoxLayout()
        body.setSpacing(0)            # cards carry their own shadow margins
        body.addLayout(self._build_left_column())
        self.journey_panel = JourneyPanel(self.session_manager, self.game_manager)
        self.journey_panel.warmup_requested.connect(self.warmup_requested.emit)
        self.journey_panel.game_requested.connect(self.game_launch_requested.emit)
        self.journey_panel.assessment_requested.connect(self.assessment_requested.emit)
        body.addWidget(self.journey_panel, 1, Qt.AlignmentFlag.AlignTop)
        root.addLayout(body)
        root.addStretch()

        self._update_stats()

    # ── Building blocks ───────────────────────────────────────────────────────

    def _build_header(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(8)
        col.setContentsMargins(CARD_INSET, 0, 0, 0)   # align with the cards' visible edge

        self._title_lbl = QLabel(t("home_title"))
        self._title_lbl.setStyleSheet(
            f"color: {_t.ON_SURFACE}; font-family: '{_t.FONT_DISPLAY}';"
            f" font-size: 60px; font-weight: 800; letter-spacing: -2px;"
            f" background: transparent;"
        )
        col.addWidget(self._title_lbl)

        self._sub_lbl = QLabel(t("home_subtitle"))
        self._sub_lbl.setStyleSheet(
            f"color: {_t.ON_SURFACE_VAR}; font-family: '{_t.FONT_BODY}';"
            f" font-size: 19px; background: transparent;"
        )
        col.addWidget(self._sub_lbl)

        chips = QHBoxLayout()
        chips.setSpacing(12)
        self._streak_chip = Chip("", "🔥", tone="accent")
        self._phase_chip = Chip("")
        chips.addWidget(self._streak_chip)
        chips.addWidget(self._phase_chip)
        chips.addStretch()
        col.addSpacing(6)
        col.addLayout(chips)
        return col

    def _build_left_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(0)

        gauge_card = GlassCard()
        gauge_card.setFixedWidth(LEFT_COLUMN_WIDTH)
        gv = QVBoxLayout(gauge_card)
        gv.setContentsMargins(30, 26, 30, 28)
        gv.setSpacing(0)
        top = QHBoxLayout()
        top.addWidget(IconBubble("🎯", 48))
        top.addStretch()
        gv.addLayout(top)
        caption = QLabel("Phase progress")
        caption.setStyleSheet(
            f"color: {_t.ON_SURFACE_VAR}; font-family: '{_t.FONT_BODY}';"
            f" font-size: 19px; font-weight: bold; background: transparent;"
        )
        gv.addSpacing(6)
        gv.addWidget(caption)
        self._gauge = ArcGauge(0.0)
        self._gauge.setMinimumHeight(190)
        gv.addWidget(self._gauge)
        self._pct_lbl = QLabel("0%")
        self._pct_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pct_lbl.setStyleSheet(
            f"color: {_t.ON_SURFACE}; font-family: '{_t.FONT_DISPLAY}';"
            f" font-size: 78px; font-weight: 800; letter-spacing: -2px;"
            f" background: transparent;"
        )
        gv.addWidget(self._pct_lbl)
        self._phase_lbl = QLabel("")
        self._phase_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._phase_lbl.setStyleSheet(
            f"color: {_t.ON_SURFACE_VAR}; font-family: '{_t.FONT_BODY}';"
            f" font-size: 18px; background: transparent;"
        )
        gv.addWidget(self._phase_lbl)
        col.addWidget(gauge_card)

        tiles = QHBoxLayout()
        tiles.setSpacing(0)
        tiles.setContentsMargins(0, 0, 0, 0)
        self._sessions_tile = StatTile("Sessions", "0", "🏅", dots=[False] * 7)
        self._streak_tile = StatTile("Day streak", "0", "🔥", unit="days")
        tiles.addWidget(self._sessions_tile)
        tiles.addWidget(self._streak_tile)
        wrap = QWidget()
        wrap.setFixedWidth(LEFT_COLUMN_WIDTH)
        wrap.setLayout(tiles)
        col.addWidget(wrap)
        col.addStretch()
        return col

    # ── Data ──────────────────────────────────────────────────────────────────

    def _week_flags(self) -> list[bool]:
        """Seven flags, oldest first: was there a session on that day?"""
        today = date.today()
        days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
        active = {s.get("date") for s in self.session_manager.get_all_sessions()}
        return [d in active for d in days]

    def _update_stats(self):
        sm = self.session_manager
        streak = sm.get_streak()
        card = get_current_card(sm, self.game_manager.get_games())
        pct = float(card.get("progress_pct", 0.0))

        self._streak_chip.set_text(t("home_streak", n=streak))
        self._phase_chip.set_text(f"Phase {card.get('phase', 1)} · {card.get('phase_name', '')}")
        self._gauge.set_value(pct)
        self._pct_lbl.setText(f"{int(round(pct * 100))}%")
        self._phase_lbl.setText(card.get("phase_name", ""))
        self._sessions_tile.set_value(str(sm.get_total_sessions()))
        self._sessions_tile.set_dots(self._week_flags())
        self._streak_tile.set_value(str(streak))

    # ── Compat stubs ───────────────────────────────────────────────────────────

    def set_selected_index(self, idx: int):
        pass

    def set_session_manager(self, sm):
        """C1 fix: rebind home + journey to the new profile on switch —
        previously they kept showing (and recording into!) the old patient."""
        self.session_manager = sm
        self.journey_panel.set_session_manager(sm)
        self.refresh_journey()

    # ── Keyboard / controller navigation ──────────────────────────────────────
    def navigate(self, direction: int):
        self.journey_panel.navigate(direction)

    def activate_selected(self):
        self.journey_panel.activate_selected()
        self._refresh_cal_banner()

    def refresh_journey(self):
        """B3: update stats + journey tiles after a session completes."""
        self.journey_panel.refresh()
        self._update_stats()
        self._refresh_cal_banner()

    def refresh_language(self):
        """Update all translatable strings when the language changes."""
        self._title_lbl.setText(t("home_title"))
        self._sub_lbl.setText(t("home_subtitle"))
        self._streak_chip.set_text(t("home_streak", n=self.session_manager.get_streak()))

    def refresh_theme(self):
        pass

    # ── Calibration nudge helpers ─────────────────────────────────────────────

    def _make_cal_banner(self) -> QFrame:
        """Soft orange nudge card, hidden once a baseline exists."""
        banner = QFrame()
        banner.setObjectName("calBanner")
        from ui.glass import is_dark
        fill, edge = (("rgba(255,154,77,0.16)", "rgba(255,154,77,0.40)") if is_dark()
                      else ("rgba(255,178,107,0.30)", "rgba(194,72,10,0.35)"))
        banner.setStyleSheet(
            f"QFrame#calBanner {{ background: {fill};"
            f" border: 1px solid {edge}; border-radius: 28px; }}"
        )
        row = QHBoxLayout(banner)
        row.setContentsMargins(26, 16, 18, 16)
        row.setSpacing(18)

        row.addWidget(IconBubble("📏", 52))

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title = QLabel("Calibration not completed")
        title.setStyleSheet(
            f"color: {_t.PRIMARY_CONTAINER}; font-family: '{_t.FONT_DISPLAY}';"
            f" font-size: 19px; font-weight: bold; background: transparent; border: none;"
        )
        sub = QLabel("Your range of motion hasn't been recorded yet. "
                     "Calibrate now so your therapist gets accurate data.")
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color: {_t.ON_SURFACE}; font-family: '{_t.FONT_BODY}';"
            f" font-size: 16px; background: transparent; border: none;"
        )
        text_col.addWidget(title)
        text_col.addWidget(sub)
        row.addLayout(text_col, 1)

        cal_btn = PillButton("Calibrate now", "dark", 50)
        cal_btn.clicked.connect(self._open_calibration)
        row.addWidget(cal_btn)

        dismiss = QPushButton("×")
        dismiss.setFixedSize(40, 40)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {_t.ON_SURFACE_VAR};"
            f" border: none; font-size: 26px; font-weight: bold; border-radius: 20px; }}"
            f"QPushButton:hover {{ background: rgba(20,19,15,0.08); color: {_t.ON_SURFACE}; }}"
        )
        dismiss.clicked.connect(self._dismiss_cal_banner)
        row.addWidget(dismiss)

        # Wrapper insets the banner to the cards' visible edge; hiding the
        # wrapper (not the banner) removes it from the layout entirely.
        wrapper = QWidget()
        wl = QHBoxLayout(wrapper)
        wl.setContentsMargins(CARD_INSET, 0, CARD_INSET, 0)
        wl.addWidget(banner)
        wrapper._dismissed = False
        wrapper.setVisible(False)
        return wrapper

    def _refresh_cal_banner(self):
        """Show banner if no baseline, hide if baseline exists or dismissed."""
        if self._cal_banner._dismissed:
            return
        self._cal_banner.setVisible(not self.session_manager.has_baseline())

    def _dismiss_cal_banner(self):
        self._cal_banner._dismissed = True
        self._cal_banner.setVisible(False)

    def _open_calibration(self):
        """Open the calibration step as a standalone full-screen dialog."""
        from ui.onboarding import _StepCalibration
        from PyQt6.QtWidgets import QDialog, QApplication

        dlg = QDialog(self)
        dlg.setWindowTitle("Solace — Calibration")
        dlg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        screen = QApplication.primaryScreen().availableGeometry()
        dlg.setFixedSize(screen.width(), screen.height())
        dlg.setStyleSheet(f"background: {_t.BACKGROUND};")

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)

        cal = _StepCalibration()

        def _on_done(ml, mr, mu, md):
            if any([ml, mr, mu, md]):
                self.session_manager.save_baseline_rom(ml, mr, mu, md)
            dlg.accept()
            self._cal_banner.setVisible(False)

        cal.completed.connect(_on_done)
        layout.addWidget(cal)
        dlg.exec()
