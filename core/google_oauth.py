"""
Google OAuth 2.0 for desktop — no external dependencies.

Uses stdlib only:
  • urllib.request  — token exchange + userinfo API call
  • http.server     — localhost callback to catch the redirect
  • webbrowser      — open the auth URL in the user's default browser
  • threading       — run callback server without blocking the UI

Setup (one-time, per developer):
  1. Go to https://console.cloud.google.com/
  2. Create a project → APIs & Services → Credentials
  3. Create an OAuth 2.0 Client ID → Application type: "Desktop app"
  4. Copy the Client ID and Client Secret into GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET below
  5. Add http://localhost to the Authorized redirect URIs

The flow:
  run_google_oauth()
    → opens browser to Google's consent page
    → user grants permission
    → Google redirects to http://localhost:{port}?code=AUTH_CODE
    → we exchange AUTH_CODE for an access token
    → we call the userinfo API to get name + email
    → returns a user dict compatible with the rest of the auth system
"""
import json
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

# ── Configure these with your Google Cloud Console credentials ─────────────────
GOOGLE_CLIENT_ID     = ""   # TODO: paste your client_id here
GOOGLE_CLIENT_SECRET = ""   # TODO: paste your client_secret here

GOOGLE_AUTH_URL    = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL   = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
SCOPES             = "openid email profile"
REDIRECT_PORT      = 8765
REDIRECT_URI       = f"http://localhost:{REDIRECT_PORT}"

_CREDENTIALS_CONFIGURED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


# ── Callback HTTP server ──────────────────────────────────────────────────────

class _CallbackHandler(BaseHTTPRequestHandler):
    auth_code: Optional[str] = None
    error: Optional[str] = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            _CallbackHandler.auth_code = params["code"][0]
            body = b"<html><body><h2>Signed in! You can close this tab.</h2></body></html>"
        elif "error" in params:
            _CallbackHandler.error = params["error"][0]
            body = b"<html><body><h2>Sign-in cancelled. Return to Solace.</h2></body></html>"
        else:
            body = b"<html><body><h2>Waiting...</h2></body></html>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # silence server logs


# ── OAuth flow ────────────────────────────────────────────────────────────────

def run_google_oauth() -> Optional[dict]:
    """
    Runs the full browser-based OAuth flow.
    Returns user dict { id, identifier, name, provider } or None on failure.
    Raises RuntimeError if credentials are not configured.
    """
    if not _CREDENTIALS_CONFIGURED:
        raise RuntimeError(
            "Google OAuth credentials not configured.\n"
            "Open core/google_oauth.py and fill in GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )

    # Reset state from any previous run
    _CallbackHandler.auth_code = None
    _CallbackHandler.error = None

    # Start local callback server
    server = HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        # Build the authorization URL
        params = {
            "client_id":     GOOGLE_CLIENT_ID,
            "redirect_uri":  REDIRECT_URI,
            "response_type": "code",
            "scope":         SCOPES,
            "access_type":   "offline",
            "prompt":        "select_account",
        }
        auth_url = GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)
        webbrowser.open(auth_url)

        # Wait for callback (up to 120 seconds)
        server.timeout = 1
        for _ in range(120):
            server.handle_request()
            if _CallbackHandler.auth_code or _CallbackHandler.error:
                break

        if _CallbackHandler.error or not _CallbackHandler.auth_code:
            return None

        # Exchange auth code for access token
        token_data = urllib.parse.urlencode({
            "code":          _CallbackHandler.auth_code,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri":  REDIRECT_URI,
            "grant_type":    "authorization_code",
        }).encode("utf-8")

        req = urllib.request.Request(GOOGLE_TOKEN_URL, data=token_data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_resp = json.loads(resp.read())

        access_token = token_resp.get("access_token")
        if not access_token:
            return None

        # Fetch user info
        info_req = urllib.request.Request(GOOGLE_USERINFO_URL)
        info_req.add_header("Authorization", f"Bearer {access_token}")
        with urllib.request.urlopen(info_req, timeout=15) as resp:
            user_info = json.loads(resp.read())

        return {
            "id":         user_info.get("sub"),          # Google's stable user ID
            "identifier": user_info.get("email", ""),
            "name":       user_info.get("name", ""),
            "provider":   "google",
        }

    except Exception:
        return None
    finally:
        server.shutdown()


def is_configured() -> bool:
    return _CREDENTIALS_CONFIGURED
