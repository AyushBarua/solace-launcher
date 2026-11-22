"""
MilestoneManager — detects and awards clinical milestones after each session.
MilestoneCelebration — full-screen celebration overlay when a milestone is hit.
"""
from core.session_manager import SessionManager


# ── Milestone definitions ─────────────────────────────────────────────────────

MILESTONES = [
    {
        "id":    "first_session",
        "emoji": "🎉",
        "title": "First Steps!",
        "desc":  "You completed your very first session. The journey starts here.",
    },
    {
        "id":    "streak_3",
        "emoji": "🔥",
        "title": "3 Days in a Row!",
        "desc":  "Consistency is the key to recovery. You're building great habits.",
    },
    {
        "id":    "streak_7",
        "emoji": "🔥",
        "title": "7-Day Streak!",
        "desc":  "One full week of practice! Your therapist will be proud.",
    },
    {
        "id":    "streak_30",
        "emoji": "🌟",
        "title": "30-Day Warrior!",
        "desc":  "A whole month of dedication. Remarkable commitment.",
    },
    {
        "id":    "sessions_10",
        "emoji": "💪",
        "title": "10 Sessions Complete!",
        "desc":  "Double digits! Your muscles are remembering how to move.",
    },
    {
        "id":    "sessions_30",
        "emoji": "🌟",
        "title": "30 Sessions!",
        "desc":  "30 times you chose to fight for your recovery. That's incredible.",
    },
    {
        "id":    "difficulty_05",
        "emoji": "🏆",
        "title": "Speed Demon!",
        "desc":  "You unlocked 0.5× difficulty. Your speed is improving!",
    },
    {
        "id":    "difficulty_10",
        "emoji": "⭐",
        "title": "Full Speed!",
        "desc":  "You're playing at full difficulty. Look how far you've come!",
    },
    {
        "id":    "rom_25",
        "emoji": "📈",
        "title": "Breaking Through!",
        "desc":  "Your range of movement has improved by 25% since you started.",
    },
    {
        "id":    "rom_50",
        "emoji": "🚀",
        "title": "Twice the Range!",
        "desc":  "50% improvement in your range of movement from baseline. Extraordinary.",
    },
]

MILESTONE_MAP = {m["id"]: m for m in MILESTONES}


def check_and_award(sm: SessionManager, session: dict) -> list[dict]:
    """
    Run after a session ends. Returns a list of newly awarded milestone dicts.
    """
    awarded = []

    total     = sm.get_total_sessions()
    streak    = sm.get_streak()
    diff      = session.get("difficulty", 0.0)
    # M1 fix: credit improvement in ANY of the four directions — previously
    # only right/up (pronation/extension) counted, so a patient whose
    # supination or flexion recovered never earned the ROM milestones.
    rom_best = max(
        (imp for imp in (sm.get_rom_improvement_pct(a)
                         for a in ("right", "left", "up", "down"))
         if imp is not None and imp > 0),
        default=0,
    )

    def _try(mid: str):
        if not sm.has_milestone(mid):
            sm.award_milestone(mid, session)
            awarded.append(MILESTONE_MAP[mid])

    # Session count milestones
    if total >= 1:  _try("first_session")
    if total >= 10: _try("sessions_10")
    if total >= 30: _try("sessions_30")

    # Streak milestones
    if streak >= 3:  _try("streak_3")
    if streak >= 7:  _try("streak_7")
    if streak >= 30: _try("streak_30")

    # Difficulty milestones
    if diff >= 0.5: _try("difficulty_05")
    if diff >= 1.0: _try("difficulty_10")

    # ROM improvement milestones
    if rom_best >= 25: _try("rom_25")
    if rom_best >= 50: _try("rom_50")

    return awarded


# ── Celebration UI ────────────────────────────────────────────────────────────

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QApplication, QGraphicsOpacityEffect
)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor

from core.theme import (
    FONT_DISPLAY, FONT_BODY, ON_SURFACE, ON_SURFACE_VAR,
    PRIMARY_CONTAINER, PRIMARY_FIXED, SURFACE_CON_LOW,
    OUTLINE_VARIANT, BACKGROUND, ON_PRIMARY_FIXED_VARIANT, PRIMARY, ON_PRIMARY
)


class MilestoneCelebration(QDialog):
    """
    Full-screen milestone celebration — not a toast, a real moment.
    Pass a list of milestone dicts; shows them one by one.
    """

    def __init__(self, milestones: list[dict], profile_name: str = "Friend", parent=None):
        super().__init__(parent)
        self._milestones = milestones
        self._current   = 0
        self._name      = profile_name

        self.setWindowTitle("Solace — Achievement!")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        screen = QApplication.primaryScreen().availableGeometry()
        self.setFixedSize(screen.width(), screen.height())
        self.setStyleSheet("background: rgba(20,19,15,0.72);")

        # Centred card
        self._card_w, self._card_h = 640, 440
        self._card = QWidget(self)
        self._card.setGeometry(
            (screen.width()  - self._card_w) // 2,
            (screen.height() - self._card_h) // 2,
            self._card_w, self._card_h
        )
        self._card.setObjectName("msCard")   # scoped: a bare rule would box every child label
        from ui import glass as _g
        self._card.setStyleSheet(
            f"QWidget#msCard {{ background: {_g.solid_pane()}; border: 1px solid {OUTLINE_VARIANT};"
            f" border-radius: 36px; }}"
        )

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(56, 48, 56, 48)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._emoji_lbl = QLabel()
        self._emoji_lbl.setStyleSheet("font-size: 88px; background: transparent;")
        self._emoji_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        badge = QLabel("ACHIEVEMENT UNLOCKED")
        badge.setFixedWidth(260)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(f"""
            color: {PRIMARY_CONTAINER};
            background: {'rgba(255,154,77,0.18)' if _g.is_dark() else 'rgba(255,178,107,0.28)'};
            border: 1px solid {PRIMARY_CONTAINER};
            border-radius: 20px;
            padding: 4px 16px;
            font-family: '{FONT_DISPLAY}';
            font-size: 12px;
            font-weight: bold;
            letter-spacing: 2px;
        """)

        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 42px; font-weight: 800; background: transparent;"
        )
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._desc_lbl = QLabel()
        self._desc_lbl.setStyleSheet(
            f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; "
            f"font-size: 19px; background: transparent;"
        )
        self._desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._desc_lbl.setWordWrap(True)

        self._btn = QPushButton()
        self._btn.setFixedHeight(52)
        self._btn.setFixedWidth(240)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setStyleSheet(f"""
            QPushButton {{
                background: {PRIMARY};
                color: {ON_PRIMARY};
                border: none;
                border-radius: 26px;
                font-family: '{FONT_DISPLAY}';
                font-size: 17px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {_g.hover_ink()};
            }}
        """)
        self._btn.clicked.connect(self._next)

        layout.addWidget(self._emoji_lbl)
        layout.addSpacing(8)

        badge_row = QHBoxLayout()
        badge_row.addStretch()
        badge_row.addWidget(badge)
        badge_row.addStretch()
        layout.addLayout(badge_row)
        layout.addSpacing(12)

        layout.addWidget(self._title_lbl)
        layout.addSpacing(12)
        layout.addWidget(self._desc_lbl)
        layout.addSpacing(32)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._show_current()

    def _show_current(self):
        m = self._milestones[self._current]
        self._emoji_lbl.setText(m["emoji"])
        self._title_lbl.setText(m["title"])
        self._desc_lbl.setText(m["desc"])
        remaining = len(self._milestones) - self._current - 1
        if remaining > 0:
            self._btn.setText(f"Next  ({remaining} more)")
        else:
            self._btn.setText(f"Amazing, {self._name}!")

    def _next(self):
        self._current += 1
        if self._current >= len(self._milestones):
            self.accept()
        else:
            self._show_current()
