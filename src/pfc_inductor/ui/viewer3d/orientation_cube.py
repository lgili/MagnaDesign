"""Top-right orientation cube widget.

Renders a small isometric cube with axis-coloured faces and labels (X/Y/Z).
Clicking a face emits ``face_clicked(name)`` where name is one of
``+x | -x | +y | -y | +z | -z``. The viewer maps that to a canonical
camera preset.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPolygonF, QPen, QBrush
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
    face_clicked = Signal(str)        # +x / -x / +y / -y / +z / -z
    view_requested = Signal(str)      # canonical view name (front/top/side)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._face_polygons: dict[str, QPolygonF] = {}
        self._compute_polygons()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Draw each face fill + outline + label.
        for name, poly in self._face_polygons.items():
            p.setBrush(QBrush(_AXIS_COLORS[name]))
            p.setPen(QPen(QColor("#22ffffff"), 1))
            p.drawPolygon(poly)
            label = name.replace("+", "").replace("-", "").upper()
            sign = "+" if name.startswith("+") else "−"
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
        for name, poly in self._face_polygons.items():
            if poly.containsPoint(pos, Qt.FillRule.OddEvenFill):
                self.face_clicked.emit(name)
                view = _AXIS_TO_VIEW.get(name)
                if view is not None:
                    self.view_requested.emit(view)
                return
        return super().mousePressEvent(event)

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
        top = QPolygonF([
            QPointF(cx,         cy - 1.10 * d),
            QPointF(cx + 1.05 * d, cy - 0.55 * d),
            QPointF(cx,         cy),
            QPointF(cx - 1.05 * d, cy - 0.55 * d),
        ])
        # Right face (+X): tilted rectangle on right.
        right = QPolygonF([
            QPointF(cx + 1.05 * d, cy - 0.55 * d),
            QPointF(cx + 1.05 * d, cy + 0.65 * d),
            QPointF(cx,         cy + 1.20 * d),
            QPointF(cx,         cy),
        ])
        # Front face (+Y): tilted rectangle on left.
        front = QPolygonF([
            QPointF(cx - 1.05 * d, cy - 0.55 * d),
            QPointF(cx,         cy),
            QPointF(cx,         cy + 1.20 * d),
            QPointF(cx - 1.05 * d, cy + 0.65 * d),
        ])
        # Hidden faces — assigned to the same polygons but inverted later
        # via a modifier key would be overkill. For now we only expose the
        # 3 visible faces; clicking any background area is a no-op.
        self._face_polygons = {
            "+z": top,
            "+x": right,
            "+y": front,
        }
