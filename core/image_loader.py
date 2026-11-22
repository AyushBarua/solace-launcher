"""
Async image loader: fetches images from URLs, caches locally,
emits a signal when the QPixmap is ready.
"""
import os
import hashlib
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QPixmap

# Cache lives next to this file's package root → assets/cache/
_HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(_HERE, "..", "assets", "cache")


class ImageLoader(QThread):
    """Downloads an image URL in a background thread and emits the QPixmap."""

    loaded = pyqtSignal(str, QPixmap)   # (url, pixmap)
    failed = pyqtSignal(str)            # (url)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _cache_path(url: str) -> str:
        os.makedirs(CACHE_DIR, exist_ok=True)
        fname = hashlib.md5(url.encode()).hexdigest() + ".jpg"
        return os.path.join(CACHE_DIR, fname)

    # ── thread body ───────────────────────────────────────────────────────────

    def run(self):
        path = self._cache_path(self.url)

        # Download only if not already cached
        if not os.path.exists(path):
            try:
                req = urllib.request.Request(
                    self.url,
                    headers={"User-Agent": "Mozilla/5.0 SolaceLauncher/1.0"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                with open(path, "wb") as fh:
                    fh.write(data)
            except Exception as exc:
                print(f"[ImageLoader] Failed to download {self.url}: {exc}")
                self.failed.emit(self.url)
                return

        px = QPixmap(path)
        if px.isNull():
            self.failed.emit(self.url)
        else:
            self.loaded.emit(self.url, px)
