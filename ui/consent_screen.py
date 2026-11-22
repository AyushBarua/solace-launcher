"""
ConsentScreen — shown on first launch before any patient data is written.
Clearly explains what data is stored and how it is used.
Patient must actively accept before proceeding.
"""
import sys
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGraphicsDropShadowEffect, QApplication
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor, QFont

from core.theme import (
    FONT_DISPLAY, FONT_BODY, ON_SURFACE, ON_SURFACE_VAR,
    PRIMARY, ON_PRIMARY, PRIMARY_CONTAINER, PRIMARY_FIXED, SURFACE_DIM,
    OUTLINE_VARIANT, ON_PRIMARY_FIXED_VARIANT, SURFACE_CON, SURFACE_CON_LOW
)
from core.session_manager import SessionManager
from ui import glass as _g


class _BulletRow(QWidget):
    """A single icon + text row for the data points list."""
    def __init__(self, icon: str, title: str, desc: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # No emoji: a slim accent bar marks each point (the `icon` argument is ignored).
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(5, 40)
        icon_lbl.setStyleSheet(f"background: {PRIMARY_CONTAINER}; border-radius: 2px;")

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 16px; font-weight: bold; background: transparent;"
        )
        d = QLabel(desc)
        d.setStyleSheet(
            f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; "
            f"font-size: 13px; background: transparent;"
        )
        d.setWordWrap(True)
        text_col.addWidget(t)
        text_col.addWidget(d)

        layout.addWidget(icon_lbl)
        layout.addLayout(text_col, stretch=1)


class ConsentScreen(QDialog):
    """
    Full-screen privacy consent dialog.
    Must be accepted before any session data is written.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Solace — Data & Privacy")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Size to screen
        screen = QApplication.primaryScreen().availableGeometry()
        self.setFixedSize(screen.width(), screen.height())

        # Dark full-screen backdrop
        bg = QWidget(self)
        bg.setGeometry(0, 0, screen.width(), screen.height())
        bg.setStyleSheet("background: rgba(0,0,0,0.85);")

        # Centred card
        card_w, card_h = 720, 640
        card = QFrame(self)
        card.setGeometry(
            (screen.width() - card_w) // 2,
            (screen.height() - card_h) // 2,
            card_w, card_h
        )
        card.setObjectName("consentCard")
        card.setStyleSheet(f"""
            QFrame#consentCard {{
                background: {_g.solid_pane()};
                border: 1px solid {OUTLINE_VARIANT};
                border-radius: 32px;
            }}
        """)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(80)
        shadow.setColor(QColor(0, 0, 0, 70))
        shadow.setOffset(0, 12)
        card.setGraphicsEffect(shadow)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(56, 48, 56, 48)
        layout.setSpacing(0)

        # ── Badge ──────────────────────────────────────────────────────────────
        badge = QLabel("YOUR PRIVACY")
        badge.setFixedWidth(160)
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
        layout.addWidget(badge)
        layout.addSpacing(20)

        # ── Heading ───────────────────────────────────────────────────────────
        title = QLabel("Your data stays with you.")
        title.setStyleSheet(
            f"color: {ON_SURFACE}; font-family: '{FONT_DISPLAY}'; "
            f"font-size: 36px; font-weight: bold; background: transparent;"
        )
        layout.addWidget(title)
        layout.addSpacing(8)

        subtitle = QLabel(
            "Solace stores your therapy data locally on this device only. "
            "Nothing is sent to the internet without your action."
        )
        subtitle.setStyleSheet(
            f"color: {ON_SURFACE_VAR}; font-family: '{FONT_BODY}'; "
            f"font-size: 16px; background: transparent; line-height: 1.5;"
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(32)

        # ── Data points ───────────────────────────────────────────────────────
        data_frame = QFrame()
        data_frame.setObjectName("consentData")   # scoped: a bare rule would box every child label
        data_frame.setStyleSheet(
            f"QFrame#consentData {{ background: {SURFACE_CON_LOW}; border-radius: 18px;"
            f" border: 1px solid {OUTLINE_VARIANT}; }}"
        )
        data_layout = QVBoxLayout(data_frame)
        data_layout.setContentsMargins(24, 20, 24, 20)
        data_layout.setSpacing(16)

        points = [
            ("🏋️", "Movement data",
             "Your daily range-of-motion readings — stored on this device only."),
            ("📅", "Session history",
             "Which games you played, for how long, and at what difficulty."),
            ("💊", "Wellbeing check-ins",
             "How you felt after each session (Good / Tired / Pain)."),
            ("📄", "Progress reports",
             "Only shared when YOU tap 'Download Report' and save or send the PDF."),
        ]
        for icon, title_txt, desc_txt in points:
            data_layout.addWidget(_BulletRow(icon, title_txt, desc_txt))

        layout.addWidget(data_frame)
        layout.addSpacing(28)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)

        exit_btn = QPushButton("Exit")
        exit_btn.setFixedHeight(52)
        exit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        exit_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {ON_SURFACE_VAR};
                border: 1px solid {OUTLINE_VARIANT};
                border-radius: 26px;
                padding: 0 32px;
                font-family: '{FONT_DISPLAY}';
                font-size: 16px;
            }}
            QPushButton:hover {{
                background: {SURFACE_DIM};
                border: 1px solid {ON_SURFACE_VAR};
            }}
        """)
        exit_btn.clicked.connect(self._on_exit)

        agree_btn = QPushButton("  I Understand && Agree  →")     # && shows a literal ampersand
        agree_btn.setFixedHeight(52)
        agree_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        agree_btn.setStyleSheet(f"""
            QPushButton {{
                background: {PRIMARY};
                color: {ON_PRIMARY};
                border: none;
                border-radius: 26px;
                padding: 0 40px;
                font-family: '{FONT_DISPLAY}';
                font-size: 17px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {_g.hover_ink()};
            }}
        """)
        agree_btn.clicked.connect(self._on_agree)

        btn_row.addWidget(exit_btn)
        btn_row.addStretch()
        btn_row.addWidget(agree_btn)
        layout.addLayout(btn_row)

    def _on_agree(self):
        SessionManager.save_consent()
        self.accept()

    def _on_exit(self):
        self.reject()
        sys.exit(0)
