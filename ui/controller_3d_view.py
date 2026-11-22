"""
Controller3DView — QWebEngineView rendering StrokeBrush.glb via Three.js.

Spins up a tiny localhost HTTP server to serve the assets/ folder so that:
  • Chromium cache is bypassed (timestamp query param on every launch)
  • GLB loads without any file:// security restrictions
  • No PyQt6-WebEngine profile hacks needed

Requirements:  pip install PyQt6-WebEngine
ImportError here → caller falls back to QPainter Controller3DWidget.
"""
import os
import sys
import time
import threading
import http.server
import socketserver

from PyQt6.QtWebEngineWidgets import QWebEngineView          # ImportError if missing
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QColor

if getattr(sys, 'frozen', False):          # compiled PyInstaller build
    _ASSETS = os.path.join(sys._MEIPASS, 'assets')
else:                                        # dev mode
    _HERE   = os.path.dirname(os.path.abspath(__file__))
    _ASSETS = os.path.normpath(os.path.join(_HERE, '..', 'assets'))

# ── One shared HTTP server for the whole process ──────────────────────────────
_PORT: int | None = None
_PORT_LOCK = threading.Lock()


def _get_port() -> int:
    global _PORT
    with _PORT_LOCK:
        if _PORT is None:
            class _Handler(http.server.SimpleHTTPRequestHandler):
                def __init__(self, *a, **kw):
                    super().__init__(*a, directory=_ASSETS, **kw)
                def log_message(self, *a):
                    pass  # silence request logs

            server = socketserver.TCPServer(('127.0.0.1', 0), _Handler)
            _PORT = server.server_address[1]
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
    return _PORT


class Controller3DView(QWebEngineView):
    def __init__(self, parent=None):
        super().__init__(parent)

        s = self.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        self.page().setBackgroundColor(QColor(0, 0, 0, 0))

        # Demo calls arriving before the page (and model) finish loading would
        # silently no-op — queue them and replay once loaded.
        self._page_loaded = False
        self._pending_demo = None
        self.page().loadFinished.connect(self._on_load_finished)

        # Timestamp busts the browser cache on every app launch
        port = _get_port()
        ts   = int(time.time())
        self.setUrl(QUrl(f"http://127.0.0.1:{port}/controller_view.html?v={ts}"))

    def _on_load_finished(self, ok: bool):
        self._page_loaded = True
        if ok and self._pending_demo:
            kind, secs = self._pending_demo
            self._pending_demo = None
            # small extra delay so the GLB model is on screen before the demo
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(900, lambda: self.play_demo(kind, secs))

    # movement/direction -> (demo axis, sign) for the 3D demonstration
    _DEMO_MAP = {
        "flexion":  ("flex", 1), "extension":  ("flex", -1),
        "pronation": ("pron", 1), "supination": ("pron", -1),
        "down":     ("flex", 1), "up":          ("flex", -1),
        "right":    ("pron", 1), "left":        ("pron", -1),
    }

    def play_demo(self, kind: str, secs: float = 2.6):
        """Make the model demonstrate a movement (pauses live feed briefly)."""
        if not self._page_loaded:
            self._pending_demo = (kind, secs)   # replayed on loadFinished
            return
        axis, sign = self._DEMO_MAP.get(kind, (None, 1))
        if axis:
            self.page().runJavaScript(
                f"if(typeof window.demoMove==='function')"
                f" window.demoMove('{axis}',{sign},{secs});"
            )

    def update_axes(self, raw_x: float, raw_y: float):
        """Reconstruct true anatomical angles from normalised axes and
        drive the 3D model so it mirrors the physical controller."""
        from core.units import axis_to_degrees
        pronsup_deg, flex_deg = axis_to_degrees(raw_x, raw_y)
        self.page().runJavaScript(
            f"if(typeof window.setPose==='function')"
            f" window.setPose({flex_deg:.2f},{pronsup_deg:.2f});"
        )
