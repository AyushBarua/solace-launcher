"""
LoginScreen — authentication gateway.

Supports:
  • Email + password (local, hashed)
  • Google Sign-In (browser OAuth2 flow)
  • Persistent session — caller checks session_store before showing this
"""
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui import QColor

from core.auth_manager import LocalAuthProvider, GoogleAuthProvider
from core.session_store import save_session
from core.profile_manager import create_profile, get_active_profile, set_active_profile, load_profiles, save_profiles


# ── Background worker for blocking auth calls ─────────────────────────────────

class _AuthWorker(QThread):
    success = pyqtSignal(dict)
    failure = pyqtSignal(str)

    def __init__(self, fn, *args):
        super().__init__()
        self._fn   = fn
        self._args = args

    def run(self):
        try:
            result = self._fn(*self._args)
            if result:
                self.success.emit(result)
            else:
                self.failure.emit("Invalid credentials")
        except RuntimeError as e:
            self.failure.emit(str(e))
        except Exception:
            self.failure.emit("Something went wrong. Please try again.")


# ── Dark-theme colour map ─────────────────────────────────────────────────────
# The login card is written with literal light colours. In the dark theme every
# stylesheet and rich-text label is passed through _dk(); in light it is a no-op.
from ui.glass import is_dark as _is_dark_theme

_DARK_MAP = (
    ("background:#111111;color:white", "background:#F4F1EA;color:#14130F"),
    ("background: white", "background: #1F1D1A"),
    ("background:white;color:#444", "background:#2E2B27;color:#E6E2D9"),
    ("background:white", "background:#1F1D1A"),
    ("color: black", "color: #F1EEE7"),
    ("color:black", "color:#F1EEE7"),
    ("color:#111111", "color:#F4F1EA"),
    ("background:#111111", "background:#F4F1EA"),
    ("border: 1px solid #111111", "border: 1px solid #F4F1EA"),
    ("#2B2A27", "#FFFFFF"),
    ("#5B5A55", "#B9B5AB"),
    ("#8A8880", "#8A877E"),
    ("#C9C5BB", "#38352F"),
    ("#e0e0e0", "#3A3732"),
    ("color:#444", "color:#E6E2D9"),
    ("color:#666", "color:#B9B5AB"),
    ("color:#aaa", "color:#77736A"),
    ("color:#ccc", "color:#6A675F"),
    ("background:#f5f5f5", "background:#2E2B27"),
    ("#fff5f5", "#3A2220"),
    ("#fdf0f0", "#3A2220"),
    ("#e8b4b4", "#7A3A36"),
    ("color:#c0392b", "color:#FF8A80"),
    ("#ebf8ff", "#1F2D3A"),
    ("color:#2b6cb0", "color:#7DB8F0"),
    ("#bee3f8", "#35506B"),
    ("#C2480A", "#FF9A4D"),
)


def _dk(css: str) -> str:
    if not _is_dark_theme():
        return css
    for old, new in _DARK_MAP:
        css = css.replace(old, new)
    return css


# ── Login screen ──────────────────────────────────────────────────────────────

class LoginScreen(QDialog):
    login_successful = pyqtSignal(dict)

    _INPUT_STYLE = _dk("""
        QLineEdit {
            background: white;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            padding: 0 12px;
            color: black;
            font-family: 'Schibsted Grotesk', sans-serif;
            font-size: 14px;
        }
        QLineEdit:focus { border: 1px solid #111111; }
    """)
    _INPUT_ERROR_STYLE = _dk("""
        QLineEdit {
            background: #fff5f5;
            border: 1.5px solid #e53e3e;
            border-radius: 6px;
            padding: 0 12px;
            color: black;
            font-family: 'Schibsted Grotesk', sans-serif;
            font-size: 14px;
        }
    """)

    def _darken(self):
        """Dark theme: remap the card's literal light colours (no-op in light)."""
        if not _is_dark_theme():
            return
        from PyQt6.QtWidgets import QLabel as _QLabel
        for w in [self.box, *self.box.findChildren(QWidget)]:
            css = w.styleSheet()
            if css:
                w.setStyleSheet(_dk(css))
            if isinstance(w, _QLabel) and "<" in w.text():
                w.setText(_dk(w.text()))

    def __init__(self, parent=None, session_expired: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Solace — Login")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)

        from core.theme import BACKGROUND as BG
        self.setStyleSheet(f"background:{BG};")
        self.showMaximized()

        self._worker = None
        self._session_expired = session_expired

        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.box = QWidget()
        self.box.setFixedSize(480, 600)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(80)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 12)
        self.box.setGraphicsEffect(shadow)
        root.addWidget(self.box)

        self._build_login_view()

    # ── View builders ─────────────────────────────────────────────────────────

    def _clear_box(self):
        old = self.box.layout()
        if old:
            while old.count():
                item = old.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QWidget().setLayout(old)

    def _build_login_view(self, *_):
        self._clear_box()
        # U4: reset any stale error/input state before building the new view
        self._error_lbl   = QLabel("")   # recreated below; reset ref now
        self.box.setStyleSheet(_dk("QWidget { background: white; border-radius: 12px; }"))

        from core.i18n import t, set_language, get_language

        layout = QVBoxLayout(self.box)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(8)

        # Language toggle (top-right): English / हिंदी
        lang_row = QHBoxLayout()
        lang_row.addStretch()
        cur = get_language()
        for code, lbl in (("en", "EN"), ("hi", "हिं")):
            b = QLabel(f"<a href='#' style='color:{'#111111' if cur==code else '#8A8880'};"
                       f"text-decoration:none;font-weight:{'bold' if cur==code else 'normal'};'>{lbl}</a>")
            b.linkActivated.connect(lambda _c, x=code: (set_language(x), self._build_login_view()))
            b.setStyleSheet("font-family:'Schibsted Grotesk'; font-size:14px; border:none;")
            lang_row.addWidget(b)
            if code == "en":
                sep = QLabel("·"); sep.setStyleSheet("color:#ccc;border:none;"); lang_row.addWidget(sep)
        layout.addLayout(lang_row)

        title = QLabel(t("login_welcome"))
        title.setStyleSheet("color:black; font-family:'Schibsted Grotesk'; font-size:32px; font-weight:bold; border:none;")
        layout.addWidget(title)

        layout.addSpacing(2)
        subtitle = QLabel(t("login_subtitle"))
        subtitle.setStyleSheet("color:#5B5A55; font-family:'Schibsted Grotesk'; font-size:15px; border:none;")
        layout.addWidget(subtitle)

        layout.addSpacing(16)

        # L6: session expired notice — shown above the error banner
        if getattr(self, '_session_expired', False):
            expired_lbl = QLabel(
                "Your session has expired — please sign in again."
            )
            expired_lbl.setWordWrap(True)
            expired_lbl.setStyleSheet(
                "color:#2b6cb0; background:#ebf8ff; border:1px solid #bee3f8; border-radius:14px;"
                "padding:8px 12px; font-family:'Schibsted Grotesk'; font-size:13px;"
            )
            layout.addWidget(expired_lbl)
            layout.addSpacing(4)

        # Error banner
        self._error_lbl = QLabel("")
        self._error_lbl.setWordWrap(True)
        self._error_lbl.setStyleSheet(
            "color:#c0392b; background:#fdf0f0; border:1px solid #e8b4b4; border-radius:14px;"
            "padding:8px 12px; font-family:'Schibsted Grotesk'; font-size:13px; border:none;"
        )
        self._error_lbl.setVisible(False)
        layout.addWidget(self._error_lbl)

        # Email
        lbl_email = QLabel(t("login_email"))
        lbl_email.setStyleSheet("color:black; font-family:'Schibsted Grotesk'; font-size:14px; font-weight:500; border:none;")
        layout.addWidget(lbl_email)
        self._ident_input = QLineEdit()
        self._ident_input.setFixedHeight(42)
        self._ident_input.setPlaceholderText("you@example.com")
        self._ident_input.setStyleSheet(self._INPUT_STYLE)
        # Pre-fill the last email so the user doesn't retype it
        from core.session_store import load_last_email
        _last = load_last_email()
        if _last:
            self._ident_input.setText(_last)
        layout.addWidget(self._ident_input)

        layout.addSpacing(12)

        # Password
        lbl_pass = QLabel(t("login_password"))
        lbl_pass.setStyleSheet("color:black; font-family:'Schibsted Grotesk'; font-size:14px; font-weight:500; border:none;")
        layout.addWidget(lbl_pass)
        self._pass_input = QLineEdit()
        self._pass_input.setFixedHeight(42)
        self._pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._pass_input.setStyleSheet(self._INPUT_STYLE)
        self._pass_input.returnPressed.connect(self._on_login)
        layout.addWidget(self._pass_input)

        layout.addSpacing(4)
        # "Keep me signed in" + Forgot password on one row
        opts = QHBoxLayout()
        from PyQt6.QtWidgets import QCheckBox
        self._keep_cb = QCheckBox(t("login_keep"))
        self._keep_cb.setChecked(True)
        self._keep_cb.setStyleSheet(
            "QCheckBox{color:#111111;font-family:'Schibsted Grotesk';font-size:13px;}")
        opts.addWidget(self._keep_cb)
        opts.addStretch()
        forgot = QLabel("<a href='#' style='color:#C2480A; text-decoration:underline;'>Forgot password?</a>")
        forgot.setOpenExternalLinks(False)
        forgot.linkActivated.connect(self._on_forgot_password)
        forgot.setStyleSheet("font-family:'Schibsted Grotesk'; font-size:13px; border:none;")
        opts.addWidget(forgot)
        layout.addLayout(opts)

        layout.addSpacing(16)

        self._login_btn = QPushButton("Sign in")
        self._login_btn.setFixedHeight(48)
        self._login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._login_btn.setStyleSheet(
            "QPushButton{background:#111111;color:white;border:none;border-radius:14px;"
            "font-size:15px;font-weight:bold;}"
            "QPushButton:hover{background:#2B2A27;}"
            "QPushButton:disabled{background:#C9C5BB;}"
        )
        self._login_btn.clicked.connect(self._on_login)
        layout.addWidget(self._login_btn)

        layout.addSpacing(16)

        # Divider
        div = QHBoxLayout()
        l1 = QWidget(); l1.setFixedHeight(1); l1.setStyleSheet("background:#e0e0e0;")
        l2 = QWidget(); l2.setFixedHeight(1); l2.setStyleSheet("background:#e0e0e0;")
        or_lbl = QLabel("or")
        or_lbl.setStyleSheet("color:#5B5A55; font-family:'Schibsted Grotesk'; font-size:13px;")
        div.addWidget(l1); div.addWidget(or_lbl); div.addWidget(l2)
        layout.addLayout(div)

        layout.addSpacing(16)

        self._google_btn = QPushButton("  Sign in with Google")
        self._google_btn.setFixedHeight(48)
        self._google_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._google_btn.setStyleSheet(
            "QPushButton{background:white;color:#444;border:1px solid #e0e0e0;border-radius:14px;"
            "font-size:15px;font-weight:500;}"
            "QPushButton:hover{background:#f5f5f5;}"
            "QPushButton:disabled{color:#aaa;}"
        )
        from core.google_oauth import is_configured
        if not is_configured():
            self._google_btn.setToolTip("Google Sign-In: configure credentials in core/google_oauth.py")
        self._google_btn.clicked.connect(self._on_google_login)
        layout.addWidget(self._google_btn)

        layout.addStretch()

        reg_lbl = QLabel("Don't have an account? <a href='#' style='color:#C2480A; text-decoration:underline;'>Sign up</a>")
        reg_lbl.linkActivated.connect(self._build_register_view)
        reg_lbl.setStyleSheet("color:#5B5A55; font-family:'Schibsted Grotesk'; font-size:14px; border:none;")
        reg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(reg_lbl)
        self._darken()

        # (No device-reset or account-removal on the login screen — too easy to
        #  hit by mistake. Cleanup lives in Settings → Developer → Factory Reset,
        #  behind two confirmations. §6.)

    def _build_manage_view(self, *_):
        from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QPushButton, QLabel
        from core.auth_manager import list_accounts, delete_user, MAX_ACCOUNTS
        from core.profile_manager import delete_profile_completely, load_profiles
        self._clear_box()
        self.box.setStyleSheet(_dk("QWidget { background: white; border-radius: 12px; }"))
        layout = QVBoxLayout(self.box)
        layout.setContentsMargins(40, 40, 40, 40); layout.setSpacing(12)

        title = QLabel("Manage Accounts")
        title.setStyleSheet("color:black;font-family:'Schibsted Grotesk';font-size:26px;font-weight:bold;border:none;")
        layout.addWidget(title)
        accts = list_accounts()
        sub = QLabel(f"{len(accts)} of {MAX_ACCOUNTS} account slots used. "
                     "Remove one to free a slot — this deletes that account's data.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#5B5A55;font-family:'Schibsted Grotesk';font-size:13px;border:none;")
        layout.addWidget(sub)
        layout.addSpacing(8)

        if not accts:
            none_lbl = QLabel("No accounts yet.")
            none_lbl.setStyleSheet("color:#666;border:none;font-family:'Schibsted Grotesk';")
            layout.addWidget(none_lbl)

        for a in accts:
            row = QHBoxLayout()
            info = QLabel(f"<b>{a['name'] or a['identifier']}</b><br>"
                         f"<span style='color:#5B5A55;font-size:12px;'>{a['identifier']}</span>")
            info.setStyleSheet("color:black;border:none;font-family:'Schibsted Grotesk';")
            row.addWidget(info); row.addStretch()
            rm = QPushButton("Remove")
            rm.setFixedHeight(36); rm.setCursor(Qt.CursorShape.PointingHandCursor)
            rm.setStyleSheet("QPushButton{background:#c0392b;color:white;border:none;"
                             "border-radius:14px;padding:0 18px;font-size:13px;font-weight:bold;}"
                             "QPushButton:hover{background:#a5281b;}")
            rm.clicked.connect(lambda _c, acc=a: self._remove_account(acc))
            row.addWidget(rm)
            layout.addLayout(row)

        layout.addStretch()
        back = QLabel("<a href='#' style='color:#C2480A;text-decoration:underline;'>← Back to sign in</a>")
        back.linkActivated.connect(self._build_login_view)
        back.setStyleSheet("font-family:'Schibsted Grotesk';font-size:13px;border:none;")
        back.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(back)
        self._darken()

    def _remove_account(self, acct: dict):
        from PyQt6.QtWidgets import QMessageBox
        from core.auth_manager import delete_user
        from core.profile_manager import load_profiles, delete_profile_completely
        m = QMessageBox(self)
        m.setWindowTitle("Remove account")
        m.setText(f"Permanently remove {acct['identifier']} and all its data "
                  "from this device? This cannot be undone.")
        m.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        m.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if m.exec() != QMessageBox.StandardButton.Yes:
            return
        # Remove the linked profile(s) + the login account
        for p in load_profiles():
            if p.get("auth_id") == acct["id"]:
                delete_profile_completely(p["id"])
        delete_user(acct["id"])
        self._build_manage_view()   # refresh the list

    def _build_register_view(self, *_):
        self._clear_box()
        # U4: reset any stale error/input state before building the new view
        self._reg_error_lbl = QLabel("")  # recreated below; reset ref now
        self.box.setStyleSheet(_dk("QWidget { background: white; border-radius: 12px; }"))

        from core.i18n import set_language, get_language

        layout = QVBoxLayout(self.box)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(8)

        # Language toggle (top-right) — same as the sign-in view
        lang_row = QHBoxLayout(); lang_row.addStretch()
        cur = get_language()
        for code, lbl in (("en", "EN"), ("hi", "हिं")):
            b = QLabel(f"<a href='#' style='color:{'#111111' if cur==code else '#8A8880'};"
                       f"text-decoration:none;font-weight:{'bold' if cur==code else 'normal'};'>{lbl}</a>")
            b.linkActivated.connect(lambda _c, x=code: (set_language(x), self._build_register_view()))
            b.setStyleSheet("font-family:'Schibsted Grotesk'; font-size:14px; border:none;")
            lang_row.addWidget(b)
            if code == "en":
                sep = QLabel("·"); sep.setStyleSheet("color:#ccc;border:none;"); lang_row.addWidget(sep)
        layout.addLayout(lang_row)

        from core.i18n import t as _t
        title = QLabel(_t("reg_title"))
        title.setStyleSheet("color:black; font-family:'Schibsted Grotesk'; font-size:32px; font-weight:bold; border:none;")
        layout.addWidget(title)

        layout.addSpacing(2)
        subtitle = QLabel(_t("reg_subtitle"))
        subtitle.setStyleSheet("color:#5B5A55; font-family:'Schibsted Grotesk'; font-size:15px; border:none;")
        layout.addWidget(subtitle)

        layout.addSpacing(16)

        self._reg_error_lbl = QLabel("")
        self._reg_error_lbl.setWordWrap(True)
        self._reg_error_lbl.setStyleSheet(
            "color:#c0392b; background:#fdf0f0; border:1px solid #e8b4b4; border-radius:14px;"
            "padding:8px 12px; font-family:'Schibsted Grotesk'; font-size:13px;"
        )
        self._reg_error_lbl.setVisible(False)
        layout.addWidget(self._reg_error_lbl)

        fields = [
            ("_reg_name",  _t("reg_name"),    _t("reg_name_ph"),  False),
            ("_reg_ident", _t("login_email"), "you@example.com",  False),
            ("_reg_pass",  _t("login_password"), _t("reg_pass_ph"), True),
        ]
        for attr, label_text, placeholder, is_password in fields:
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color:black; font-family:'Schibsted Grotesk'; font-size:14px; font-weight:500; border:none;")
            layout.addWidget(lbl)
            field = QLineEdit()
            field.setFixedHeight(42)
            field.setPlaceholderText(placeholder)
            field.setStyleSheet(self._INPUT_STYLE)
            if is_password:
                field.setEchoMode(QLineEdit.EchoMode.Password)
            setattr(self, attr, field)
            layout.addWidget(field)
            layout.addSpacing(8)

        layout.addSpacing(8)

        self._reg_btn = QPushButton(_t("reg_button"))
        self._reg_btn.setFixedHeight(48)
        self._reg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reg_btn.setStyleSheet(
            "QPushButton{background:#111111;color:white;border:none;border-radius:14px;"
            "font-size:15px;font-weight:bold;}"
            "QPushButton:hover{background:#2B2A27;}"
            "QPushButton:disabled{background:#C9C5BB;}"
        )
        self._reg_btn.clicked.connect(self._on_register)
        layout.addWidget(self._reg_btn)

        layout.addStretch()

        back = QLabel(f"{_t('reg_have_account')} <a href='#' style='color:#C2480A; text-decoration:underline;'>{_t('login_signin')}</a>")
        back.linkActivated.connect(self._build_login_view)
        back.setStyleSheet("color:#5B5A55; font-family:'Schibsted Grotesk'; font-size:14px; border:none;")
        back.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(back)
        self._darken()

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _show_error(self, msg: str, label=None):
        lbl = label if label is not None else self._error_lbl
        lbl.setText(msg)
        lbl.setVisible(bool(msg))

    def _set_busy(self, busy: bool):
        for w in [self._login_btn, self._google_btn, self._ident_input, self._pass_input]:
            try:
                w.setEnabled(not busy)
            except RuntimeError:
                pass
        try:
            self._login_btn.setText("Signing in…" if busy else "Sign in")
        except RuntimeError:
            pass

    def _set_register_busy(self, busy: bool):
        for attr in ["_reg_btn", "_reg_name", "_reg_ident", "_reg_pass"]:
            try:
                getattr(self, attr).setEnabled(not busy)
            except (RuntimeError, AttributeError):
                pass
        try:
            self._reg_btn.setText("Creating account…" if busy else "Create account")
        except RuntimeError:
            pass

    # ── Action handlers ───────────────────────────────────────────────────────

    def _on_login(self):
        ident = self._ident_input.text().strip()
        pwd   = self._pass_input.text()
        self._show_error("")
        self._ident_input.setStyleSheet(self._INPUT_STYLE)
        self._pass_input.setStyleSheet(self._INPUT_STYLE)

        if not ident or not pwd:
            self._show_error("Please enter your email and password.")
            return

        # Respect the "Keep me signed in" choice on this login
        self._keep_signed = self._keep_cb.isChecked() if hasattr(self, "_keep_cb") else True
        self._set_busy(True)
        self._worker = _AuthWorker(LocalAuthProvider().authenticate, ident, pwd)
        self._worker.success.connect(self._on_auth_success)
        self._worker.failure.connect(self._on_login_failed)
        self._worker.start()

    @pyqtSlot(str)
    def _on_login_failed(self, msg: str = ""):
        self._set_busy(False)
        # U5: surface actionable error messages
        msg_lower = msg.lower()
        if "not found" in msg_lower or "no user" in msg_lower or "not registered" in msg_lower:
            friendly = "No account found for that email. Would you like to sign up instead?"
            self._ident_input.setStyleSheet(self._INPUT_ERROR_STYLE)
        elif "password" in msg_lower or "invalid" in msg_lower or "credentials" in msg_lower:
            friendly = "Incorrect password. Please try again or use 'Forgot password'."
            self._pass_input.setStyleSheet(self._INPUT_ERROR_STYLE)
        elif "network" in msg_lower or "connection" in msg_lower:
            friendly = "Network error — please check your connection and try again."
        else:
            friendly = "Sign in failed. Please check your details and try again."
        self._show_error(friendly)

    def _on_google_login(self):
        from core.google_oauth import is_configured
        if not is_configured():
            self._show_error(
                "Google Sign-In isn't set up yet. "
                "Ask your administrator to configure the Google credentials."
            )
            return
        self._show_error("")
        self._google_btn.setEnabled(False)
        self._google_btn.setText("Opening browser…")
        self._worker = _AuthWorker(GoogleAuthProvider().authenticate, "", "")
        self._worker.success.connect(self._on_auth_success)
        self._worker.failure.connect(self._on_google_failed)
        self._worker.start()

    @pyqtSlot(str)
    def _on_google_failed(self, msg: str):
        self._google_btn.setEnabled(True)
        self._google_btn.setText("  Sign in with Google")
        self._show_error(f"Google Sign-In failed: {msg}")

    def _on_register(self):
        name  = self._reg_name.text().strip()
        ident = self._reg_ident.text().strip()
        pwd   = self._reg_pass.text()
        self._show_error("", self._reg_error_lbl)

        if not name:
            self._show_error("Please enter your full name.", self._reg_error_lbl)
            return

        # L3: proper email validation before hitting the backend
        from core.auth_manager import validate_email
        valid, email_err = validate_email(ident)
        if not valid:
            self._show_error(email_err, self._reg_error_lbl)
            self._reg_ident.setStyleSheet(self._INPUT_ERROR_STYLE)
            return

        if len(pwd) < 6:
            self._show_error("Password must be at least 6 characters.", self._reg_error_lbl)
            return

        self._keep_signed = True    # a new account stays signed in
        self._set_register_busy(True)
        self._worker = _AuthWorker(LocalAuthProvider().register, ident, pwd, name)
        self._worker.success.connect(self._on_auth_success)
        self._worker.failure.connect(self._on_register_failed)
        self._worker.start()

    @pyqtSlot(str)
    def _on_register_failed(self, msg: str = ""):
        self._set_register_busy(False)
        # U5: distinguish duplicate email from other failures
        msg_lower = msg.lower()
        if "account_limit" in msg_lower or "maximum" in msg_lower:
            friendly = ("This device already has the maximum of 3 accounts. "
                        "Remove one from Settings → Delete Account to add another.")
        elif "already registered" in msg_lower or "duplicate" in msg_lower:
            friendly = "That email is already registered. Try signing in instead."
        elif "password" in msg_lower:
            friendly = "Password doesn't meet requirements. Please use at least 6 characters."
        else:
            friendly = "Could not create account. Please check your details and try again."
        self._show_error(friendly, self._reg_error_lbl)

    def _on_forgot_password(self, *_):
        self._show_error(
            "Password reset isn't available yet. Please contact your clinic administrator."
        )

    @pyqtSlot(dict)
    def _on_auth_success(self, user: dict):
        self._set_busy(False)
        from core.session_store import save_last_email, clear_session
        # Always remember the email for pre-fill next time.
        save_last_email(user.get("identifier", ""))
        # Only persist a full auto-login session if "Keep me signed in" was set.
        if getattr(self, "_keep_signed", True):
            save_session(user)
        else:
            clear_session()   # next launch will show login (email pre-filled)
        self._finish_login(user)

    def _finish_login(self, user: dict):
        profiles = load_profiles()
        match = next((p for p in profiles if p.get("auth_id") == user["id"]), None)

        if match:
            set_active_profile(match)
        else:
            profile = create_profile(user["name"], "🙂", "#5B9BD5")
            # Persist auth_id on the stored profile
            all_profiles = load_profiles()
            for p in all_profiles:
                if p["id"] == profile["id"]:
                    p["auth_id"] = user["id"]
                    break
            save_profiles(all_profiles)
            set_active_profile(profile)

        self.login_successful.emit(user)
        self.accept()
