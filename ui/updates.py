"""
ui/updates.py

UpdateController: runs the update check and download on a background thread and
reports progress with one signal, so any widget can follow it.

UpdateToast: the small dark notice that rises from the bottom of the window when
an update is available, while it downloads, or if it fails. "Later" hides it for
that version until the next start.
"""
from __future__ import annotations

import os
import threading

from PyQt6.QtCore import (
    QEasingCurve, QEvent, QObject, QPropertyAnimation, QRectF, Qt, pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QWidget,
)

from core import updater
from core.version import __version__

IDLE, CHECKING, UP_TO_DATE, AVAILABLE, DOWNLOADING, READY, FAILED = range(7)

TOAST_HEIGHT = 56
TOAST_BOTTOM_GAP = 28
FADE_IN_MS, FADE_OUT_MS = 180, 240        # same timings as the window tab


def downloads_dir() -> str:
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), "updates")


def clear_old_downloads() -> None:
    """Remove an installer left over from an earlier update. Never raises."""
    for name in (updater.INSTALLER_NAME, updater.INSTALLER_NAME + ".part"):
        try:
            os.remove(os.path.join(downloads_dir(), name))
        except OSError:
            pass


class UpdateController(QObject):
    changed = pyqtSignal()            # state, info, progress or error changed
    quit_requested = pyqtSignal()     # the installer is running; Solace should close

    _check_finished = pyqtSignal(object, str)
    _download_progress = pyqtSignal(int, int)
    _download_finished = pyqtSignal(str, str)

    def __init__(self, current: str = __version__, parent=None):
        super().__init__(parent)
        self.current = current
        self.state = IDLE
        self.info = None
        self.progress = 0.0
        self.error = ""
        self._check_finished.connect(self._on_check_finished)
        self._download_progress.connect(self._on_progress)
        self._download_finished.connect(self._on_download_finished)
        clear_old_downloads()

    # ── Actions ───────────────────────────────────────────────────────────────
    def check(self) -> None:
        if self.state in (CHECKING, DOWNLOADING, READY):
            return
        self._set(CHECKING)
        threading.Thread(target=self._run_check, daemon=True).start()

    def install(self) -> None:
        """Download the new installer, then run it and ask Solace to close."""
        if self.state not in (AVAILABLE, FAILED) or self.info is None:
            return
        self.progress = 0.0
        self._set(DOWNLOADING)
        threading.Thread(target=self._run_download, args=(self.info,), daemon=True).start()

    # ── Background work ───────────────────────────────────────────────────────
    def _run_check(self) -> None:
        try:
            info, error = updater.check_for_update(self.current), ""
        except updater.UpdateError as exc:
            info, error = None, str(exc)
        self._check_finished.emit(info, error)

    def _run_download(self, info) -> None:
        try:
            path = updater.download_installer(
                info, downloads_dir(),
                progress=lambda done, total: self._download_progress.emit(done, total))
            error = ""
        except updater.UpdateError as exc:
            path, error = "", str(exc)
        self._download_finished.emit(path, error)

    # ── Back on the interface thread ──────────────────────────────────────────
    def _on_check_finished(self, info, error: str) -> None:
        self.info = info
        self.error = error
        self._set(FAILED if error else AVAILABLE if info else UP_TO_DATE)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress = (done / total) if total else 0.0
        self.changed.emit()

    def _on_download_finished(self, path: str, error: str) -> None:
        if error:
            self.error = error
            self._set(FAILED)
            return
        try:
            updater.launch_installer(path)
        except OSError as exc:
            self.error = f"could not start the installer: {exc}"
            self._set(FAILED)
            return
        self._set(READY)
        self.quit_requested.emit()

    def _set(self, state: int) -> None:
        self.state = state
        self.changed.emit()

    # ── Wording ───────────────────────────────────────────────────────────────
    def status_text(self) -> str:
        version = self.info.version if self.info else ""
        return {
            IDLE: f"Version {self.current}",
            CHECKING: "Checking for updates...",
            UP_TO_DATE: f"Version {self.current}. You have the latest version.",
            AVAILABLE: f"Version {version} is available. You have {self.current}.",
            DOWNLOADING: f"Downloading version {version}: {int(self.progress * 100)}%",
            READY: "Starting the installer...",
            FAILED: f"The update did not work: {self.error}",
        }[self.state]


class UpdateToast(QWidget):
    """Dark pill at the bottom centre of its parent window."""

    def __init__(self, controller: UpdateController, parent: QWidget):
        super().__init__(parent)
        self._controller = controller
        self._dismissed_version = ""
        self._shown = False

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._after_fade)

        self._label = QLabel(self)
        self._action = QPushButton(self)
        self._later = QPushButton("Later", self)
        for button in (self._action, self._later):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setFixedHeight(36)
        self._action.clicked.connect(self._on_action)
        self._later.clicked.connect(self._on_later)

        row = QHBoxLayout(self)
        row.setContentsMargins(26, 0, 10, 0)
        row.setSpacing(10)
        row.addWidget(self._label)
        row.addWidget(self._action)
        row.addWidget(self._later)

        controller.changed.connect(self._refresh)
        parent.installEventFilter(self)
        self.hide()

    # ── Behaviour ─────────────────────────────────────────────────────────────
    def _wanted(self) -> bool:
        c = self._controller
        if c.state == DOWNLOADING or c.state == FAILED and c.info is not None:
            return True
        return c.state == AVAILABLE and c.info.version != self._dismissed_version

    def _on_action(self) -> None:
        self._controller.install()

    def _on_later(self) -> None:
        c = self._controller
        if c.info is not None:
            self._dismissed_version = c.info.version
        self._refresh()

    def _refresh(self) -> None:
        c = self._controller
        want = self._wanted()
        if want:
            version = c.info.version
            if c.state == AVAILABLE:
                text, action = f"Solace {version} is available", "Install"
            elif c.state == DOWNLOADING:
                text, action = f"Downloading Solace {version}: {int(c.progress * 100)}%", ""
            else:
                text, action = "The update did not work", "Try again"
            self._label.setText(text)
            self._action.setText(action)
            self._action.setVisible(bool(action))
            self._later.setVisible(c.state != DOWNLOADING)
            self._style()
            self.adjustSize()
            self.setFixedHeight(TOAST_HEIGHT)
            self.reposition()
        self._fade_to(want)

    def _fade_to(self, visible: bool) -> None:
        if visible == self._shown:
            return
        self._shown = visible
        self._fade.stop()
        self._fade.setDuration(FADE_IN_MS if visible else FADE_OUT_MS)
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(1.0 if visible else 0.0)
        if visible:
            self.show()
            self.raise_()
        self._fade.start()

    def _after_fade(self) -> None:
        if not self._shown:
            self.hide()

    # ── Looks ─────────────────────────────────────────────────────────────────
    def _style(self) -> None:
        import core.theme as _t
        self._label.setStyleSheet(
            f"color:{_t.ON_PRIMARY}; font-family:'{_t.FONT_DISPLAY}'; font-size:16px;"
            f" font-weight:600; background:transparent;")
        self._action.setStyleSheet(
            f"QPushButton {{ background:{_t.ON_PRIMARY}; color:{_t.PRIMARY};"
            f" font-family:'{_t.FONT_DISPLAY}'; font-size:15px; font-weight:bold;"
            f" border:none; border-radius:18px; padding:0 20px; }}")
        self._later.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{_t.ON_PRIMARY};"
            f" font-family:'{_t.FONT_DISPLAY}'; font-size:15px; font-weight:600;"
            f" border:none; border-radius:18px; padding:0 16px; }}"
            f"QPushButton:hover {{ background:rgba(255,255,255,0.12); }}")

    def paintEvent(self, _event) -> None:
        import core.theme as _t
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_t.PRIMARY))
        p.drawRoundedRect(QRectF(self.rect()), self.height() / 2, self.height() / 2)
        p.end()

    # ── Placement ─────────────────────────────────────────────────────────────
    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.move((parent.width() - self.width()) // 2,
                  parent.height() - self.height() - TOAST_BOTTOM_GAP)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self._shown:
            self.reposition()
        return False
