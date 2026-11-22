"""
GameCard — a 400px tall widget representing a game.
Replicates the Stitch "Trending Now" cards.

  ┌────────────────────────┐
  │  [image]               │
  │                        │
  │  Title                 │
  │  [ BADGE ]             │
  └────────────────────────┘

Features:
- Async image loading via ImageLoader
- Gradient overlay at the bottom so text is readable
- Hover effect: scale up image slightly, show amber border
"""
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QWidget, QGraphicsDropShadowEffect, QSizePolicy
from PyQt6.QtCore import Qt, QRectF, QPropertyAnimation, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QPainter, QLinearGradient, QColor, QPixmap, QPainterPath

from core.theme import (BACKGROUND, SURFACE_CON_HIGH2, ON_SURFACE, ON_SURFACE_VAR,
                         OUTLINE_VARIANT, PRIMARY, FONT_DISPLAY, FONT_MONO)
from core.image_loader import ImageLoader

_BG = QColor(BACKGROUND)


class GameCard(QFrame):
    CORNER_RADIUS = 12
    clicked = pyqtSignal()

    def __init__(self, title: str, badge_text: str, image_url: str, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(450)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        self._title = title
        self._badge = badge_text
        self._pixmap = None
        self._hover = False
        self._selected = False
        
        # For hover-to-launch in Library page
        self._progress = 0.0

        # Overlay layout for text
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addStretch()

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(24, 0, 24, 24)
        cl.setSpacing(8)

        lbl_title = QLabel(self._title)
        lbl_title.setStyleSheet(f"""
            color: {ON_SURFACE};
            font-family: "{FONT_DISPLAY}";
            font-size: 20px;
            font-weight: 600;
        """)
        lbl_title.setWordWrap(True)

        lbl_badge = QLabel(self._badge)
        lbl_badge.setFixedHeight(24)
        lbl_badge.setStyleSheet(f"""
            background-color: rgba(42,42,38,200);
            color: {ON_SURFACE_VAR};
            font-family: "{FONT_MONO}";
            font-size: 10px;
            font-weight: bold;
            border: 1px solid rgba(242,202,80,0.2);
            border-radius: 4px;
            padding: 0px 8px;
            letter-spacing: 1px;
        """)
        lbl_badge.setSizePolicy(lbl_badge.sizePolicy().Policy.Maximum, lbl_badge.sizePolicy().Policy.Fixed)

        cl.addWidget(lbl_title)
        cl.addWidget(lbl_badge)
        
        root.addWidget(content)

        if image_url.startswith("http"):
            self._loader = ImageLoader(image_url, self)
            self._loader.loaded.connect(self._on_image)
            self._loader.start()
        elif image_url:
            self._pixmap = QPixmap(image_url)

    def _on_image(self, url: str, px: QPixmap):
        self._pixmap = px
        self.update()

    def set_selected(self, selected: bool):
        self._selected = selected
        if not selected:
            self._progress = 0.0
        self.update()
        
    def set_progress(self, val: float):
        self._progress = max(0.0, min(1.0, val))
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )

        rect = QRectF(self.rect())

        clip = QPainterPath()
        clip.addRoundedRect(rect, self.CORNER_RADIUS, self.CORNER_RADIUS)
        p.setClipPath(clip)

        p.fillRect(rect, QColor(SURFACE_CON_HIGH2))

        if self._pixmap and not self._pixmap.isNull():
            # scale up slightly on hover
            scale = 1.05 if self._hover else 1.0
            w = int(self.width() * scale)
            h = int(self.height() * scale)
            
            px = self._pixmap.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            ox = (px.width() - self.width()) // 2
            oy = (px.height() - self.height()) // 2
            p.drawPixmap(0, 0, px, ox, oy, self.width(), self.height())

        # Gradient
        grad = QLinearGradient(0, self.height(), 0, 0)
        grad.setColorAt(0.0, QColor(_BG.red(), _BG.green(), _BG.blue(), 230))
        grad.setColorAt(0.6, QColor(_BG.red(), _BG.green(), _BG.blue(), 100))
        grad.setColorAt(1.0, QColor(_BG.red(), _BG.green(), _BG.blue(), 0))
        p.fillRect(rect, grad)

        # Border
        p.setClipRect(self.rect()) # clear clip path for drawing border correctly
        
        pen_color = QColor(PRIMARY) if (self._hover or self._selected) else QColor(OUTLINE_VARIANT)
        pen_width = 2 if (self._hover or self._selected) else 1
        
        p.setPen(pen_color)
        pen = p.pen()
        pen.setWidth(pen_width)
        p.setPen(pen)
        
        # Draw rounded rect border
        # Adjust rect to account for pen width to avoid clipping the border
        adj = pen_width / 2.0
        border_rect = rect.adjusted(adj, adj, -adj, -adj)
        p.drawRoundedRect(border_rect, self.CORNER_RADIUS, self.CORNER_RADIUS)
        
        # Draw progress bar if selected
        if self._selected and self._progress > 0:
            prog_rect = QRectF(0, self.height() - 4, self.width() * self._progress, 4)
            p.fillRect(prog_rect, QColor(PRIMARY))

        p.end()
