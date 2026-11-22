"""
CalibrationBanner — a soft orange nudge shown on the Play page until the
patient has a movement baseline. Dismissable for the session. The Calibrate
button opens the calibration step full screen and saves the result as the
baseline.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QDialog,
    QApplication,
)

from core import theme as _t
from ui import glass as _g
from ui.glass import PillButton


class CalibrationBanner(QWidget):
    changed = pyqtSignal()          # shown or hidden: the page re-fits the featured card

    def __init__(self, session_manager, parent=None):
        super().__init__(parent)
        self.session_manager = session_manager
        self._dismissed = False
        self.setVisible(False)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._build_card())

    def _build_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("calBanner")
        fill, edge = (("rgba(255,154,77,0.16)", "rgba(255,154,77,0.40)") if _g.is_dark()
                      else ("rgba(255,178,107,0.30)", "rgba(194,72,10,0.35)"))
        card.setStyleSheet(
            f"QFrame#calBanner {{ background: {fill};"
            f" border: 1px solid {edge}; border-radius: 28px; }}"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(26, 16, 18, 16)
        row.setSpacing(18)

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
            f"QPushButton:hover {{ background: {_g.tint(0.08)}; color: {_t.ON_SURFACE}; }}"
        )
        dismiss.clicked.connect(self._dismiss)
        row.addWidget(dismiss)
        return card

    # ── state ────────────────────────────────────────────────────────────────
    def set_session_manager(self, sm) -> None:
        self.session_manager = sm
        self.refresh()

    def refresh(self) -> None:
        """Show when there is no baseline, hide once there is one or dismissed."""
        if self._dismissed:
            return
        show = not self.session_manager.has_baseline()
        if show != (not self.isHidden()):
            self.setVisible(show)
            self.changed.emit()

    def _dismiss(self) -> None:
        self._dismissed = True
        self.setVisible(False)
        self.changed.emit()

    def _open_calibration(self) -> None:
        """Run the calibration step as a standalone full-screen dialog."""
        from ui.onboarding import _StepCalibration

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
            self.setVisible(False)
            self.changed.emit()

        cal.completed.connect(_on_done)
        layout.addWidget(cal)
        dlg.exec()
