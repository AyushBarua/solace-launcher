"""
StoreItem — Visual-first game card for the Rehab Store.

Layout (vertical):
  ┌────────────────────────────────────┐
  │                                    │
  │         GAME IMAGE (cover)         │  ← 340px tall, full width, clipped
  │                                    │
  ├────────────────────────────────────┤
  │  Title                     [+ADD]  │
  │  Short description                 │
  └────────────────────────────────────┘
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QLinearGradient

from core.image_loader import ImageLoader
from core.theme import (
    FONT_DISPLAY, FONT_BODY, FONT_MONO,
    ON_SURFACE, ON_SURFACE_VAR, PRIMARY, ON_PRIMARY, PRIMARY_FIXED,
    SURFACE_CON_HIGH, OUTLINE_VARIANT, BACKGROUND,
)


class _CoverImage(QWidget):
    """Full-bleed cover image widget with rounded top corners and gradient overlay at bottom."""

    RADIUS = 16  # must match card border-radius

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_pixmap(self, px: QPixmap):
        self._pixmap = px
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        w, h = self.width(), self.height()

        # Clip only TOP corners (bottom corners are square, card body is below)
        clip = QPainterPath()
        clip.moveTo(self.RADIUS, 0)
        clip.lineTo(w - self.RADIUS, 0)
        clip.quadTo(w, 0, w, self.RADIUS)
        clip.lineTo(w, h)
        clip.lineTo(0, h)
        clip.lineTo(0, self.RADIUS)
        clip.quadTo(0, 0, self.RADIUS, 0)
        clip.closeSubpath()
        p.setClipPath(clip)

        if self._pixmap and not self._pixmap.isNull():
            # Cover-fill (expand to fill, centre-crop)
            scaled = self._pixmap.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            ox = (scaled.width()  - w) // 2
            oy = (scaled.height() - h) // 2
            p.drawPixmap(0, 0, scaled, ox, oy, w, h)
        else:
            from core.theme import SURFACE_CON_HIGH
            p.fillRect(0, 0, w, h, QColor(SURFACE_CON_HIGH))

        # Gradient: transparent top → dark bottom (so title is readable)
        from core.theme import BACKGROUND
        bg = QColor(BACKGROUND)
        grad = QLinearGradient(0, h * 0.5, 0, h)
        grad.setColorAt(0.0, QColor(bg.red(), bg.green(), bg.blue(), 0))
        grad.setColorAt(1.0, QColor(bg.red(), bg.green(), bg.blue(), 200))
        p.fillRect(0, 0, w, h, grad)
        p.end()


class StoreItem(QFrame):
    add_clicked = pyqtSignal()

    def __init__(self, title: str, description: str, meta_html: str, image_url: str, is_installed: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("storeItem")
        self.setStyleSheet(f"""
            QFrame#storeItem {{
                background-color: {SURFACE_CON_HIGH};
                border: 1px solid {OUTLINE_VARIANT};
                border-radius: 16px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Cover image ───────────────────────────────────────────────────────
        self._cover = _CoverImage()
        root.addWidget(self._cover)

        # ── Text + button area ────────────────────────────────────────────────
        info = QWidget()
        info.setStyleSheet("background: transparent;")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(28, 20, 28, 24)
        info_layout.setSpacing(8)

        # Title row
        title_row = QHBoxLayout()
        title_row.setSpacing(16)

        self._lbl_title = QLabel(title)
        self._lbl_title.setStyleSheet(f"""
            color: {ON_SURFACE};
            font-family: "{FONT_DISPLAY}";
            font-size: 26px;
            font-weight: bold;
            background: transparent;
            border: none;
        """)
        title_row.addWidget(self._lbl_title, stretch=1)

        self.add_btn = QPushButton("LAUNCH" if is_installed else "DOWNLOAD")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setFixedSize(120, 44)
        self.add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {PRIMARY};
                color: {ON_PRIMARY};
                font-family: "{FONT_MONO}";
                font-size: 13px;
                font-weight: bold;
                border-radius: 22px;
                border: none;
            }}
            QPushButton:hover {{ background-color: {PRIMARY_FIXED}; }}
        """)
        self.add_btn.clicked.connect(self.add_clicked.emit)
        title_row.addWidget(self.add_btn)
        info_layout.addLayout(title_row)

        # Short description only (1-2 lines max)
        self._lbl_desc = QLabel(description)
        self._lbl_desc.setWordWrap(True)
        self._lbl_desc.setMaximumHeight(52)  # ~2 lines
        self._lbl_desc.setStyleSheet(f"""
            color: {ON_SURFACE_VAR};
            font-family: "{FONT_BODY}";
            font-size: 14px;
            background: transparent;
            border: none;
        """)
        info_layout.addWidget(self._lbl_desc)

        root.addWidget(info)

        # ── Load image ────────────────────────────────────────────────────────
        if image_url.startswith("http"):
            self._loader = ImageLoader(image_url, self)
            self._loader.loaded.connect(self._on_loaded)
            self._loader.failed.connect(self._on_failed)
            self._loader.start()
        else:
            px = QPixmap(image_url)
            if not px.isNull():
                self._on_loaded(image_url, px)
            else:
                self._on_failed(image_url)

    def set_selected(self, selected: bool):
        """Highlight this card with a bold border and glow when navigated to by controller."""
        self._selected = selected
        import core.theme as _t
        if selected:
            self.setStyleSheet(f"""
                QFrame#storeItem {{
                    background-color: {_t.SURFACE_CON_HIGH};
                    border: 5px solid {_t.PRIMARY};
                    border-radius: 16px;
                }}
            """)
            # Border-only highlight — no shadow (avoids QGraphicsProxyWidget clipping)
            self._cover.setWindowOpacity(1.0)
        else:
            self.setStyleSheet(f"""
                QFrame#storeItem {{
                    background-color: {_t.SURFACE_CON_HIGH};
                    border: 2px solid {_t.OUTLINE_VARIANT};
                    border-radius: 16px;
                }}
            """)
            self.setGraphicsEffect(None)
            self._cover.setWindowOpacity(0.6)

    def refresh_theme(self):
        import core.theme as _t
        self.set_selected(getattr(self, '_selected', False))
        self._lbl_title.setStyleSheet(f"""
            color: {_t.ON_SURFACE}; font-family: "{_t.FONT_DISPLAY}";
            font-size: 26px; font-weight: bold; background: transparent; border: none;
        """)
        self._lbl_desc.setStyleSheet(f"""
            color: {_t.ON_SURFACE_VAR}; font-family: "{_t.FONT_BODY}";
            font-size: 14px; background: transparent; border: none;
        """)
        self.add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_t.PRIMARY}; color: {_t.ON_PRIMARY};
                font-family: "{_t.FONT_MONO}"; font-size: 13px;
                font-weight: bold; border-radius: 22px; border: none;
            }}
            QPushButton:hover {{ background-color: {_t.PRIMARY_FIXED}; }}
        """)
        self._cover.update()

    def _on_loaded(self, _url: str, px: QPixmap):
        self._cover.set_pixmap(px)

    def _on_failed(self, _url: str):
        pass  # Cover widget shows grey placeholder automatically

    def set_downloading(self):
        self.add_btn.setText("DOWNLOADING...")
        self.add_btn.setEnabled(False)

    def set_installed(self):
        self.add_btn.setText("LAUNCH")
        self.add_btn.setEnabled(True)
