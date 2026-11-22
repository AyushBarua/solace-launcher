"""
HeroBanner — 500 px tall widget that replicates the Stitch featured section:

  ┌──────────────────────────────────────────────────────────────┐
  │  [background image, scale-to-fill]                           │
  │  [gradient: transparent top → opaque black bottom]           │
  │                                                              │
  │    FEATURED RELEASE                                          │
  │    Chronicles of the Fallen Kingdom                          │
  │    Explore a meticulously crafted world…                     │
  │    [ ↓  DOWNLOAD ]                                           │
  └──────────────────────────────────────────────────────────────┘

The image is loaded asynchronously and a dark placeholder is shown until ready.
Rounded corners (8 px) are painted via QPainterPath clipping so the image
corners are clipped correctly — no stylesheet border-radius tricks needed.
"""
from PyQt6.QtWidgets import (QFrame, QVBoxLayout, QWidget,
                              QLabel, QPushButton, QGraphicsDropShadowEffect)
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import (QPainter, QLinearGradient, QColor,
                          QPixmap, QPainterPath)

from core.theme import (BACKGROUND, SURFACE_CON, SURFACE_CON_HIGH,
                         ON_SURFACE, ON_SURFACE_VAR, PRIMARY, PRIMARY_CONTAINER,
                         ON_PRIMARY, FONT_DISPLAY, FONT_BODY, FONT_MONO,
                         PRIMARY_FIXED, HERO_IMAGE_URL)
from core.image_loader import ImageLoader


_BG = QColor(BACKGROUND)          # #131410 parsed once


class HeroBanner(QFrame):
    CORNER_RADIUS = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self.setMinimumHeight(550)
        self.setMaximumHeight(800)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        # ── overlay layout ────────────────────────────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addStretch()                          # push content to bottom

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(48, 0, 48, 48)
        cl.setSpacing(0)

        # FEATURED RELEASE badge
        badge = QLabel("FEATURED RELEASE")
        badge.setFixedHeight(28)
        badge.setStyleSheet(f"""
            background-color: rgba(42,42,38,200);
            color: {PRIMARY};
            font-family: "{FONT_MONO}";
            font-size: 11px;
            font-weight: 600;
            border: 1px solid rgba(242,202,80,0.25);
            border-radius: 4px;
            padding: 0px 12px;
            letter-spacing: 2px;
        """)
        badge.setFixedWidth(185)

        # Title
        title = QLabel("Space Warrior")
        title.setStyleSheet(f"""
            color: {ON_SURFACE};
            font-family: "{FONT_DISPLAY}";
            font-size: 42px;
            font-weight: bold;
            letter-spacing: -1px;
            background: transparent;
        """)
        title.setWordWrap(True)

        # Description
        desc = QLabel(
            "A vertical space shooter built specifically as a rehab game interface. "
            "Move the ship with wrist motion and shoot enemies to restore strength."
        )
        desc.setStyleSheet(f"""
            color: {ON_SURFACE_VAR};
            font-family: "{FONT_BODY}";
            font-size: 18px;
            background: transparent;
        """)
        desc.setWordWrap(True)
        desc.setMaximumWidth(580)

        # Download button
        dl = QPushButton("+   ADD")
        dl.setFixedSize(280, 64)
        dl.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {PRIMARY}, stop:1 {PRIMARY_CONTAINER}
                );
                color: {ON_PRIMARY};
                font-family: "{FONT_DISPLAY}";
                font-size: 22px;
                font-weight: bold;
                border-radius: 32px;
                border: none;
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {PRIMARY_FIXED}, stop:1 {PRIMARY}
                );
            }}
            QPushButton:pressed {{
                background: {PRIMARY_CONTAINER};
            }}
        """)
        glow = QGraphicsDropShadowEffect(dl)
        from PyQt6.QtGui import QColor as _QC
        from core.theme import PRIMARY_CONTAINER as _PC
        _gc = _QC(_PC); _gc.setAlpha(120)
        glow.setColor(_gc)
        glow.setBlurRadius(18)
        glow.setOffset(0, 4)
        dl.setGraphicsEffect(glow)

        cl.addWidget(badge)
        cl.addSpacing(16)
        cl.addWidget(title)
        cl.addSpacing(10)
        cl.addWidget(desc)
        cl.addSpacing(32)
        cl.addWidget(dl)

        root.addWidget(content)

        # ── async image load ──────────────────────────────────────────────────
        self._loader = ImageLoader(HERO_IMAGE_URL, self)
        self._loader.loaded.connect(self._on_image)
        self._loader.start()

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_image(self, _url: str, px: QPixmap):
        self._pixmap = px
        self.update()

    # ── painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )

        # Clip to rounded rect
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), self.CORNER_RADIUS, self.CORNER_RADIUS)
        p.setClipPath(clip)

        # Background image (cover)
        if self._pixmap and not self._pixmap.isNull():
            px = self._pixmap.scaled(
                self.width(), self.height(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            ox = (px.width()  - self.width())  // 2
            oy = (px.height() - self.height()) // 2
            p.drawPixmap(0, 0, px, ox, oy, self.width(), self.height())
        else:
            p.fillRect(self.rect(), QColor(SURFACE_CON))

        # Gradient overlay: opaque bottom → transparent top
        grad = QLinearGradient(0, self.height(), 0, 0)
        grad.setColorAt(0.00, QColor(_BG.red(), _BG.green(), _BG.blue(), 255))
        grad.setColorAt(0.45, QColor(_BG.red(), _BG.green(), _BG.blue(), 153))
        grad.setColorAt(1.00, QColor(_BG.red(), _BG.green(), _BG.blue(), 0))
        p.fillRect(self.rect(), grad)

        p.end()
