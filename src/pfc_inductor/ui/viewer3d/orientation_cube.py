"""Top-right orientation cube widget.

Renders a small isometric cube with axis-coloured faces and labels
(±X/±Y/±Z). Clicking a face emits ``face_clicked(name)`` where name
is one of ``+x | -x | +y | -y | +z | -z``. The viewer maps that to a
canonical camera preset.

The cube tracks the live camera direction: as the user orbits the
3D scene, :meth:`update_from_camera` recomputes which 3 faces are
visible (the ones whose outward normal has positive dot product with
the camera direction). The polygon geometry stays fixed; only the
face *labels* and *colours* swap so the cube keeps reading correctly.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

# Axis colours echo VTK's defaults — easy to recognise in 3D apps.
_AXIS_COLORS = {
    "+x": QColor("#E84545"),  # red
    "-x": QColor("#7D2222"),
    "+y": QColor("#3DB36C"),  # green
    "-y": QColor("#1F6B3F"),
    "+z": QColor("#3D7BD5"),  # blue
    "-z": QColor("#23457A"),
}

_AXIS_TO_VIEW = {
    "+y": "front",
    "-y": "front",
    "+z": "top",
    "-z": "top",
    "+x": "side",
    "-x": "side",
}


class OrientationCube(QWidget):
    """Compact orientation cube — 60×60 px self-painted."""

    SIZE = 60
    face_clicked = Signal(str)  # +x / -x / +y / -y / +z / -z
    view_requested = Signal(str)  # canonical view name (front/top/side)

    # Polygon slot → which face is currently rendered there.
    # Default: iso view sees +Z (top), +X (right), +Y (front-left).
    _DEFAULT_SLOT_TO_FACE = {
        "top": "+z",
        "right": "+x",
        "front": "+y",
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._slot_polygons: dict[str, QPolygonF] = {}
        self._slot_to_face: dict[str, str] = dict(self._DEFAULT_SLOT_TO_FACE)
        self._compute_polygons()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Draw each visible face into its slot polygon.
        for slot, poly in self._slot_polygons.items():
            face_name = self._slot_to_face[slot]
            p.setBrush(QBrush(_AXIS_COLORS[face_name]))
            p.setPen(QPen(QColor("#22ffffff"), 1))
            p.drawPolygon(poly)
            label = face_name.replace("+", "").replace("-", "").upper()
            sign = "+" if face_name.startswith("+") else "−"
            text = sign + label
            self._draw_label(p, poly, text)

    def _draw_label(self, p: QPainter, poly: QPolygonF, text: str) -> None:
        n = poly.size()
        if n == 0:
            return
        cx = sum(poly.at(i).x() for i in range(n)) / n
        cy = sum(poly.at(i).y() for i in range(n)) / n
        p.setPen(QPen(QColor("#FFFFFF")))
        font = p.font()
        font.setPixelSize(8)
        font.setBold(True)
        p.setFont(font)
        rect = QRectF(cx - 12, cy - 6, 24, 12)
        p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)

    # ------------------------------------------------------------------
    # Hit testing
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        pos = QPointF(event.position())
        for slot, poly in self._slot_polygons.items():
            if poly.containsPoint(pos, Qt.FillRule.OddEvenFill):
                face_name = self._slot_to_face[slot]
                self.face_clicked.emit(face_name)
                view = _AXIS_TO_VIEW.get(face_name)
                if view is not None:
                    self.view_requested.emit(view)
                return
        return super().mousePressEvent(event)

    # ------------------------------------------------------------------
    # Camera-tracking
    # ------------------------------------------------------------------
    def update_from_camera(self, payload: dict) -> None:
        """Re-compute which faces are visible from the camera direction.

        ``payload`` is the ``camera_changed`` dict emitted by
        :class:`CoreView3D`: ``{"position": (x, y, z),
        "focal": (x, y, z), "up": (x, y, z)}``.

        We pick the 3 visible faces by the sign of the camera-direction
        components (the vector pointing *from* the focal point *to* the
        camera). For each axis, the face whose outward normal has the
        same sign is the visible one.
        """
        try:
            pos = payload.get("position", (1.0, -1.0, 1.0))
            focal = payload.get("focal", (0.0, 0.0, 0.0))
        except AttributeError:
            return
        dx = float(pos[0]) - float(focal[0])
        dy = float(pos[1]) - float(focal[1])
        dz = float(pos[2]) - float(focal[2])

        face_x = "+x" if dx >= 0 else "-x"
        face_y = "+y" if dy >= 0 else "-y"
        face_z = "+z" if dz >= 0 else "-z"

        # Slot mapping is stable: "right" always maps to the visible
        # X-axis face, "top" to the Z-axis face, "front" to the Y-axis
        # face. We only swap the +/- which face fills each slot.
        new_map = {"top": face_z, "right": face_x, "front": face_y}
        if new_map != self._slot_to_face:
            self._slot_to_face = new_map
            self.update()

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------
    def _compute_polygons(self) -> None:
        """Pre-compute the 3 visible faces of an isometric cube.

        The cube is rendered with the +X face on the right, +Z on top,
        and +Y facing the user (front). Hidden faces are not drawn but
        still hit-test via inverted regions of the visible faces — the
        user clicks the face *they see*, never the hidden one. This is
        consistent with most CAD orientation cubes.
        """
        s = self.SIZE
        cx = s / 2
        cy = s / 2 + 4
        d = s * 0.30  # half edge

        # Three visible face polygons: +Z (top), +Y (front), +X (right)
        # In screen coords: +X right, -Y up.
        # Top face (+Z): rhombus on top.
        top = QPolygonF(
            [
                QPointF(cx, cy - 1.10 * d),
                QPointF(cx + 1.05 * d, cy - 0.55 * d),
                QPointF(cx, cy),
                QPointF(cx - 1.05 * d, cy - 0.55 * d),
            ]
        )
        # Right face (+X): tilted rectangle on right.
        right = QPolygonF(
            [
                QPointF(cx + 1.05 * d, cy - 0.55 * d),
                QPointF(cx + 1.05 * d, cy + 0.65 * d),
                QPointF(cx, cy + 1.20 * d),
                QPointF(cx, cy),
            ]
        )
        # Front face (+Y): tilted rectangle on left.
        front = QPolygonF(
            [
                QPointF(cx - 1.05 * d, cy - 0.55 * d),
                QPointF(cx, cy),
                QPointF(cx, cy + 1.20 * d),
                QPointF(cx - 1.05 * d, cy + 0.65 * d),
            ]
        )
        # Slot polygons (stable geometry); the *face* drawn into each
        # slot rotates with the camera via :meth:`update_from_camera`.
        self._slot_polygons = {
            "top": top,
            "right": right,
            "front": front,
        }
