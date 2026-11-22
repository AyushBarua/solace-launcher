"""
ProfileScreen — Netflix-style "Who's Playing?" screen.
Centered profile tiles, click to enter instantly.
"""
import os
import sys
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QGraphicsDropShadowEffect, QScrollArea, QApplication
)
from PyQt6.QtCore import (Qt, QPropertyAnimation, QEasingCurve, pyqtSignal,
                          QSize, QRect, pyqtProperty, QPoint)
from PyQt6.QtGui import (QColor, QPainter, QPainterPath, QLinearGradient,
                         QFont, QKeyEvent, QFontDatabase, QCursor)

from core.theme import (FONT_DISPLAY, FONT_BODY, ON_SURFACE, ON_SURFACE_VAR,
                        PRIMARY_CONTAINER, SURFACE_DIM, OUTLINE_VARIANT,
                        ON_PRIMARY_FIXED_VARIANT, PRIMARY_FIXED, SURFACE_VARIANT,
                        PRIMARY, ON_PRIMARY, SURFACE_CON, SURFACE_CON_LOW, OUTLINE)
from core.profile_manager import (load_profiles, create_profile, delete_profile,
                                   set_active_profile, get_active_profile)

AVATARS = ["🧑‍⚕️", "🧑", "👦", "👧", "👨", "👩", "🧓", "👴", "👵", "🙂", "😎", "🥳", "👽", "🤖", "👻", "🤠"]
COLORS  = ["#D2A857", "#5B9BD5", "#70B87E", "#C26B6B", "#9B7EC8", "#E08A4F",
           "#5BBDB8", "#D46BA3", "#8BC34A", "#FF7043", "#26A69A", "#7E57C2",
           "#F4D03F", "#E74C3C", "#34495E", "#8E44AD"]

TILE_SIZE   = 160
TILE_TOP    = 8      # room above the tile so its hover/selected swell is not clipped
TILE_GAP    = 32
from core.theme import BACKGROUND as BG_COLOR
from core.theme import PRIMARY as _PRIMARY, ON_PRIMARY as _ON_PRIMARY
from ui import glass as _g
HOVER_SCALE = 1.08


# ──────────────────────────────────────────────────────────────────────────────
# Avatar / colour picker (reused in dialog)
# ──────────────────────────────────────────────────────────────────────────────
class AvatarPicker(QWidget):
    avatar_changed = pyqtSignal(str)
    color_changed  = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_avatar = AVATARS[0]
        self.selected_color  = COLORS[0]

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(0, 0, 0, 0)

        for label_text, items, is_color in [
            ("Avatar", AVATARS, False),
            ("Colour",  COLORS,  True),
        ]:
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"color:{ON_SURFACE_VAR}; font-family:'{FONT_BODY}'; font-size:13px; background:transparent;")
            root.addWidget(lbl)

            row_w = QWidget()
            row_w.setObjectName("pickerRow")
            row_w.setStyleSheet(f"QWidget#pickerRow {{ background: {SURFACE_CON}; border-radius: 16px; }}")
            row_l = QHBoxLayout(row_w)
            row_l.setSpacing(6)
            row_l.setContentsMargins(8, 8, 8, 8)

            self._av_btns  = getattr(self, '_av_btns',  [])
            self._col_btns = getattr(self, '_col_btns', [])

            for item in items:
                btn = QPushButton(item if not is_color else "")
                if is_color:
                    btn.setFixedSize(46, 46)
                    btn.setStyleSheet(f"QPushButton{{background:{item};border:3px solid transparent;border-radius:23px;}}QPushButton:hover{{border:3px solid white;}}")
                    btn.clicked.connect(lambda _, c=item: self._pick_color(c))
                    self._col_btns.append((item, btn))
                else:
                    btn.setFixedSize(46, 46)
                    btn.setStyleSheet(f"QPushButton{{font-size:22px;background:{SURFACE_DIM};border:2px solid transparent;border-radius:10px;}}QPushButton:hover{{border:2px solid {OUTLINE_VARIANT};}}")
                    btn.clicked.connect(lambda _, a=item: self._pick_avatar(a))
                    self._av_btns.append((item, btn))
                row_l.addWidget(btn)

            row_l.addStretch()
            root.addWidget(row_w)

        self._pick_avatar(AVATARS[0])
        self._pick_color(COLORS[0])

    def _pick_avatar(self, av):
        self.selected_avatar = av
        for a, btn in self._av_btns:
            sel = a == av
            btn.setStyleSheet(f"QPushButton{{font-size:22px;background:{SURFACE_DIM};border:2px solid {''+PRIMARY_CONTAINER if sel else 'transparent'};border-radius:10px;}}QPushButton:hover{{border:2px solid {OUTLINE_VARIANT};}}")
        self.avatar_changed.emit(av)

    def _pick_color(self, col):
        self.selected_color = col
        for c, btn in self._col_btns:
            sel = c == col
            btn.setStyleSheet(f"QPushButton{{background:{c};border:3px solid {'white' if sel else 'transparent'};border-radius:23px;}}QPushButton:hover{{border:3px solid white;}}")
        self.color_changed.emit(col)


# ──────────────────────────────────────────────────────────────────────────────
# New profile dialog
# ──────────────────────────────────────────────────────────────────────────────
class NewProfileDialog(QDialog):
    profile_created = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(980, 560)

        bg = QWidget(self)
        bg.setGeometry(0, 0, 980, 560)
        bg.setObjectName("dialogBg")
        bg.setStyleSheet(f"QWidget#dialogBg {{ background:{SURFACE_CON_LOW}; border-radius:20px; border:1px solid {OUTLINE_VARIANT}; }}")
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(80); shadow.setColor(QColor(0,0,0,220)); shadow.setOffset(0,12)
        bg.setGraphicsEffect(shadow)

        inner = QVBoxLayout(bg)
        inner.setContentsMargins(48, 40, 48, 40)
        inner.setSpacing(18)

        title = QLabel("Create Profile")
        title.setStyleSheet(f"color:{ON_SURFACE}; font-family:'{FONT_DISPLAY}'; font-size:32px; font-weight:bold; background:transparent;")
        inner.addWidget(title)

        # Preview row
        prev_row = QHBoxLayout(); prev_row.setSpacing(24)
        self._preview = QLabel(AVATARS[0])
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setFixedSize(100, 100)
        self._preview.setStyleSheet(f"font-size:52px; background:{COLORS[0]}; border-radius:12px;")
        prev_row.addWidget(self._preview)

        name_col = QVBoxLayout(); name_col.setSpacing(6)
        name_lbl = QLabel("Display Name")
        name_lbl.setStyleSheet(f"color:{ON_SURFACE_VAR}; font-size:13px; background:transparent;")
        self._name = QLineEdit()
        self._name.setPlaceholderText("Your name…")
        self._name.setStyleSheet(f"""
            QLineEdit{{background:{SURFACE_CON}; color:{ON_SURFACE}; border:1px solid {OUTLINE_VARIANT};
                      border-radius:10px; padding:12px 16px;
                      font-family:'{FONT_DISPLAY}'; font-size:20px;}}
            QLineEdit:focus{{border:1px solid {PRIMARY_CONTAINER};}}
        """)
        name_col.addWidget(name_lbl); name_col.addWidget(self._name); name_col.addStretch()
        prev_row.addLayout(name_col)
        inner.addLayout(prev_row)

        self._picker = AvatarPicker()
        self._picker.avatar_changed.connect(lambda a: self._preview.setText(a))
        self._picker.color_changed.connect(lambda c: self._preview.setStyleSheet(f"font-size:52px; background:{c}; border-radius:12px;"))
        inner.addWidget(self._picker)
        inner.addStretch()

        btn_row = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setFixedHeight(46)
        cancel.setStyleSheet(f"QPushButton{{background:transparent;color:{ON_SURFACE_VAR};border:1px solid {OUTLINE_VARIANT};border-radius:10px;padding:0 28px;font-size:15px;}}QPushButton:hover{{background:{SURFACE_CON};}}")
        cancel.clicked.connect(self.reject)

        ok = QPushButton("Create")
        ok.setFixedHeight(46)
        ok.setStyleSheet(f"QPushButton{{background:{PRIMARY_CONTAINER};color:{ON_PRIMARY};border:none;border-radius:10px;padding:0 32px;font-size:15px;font-weight:bold;}}QPushButton:hover{{background:{PRIMARY};color:{ON_PRIMARY};}}")
        ok.clicked.connect(self._create)
        btn_row.addWidget(cancel); btn_row.addStretch(); btn_row.addWidget(ok)
        inner.addLayout(btn_row)

    def _create(self):
        name = self._name.text().strip()
        if not name:
            self._name.setPlaceholderText("Enter a name!"); return
        profile = create_profile(name, self._picker.selected_avatar, self._picker.selected_color)
        self.profile_created.emit(profile)
        self.accept()


# ──────────────────────────────────────────────────────────────────────────────
# A single Netflix-style profile tile
# ──────────────────────────────────────────────────────────────────────────────
class ProfileTile(QWidget):
    clicked = pyqtSignal(dict)
    delete_requested = pyqtSignal(str)

    def __init__(self, profile: dict, parent=None):
        super().__init__(parent)
        self.profile  = profile
        self._selected = False
        self._scale   = 1.0
        self.setFixedSize(TILE_SIZE + 20, TILE_SIZE + 56 + TILE_TOP)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Delete button (top-right, hidden until hover)
        self._del = QPushButton("✕", self)
        self._del.setFixedSize(26, 26)
        self._del.move(self.width() - 30, 4)
        self._del.setStyleSheet("QPushButton{background:rgba(200,50,50,0.85);color:white;border:none;border-radius:13px;font-size:12px;}QPushButton:hover{background:#cc3333;}")
        self._del.hide()
        self._del.clicked.connect(lambda: self.delete_requested.emit(profile["id"]))

    def set_selected(self, v):
        self._selected = v
        self.update()

    def enterEvent(self, e):
        self._del.show()
        self.update()

    def leaveEvent(self, e):
        self._del.hide()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.profile)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        color  = self.profile.get("color", COLORS[0])
        avatar = self.profile.get("avatar", "🧑")
        name   = self.profile.get("name", "Player")

        hovered   = self.underMouse()
        tile_w    = TILE_SIZE
        tile_h    = TILE_SIZE
        offset_x  = 10   # centre padding
        offset_y  = TILE_TOP

        # Scale up on hover / selection
        scale = HOVER_SCALE if (hovered or self._selected) else 1.0
        scaled_w = int(tile_w * scale)
        scaled_h = int(tile_h * scale)
        x = offset_x + (tile_w - scaled_w) // 2
        y = offset_y + (tile_h - scaled_h) // 2

        # Tile background
        tile_rect = QRect(x, y, scaled_w, scaled_h)
        path = QPainterPath()
        path.addRoundedRect(float(x), float(y), float(scaled_w), float(scaled_h), 10, 10)

        # Gradient fill
        grad = QLinearGradient(x, y, x + scaled_w, y + scaled_h)
        c = QColor(color)
        darker = c.darker(180)
        grad.setColorAt(0, c)
        grad.setColorAt(1, darker)
        p.fillPath(path, grad)

        # Selection/hover border
        if self._selected:
            from PyQt6.QtGui import QPen
            pen = QPen(QColor(_PRIMARY), 4)           # ink ring: black on light, off-white on dark
            p.setPen(pen)
            p.drawPath(path)
        elif hovered:
            from PyQt6.QtGui import QPen
            ink = QColor(_PRIMARY)
            ink.setAlpha(110)
            pen = QPen(ink, 2)
            p.setPen(pen)
            p.drawPath(path)

        # Avatar emoji
        p.setPen(QColor("white"))
        emoji_font = QFont()
        emoji_font.setPixelSize(int(scaled_h * 0.48))
        p.setFont(emoji_font)
        p.drawText(tile_rect, Qt.AlignmentFlag.AlignCenter, avatar)

        # Name label below the tile
        name_y = TILE_TOP + tile_h + 8
        name_rect = QRect(0, name_y, self.width(), 36)
        name_font = QFont(FONT_DISPLAY)
        name_font.setPixelSize(15)
        name_font.setBold(self._selected)
        p.setFont(name_font)
        p.setPen(QColor(ON_SURFACE if (hovered or self._selected) else ON_SURFACE_VAR))
        p.drawText(name_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, name)


# ──────────────────────────────────────────────────────────────────────────────
# Add-profile tile
# ──────────────────────────────────────────────────────────────────────────────
class AddTile(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(TILE_SIZE + 20, TILE_SIZE + 56 + TILE_TOP)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        hovered = self.underMouse()
        scale   = HOVER_SCALE if hovered else 1.0
        tile_w  = TILE_SIZE
        scaled  = int(tile_w * scale)
        x = 10 + (tile_w - scaled) // 2
        y = TILE_TOP + (tile_w - scaled) // 2

        path = QPainterPath()
        path.addRoundedRect(float(x), float(y), float(scaled), float(scaled), 10, 10)

        bg = QColor(SURFACE_CON) if hovered else QColor(SURFACE_CON_LOW)
        p.fillPath(path, bg)

        from PyQt6.QtGui import QPen
        pen = QPen(QColor(OUTLINE), 2, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawPath(path)

        # Plus icon
        plus_font = QFont()
        plus_font.setPixelSize(int(scaled * 0.38))
        p.setFont(plus_font)
        p.setPen(QColor(PRIMARY_CONTAINER if hovered else ON_SURFACE_VAR))
        p.drawText(QRect(x, y, scaled, scaled), Qt.AlignmentFlag.AlignCenter, "+")

        # Label
        name_rect = QRect(0, TILE_TOP + TILE_SIZE + 8, self.width(), 36)
        name_font = QFont(FONT_DISPLAY); name_font.setPixelSize(15)
        p.setFont(name_font)
        p.setPen(QColor(PRIMARY_CONTAINER if hovered else ON_SURFACE_VAR))
        p.drawText(name_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "Add Profile")


# ──────────────────────────────────────────────────────────────────────────────
# Main profile screen
# ──────────────────────────────────────────────────────────────────────────────
class ProfileScreen(QDialog):
    profile_selected = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Solace — Who's Playing?")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setStyleSheet(f"background:{BG_COLOR};")
        self.showMaximized()

        self._tiles: list[ProfileTile] = []
        self._selected_idx = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Title ──────────────────────────────────────────────────────────────
        title_w = QWidget()
        title_w.setStyleSheet("background:transparent;")
        title_l = QVBoxLayout(title_w)
        title_l.setContentsMargins(0, 80, 0, 56)
        title_l.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._title = QLabel("Who's Playing?")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet(f"color:{ON_SURFACE}; font-family:'{FONT_DISPLAY}'; font-size:56px; font-weight:800; letter-spacing:-1px; background:transparent;")
        title_l.addWidget(self._title)
        root.addWidget(title_w)

        # ── Tiles row (centred) ────────────────────────────────────────────────
        self._tiles_container = QWidget()
        self._tiles_container.setStyleSheet("background:transparent;")
        self._tiles_row = QHBoxLayout(self._tiles_container)
        self._tiles_row.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._tiles_row.setSpacing(TILE_GAP)
        self._tiles_row.setContentsMargins(80, 0, 80, 0)

        root.addWidget(self._tiles_container, stretch=1)

        # ── Manage button (bottom centre) ──────────────────────────────────────
        bottom_w = QWidget(); bottom_w.setStyleSheet("background:transparent;")
        bottom_l = QVBoxLayout(bottom_w)
        bottom_l.setContentsMargins(0, 0, 0, 56)
        bottom_l.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._manage_btn = QPushButton("Manage Profiles")
        self._manage_btn.setFixedHeight(46)
        self._manage_btn.setMinimumWidth(200)
        self._manage_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {ON_SURFACE_VAR};
                border: 1px solid {_g.tint(0.28)};
                border-radius: 24px;
                font-family: '{FONT_DISPLAY}';
                font-size: 16px;
                font-weight: bold;
                padding: 0 32px;
            }}
            QPushButton:hover {{
                color: {_ON_PRIMARY};
                background: {_PRIMARY};
                border: 1px solid {_PRIMARY};
            }}
        """)
        self._manage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manage_btn.clicked.connect(self._open_new_profile)
        bottom_l.addWidget(self._manage_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(bottom_w)

        self._build_tiles()
        self.setFocus()

    def _build_tiles(self):
        while self._tiles_row.count():
            item = self._tiles_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._tiles.clear()

        for p in load_profiles():
            tile = ProfileTile(p)
            tile.clicked.connect(self._on_tile_clicked)
            tile.delete_requested.connect(self._delete_profile)
            self._tiles_row.addWidget(tile)
            self._tiles.append(tile)

        add = AddTile()
        add.clicked.connect(self._open_new_profile)
        self._tiles_row.addWidget(add)

        if self._tiles:
            self._selected_idx = max(0, min(self._selected_idx, len(self._tiles) - 1))
            self._refresh_selection()

    def _on_tile_clicked(self, profile: dict):
        # Single click = enter immediately (most accessible for patients)
        self._enter(profile)

    def _refresh_selection(self):
        for i, t in enumerate(self._tiles):
            t.set_selected(i == self._selected_idx)

    def _enter(self, profile: dict):
        set_active_profile(profile)
        self.profile_selected.emit(profile)
        self.accept()

    def _delete_profile(self, pid: str):
        delete_profile(pid)
        self._selected_idx = 0
        self._build_tiles()

    def _open_new_profile(self):
        dlg = NewProfileDialog(self)
        dlg.profile_created.connect(self._on_new_profile)
        dlg.exec()

    def _on_new_profile(self, profile: dict):
        self._build_tiles()
        for i, t in enumerate(self._tiles):
            if t.profile["id"] == profile["id"]:
                self._selected_idx = i
        self._refresh_selection()

    def keyPressEvent(self, e: QKeyEvent):
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._selected_idx = max(0, self._selected_idx - 1)
            self._refresh_selection()
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._selected_idx = min(len(self._tiles) - 1, self._selected_idx + 1)
            self._refresh_selection()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self._tiles:
                self._enter(self._tiles[self._selected_idx].profile)
        else:
            super().keyPressEvent(e)

    def nav_action(self, action: str):
        if action == 'left':
            self._selected_idx = max(0, self._selected_idx - 1); self._refresh_selection()
        elif action == 'right':
            self._selected_idx = min(len(self._tiles) - 1, self._selected_idx + 1); self._refresh_selection()
        elif action == 'action':
            if self._tiles: self._enter(self._tiles[self._selected_idx].profile)
