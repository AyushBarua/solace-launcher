"""
Controller3DWidget — real-time 3D visualisation of the Stroky Brush controller.

Renders a perspective-projected 3D controller body using pure QPainter.
No extra dependencies — pure PyQt6.

Feed live raw axis values from GamepadThread.raw_axes:
  raw_x  →  pronation/supination (sideways lean),  per-direction range
  raw_y  →  flexion/extension (spin about the vertical grip axis)
Ranges match Solace_Gamepad_v3.1 firmware: flex +50/-43, pron +63/sup -72 deg.

The box is drawn with painter's-algorithm face sorting so near faces
always overdraw far ones.  Face colours follow the active app theme.
"""

import math
from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPolygonF,
    QLinearGradient, QFont,
)


# ── pure-Python 3-D math (no numpy) ──────────────────────────────────────────

def _rx(vx, vy, vz, a):
    """Rotate around X axis."""
    c, s = math.cos(a), math.sin(a)
    return vx, vy * c - vz * s, vy * s + vz * c


def _ry(vx, vy, vz, a):
    """Rotate around Y axis."""
    c, s = math.cos(a), math.sin(a)
    return vx * c + vz * s, vy, -vx * s + vz * c


def _rz(vx, vy, vz, a):
    """Rotate around Z axis."""
    c, s = math.cos(a), math.sin(a)
    return vx * c - vy * s, vx * s + vy * c, vz


def _project(vx, vy, vz, cx, cy, fov=420, cam_z=380):
    """Perspective project a 3-D point to screen (cx, cy)."""
    z = vz + cam_z
    if z < 1.0:
        z = 1.0
    return cx + fov * vx / z, cy + fov * vy / z


# ── Controller3DWidget ────────────────────────────────────────────────────────

class Controller3DWidget(QWidget):
    """
    Live 3-D controller preview widget.

    Usage
    -----
    widget = Controller3DWidget(parent)
    gamepad_thread.raw_axes.connect(widget.update_axes)
    """

    # Controller box half-extents (3-D units) — tall vertical grip
    _W = 30     # half-width  (left–right)
    _H = 105    # half-height (grip length, vertical)
    _D = 30     # half-depth  (front–back)

    # Fixed ambient view angle so the box looks 3-D at rest
    _AX = math.radians(-22)   # tilt slightly top-down
    _AY = math.radians(18)    # tilt slightly to the right

    def __init__(self, parent=None):
        super().__init__(parent)
        self._flex    = 0.0   # radians, flexion/extension (vertical spin)
        self._pronsup = 0.0   # radians, pronation/supination (sideways lean)
        self.setMinimumSize(300, 180)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    # ── public API ────────────────────────────────────────────────────────────

    def play_demo(self, kind: str, secs: float = 2.6):
        """Demo animations aren't implemented in the QPainter fallback."""
        pass

    def update_axes(self, raw_x: float, raw_y: float):
        """
        Drive the 3-D rotation from live raw gamepad axes.

        raw_x  – pronation(+)/supination(-) axis, range [-1, 1]
        raw_y  – flexion(+)/extension(-)   axis, range [-1, 1]
        """
        from core.units import axis_to_degrees
        pronsup_deg, flex_deg = axis_to_degrees(raw_x, raw_y)
        self._pronsup = math.radians(pronsup_deg)
        self._flex    = math.radians(flex_deg)
        self.update()

    # ── internal geometry ─────────────────────────────────────────────────────

    def _base_vertices(self):
        W, H, D = self._W, self._H, self._D
        # 8 corners of the box
        return [
            (-W, -H, -D), ( W, -H, -D), ( W,  H, -D), (-W,  H, -D),  # 0-3 back
            (-W, -H,  D), ( W, -H,  D), ( W,  H,  D), (-W,  H,  D),  # 4-7 front
        ]

    def _transform(self, verts):
        flex    = self._flex
        pronsup = self._pronsup
        ax, ay = self._AX, self._AY
        out = []
        for vx, vy, vz in verts:
            # 1. Apply live controller movement (matches the real device)
            vx, vy, vz = _ry(vx, vy, vz, flex)     # flexion = spin about vertical grip axis
            vx, vy, vz = _rz(vx, vy, vz, pronsup)  # pron/sup = sideways lean
            # 2. Apply fixed ambient view angle
            vx, vy, vz = _rx(vx, vy, vz, ax)
            vx, vy, vz = _ry(vx, vy, vz, ay)
            out.append((vx, vy, vz))
        return out

    # ── painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        import core.theme as _t

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0 + 10   # shift slightly down for label

        # ── transform + project ───────────────────────────────────────────────
        trans    = self._transform(self._base_vertices())
        proj2d   = [_project(vx, vy, vz, cx, cy) for vx, vy, vz in trans]
        depth    = [vz for _, _, vz in trans]

        def qpt(i):
            return QPointF(*proj2d[i])

        # ── face definitions ─────────────────────────────────────────────────
        # (name, vertex-index list)
        FACES = [
            ("top",    [3, 2, 6, 7]),
            ("bottom", [0, 1, 5, 4]),
            ("front",  [4, 5, 6, 7]),
            ("back",   [0, 1, 2, 3]),
            ("left",   [0, 3, 7, 4]),
            ("right",  [1, 2, 6, 5]),
        ]

        def face_depth(face):
            _, idxs = face
            return sum(depth[i] for i in idxs) / len(idxs)

        faces_sorted = sorted(FACES, key=face_depth, reverse=True)

        # ── theme colours ─────────────────────────────────────────────────────
        c_top    = QColor(_t.PRIMARY_FIXED)
        c_main   = QColor(_t.PRIMARY_CONTAINER)
        c_dark   = QColor(_t.ON_PRIMARY_FIXED_VARIANT)
        c_edge   = QColor(_t.OUTLINE_VARIANT)

        # Darken/lighten helper
        def shade(base: QColor, factor: float) -> QColor:
            r = max(0, min(255, int(base.red()   * factor)))
            g = max(0, min(255, int(base.green() * factor)))
            b = max(0, min(255, int(base.blue()  * factor)))
            return QColor(r, g, b)

        face_color = {
            "top":    c_top,
            "front":  c_main,
            "right":  shade(c_main, 0.85),
            "left":   c_dark,
            "bottom": c_dark,
            "back":   shade(c_dark, 0.80),
        }

        pen = QPen(c_edge, 1.2)
        p.setPen(pen)

        for name, idxs in faces_sorted:
            poly = QPolygonF([qpt(i) for i in idxs])
            p.setBrush(QBrush(face_color[name]))
            p.drawPolygon(poly)

        # ── grip detail lines on top face ─────────────────────────────────────
        # Draw 3 parallel lines across the top face to suggest grip texture
        # Top face vertices: 3, 2, 6, 7  (back-right, front-right, front-left, back-left)
        top_pts = [qpt(i) for i in [3, 2, 6, 7]]
        grip_pen = QPen(shade(c_top, 0.75), 1.5)
        p.setPen(grip_pen)
        for t in (0.30, 0.50, 0.70):
            # Lerp along left edge (3→7) and right edge (2→6)
            def lerp(a, b, t):
                return QPointF(a.x() + (b.x() - a.x()) * t,
                               a.y() + (b.y() - a.y()) * t)
            lp = lerp(top_pts[0], top_pts[3], t)
            rp = lerp(top_pts[1], top_pts[2], t)
            p.drawLine(lp, rp)

        # ── flexion / pron-sup angle readout ─────────────────────────────────
        flex_deg    = math.degrees(self._flex)
        pronsup_deg = math.degrees(self._pronsup)

        label = f"Flex/Ext {flex_deg:+.1f}°   Pron/Sup {pronsup_deg:+.1f}°"
        lbl_color = QColor(_t.ON_SURFACE_VAR)

        font = QFont(_t.FONT_MONO, 11)
        p.setFont(font)
        p.setPen(QPen(lbl_color))
        p.drawText(0, h - 24, w, 20,
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                   label)

        p.end()
