import sys
import os
import json

# ── Frozen (PyInstaller) WebEngine path setup ─────────────────────────────────
# Must happen BEFORE any PyQt6 import so Qt finds its helper process & resources.
if getattr(sys, 'frozen', False):
    _mp = sys._MEIPASS
    _webengine_exe = os.path.join(_mp, 'PyQt6', 'Qt6', 'bin', 'QtWebEngineProcess.exe')
    if os.path.exists(_webengine_exe):
        os.environ['QTWEBENGINEPROCESS_PATH'] = _webengine_exe
    os.environ.setdefault('QTWEBENGINE_RESOURCES_PATH',
                          os.path.join(_mp, 'PyQt6', 'Qt6', 'resources'))
    os.environ.setdefault('QTWEBENGINE_LOCALES_PATH',
                          os.path.join(_mp, 'PyQt6', 'Qt6', 'translations', 'qtwebengine_locales'))
# ─────────────────────────────────────────────────────────────────────────────

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QStackedWidget, QGraphicsView, QGraphicsScene, QFrame
)
from PyQt6.QtGui import QFontDatabase, QPainter
from PyQt6.QtCore import Qt

from core.theme import APP_QSS, FONT_DISPLAY, get_ui_scale
from core.game_manager import GameManager
from core.controller import GamepadThread
from core.input_processor import InputProcessor
from core.session_manager import SessionManager
from core.profile_manager import get_active_profile
from ui.top_bar import TopBar, TOP_BAR_HEIGHT
from ui.nav_pill import NavPill
from ui.glass import GlassBackground
from ui.play_page import PlayPage
from ui.settings_page import SettingsPage
from ui.progress_page import ProgressPage
from ui.login_screen import LoginScreen
from core import app_flags

def get_settings_path():
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), "global_settings.json")


class ScalableContentView(QGraphicsView):
    """
    Wraps the main content widget in a QGraphicsScene and applies a
    real-time scale transform so the entire UI scales without restarting.
    """
    def __init__(self, content_widget: QWidget, parent=None):
        super().__init__(parent)
        self._content = content_widget
        self._scale   = 1.0

        scene = QGraphicsScene(self)
        self._proxy = scene.addWidget(content_widget)
        self.setScene(scene)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QGraphicsView { background: transparent; border: none; }")
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

    def set_scale(self, factor: float):
        self._scale = max(0.5, factor)
        self.resetTransform()
        self.scale(self._scale, self._scale)
        self._sync_size()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_size()

    def _sync_size(self):
        """Size the content widget to viewport / scale so after transform it fills exactly."""
        vw = self.viewport().width()
        vh = self.viewport().height()
        w  = max(1, int(vw / self._scale))
        h  = max(1, int(vh / self._scale))
        self._content.setFixedSize(w, h)
        self.scene().setSceneRect(0, 0, w, h)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Solace")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.resize(1600, 900)

        
        # Intercept ALL key events globally to prevent child widgets from eating arrows
        QApplication.instance().installEventFilter(self)
        
        # We handle our own background drawing or stylesheet
        self.setStyleSheet(APP_QSS)
        
        # ── Active profile & session manager ──────────────────────────────────
        self._active_profile = get_active_profile() or {}
        self._session_manager = SessionManager(
            self._active_profile.get("id", "default")
        )
        self._active_session = None   # set when a game launches
        self._apply_patient_limits()  # push this patient's ROM to the controller

        # ── Services ──────────────────────────────────────────────────────────
        self.game_manager = GameManager(self)
        self.game_manager.game_finished.connect(self._on_game_finished)
        self.game_manager.game_not_started.connect(self._on_game_not_started)
        self.game_manager.download_finished.connect(self._on_download_finished)
        self.game_manager.web_game_requested.connect(self._on_web_game_requested)
        
        # ── Input pipeline ────────────────────────────────────────────────────
        # H3 fix: input settings (flips, sensitivity, dead-zone…) are per-profile
        self.input_processor = InputProcessor(
            self._active_profile.get("id", "default"))
        
        # ── Main layout ───────────────────────────────────────────────────────
        central = GlassBackground()          # paper colour plus soft colour haze
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        # One grid cell holds both layers: the pages fill the window and the top bar
        # floats over them, so the Play tab's art can run edge to edge behind it.
        root_layout = QGridLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        
        # 1. Top Bar — shows active profile
        self.top_bar = TopBar(active_profile=self._active_profile)
        self.top_bar.profile_clicked.connect(self._open_profiles)
        # §6 SECURITY: with login on, every switch goes through the authenticated
        # login flow. With login off (app_flags.REQUIRE_LOGIN) the profile page switches
        # directly, still asking for the profile's PIN when it has one.

        # 2. Main Content Area — real-time scalable via QGraphicsView transform
        inner_col = QWidget()
        inner_col.setStyleSheet("background: transparent;")
        inner_layout = QVBoxLayout(inner_col)
        inner_layout.setContentsMargins(0, 0, 0, 0)     # the top inset is set per tab (_sync_chrome)
        inner_layout.setSpacing(0)
        self._inner_layout = inner_layout

        self.stack = QStackedWidget()

        # ── Updates: background checks, and the notice shown when one is ready ──
        from ui.updates import UpdateController
        self.updates = UpdateController(parent=self)
        self.updates.quit_requested.connect(self.close)     # the installer is running

        # ── Pages (3-tab nav) ─────────────────────────────────────────────────
        self._create_pages()

        self.stack.addWidget(self.play_page)         # 0 — Play
        self.stack.addWidget(self.progress_page)     # 1 — Progress
        self.stack.addWidget(self.settings_page)     # 2 — Settings

        inner_layout.addWidget(self.stack)

        # Wrap in scalable view and apply saved scale
        self._content_view = ScalableContentView(inner_col)
        self._content_view.set_scale(get_ui_scale())
        
        # Create a container so the bottom nav floats OVER the content
        content_container = QWidget()
        content_layout = QGridLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._content_view, 0, 0)
        
        # 3. Navigation pill — lives in the centre of the top bar
        self.nav_pill = NavPill()
        self.nav_pill.tab_changed.connect(self.on_tab_changed)
        self.top_bar.set_center_widget(self.nav_pill)

        # Live language refresh — update all pages when user switches language
        from core.i18n import i18n as _i18n
        _i18n.language_changed.connect(lambda _: self.nav_pill.refresh_language())
        _i18n.language_changed.connect(lambda _: self.play_page.refresh_language())

        root_layout.addWidget(content_container, 0, 0)
        root_layout.addWidget(self.top_bar, 0, 0, Qt.AlignmentFlag.AlignTop)
        self.top_bar.raise_()
        self._root_layout = root_layout
        self._make_profile_overlay()          # the "Who's Playing?" page, over everything
        from ui.updates import UpdateToast
        self.update_toast = UpdateToast(self.updates, self.centralWidget())

        # Default to Play
        self.stack.setCurrentIndex(0)
        self._sync_chrome(0)
        
        # Controller Integration State
        self.is_controller_connected = False
        self.current_controller_name = "KEYBOARD"

        # Controller integration
        self.gamepad = GamepadThread(self.input_processor, self)
        self.gamepad.controller_state.connect(self._on_controller_state)
        self.gamepad.button_pressed.connect(self.handle_gamepad_action)
        self.gamepad.hover_progress.connect(self.handle_gamepad_hover)
        self.gamepad.raw_axes.connect(self._on_raw_axes)
        self.gamepad.start()
        
        # ── Per-page navigation state ──────────────────────────────────────────
        self.gamepad_active = False
        # True while controller focus is on the tab bar (reached by pressing up
        # from the first row of the Play page): left/right then switch tabs.
        self._nav_focus = False

        # F2: Keyboard shortcuts for tab navigation (Ctrl+1–3)
        from PyQt6.QtGui import QShortcut, QKeySequence
        for tab_num in range(1, 4):
            sc = QShortcut(QKeySequence(f"Ctrl+{tab_num}"), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(lambda n=tab_num - 1: self._switch_tab(n))
        # Ctrl+W: open warmup from anywhere
        sc_warmup = QShortcut(QKeySequence("Ctrl+W"), self)
        sc_warmup.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_warmup.activated.connect(self._open_warmup_standalone)

        # First launch for this profile: run the movement assessment once the
        # window is up and the gamepad thread has had time to detect the device.
        # Second check at 8 s covers slow controller enumeration.
        from PyQt6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(2500, self._maybe_first_assessment)
        _QTimer.singleShot(8000, self._maybe_first_assessment)
        _QTimer.singleShot(6000, self._check_for_updates_on_start)

    def _check_for_updates_on_start(self) -> None:
        """Look for a newer release once after start-up, if installed and switched on."""
        from core import updater
        if updater.should_check_on_start(updater.load_settings()):
            self.updates.check()

    # ── Page construction (also used to rebuild pages on a live theme switch) ──

    def _create_pages(self):
        """Build the three tab pages and wire their signals.

        Uses the module-level page classes, which _rebuild_for_theme() rebinds to
        freshly reloaded versions so new pages pick up the active theme colours.
        """
        # Tab 0: Play — featured game, then rows of games to play or download
        self.play_page = PlayPage(self.game_manager, self._session_manager)
        self.play_page.game_launch_requested.connect(self._launch_game_by_id)
        self.play_page.download_requested.connect(self._on_store_download)
        self.play_page.art_state_changed.connect(
            lambda _on: self._sync_chrome(self.stack.currentIndex()))
        # U1: show failed state on download error
        self.game_manager.download_failed.connect(self.play_page.mark_failed)

        # Tab 1: Progress
        self.progress_page = ProgressPage(
            session_manager=self._session_manager,
            profile=self._active_profile,
        )

        # Tab 2: Settings
        # (Report Lab page removed from the nav by request — PDF reports are
        #  generated from the Progress page / report_generator as before.
        #  ui/report_lab_page.py is kept on disk if it's ever wanted back.)
        self.settings_page = SettingsPage(processor=self.input_processor)
        # "Redo assessment" button on the settings page
        try:
            self.settings_page.input_card.assessment_requested.connect(
                self._open_assessment)
        except AttributeError:
            pass
        self.settings_page.bind_updates(self.updates)

    def _rebuild_for_theme(self):
        """Reload every module that bakes theme colours at import, then rebuild
        the three pages from the fresh classes. Keeps the current tab."""
        import importlib
        global PlayPage, ProgressPage, SettingsPage, LoginScreen

        # Dependency order: glass first, play_tiles before play_page.
        first = ["ui.glass", "ui.play_tiles"]
        names = [n for n in sys.modules
                 if (n.startswith("ui.") or n == "core.milestone_manager")
                 and n not in first]
        for name in first + sorted(names):
            mod = sys.modules.get(name)
            if mod is None:
                continue
            try:
                importlib.reload(mod)
            except Exception as exc:                      # keep the old module; never crash a theme switch
                print(f"[theme] could not reload {name}: {exc}")

        PlayPage = sys.modules["ui.play_page"].PlayPage
        ProgressPage = sys.modules["ui.progress_page"].ProgressPage
        SettingsPage = sys.modules["ui.settings_page"].SettingsPage
        LoginScreen = sys.modules["ui.login_screen"].LoginScreen

        current = self.stack.currentIndex()
        old_pages = [self.play_page, self.progress_page, self.settings_page]
        self._create_pages()
        new_pages = [self.play_page, self.progress_page, self.settings_page]
        for idx, (old, new) in enumerate(zip(old_pages, new_pages)):
            self.stack.removeWidget(old)
            old.deleteLater()
            self.stack.insertWidget(idx, new)
        self.stack.setCurrentIndex(current)
        self._sync_chrome(current)
        self._make_profile_overlay()

    def _sync_chrome(self, idx: int) -> None:
        """Fit the floating top bar to the current tab.

        Play runs its art behind the bar, so it gets no inset and the bar turns
        light-on-dark while it is over the art. Every other tab starts below the bar.
        """
        if not hasattr(self, "_content_view") or not hasattr(self, "top_bar"):
            return                                    # still being built
        scale = max(0.1, self._content_view._scale)
        inset = 0 if idx == 0 else int(TOP_BAR_HEIGHT / scale) + 16
        self._inner_layout.setContentsMargins(0, inset, 0, 0)
        self.top_bar.set_on_art(idx == 0 and self.play_page.over_art())

    # ── Real-time UI scale ────────────────────────────────────────────────────

    def set_ui_scale(self, scale: float):
        """Called by the Interface Scale slider to scale the whole UI in real time."""
        self._content_view.set_scale(scale)
        self._sync_chrome(self.stack.currentIndex())

    # ── Theme refresh ─────────────────────────────────────────────────────────

    def apply_theme_live(self, theme_name: str):
        from PyQt6.QtWidgets import QLabel, QGraphicsOpacityEffect, QApplication
        from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
        from core.theme import generate_app_qss, BACKGROUND
        # Guard against rapid re-triggering while the fade is still running
        if getattr(self, '_theme_anim', None) and \
                self._theme_anim.state() == QPropertyAnimation.State.Running:
            return

        snapshot = self.grab()
        QApplication.instance().setStyleSheet(generate_app_qss(theme_name))
        self.centralWidget().update()        # GlassBackground repaints from the new tokens
        self.top_bar.refresh_theme()
        self.nav_pill.refresh_theme()
        # Pages bake colours when built, so rebuild them from reloaded modules.
        self._rebuild_for_theme()

        overlay = QLabel(self)
        overlay.setPixmap(snapshot)
        overlay.setGeometry(self.rect())
        overlay.raise_()
        overlay.show()

        effect = QGraphicsOpacityEffect()
        effect.setOpacity(1.0)
        overlay.setGraphicsEffect(effect)

        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(600)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(overlay.deleteLater)
        anim.start()

        overlay._anim   = anim
        overlay._effect = effect
        self._theme_anim = anim   # track for re-entry guard

    # ── Profile switching ─────────────────────────────────────────────────────

    def _make_profile_overlay(self) -> None:
        """(Re)build the profile page panel; rebuilt on a theme switch so it takes the new colours."""
        from ui.profile_overlay import ProfileOverlay
        old = getattr(self, "profile_overlay", None)
        if old is not None:
            self._root_layout.removeWidget(old)
            old.setParent(None)
            old.deleteLater()
        self.profile_overlay = ProfileOverlay(self.centralWidget())
        self.profile_overlay.profile_chosen.connect(self._switch_to_profile)
        self._root_layout.addWidget(self.profile_overlay, 0, 0)
        self.profile_overlay.hide()

    def _open_profiles(self) -> None:
        """The avatar was clicked: the sign-in flow (login on) or the profile page panel."""
        if app_flags.REQUIRE_LOGIN:
            self._switch_profile()
        elif self.profile_overlay.is_open():
            self.profile_overlay.close_overlay()
        else:                                   # also while it is closing: turn it back round
            self.profile_overlay.open((self._active_profile or {}).get("id"))

    def _switch_profile(self):
        """Back to profile selection: the sign-in screen (login on), or the profile page panel."""
        if not app_flags.REQUIRE_LOGIN:
            if not self.profile_overlay.is_open():
                self.profile_overlay.open((self._active_profile or {}).get("id"))
            return
        self.hide()
        # L6: clear the current session token before re-authenticating
        from core.session_store import clear_session
        clear_session()
        screen = LoginScreen(parent=None)
        screen.login_successful.connect(
            lambda user: self._on_profile_selected(get_active_profile()))
        screen.exec()
        self.show()

    def _on_quick_switch(self, profile: dict):
        """Profile dropdown in the top bar."""
        if app_flags.REQUIRE_LOGIN:
            self._switch_profile()
        else:
            self._switch_to_profile(profile)

    def _switch_to_profile(self, profile: dict):
        """Make `profile` the active one (asking for its PIN first, if it has one)."""
        if profile.get("id") == (self._active_profile or {}).get("id"):
            return
        if not self._pin_ok(profile):
            return
        self._on_profile_selected(profile)

    @staticmethod
    def _pin_ok(profile: dict) -> bool:
        """True when the profile has no PIN or the right one is typed within 3 tries."""
        pin = profile.get("pin")
        if not pin:
            return True
        from PyQt6.QtWidgets import QInputDialog
        for _ in range(3):
            val, ok = QInputDialog.getText(None, "Profile Locked",
                                           f"Enter {profile.get('name', 'this profile')}'s 4-digit PIN:")
            if not ok:
                return False
            if val == pin:
                return True
        return False

    def _on_profile_selected(self, profile: dict):
        from core.profile_manager import set_active_profile
        set_active_profile(profile)
        self._active_profile = profile
        self._session_manager = SessionManager(profile.get("id", "default"))
        self.top_bar.set_profile(profile)
        self._apply_patient_limits()
        # C1 fix: Play (its recommendation) must follow the new profile too
        # (Progress is rebuilt below; it was once left on the previous patient).
        self.play_page.set_session_manager(self._session_manager)
        # H3 fix: switch to this patient's input settings
        self.input_processor.set_profile(profile.get("id", "default"))
        # Rebuild progress page for new profile
        new_progress = ProgressPage(
            session_manager=self._session_manager,
            profile=self._active_profile,
        )
        self.stack.removeWidget(self.progress_page)
        self.progress_page.deleteLater()
        self.progress_page = new_progress
        self.stack.insertWidget(1, self.progress_page)
        # Onboarding for profiles created at RUNTIME (sign-up after logout) —
        # previously it only ran at app startup, so runtime sign-ups skipped
        # the welcome/device/learn flow entirely.
        from ui.onboarding import should_show_onboarding, OnboardingFlow
        if should_show_onboarding(profile.get("id", "default")):
            self._warmup_open = True     # lock controller nav behind the dialog
            try:
                onboarding = OnboardingFlow(
                    profile=profile,
                    session_manager=self._session_manager,
                    # Reuse the running gamepad thread for device detection —
                    # onboarding's own poller re-inits pygame's joystick
                    # subsystem and hard-crashes the app at runtime.
                    gamepad=self.gamepad,
                    connected_name=(self.current_controller_name
                                    if self.is_controller_connected else None),
                )
                onboarding.exec()
            finally:
                self._warmup_open = False

        # After sign-up / login always land on HOME (not whatever tab Log Out
        # was pressed from — usually Settings). Exception as requested.
        self._switch_tab(0)

        # New profile might not have a baseline yet → assess
        self._assessment_prompted = False   # fresh chance for the new profile
        from PyQt6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(800, self._maybe_first_assessment)


    # ── First-launch movement assessment ──────────────────────────────────────

    def _maybe_first_assessment(self):
        """On first launch for a profile (no baseline), run the assessment.
        Only auto-opens when a controller is connected, and at most once per
        profile per app run — the home journey's assessment card is always
        available as the manual entry point (H1 fix)."""
        baseline = self._session_manager.get_baseline_rom() or {}
        needs_assessment = (not self._session_manager.has_baseline()
                            or baseline.get("source") == "warmup")  # provisional
        connected = getattr(self, "is_controller_connected", False)
        prompted  = getattr(self, "_assessment_prompted", False)
        print(f"[Assessment] check: needs={needs_assessment} "
              f"controller={connected} already_prompted={prompted}")
        if not needs_assessment or prompted:
            return
        if not connected:
            # No pop-up: the Play page's calibration banner already says what is pending,
            # and the assessment starts by itself once a controller connects.
            return
        self._assessment_prompted = True
        self._open_assessment()

    def _open_assessment(self):
        from ui.assessment_wizard import AssessmentWizard
        wiz = AssessmentWizard(parent=self, processor=self.input_processor)
        self._warmup_open = True                    # block nav behind the dialog
        self.gamepad.raw_axes.connect(wiz.update_raw_axes)
        self.gamepad.raw_squeeze.connect(wiz.update_squeeze)
        try:
            accepted = wiz.exec()
        finally:
            try:
                self.gamepad.raw_axes.disconnect(wiz.update_raw_axes)
                self.gamepad.raw_squeeze.disconnect(wiz.update_squeeze)
            except TypeError:
                pass
            self._warmup_open = False

        # Treat an all-zero result as a skip — no movement was actually
        # captured (controller unplugged / patient didn't participate).
        got_movement = accepted and any(
            v >= 3.0 for v in (wiz.baseline_deg or {}).values())
        if accepted and not got_movement:
            print("[Assessment] No movement captured — baseline NOT saved")
        if got_movement:
            self._session_manager.save_assessment_baseline(
                wiz.baseline_deg, wiz.squeeze_max, wiz.hand,
                tremor=wiz.tremor_level)
            self._apply_tremor_adaptation(wiz.tremor_level)
            # Skip the first warmup TODAY — the assessment just measured full
            # ROM, so it counts as today's daily measurement (plan §4).
            try:
                from core.units import axis_to_degrees  # noqa
                d = wiz.baseline_deg
                self._session_manager.save_daily_rom(
                    max_left=-(d.get("supination", 0) / 72.0),
                    max_right=(d.get("pronation", 0) / 63.0),
                    max_up=-(d.get("extension", 0) / 43.0),
                    max_down=(d.get("flexion", 0) / 50.0),
                    tremor=wiz.tremor_level)
            except Exception as exc:
                print(f"[Assessment] daily_rom seed skipped: {exc}")
            from core.suggestion_engine import seed_journey_from_baseline
            seed_journey_from_baseline(self._session_manager)
            self._apply_patient_limits()            # controller now fits THEM
            if hasattr(self, 'play_page'):
                self.play_page.refresh()
        else:
            # Skipped: device reset to healthy defaults stays in effect
            self._apply_patient_limits()

    def _check_red_flags(self):
        """§4B Tier 4 — warn (once/day) if the data suggests a therapist check-in."""
        try:
            from core.patient_model import pain_rate, trends
            from datetime import date
            sm = self._session_manager
            if getattr(self, "_red_flag_day", None) == date.today().isoformat():
                return
            flags = []
            if pain_rate(sm, last_n=4) >= 0.5:
                flags.append("pain has come up in several recent sessions")
            tr = trends(sm)
            declining = [d for d, v in tr.items() if v.get("cls") == "declining"]
            if declining:
                flags.append("movement is trending down in: " + ", ".join(declining))
            if not flags:
                return
            self._red_flag_day = date.today().isoformat()
            from PyQt6.QtWidgets import QMessageBox
            m = QMessageBox(self)
            m.setWindowTitle("A gentle heads-up")
            m.setText("We noticed " + "; and ".join(flags) + ".\n\n"
                      "It may be worth checking in with your therapist. Your "
                      "progress report has the details to share with them.")
            m.exec()
        except Exception as exc:
            print(f"[RedFlags] {exc}")

    def _safety_dialog(self, title: str, text: str, allow_continue: bool) -> bool:
        """Gentle patient-safety dialog. Returns True to proceed."""
        from PyQt6.QtWidgets import QMessageBox
        m = QMessageBox(self)
        m.setWindowTitle(title)
        m.setText(text)
        if allow_continue:
            m.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            m.button(QMessageBox.StandardButton.Yes).setText("Play a bit more")
            m.button(QMessageBox.StandardButton.No).setText("I'll rest")
            m.setDefaultButton(QMessageBox.StandardButton.No)
        else:
            m.setStandardButtons(QMessageBox.StandardButton.Ok)
        res = m.exec()
        return (not allow_continue) or res == QMessageBox.StandardButton.Yes

    def _check_daily_dose(self) -> bool:
        """SAFETY §1.1 — enforce the therapist's daily-minutes cap before a
        launch. Returns True if it's OK to play."""
        try:
            g = self._session_manager.get_guardrails()
            cap = int(g.get("max_daily_min", 45))
            done = self._session_manager.get_today_duration_seconds() // 60
            if cap and done >= cap:
                return self._safety_dialog(
                    "Time to rest",
                    f"You've done {done} minutes of therapy today — that meets "
                    f"your daily goal of {cap} minutes.\n\nRest is part of "
                    "recovery. Playing more is optional; listen to your body.",
                    allow_continue=True)
        except Exception as exc:
            print(f"[Safety] daily-dose check: {exc}")
        return True

    def _maybe_suggest_rest(self):
        """SAFETY §1.1 — after a long single session, gently suggest a break."""
        try:
            g = self._session_manager.get_guardrails()
            if not g.get("rest_reminder", True):
                return
            limit = int(g.get("max_session_min", 20))
            dur = (self._active_session or {}).get("duration_seconds", 0) // 60
            if limit and dur >= limit:
                self._safety_dialog(
                    "Nice work — take a break",
                    f"That was a {dur}-minute session. A short rest helps your "
                    "muscles recover and keeps your movement quality high.\n\n"
                    "Come back when you're ready.",
                    allow_continue=False)
        except Exception as exc:
            print(f"[Safety] rest suggestion: {exc}")

    def _should_ask_pain(self) -> bool:
        """True unless a pain answer was recorded in the last 30 minutes."""
        from datetime import datetime, timedelta
        for s in reversed(self._session_manager.get_all_sessions()):
            if s.get("pain_report") and s.get("ended_at"):
                try:
                    last = datetime.fromisoformat(s["ended_at"])
                    return (datetime.now() - last) > timedelta(minutes=30)
                except Exception:
                    return True
        return True

    # ── Tremor adaptation ──────────────────────────────────────────────────────

    def _apply_tremor_adaptation(self, tremor: float):
        """Raise the inner dead-zone to sit above the measured hand-shake so
        tremor never registers as navigation input. Only ever RAISES it
        (a therapist can still lower it manually in Settings)."""
        if not tremor:
            return
        suggested = min(0.35, max(0.05, round(tremor * 3.0, 3)))
        if suggested > self.input_processor.inner_dead_zone:
            self.input_processor.inner_dead_zone = suggested
            self.input_processor.save()
            print(f"[Tremor] RMS {tremor:.3f} → inner dead-zone raised to {suggested:.2f}")

    # ── Per-patient controller range (ease-of-use fix) ────────────────────────

    def _apply_patient_limits(self):
        """Tell the controller (firmware v6) to map full deflection to this
        patient's comfortable ROM. Falls back to healthy defaults when no
        baseline exists. Runs in a thread — serial can block briefly."""
        import threading
        baseline = self._session_manager.get_baseline_rom() or {}
        deg = baseline.get("deg")

        def _worker():
            from core.device_link import apply_patient_limits
            apply_patient_limits(deg)

        threading.Thread(target=_worker, daemon=True).start()

    # ── Input UI Switching ────────────────────────────────────────────────────

    # ── Game launch flow (warmup → game → pain check-in → milestones) ──────────

    def _launch_game_by_id(self, game_id: str):
        """Launch a game by ID — used by journey panel and game store clicks."""
        game = self.game_manager.get_game(game_id)
        if not game:
            return
        if game.get("is_installed", False):
            # FULL flow for every launch (home, library, journey):
            # warmup → session start → game → minutes/pain/milestones/journey.
            # (Previously launched directly, so sessions were never recorded —
            #  no minutes played, no session count, no journey progress.)
            self._launch_with_warmup(game_id, game)
        else:
            self._on_store_download(game_id)

    def _open_warmup_standalone(self):
        """Open the warmup/calibration dialog without launching a game after."""
        if getattr(self, '_warmup_open', False):
            return  # prevent re-entrant opens
        from ui.calibration_warmup import CalibrationWarmup
        warmup = CalibrationWarmup(processor=self.input_processor, parent=self)
        self.gamepad.raw_axes.connect(warmup.update_raw_axes)
        self._warmup_open = True
        result = warmup.exec()
        self._warmup_open = False
        try:
            self.gamepad.raw_axes.disconnect(warmup.update_raw_axes)
        except RuntimeError:
            pass
        # Only seed a baseline if none exists yet — the AssessmentWizard owns
        # the baseline; a casual warmup must never overwrite it. A warmup
        # baseline is provisional but still seeds the journey (M2 fix).
        if result and any(warmup.rom_data) and not self._session_manager.has_baseline():
            self._session_manager.save_baseline_rom(*warmup.rom_data)
            from core.suggestion_engine import seed_journey_from_baseline
            seed_journey_from_baseline(self._session_manager)
            self._apply_patient_limits()
        # Journey warmup step: this IS today's measurement — games launched
        # afterwards attach it and skip their own warmup dialog.
        # Save on genuine completion even if ROM is all-zero (a severely
        # impaired hand may register ~0 movement — that's a valid warmup, and
        # gating on any(rom_data) would lock such a patient out permanently).
        if result and warmup.completed:
            self._session_manager.save_daily_rom(
                *warmup.rom_data, tremor=warmup.tremor_level)
            if hasattr(self, 'play_page'):
                self.play_page.refresh()
        if result:
            self._apply_tremor_adaptation(warmup.tremor_level)

    def _launch_with_warmup(self, game_id: str, game: dict):
        """
        Start session → launch game. The warmup dialog only appears if today's
        warmup hasn't been done yet (it lives in the journey as its own step);
        otherwise today's measurement is attached to the session silently.
        """
        # SAFETY §1.1 — daily dose cap. Don't let a patient silently overdo it.
        if not self._check_daily_dose():
            return

        daily = self._session_manager.get_daily_rom()
        # Games found on this PC use their own controls, so no controller warmup.
        store_game = bool(game.get("detected"))

        if daily is None and not store_game:
            from ui.calibration_warmup import CalibrationWarmup
            warmup = CalibrationWarmup(processor=self.input_processor, parent=self)
            self.gamepad.raw_axes.connect(warmup.update_raw_axes)
            self._warmup_open = True
            result = warmup.exec()
            self._warmup_open = False
            try:
                self.gamepad.raw_axes.disconnect(warmup.update_raw_axes)
            except RuntimeError:
                pass
            if result and warmup.completed:
                self._session_manager.save_daily_rom(
                    *warmup.rom_data, tremor=warmup.tremor_level)
                daily = self._session_manager.get_daily_rom()
            if result:
                self._apply_tremor_adaptation(warmup.tremor_level)

        # Per-patient adaptive difficulty from the SuggestionEngine — the
        # value that is ACTUALLY written into the game's config.
        from core.suggestion_engine import get_game_difficulty
        difficulty = get_game_difficulty(self._session_manager, game_id)
        self._active_session = self._session_manager.start_session(
            game_id, difficulty, actual_difficulty=difficulty)

        # Attach today's measurement to this session for progress tracking
        if daily:
            self._active_session["rom"] = dict(daily)

        if store_game:
            self.showMinimized()      # stays reachable while the store starts the game
        else:
            self.hide()
        self.game_manager.launch(game_id, difficulty=difficulty)

    def _on_game_not_started(self, name: str) -> None:
        """A store game was never seen running: discard the session and say so."""
        self._active_session = None
        self.showMaximized()
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Solace", f"Solace did not see {name} start.\n"
                            "Open its store, check the game runs there, then try again.")

    def _get_difficulty(self) -> float:
        """Read current difficulty multiplier from global settings."""
        try:
            import json
            with open(get_settings_path(), "r", encoding="utf-8") as f:
                return float(json.load(f).get("difficulty_multiplier", 0.25))
        except Exception:
            return 0.25

    def _on_web_game_requested(self, game: dict):
        """Open a web game in a fullscreen QWebEngineView (no warmup for now)."""
        from core.web_game_window import WebGameWindow
        player_name = self._active_profile.get("name", "Player")
        self._web_window = WebGameWindow(
            index_html=game["path"],
            game_data=game,
            gamepad_thread=self.gamepad,
            player_name=player_name,
            parent=None,   # top-level so it gets its own taskbar entry
        )
        self._web_window.game_finished.connect(self._on_web_game_finished)
        self._web_window.showFullScreen()

    def _on_web_game_finished(self):
        """Called when the WebGameWindow closes."""
        self.game_manager.is_running = False
        # Drop our reference so the window (and its web render process) is
        # actually destroyed — otherwise it lingered and kept playing audio.
        w = getattr(self, "_web_window", None)
        if w is not None:
            self._web_window = None
            w.deleteLater()
        self.show()
        if self._active_session is None:
            return
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._run_post_game_flow)

    def _on_game_finished(self):
        """Called when the game subprocess exits (always on the GUI thread)."""
        if self.isMinimized():
            self.showMaximized()
        else:
            self.show()
        if self._active_session is None:
            return
        # Defer one event-loop tick so the window is fully rendered before
        # modal dialogs open (avoids misplaced dialogs on rapid exit).
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._run_post_game_flow)

    def _run_post_game_flow(self):
        if self._active_session is None:
            return

        # End session & save
        self._session_manager.end_session(self._active_session)

        # Pain check-in — at most once per 30 minutes (M3 fix): three games
        # in an evening shouldn't mean three modal interrogations.
        name = self._active_profile.get("name", "Friend")
        if self._should_ask_pain():
            from ui.pain_checkin import PainCheckIn
            checkin = PainCheckIn(profile_name=name, parent=self)
            checkin.exec()
            self._session_manager.record_pain(self._active_session, checkin.result)

        # Milestones
        from core.milestone_manager import check_and_award, MilestoneCelebration
        new_milestones = check_and_award(self._session_manager, self._active_session)
        if new_milestones:
            celebration = MilestoneCelebration(
                milestones=new_milestones,
                profile_name=name,
                parent=self,
            )
            celebration.exec()

        # Update journey engine
        from core.suggestion_engine import update_journey
        all_games = self.game_manager.get_games()
        update_journey(self._session_manager, self._active_session, all_games)

        # §4B Tier 4 — red-flag escalation: surface a "see your therapist"
        # note when the data shows repeated pain or a sustained decline.
        self._check_red_flags()

        # SAFETY §1.1 — after a long session, suggest a rest break.
        self._maybe_suggest_rest()

        # §6.3 — simulated cloud sync: this session's data "backs up" to the
        # owning account (real backend later; ownership is already correct).
        try:
            from core.cloud_sync import mark_pending
            mark_pending(self._active_profile.get("auth_id")
                         or self._active_profile.get("id"))
        except Exception as exc:
            print(f"[CloudSync] {exc}")

        self._active_session = None

        # B2 + B3: refresh play (recommendation) and progress immediately
        self.play_page.refresh()
        self.progress_page.refresh()

    def _on_store_download(self, game_id: str):
        """Triggered by a Download tile or the featured-game button."""
        # U1: show downloading state immediately
        self.play_page.mark_downloading(game_id)
        self.game_manager.download_game(game_id)

    def _on_download_finished(self, game_id: str):
        """Move the game from "Get more games" into "My games"."""
        self.play_page.mark_installed(game_id)

    def _on_controller_state(self, connected: bool, name: str):
        was_connected = getattr(self, 'is_controller_connected', False)
        self.is_controller_connected = connected
        self.current_controller_name = name
        self.top_bar.set_controller_connected(connected, name)
        # Flaw #13 fix: firmware range limits are RAM-only — a reboot/replug
        # silently reverts them to healthy defaults. Re-send on every
        # (re)connection so games keep matching the patient's ability.
        # Delay slightly so the CDC serial port has time to enumerate.
        if connected and not was_connected:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(2500, self._apply_patient_limits)
            # The assessment is a POP-UP, not a journey step: if this profile
            # has no baseline yet, offer it as soon as a controller appears
            # (once per profile per run; skippable; redo via Settings).
            QTimer.singleShot(3000, self._maybe_first_assessment)

    def _mark_controller_active(self):
        if self.is_controller_connected:
            self.top_bar.set_controller_connected(True, self.current_controller_name)

    def _mark_keyboard_active(self):
        self.top_bar.set_controller_connected(False, "KEYBOARD")

    def _on_raw_axes(self, x: float, y: float):
        # Run through the processor to filter out deadzone and hardware drift noise
        nx, ny, _ = self.input_processor.process(x, y)
        
        # Switch UI to controller ONLY if it's a genuine movement outside the deadzone
        if nx != 0.0 or ny != 0.0:
            self._mark_controller_active()
        
        # Pass raw values to settings page for live preview dial
        if hasattr(self.settings_page, 'input_card') and self.settings_page.input_card is not None:
            self.settings_page.input_card.update_raw_axes(x, y)

    # ── Tab switching ─────────────────────────────────────────────────────────

    def _switch_tab(self, idx: int):
        """Programmatically switch tab and update the bottom nav highlight."""
        idx = max(0, min(len(self.nav_pill.buttons) - 1, idx))
        self.nav_pill.set_active_tab(idx)
        self.nav_pill.flash()                      # open the island for a moment so the change is seen
        self.on_tab_changed(idx)

    def on_tab_changed(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self._sync_chrome(idx)
        self.calibration_locked = False
        self._set_nav_focus(False)
        # Refresh data-driven pages on tab switch
        if idx == 1:
            self.progress_page.refresh()


    # ── Gamepad dispatcher ────────────────────────────────────────────────────

    def handle_gamepad_action(self, action: str, is_hover: bool = False):
        if self.game_manager.is_running:
            return
        # Navigation lock: while the calibration/warmup dialog is open,
        # controller movement feeds ONLY the calibration — no page changes,
        # no hover-to-launch behind the dialog.
        if getattr(self, '_warmup_open', False):
            return

        # The profile page is open: it takes the controller until it closes.
        if self.profile_overlay.isVisible():
            if not is_hover:
                self.profile_overlay.nav_action(action)
            return

        current_tab = self.stack.currentIndex()

        # Focus is on the tab bar: left/right change tab, down or select returns
        # to the page. (Reached by pressing up from the first row of Play.)
        if self._nav_focus:
            if action in ('left', 'right'):
                self._switch_tab(current_tab + (-1 if action == 'left' else 1))
                self._set_nav_focus(True)      # stay on the bar to hop again
            elif action == 'down' or (action == 'action' and not is_hover):
                self._set_nav_focus(False)
            return

        # Play owns all four directions (rows and tiles). Up from the first row
        # is not consumed, which moves the focus to the tab bar.
        if current_tab == 0:
            if action == 'action' and is_hover:
                return
            if not self.play_page.handle_action(action) and action == 'up':
                self._set_nav_focus(True)
            return

        # Other tabs: LEFT / RIGHT switch tabs, UP / DOWN / PUSH navigate the page
        if action == 'left':
            self._switch_tab(current_tab - 1)
            return
        if action == 'right':
            self._switch_tab(current_tab + 1)
            return
        if current_tab == 1:
            self._nav_page(self.progress_page, action, is_hover)
        elif current_tab == 2:
            self._nav_settings(action, is_hover)

    def _set_nav_focus(self, on: bool):
        self._nav_focus = on
        self.nav_pill.set_focused(on)

    def _nav_page(self, page, action: str, is_hover: bool):
        """Generic up/down/select navigation for pages exposing navigate() +
        activate_selected() (Progress)."""
        if action == 'up' and hasattr(page, 'navigate'):
            page.navigate(-1)
        elif action == 'down' and hasattr(page, 'navigate'):
            page.navigate(1)
        elif action == 'action' and not is_hover and hasattr(page, 'activate_selected'):
            page.activate_selected()

    # ── Settings navigation — panel-level snapping ───────────────────────────

    def _nav_settings(self, action: str, is_hover: bool):
        if action == 'up':
            self.settings_page.navigate(-1)
        elif action == 'down':
            self.settings_page.navigate(1)
        elif action == 'action' and not is_hover:
            self.settings_page.activate_selected()


    # ── Hover-to-launch (disabled in new library) ──────────────────────────────

    def handle_gamepad_hover(self, progress: float):
        pass

    # ── Keyboard Fallback ─────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._mark_keyboard_active()
                if key == Qt.Key.Key_Up:
                    self.handle_gamepad_action('up')
                elif key == Qt.Key.Key_Down:
                    self.handle_gamepad_action('down')
                elif key == Qt.Key.Key_Left:
                    self.handle_gamepad_action('left')
                elif key == Qt.Key.Key_Right:
                    self.handle_gamepad_action('right')
                elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self.handle_gamepad_action('action')
                return True # Consume the event so Qt doesn't scroll natively
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self.gamepad.stop()
        super().closeEvent(event)


APP_USER_MODEL_ID = "AyushBarua.Solace"     # same id as the installer's shortcuts


def set_app_identity(app) -> None:
    """Name and icon, so Windows shows Solace (not Python) in the taskbar."""
    from PyQt6.QtGui import QIcon
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    app.setApplicationName("Solace")
    app.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), "assets", "solace.ico")))


def report_startup_crash(details: str) -> None:
    """The installed app has no console, so save the error and say where it is."""
    from core.paths import get_data_dir
    path = os.path.join(get_data_dir(), "crash.log")
    with open(path, "w", encoding="utf-8") as f:
        f.write(details)
    print(details)
    from PyQt6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication(sys.argv)
    QMessageBox.critical(None, "Solace",
                         f"Solace could not start.\nThe details were saved to:\n{path}")


def load_fonts():
    from PyQt6.QtGui import QFont
    # ONLY load from assets/fonts/ — the top-level assets/ copies of
    # NotoSansDevanagari are corrupt (bad sfnt header) and make DirectWrite
    # throw "Failed to create DirectWrite face". The valid fonts are in fonts/.
    fonts_dir = os.path.join(os.path.dirname(__file__), "assets", "fonts")
    noto_family = None
    if os.path.exists(fonts_dir):
        for f in os.listdir(fonts_dir):
            if not (f.endswith(".ttf") or f.endswith(".otf")):
                continue
            fid = QFontDatabase.addApplicationFont(os.path.join(fonts_dir, f))
            if fid == -1:
                print(f"[fonts] failed to load {f}")
                continue
            fams = QFontDatabase.applicationFontFamilies(fid)
            if fams and "devanagari" in fams[0].lower():
                noto_family = fams[0]

    # Register Noto Sans Devanagari as the fallback for Hindi (script 11), which
    # Parkinsans / system fonts don't cover — so Hindi renders, not tofu boxes.
    if noto_family:
        for fam in ("Parkinsans", FONT_DISPLAY, "Segoe UI"):
            QFont.insertSubstitution(fam, noto_family)
        print(f"[fonts] Devanagari fallback: {noto_family}")


if __name__ == "__main__":
    import sys

    # ── Game subprocess launcher ──────────────────────────────────────────────
    # When a game .py file is passed as the first argument, run it directly.
    if len(sys.argv) > 1 and sys.argv[1].endswith(".py"):
        import runpy
        import os
        import importlib.abc
        import importlib.util

        class LocalSourceFinder(importlib.abc.MetaPathFinder):
            def __init__(self, base_path):
                self.base_path = base_path

            def find_spec(self, fullname, path, target=None):
                rel_path = fullname.replace('.', os.sep)
                pkg_path = os.path.join(self.base_path, rel_path, '__init__.py')
                if os.path.exists(pkg_path):
                    spec = importlib.util.spec_from_file_location(fullname, pkg_path)
                    spec.submodule_search_locations = [os.path.join(self.base_path, rel_path)]
                    return spec
                mod_path = os.path.join(self.base_path, rel_path + '.py')
                if os.path.exists(mod_path):
                    return importlib.util.spec_from_file_location(fullname, mod_path)
                return None

        base_dir = os.path.dirname(os.path.abspath(sys.argv[1]))
        sys.meta_path.insert(0, LocalSourceFinder(base_dir))
        sys.argv = [sys.argv[1]] + sys.argv[2:]
        try:
            runpy.run_path(sys.argv[0], run_name="__main__")
        except Exception as e:
            import traceback
            err_path = os.path.join(os.path.dirname(sys.argv[0]), "error.log")
            with open(err_path, "w") as f:
                f.write(traceback.format_exc())
        sys.exit(0)

    # ── Main launcher startup ─────────────────────────────────────────────────
    try:
        # Quiet the non-actionable Qt font-fallback noise (Devanagari falls back
        # to Noto correctly; Qt still logs that it tried Parkinsans first).
        os.environ.setdefault("QT_LOGGING_RULES",
                              "qt.text.font.db=false;qt.qpa.fonts.warning=false")

        # Must be set BEFORE QApplication for QtWebEngineWidgets to work
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView as _WebView  # noqa: F401
        except Exception:
            pass  # WebEngine not installed — fallback widget will be used

        app = QApplication(sys.argv)
        set_app_identity(app)
        load_fonts()

        # ── i18n: restore saved language before any UI is created ─────────────
        from core.i18n import init as _i18n_init, has_chosen_language, set_language, get_language
        _i18n_init()

        # ── Language picker: shown for ANY user who hasn't chosen yet ─────────
        if not has_chosen_language():
            from ui.onboarding import _StepLanguage
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QApplication as _QApp
            from core.theme import BACKGROUND

            lang_dlg = QDialog()
            lang_dlg.setWindowTitle("Solace — Choose Language")
            lang_dlg.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
            )
            _screen = _QApp.primaryScreen().availableGeometry()
            lang_dlg.setFixedSize(_screen.width(), _screen.height())
            lang_dlg.setStyleSheet(f"background: {BACKGROUND};")

            _ll = QVBoxLayout(lang_dlg)
            _ll.setContentsMargins(0, 0, 0, 0)
            _lang_step = _StepLanguage()
            _lang_step.proceed.connect(lang_dlg.accept)
            _ll.addWidget(_lang_step)
            lang_dlg.exec()

        # Parse custom restart flags
        skip_profile = "--skip-profile" in sys.argv
        start_tab = 0
        if "--tab" in sys.argv:
            try:
                start_tab = int(sys.argv[sys.argv.index("--tab") + 1])
            except ValueError:
                pass

        # ── Step 2: Settings generation (fallback for dev) ────────────────────
        s_path = get_settings_path()
        if not os.path.exists(s_path):
            g_dir = os.path.join(os.path.dirname(s_path), "Games")
            os.makedirs(g_dir, exist_ok=True)
            with open(s_path, "w", encoding="utf-8") as f:
                json.dump({
                    "difficulty_multiplier": 1.0,
                    "games_dir": g_dir,
                    "data_dir": os.path.dirname(s_path)
                }, f)

        # ── Step 3: Login (skip if a valid session already exists) ───────────
        from core.session_store import load_session, _get_session_path
        from core.profile_manager import set_active_profile as _set_active
        existing_session = load_session()
        if not app_flags.REQUIRE_LOGIN:
            # No sign-in screen and no start-up chooser: open straight into the profile
            # used last (the avatar in the nav pill switches). Only a brand-new install
            # with no profile at all shows the chooser, so a first profile can be made.
            from core.profile_manager import load_profiles
            profiles = load_profiles()
            current = get_active_profile()
            if current and any(p.get("id") == current.get("id") for p in profiles):
                pass                                     # keep the last-used profile
            elif profiles:
                _set_active(profiles[0])
            else:
                from ui.profile_screen import ProfileScreen
                ProfileScreen().exec()
                if not get_active_profile():             # window closed without choosing
                    sys.exit(0)
        elif existing_session and not skip_profile:
            # Restore the profile linked to the saved session
            from core.profile_manager import load_profiles
            profiles = load_profiles()
            match = next((p for p in profiles if p.get("auth_id") == existing_session.get("id")), None)
            if match:
                _set_active(match)
        elif not skip_profile:
            # L6: check whether a session file exists but is expired
            session_expired = False
            try:
                with open(_get_session_path(), "r", encoding="utf-8") as _sf:
                    _sd = json.load(_sf)
                from datetime import datetime as _dt
                if _dt.now() > _dt.fromisoformat(_sd["expires_at"]):
                    session_expired = True
            except Exception:
                pass
            login_screen = LoginScreen(session_expired=session_expired)
            login_screen.exec()

        # (Medical disclaimer / safety briefing lives in the installer T&C and is
        #  verified by the therapist — not shown here. Dose limits + pain-gating
        #  still enforce safety during play.)

        # ── Optional profile PIN gate (§6) ────────────────────────────────────
        # If the active profile has a PIN, ask for it before continuing.
        _active_pin = (get_active_profile() or {}).get("pin")
        if _active_pin:
            from PyQt6.QtWidgets import QInputDialog
            for _ in range(3):
                val, ok = QInputDialog.getText(None, "Profile Locked",
                                               "Enter your 4-digit PIN:")
                if not ok:
                    sys.exit(0)
                if val == _active_pin:
                    break
            else:
                sys.exit(0)

        # ── Step 4: Onboarding (new profiles only) ────────────────────────────
        active = get_active_profile() or {}
        profile_id = active.get("id", "default")
        sm = SessionManager(profile_id)
        from ui.onboarding import should_show_onboarding, OnboardingFlow
        if should_show_onboarding(profile_id):
            onboarding = OnboardingFlow(profile=active, session_manager=sm)
            onboarding.exec()

        # ── Step 5: Launch main window ────────────────────────────────────────
        window = MainWindow()
        if start_tab > 0:
            window._switch_tab(start_tab)
        window.showMaximized()
        window.raise_()
        window.activateWindow()
        sys.exit(app.exec())

    except Exception:
        import traceback
        report_startup_crash(traceback.format_exc())
        sys.exit(1)
