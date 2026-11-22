"""
WebGameWindow — fullscreen QWebEngineView for JS/HTML rehabilitation games.

Architecture:
  Python (GamepadThread) ──signal──▶ Bridge.direction_signal ──QWebChannel──▶ web_controller.js
  web_controller.js ──QWebChannel──▶ Bridge.quit_game() slot ──▶ close window

The JS controller (assets/web_controller.js) is injected at DocumentReady on every
page load, so no HTML files need to be modified on disk.
"""
import os
from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineScript, QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QObject, QUrl, QFile, QIODevice, Qt, pyqtSignal, pyqtSlot

_HERE = os.path.dirname(os.path.abspath(__file__))
_ASSETS = os.path.join(_HERE, "..", "assets")


class _Bridge(QObject):
    """
    Exposed to JavaScript via QWebChannel as 'bridge'.

    Python → JS : direction_signal  (str: 'up'|'down'|'left'|'right'|'action')
                  axes_signal       (float x, float y — continuous, ~30 Hz,
                                     processed values in [-1, 1]; JS holds/
                                     releases arrow keys from these)
    JS → Python : quit_game()  slot
    """
    direction_signal = pyqtSignal(str)
    axes_signal      = pyqtSignal(float, float)

    def __init__(self, window: "WebGameWindow"):
        super().__init__()
        self._window = window

    @pyqtSlot()
    def quit_game(self):
        """Called by JavaScript when the user activates the QUIT overlay."""
        self._window._do_quit()


class WebGameWindow(QMainWindow):
    """
    Fullscreen window that loads a local HTML game and injects the Solace
    web controller so keyboard/gamepad input is forwarded as KeyboardEvents.
    """
    game_finished = pyqtSignal()

    def __init__(self, index_html: str, game_data: dict, gamepad_thread,
                 player_name: str = "Player", parent=None):
        super().__init__(parent)
        self._gamepad      = gamepad_thread
        self._game_data    = game_data
        self._index_html   = index_html
        self._player_name  = player_name
        self._quit_done    = False

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        # ── WebEngine view ────────────────────────────────────────────────────
        self._view = QWebEngineView(self)
        self.setCentralWidget(self._view)

        # Allow local file access (needed for most standalone HTML games)
        settings = self._view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        # Trusted local rehab games: allow audio/video to play without a prior
        # user gesture (fixes "play() failed because the user didn't interact
        # with the document first" — the controller's synthetic key events
        # don't count as a gesture for the browser autoplay policy).
        try:
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        except AttributeError:
            pass  # older Qt without this attribute

        # ── QWebChannel bridge ────────────────────────────────────────────────
        self._bridge  = _Bridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)
        self._view.page().setWebChannel(self._channel)

        # ── Inject scripts (persistent — survive page navigations) ────────────
        self._inject_scripts()

        # ── Load the game ─────────────────────────────────────────────────────
        # Inject player name at DocumentCreation so games/web_controller can read it
        import json as _json
        # C2 fix: expose the game config (incl. adaptive difficulty) to the
        # page — web_controller.js and patched games read __solaceGameConfig.
        _cfg = dict(game_data.get("game_config", {}))
        if game_data.get("adaptive_difficulty") is not None:
            _cfg["difficulty_multiplier"] = game_data["adaptive_difficulty"]
        name_script = QWebEngineScript()
        name_script.setName("_solace_player_name")
        name_script.setSourceCode(
            f"window.__solacePlayerName = {_json.dumps(self._player_name)};\n"
            f"window.__solaceGameConfig = {_json.dumps(_cfg)};"
        )
        name_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        name_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        name_script.setRunsOnSubFrames(False)
        self._view.page().scripts().insert(name_script)

        self._view.load(QUrl.fromLocalFile(os.path.abspath(index_html)))

        # ── Connect gamepad ───────────────────────────────────────────────────
        # Discrete events: only 'action' (squeeze) is forwarded — arrow taps
        # from menu navigation are useless for gameplay (333 ms cooldown).
        self._gamepad.button_pressed.connect(self._on_gamepad_button)
        # Continuous analog axes → JS holds/releases keys like a real player.
        self._axes_tick = 0
        self._gamepad.raw_axes.connect(self._on_gamepad_axes)

    # ── Script injection ──────────────────────────────────────────────────────

    def _inject_scripts(self):
        page = self._view.page()

        # 1. qwebchannel.js — must be injected at DocumentCreation so that
        #    'qt.webChannelTransport' exists when our controller runs.
        qwc_content = self._read_qt_resource(":/qtwebchannel/qwebchannel.js")
        if qwc_content:
            s = QWebEngineScript()
            s.setName("_solace_qwebchannel")
            s.setSourceCode(qwc_content)
            s.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            s.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            s.setRunsOnSubFrames(False)
            page.scripts().insert(s)
        else:
            print("[WebGameWindow] WARNING: could not load qwebchannel.js from Qt resources")

        # 2. web_controller.js — inject at DocumentReady (DOM exists, scripts not yet run)
        ctrl_path = os.path.join(_ASSETS, "web_controller.js")
        if os.path.exists(ctrl_path):
            with open(ctrl_path, "r", encoding="utf-8") as f:
                ctrl_content = f.read()
            s2 = QWebEngineScript()
            s2.setName("_solace_web_controller")
            s2.setSourceCode(ctrl_content)
            s2.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
            s2.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            s2.setRunsOnSubFrames(False)
            page.scripts().insert(s2)
        else:
            print(f"[WebGameWindow] WARNING: web_controller.js not found at {ctrl_path}")

    @staticmethod
    def _read_qt_resource(path: str) -> str | None:
        f = QFile(path)
        if not f.open(QIODevice.OpenModeFlag.ReadOnly):
            return None
        content = f.readAll().data().decode("utf-8", errors="replace")
        f.close()
        return content

    # ── Gamepad → JS bridge ───────────────────────────────────────────────────

    def _on_gamepad_button(self, direction: str, is_hover: bool):
        """Forward only the squeeze/action to JS — movement comes from the
        continuous axes stream. Hover-stillness 'action' is ignored so
        holding still mid-game can't fire spurious Space presses."""
        if direction == "action" and not is_hover:
            self._bridge.direction_signal.emit(direction)

    def _on_gamepad_axes(self, x: float, y: float):
        """Stream processed axes to JS at ~30 Hz (gamepad polls at 60)."""
        self._axes_tick ^= 1
        if self._axes_tick:
            return
        try:
            nx, ny, _ = self._gamepad.processor.process(x, y, apply_deadzone=False)
        except Exception:
            nx, ny = x, y
        # Pron/sup (x) reads inverted relative to game direction convention —
        # turning the wrist right was driving left in-game. Menu navigation uses
        # the same axis correctly, so we flip ONLY the in-game feed here.
        self._bridge.axes_signal.emit(-nx, ny)

    # ── Quit flow ─────────────────────────────────────────────────────────────

    def _do_quit(self):
        if self._quit_done:
            return
        self._quit_done = True
        try:
            self._gamepad.button_pressed.disconnect(self._on_gamepad_button)
        except RuntimeError:
            pass
        try:
            self._gamepad.raw_axes.disconnect(self._on_gamepad_axes)
        except RuntimeError:
            pass
        # Tear the page down so the game (and its AUDIO) actually stops. Just
        # closing the window leaves the QWebEngineView's render process alive,
        # so music kept playing. Mute immediately, halt loading, then navigate
        # to a blank page to unload the game's scripts/audio contexts.
        try:
            page = self._view.page()
            page.setAudioMuted(True)
            self._view.stop()
            self._view.setUrl(QUrl("about:blank"))
        except Exception:
            pass
        self.close()

    def closeEvent(self, event):
        self._do_quit()          # safe to call twice — guarded by flag
        # Explicitly delete the web view so its render process is reclaimed and
        # can't keep audio/timers running after the window is gone.
        try:
            self._view.setParent(None)
            self._view.deleteLater()
        except Exception:
            pass
        self.game_finished.emit()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        """Escape key also exits — useful for dev/testing."""
        if event.key() == Qt.Key.Key_Escape:
            self._do_quit()
        else:
            super().keyPressEvent(event)
