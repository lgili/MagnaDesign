"""Procedural topology schematic widget.

Renders a small inline circuit schematic for each of the 4 supported
topologies via :class:`QPainter` primitives. The inductor block — the
component this app is sizing — is highlighted with the brand accent
colour and a soft glow rectangle behind it.

Public API
----------

::

    sw = TopologySchematicWidget()
    sw.set_topology("boost_ccm")  # or passive_choke / line_reactor_1ph /
                                  # line_reactor_3ph

Coordinate system: logical units in ``[0, 1000] × [0, 250]``. The
widget converts logical → device pixels via the ``QTransform`` set on
the painter at the start of each ``paintEvent``.
"""
from __future__ import annotations

from typing import Literal, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from pfc_inductor.ui.theme import get_theme, on_theme_changed

TopologyKind = Literal[
    "boost_ccm",
    "passive_choke",
    "line_reactor_1ph",
    "line_reactor_3ph",
]


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------

class _SchematicPainter:
    """Logical-coordinate wrapper around ``QPainter``.

    Logical units: 0..1000 horizontally, 0..250 vertically. The widget's
    ``paintEvent`` configures the ``QTransform`` so this painter maps to
    pixels.
    """

    LOGICAL_W = 1000
    LOGICAL_H = 250

    def __init__(self, qp: QPainter) -> None:
        self._qp = qp

    # ---- pen helpers --------------------------------------------------
    def _pen(self, color: QColor, width: float = 1.6) -> QPen:
        pen = QPen(color)
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    # ---- primitives ---------------------------------------------------
    def wire(self, p1: tuple[float, float], p2: tuple[float, float],
             color: QColor, width: float = 1.6) -> None:
        self._qp.setPen(self._pen(color, width))
        self._qp.drawLine(QPointF(*p1), QPointF(*p2))

    def junction_dot(self, p: tuple[float, float], color: QColor) -> None:
        self._qp.setPen(self._pen(color, 1.0))
        self._qp.setBrush(QBrush(color))
        self._qp.drawEllipse(QPointF(*p), 3.0, 3.0)

    def text(self, p: tuple[float, float], text: str, color: QColor,
             *, weight: int = 500, size: int = 10,
             align: int = Qt.AlignmentFlag.AlignCenter) -> None:
        self._qp.setPen(self._pen(color, 1.0))
        font = QFont()
        font.setPixelSize(size)
        font.setWeight(QFont.Weight(weight))
        self._qp.setFont(font)
        rect = QRectF(p[0] - 60, p[1] - 8, 120, 16)
        self._qp.drawText(rect, int(align), text)

    # ---- inductor (the highlighted component) ------------------------
    def inductor(self, centre: tuple[float, float], length: float,
                 *, accent: QColor, glow_bg: QColor,
                 highlighted: bool = True) -> None:
        cx, cy = centre
        x0 = cx - length / 2
        # Glow rectangle behind the inductor
        if highlighted:
            self._qp.setPen(Qt.PenStyle.NoPen)
            self._qp.setBrush(QBrush(glow_bg))
            self._qp.drawRoundedRect(
                QRectF(x0 - 8, cy - 18, length + 16, 36), 10, 10,
            )
        # Classic coil symbol: 3 semi-circles
        color = accent if highlighted else QColor("#000000")
        self._qp.setPen(self._pen(color, 1.8))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        n_humps = 3
        hump_w = length / n_humps
        path = QPainterPath()
        path.moveTo(x0, cy)
        for i in range(n_humps):
            cx_i = x0 + (i + 0.5) * hump_w
            path.arcTo(QRectF(cx_i - hump_w / 2, cy - hump_w / 2,
                              hump_w, hump_w),
                       180, -180)
        self._qp.drawPath(path)

    # ---- transistor (MOSFET symbol simplified) -----------------------
    def mosfet(self, centre: tuple[float, float], color: QColor,
               label: str = "Q1") -> None:
        cx, cy = centre
        self._qp.setPen(self._pen(color, 1.5))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        # Gate plate
        self._qp.drawLine(QPointF(cx - 18, cy - 12), QPointF(cx - 18, cy + 12))
        # Gate stub
        self._qp.drawLine(QPointF(cx - 28, cy), QPointF(cx - 18, cy))
        # Drain/source plates
        self._qp.drawLine(QPointF(cx - 8, cy - 18), QPointF(cx - 8, cy - 8))
        self._qp.drawLine(QPointF(cx - 8, cy + 8), QPointF(cx - 8, cy + 18))
        self._qp.drawLine(QPointF(cx - 8, cy - 8), QPointF(cx + 4, cy - 8))
        self._qp.drawLine(QPointF(cx - 8, cy + 8), QPointF(cx + 4, cy + 8))
        # Channel
        self._qp.drawLine(QPointF(cx + 4, cy - 8), QPointF(cx + 4, cy + 8))
        self.text((cx + 16, cy - 22), label, color, size=9, weight=600)

    # ---- diode --------------------------------------------------------
    def diode(self, p1: tuple[float, float], p2: tuple[float, float],
              color: QColor, label: Optional[str] = None) -> None:
        self._qp.setPen(self._pen(color, 1.5))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        # Line
        self._qp.drawLine(QPointF(*p1), QPointF(*p2))
        # Triangle (arrow) at the midpoint
        cx = (p1[0] + p2[0]) / 2
        cy = (p1[1] + p2[1]) / 2
        path = QPainterPath()
        path.moveTo(cx - 8, cy - 8)
        path.lineTo(cx + 8, cy)
        path.lineTo(cx - 8, cy + 8)
        path.lineTo(cx - 8, cy - 8)
        self._qp.drawPath(path)
        # Bar at the end
        self._qp.drawLine(QPointF(cx + 8, cy - 8), QPointF(cx + 8, cy + 8))
        if label:
            self.text((cx, cy - 18), label, color, size=9, weight=600)

    # ---- capacitor ----------------------------------------------------
    def capacitor(self, centre: tuple[float, float], color: QColor,
                  label: str = "C", polarised: bool = True) -> None:
        cx, cy = centre
        self._qp.setPen(self._pen(color, 1.5))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        # Flat plate
        self._qp.drawLine(QPointF(cx - 12, cy - 6), QPointF(cx + 12, cy - 6))
        # Curved or flat plate
        if polarised:
            path = QPainterPath()
            path.moveTo(cx - 12, cy + 6)
            path.quadTo(cx, cy + 18, cx + 12, cy + 6)
            self._qp.drawPath(path)
        else:
            self._qp.drawLine(QPointF(cx - 12, cy + 6),
                              QPointF(cx + 12, cy + 6))
        # Leads
        self._qp.drawLine(QPointF(cx, cy - 18), QPointF(cx, cy - 6))
        self._qp.drawLine(QPointF(cx, cy + 6), QPointF(cx, cy + 18))
        self.text((cx + 22, cy), label, color, size=9, weight=600)

    # ---- AC source ---------------------------------------------------
    def voltage_source_ac(self, centre: tuple[float, float], color: QColor,
                          label: str = "Vac") -> None:
        cx, cy = centre
        self._qp.setPen(self._pen(color, 1.6))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        self._qp.drawEllipse(QPointF(cx, cy), 14, 14)
        # Sine glyph
        path = QPainterPath()
        path.moveTo(cx - 8, cy)
        path.cubicTo(cx - 4, cy - 8, cx + 4, cy + 8, cx + 8, cy)
        self._qp.drawPath(path)
        self.text((cx, cy + 24), label, color, size=9, weight=600)

    # ---- DC bus rail (heavy line) ------------------------------------
    def dc_bus(self, p1: tuple[float, float], p2: tuple[float, float],
               color: QColor, label: str = "+VDC") -> None:
        self.wire(p1, p2, color, width=2.0)
        mid_x = (p1[0] + p2[0]) / 2
        mid_y = (p1[1] + p2[1]) / 2 - 12
        self.text((mid_x, mid_y), label, color, size=9, weight=600)


# ---------------------------------------------------------------------------
# Topology renderers
# ---------------------------------------------------------------------------

def _render_boost_ccm(p: _SchematicPainter, accent: QColor,
                      neutral: QColor, glow: QColor) -> None:
    """Vac → bridge → L → Q1 / D → Cbus → load."""
    y_top, y_bot = 80, 180
    x_ac, x_br_in, x_br_out, x_L, x_sw, x_cap, x_load = [80, 180, 280, 400, 540, 720, 880]

    # AC Source and connections to bridge
    p.voltage_source_ac((x_ac, (y_top + y_bot) / 2), neutral, "Vac")
    p.wire((x_ac + 14, y_top), (x_br_in, y_top), neutral)
    p.wire((x_ac + 14, y_bot), (x_br_in, y_bot), neutral)

    # Diode Bridge (drawn as 4 individual diodes)
    p.diode((x_br_in, y_top), (x_br_in + 40, (y_top + y_bot) / 2), neutral)
    p.diode((x_br_in, y_bot), (x_br_in + 40, (y_top + y_bot) / 2), neutral)
    p.diode((x_br_out - 40, (y_top + y_bot) / 2), (x_br_out, y_top), neutral)
    p.diode((x_br_out - 40, (y_top + y_bot) / 2), (x_br_out, y_bot), neutral)
    p.junction_dot((x_br_in + 40, (y_top + y_bot) / 2), neutral)
    p.junction_dot((x_br_out - 40, (y_top + y_bot) / 2), neutral)
    p.wire((x_br_in + 40, (y_top + y_bot) / 2), (x_br_out - 40, (y_top + y_bot) / 2), neutral)
    p.text((230, 194), "BR", neutral, size=9, weight=600)

    # Bridge DC outputs
    p.wire((x_br_out, y_top), (x_L - 55, y_top), neutral)  # +DC out
    p.wire((x_br_out, y_bot), (x_cap, y_bot), neutral)    # -DC bus

    # Inductor, Switch, Diode
    p.inductor((x_L, y_top), length=110, accent=accent, glow_bg=glow, highlighted=True)
    p.text((x_L, y_top - 30), "L", accent, size=11, weight=700)
    p.wire((x_L + 55, y_top), (x_sw, y_top), neutral)
    p.mosfet((x_sw, 115), neutral, "Q1")
    p.wire((x_sw, y_top), (x_sw, 97), neutral)
    p.wire((x_sw, 133), (x_sw, y_bot), neutral)
    p.junction_dot((x_sw, y_top), neutral)
    p.junction_dot((x_sw, y_bot), neutral)
    p.diode((x_sw + 40, y_top), (x_cap, y_top), neutral, "D")
    p.junction_dot((x_sw + 40, y_top), neutral)
    p.wire((x_sw, y_top), (x_sw + 40, y_top), neutral)


    # Output capacitor + DC bus
    p.capacitor((x_cap, 130), neutral, "C_bus", polarised=True)
    p.wire((x_cap, y_top), (x_cap, 112), neutral)
    p.wire((x_cap, 148), (x_cap, y_bot), neutral)
    p.junction_dot((x_cap, y_top), neutral)
    p.junction_dot((x_cap, y_bot), neutral)
    p.dc_bus((x_cap + 40, y_top), (x_load + 30, y_top), neutral, "+VDC")
    p.wire((x_cap + 40, y_bot), (x_load + 30, y_bot), neutral)
    p.text((x_load + 30, 130), "load", neutral, size=9, weight=500)


def _render_passive_choke(p: _SchematicPainter, accent: QColor,
                          neutral: QColor, glow: QColor) -> None:
    """Vac → bridge → L → Cbus → load."""
    y_top, y_bot = 80, 180
    x_ac, x_br_in, x_br_out, x_L, x_cap, x_load = [80, 180, 280, 430, 680, 880]

    # AC Source and connections to bridge
    p.voltage_source_ac((x_ac, (y_top + y_bot) / 2), neutral, "Vac")
    p.wire((x_ac + 14, y_top), (x_br_in, y_top), neutral)
    p.wire((x_ac + 14, y_bot), (x_br_in, y_bot), neutral)

    # Diode Bridge
    p.diode((x_br_in, y_top), (x_br_in + 40, (y_top + y_bot) / 2), neutral)
    p.diode((x_br_in, y_bot), (x_br_in + 40, (y_top + y_bot) / 2), neutral)
    p.diode((x_br_out - 40, (y_top + y_bot) / 2), (x_br_out, y_top), neutral)
    p.diode((x_br_out - 40, (y_top + y_bot) / 2), (x_br_out, y_bot), neutral)
    p.junction_dot((x_br_in + 40, (y_top + y_bot) / 2), neutral)
    p.junction_dot((x_br_out - 40, (y_top + y_bot) / 2), neutral)
    p.wire((x_br_in + 40, (y_top + y_bot) / 2), (x_br_out - 40, (y_top + y_bot) / 2), neutral)
    p.text((230, 194), "BR", neutral, size=9, weight=600)

    # Inductor
    p.wire((x_br_out, y_top), (x_L-80, y_top), neutral)
    p.inductor((x_L, y_top), length=160, accent=accent, glow_bg=glow, highlighted=True)
    p.text((x_L, y_top - 30), "L", accent, size=11, weight=700)
    p.wire((x_L + 80, y_top), (x_cap, y_top), neutral)

    # DC Bus
    p.wire((x_br_out, y_bot), (x_cap, y_bot), neutral)

    # Output Cap and Load
    p.capacitor((x_cap, 130), neutral, "C_bus", polarised=True)
    p.wire((x_cap, y_top), (x_cap, 112), neutral)
    p.wire((x_cap, 148), (x_cap, y_bot), neutral)
    p.junction_dot((x_cap, y_top), neutral)
    p.junction_dot((x_cap, y_bot), neutral)
    p.dc_bus((x_cap + 40, y_top), (x_load + 30, y_top), neutral, "+VDC")
    p.wire((x_cap + 40, y_bot), (x_load + 30, y_bot), neutral)
    p.text((x_load + 30, 130), "load", neutral, size=9, weight=500)


def _render_line_reactor_1ph(p: _SchematicPainter, accent: QColor,
                             neutral: QColor, glow: QColor) -> None:
    """Vac → L (AC side) → bridge → Cbus → load."""
    y_top, y_bot = 80, 180
    x_ac, x_L, x_br_in, x_br_out, x_cap, x_load = [80, 230, 380, 480, 720, 880]

    p.voltage_source_ac((x_ac, (y_top + y_bot) / 2), neutral, "Vac")
    # Inductor on the top AC line
    p.wire((x_ac + 14, y_top), (x_L - 60, y_top), neutral)
    p.inductor((x_L, y_top), length=120, accent=accent, glow_bg=glow, highlighted=True)
    p.text((x_L, 50), "L", accent, size=11, weight=700)
    p.wire((x_L + 60, y_top), (x_br_in, y_top), neutral)
    p.wire((x_ac + 14, y_bot), (x_br_in, y_bot), neutral)
    # Diode Bridge
    p.diode((x_br_in, y_top), (x_br_in + 40, (y_top + y_bot) / 2), neutral)
    p.diode((x_br_in, y_bot), (x_br_in + 40, (y_top + y_bot) / 2), neutral)
    p.diode((x_br_out - 40, (y_top + y_bot) / 2), (x_br_out, y_top), neutral)
    p.diode((x_br_out - 40, (y_top + y_bot) / 2), (x_br_out, y_bot), neutral)
    p.junction_dot((x_br_in + 40, (y_top + y_bot) / 2), neutral)
    p.junction_dot((x_br_out - 40, (y_top + y_bot) / 2), neutral)
    p.wire((x_br_in + 40, (y_top + y_bot) / 2), (x_br_out - 40, (y_top + y_bot) / 2), neutral)
    p.text((430, 194), "BR", neutral, size=9, weight=600)

    # Output capacitor + bus
    p.wire((x_br_out, y_top), (x_cap, y_top), neutral)
    p.wire((x_br_out, y_bot), (x_cap, y_bot), neutral)
    p.capacitor((x_cap, 130), neutral, "C_bus", polarised=True)
    p.wire((x_cap, y_top), (x_cap, 112), neutral)
    p.wire((x_cap, 148), (x_cap, y_bot), neutral)
    p.junction_dot((x_cap, y_top), neutral)
    p.junction_dot((x_cap, y_bot), neutral)
    p.dc_bus((x_cap + 40, y_top), (x_load + 30, y_top), neutral, "+VDC")
    p.wire((x_cap + 40, y_bot), (x_load + 30, y_bot), neutral)
    p.text((x_load + 30, 130), "load", neutral, size=9, weight=500)


def _render_line_reactor_3ph(p: _SchematicPainter, accent: QColor,
                             neutral: QColor, glow: QColor) -> None:
    """L1/L2/L3 → 3 inductors → 6-pulse bridge → Cbus → load."""
    y_l1, y_l2, y_l3 = 60, 130, 200
    x_in, x_L, x_br_in, x_br_out, x_cap, x_load = [30, 200, 370, 490, 720, 880]

    for y, label in zip((y_l1, y_l2, y_l3), ("L1", "L2", "L3"), strict=False):
        p.text((x_in, y), label, neutral, size=10, weight=600)
        p.wire((x_in + 20, y), (x_L - 50, y), neutral)
    # Three inductors
    sub = ["L_a", "L_b", "L_c"]
    for y, lbl in zip((y_l1, y_l2, y_l3), sub, strict=False):
        p.inductor((x_L, y), length=100, accent=accent, glow_bg=glow, highlighted=True)
        p.text((x_L, y - 28), lbl, accent, size=9, weight=600)
        p.wire((x_L + 50, y), (x_br_in, y), neutral)

    # 6-pulse bridge (conceptual block)
    s = 70
    cx, cy = 420, 130
    path = QPainterPath()
    path.moveTo(cx, cy - s)
    path.lineTo(cx + s, cy)
    path.lineTo(cx, cy + s)
    path.lineTo(cx - s, cy)
    path.lineTo(cx, cy - s)
    p._qp.setPen(p._pen(neutral, 1.6))
    p._qp.setBrush(Qt.BrushStyle.NoBrush)
    p._qp.drawPath(path)
    p.text((cx, cy + s + 14), "BR (6-pulse)", neutral, size=9, weight=600)
    p.wire((x_br_in, y_l1), (cx, cy-s), neutral)
    p.wire((x_br_in, y_l2), (cx-s, cy), neutral)
    p.wire((x_br_in, y_l3), (cx, cy+s), neutral)


    # +DC / −DC bus
    p.wire((x_br_out, y_l1), (x_cap, y_l1), neutral)
    p.wire((x_br_out, y_l3), (x_cap, y_l3), neutral)
    p.capacitor((x_cap, 130), neutral, "C_bus", polarised=True)
    p.wire((x_cap, y_l1), (x_cap, 112), neutral)
    p.wire((x_cap, 148), (x_cap, y_l3), neutral)
    p.junction_dot((x_cap, y_l1), neutral)
    p.junction_dot((x_cap, y_l3), neutral)
    p.dc_bus((x_cap + 40, y_l1), (x_load + 40, y_l1), neutral, "+VDC")
    p.wire((x_cap + 40, y_l3), (x_load + 40, y_l3), neutral)
    p.text((x_load + 40, 130), "load", neutral, size=9, weight=500)


_TOPOLOGY_RENDERERS = {
    "boost_ccm":         _render_boost_ccm,
    "passive_choke":     _render_passive_choke,
    "line_reactor_1ph":  _render_line_reactor_1ph,
    "line_reactor_3ph":  _render_line_reactor_3ph,
}


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class TopologySchematicWidget(QWidget):
    """Vector circuit schematic for one of the supported topologies."""

    LOGICAL_W = 1000
    LOGICAL_H = 250

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setMaximumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)
        self._topology: TopologyKind = "boost_ccm"
        on_theme_changed(self.update)

    # ------------------------------------------------------------------
    def set_topology(self, name: str) -> None:
        """Set the topology to render. Accepts the canonical names plus
        the convenience alias ``"line_reactor"`` which is mapped to the
        1-phase variant unless followed by ``_3ph``."""
        if name == "line_reactor":
            name = "line_reactor_1ph"
        if name not in _TOPOLOGY_RENDERERS:
            raise ValueError(f"Unknown topology: {name}")
        self._topology = name  # type: ignore[assignment]
        self.update()

    def topology(self) -> TopologyKind:
        return self._topology

    # ------------------------------------------------------------------
    def paintEvent(self, _event):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        qp.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Map logical → device pixels.
        sx = self.width() / float(self.LOGICAL_W)
        sy = self.height() / float(self.LOGICAL_H)
        qp.scale(sx, sy)

        palette = get_theme().palette
        accent = QColor(palette.accent)
        neutral = QColor(palette.text_secondary)
        glow = QColor(palette.accent_subtle_bg)

        sp = _SchematicPainter(qp)
        renderer = _TOPOLOGY_RENDERERS[self._topology]
        renderer(sp, accent, neutral, glow)


# ---------------------------------------------------------------------------
# Topology picker dialog
# ---------------------------------------------------------------------------

def topology_picker_choices() -> list[tuple[str, str]]:
    """Return ``(key, label)`` pairs for the topology picker dialog."""
    return [
        ("boost_ccm",         "Boost CCM Active"),
        ("passive_choke",     "Passive PFC Choke"),
        ("line_reactor_1ph",  "Line Reactor (1ph)"),
        ("line_reactor_3ph",  "Line Reactor (3ph)"),
    ]
