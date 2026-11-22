"""
PainCheckIn — post-session wellbeing check shown after every game session.

Three large accessible buttons: Good / Tired / Pain.
Auto-closes after 30 seconds defaulting to "good".
Result is stored in the session log.
"""
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QApplication
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor

from core.theme import (
    FONT_DISPLAY, FONT_BODY, ON_SURFACE, ON_SURFACE_VAR,
    SURFACE_CON_LOW, OUTLINE_VARIANT, BACKGROUND, SURFACE_DIM
)
from core.i18n import t


class PainCheckIn(QDialog):
    """
    Shows after a game session ends.
    Read .result after exec() — "good" | "tired" | "pain"
    """

    AUTO_CLOSE_SECONDS = 90     # U3: was 30s — too short for elderly / fatigued patients
    AUTO_CLOSE_DEFAULT  = "tired" # U3: safer clinical default than "good"

    def __init__(self, profile_name: str = "Friend", parent=None):
        super().__init__(parent)
        self.result = self.AUTO_CLOSE_DEFAULT
        self._countdown = self.AUTO_CLOSE_SECONDS

        self.setWindowTitle("Solace — How did that feel?")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        screen = QApplication.primaryScreen().availableGeometry()
        self.setFixedSize(screen.width(), screen.height())
        self.setStyleSheet(f"background: {BACKGROUND};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch()

        # ── Heading ───────────────────────────────────────────────────────────
        title = QLabel(t("pain_title", name=profile_name))
        title.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 40px; font-weight: bold; background: transparent;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)
        root.addSpacing(12)

        sub = QLabel(t("pain_subtitle"))
        sub.setStyleSheet(
            f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; "
            f"font-size: 18px; background: transparent;"
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(sub)
        root.addSpacing(56)

        # ── Three big buttons ─────────────────────────────────────────────────
        # U2: wrap in a named widget so _select() can hide all three at once
        self._btn_row_widget = QWidget()
        self._btn_row_widget.setStyleSheet("background: transparent;")
        btn_row = QHBoxLayout(self._btn_row_widget)
        btn_row.setSpacing(32)
        btn_row.addStretch()

        buttons = [
            ("😊", t("pain_good"), "#1E9E4A", "rgba(46,160,90,0.14)", "#177A39", "good"),
            ("😐", t("pain_tired"), "#A86A00", "rgba(255,178,50,0.20)", "#875400", "tired"),
            ("😣", t("pain_pain"), "#C93A32", "rgba(230,80,70,0.14)", "#A52D26", "pain"),
        ]

        for emoji, label, color, bg, hover, key in buttons:
            card = self._make_response_card(emoji, label, color, bg, hover, key)
            btn_row.addWidget(card)

        btn_row.addStretch()
        root.addWidget(self._btn_row_widget)
        root.addSpacing(48)

        # ── Auto-close countdown ──────────────────────────────────────────────
        self._countdown_lbl = QLabel(
            t("pain_countdown", sec=self._countdown)
        )
        self._countdown_lbl.setStyleSheet(
            f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; "
            f"font-size: 14px; background: transparent;"
        )
        self._countdown_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._countdown_lbl)

        # U2: hidden support message shown after a selection is made
        self._support_lbl = QLabel("")
        self._support_lbl.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 26px; font-weight: bold; background: transparent;"
        )
        self._support_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._support_lbl.setWordWrap(True)
        self._support_lbl.setVisible(False)
        root.addWidget(self._support_lbl)

        root.addStretch()

        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def _make_response_card(self, emoji, label, color, bg, hover, key):
        card = QPushButton()
        card.setFixedSize(220, 240)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                border: 2px solid {color};
                border-radius: 28px;
                font-family: '{FONT_DISPLAY}';
            }}
            QPushButton:hover {{
                background: {bg.replace('0.12', '0.22')};
                border: 2px solid {hover};
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        emoji_lbl = QLabel(emoji)
        emoji_lbl.setStyleSheet("font-size: 64px; background: transparent;")
        emoji_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_lbl = QLabel(label)
        text_lbl.setStyleSheet(
            f"color: {color}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 22px; font-weight: bold; background: transparent;"
        )
        text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(emoji_lbl)
        layout.addWidget(text_lbl)

        card.clicked.connect(lambda _, k=key: self._select(k))
        return card

    def _select(self, key: str):
        self._timer.stop()
        self.result = key
        # U2: hide the three choice cards and show a centred support message
        self._btn_row_widget.setVisible(False)
        self._countdown_lbl.setVisible(False)
        if key == "good":
            self._show_support_message(t("pain_msg_good"), delay_ms=1800)
        elif key == "tired":
            self._show_support_message(t("pain_msg_tired"), delay_ms=2200)
        else:
            self._show_support_message(t("pain_msg_pain"), delay_ms=3000)

    def _show_support_message(self, text: str, delay_ms: int = 2000):
        """U2: Show centred support message after selection, then close."""
        self._support_lbl.setText(text)
        self._support_lbl.setVisible(True)
        QTimer.singleShot(delay_ms, self.accept)

    def _show_pain_message(self):
        """Kept for legacy compatibility — now handled by _show_support_message."""
        self._show_support_message(
            "We'll go a little easier next time.\n"
            "Your therapist will see this in your next report.",
            delay_ms=3000
        )

    def _tick(self):
        self._countdown -= 1
        if self._countdown <= 0:
            self._timer.stop()
            self.accept()
        else:
            self._countdown_lbl.setText(
                t("pain_countdown", sec=self._countdown)
            )
