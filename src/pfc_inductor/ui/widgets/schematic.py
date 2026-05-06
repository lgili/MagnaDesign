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
    def _pen(self, color: QColor, width: float = 1.5) -> QPen:
        pen = QPen(color)
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    # ---- primitives ---------------------------------------------------
    def wire(self, p1: tuple[float, float], p2: tuple[float, float],
             color: QColor, width: float = 1.5) -> None:
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
        x1 = cx + length / 2
        # Glow rectangle behind the inductor
        if highlighted:
            self._qp.setPen(Qt.PenStyle.NoPen)
            self._qp.setBrush(QBrush(glow_bg))
            self._qp.drawRoundedRect(
                QRectF(x0 - 8, cy - 18, length + 16, 36), 10, 10,
            )
        # Four humps
        color = accent if highlighted else QColor("#000000")
        self._qp.setPen(self._pen(color, 1.8))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        n_humps = 4
        hump_w = length / n_humps
        path = QPainterPath()
        path.moveTo(x0, cy)
        for i in range(n_humps):
            cx_i = x0 + (i + 0.5) * hump_w
            path.arcTo(QRectF(cx_i - hump_w / 2, cy - hump_w / 2,
                              hump_w, hump_w),
                       180, -180)
        self._qp.drawPath(path)

    # ---- diode bridge -------------------------------------------------
    def bridge_4_diode(self, centre: tuple[float, float], size: float,
                       color: QColor, label: str = "BR") -> None:
        cx, cy = centre
        s = size
        # Diamond
        path = QPainterPath()
        path.moveTo(cx, cy - s)
        path.lineTo(cx + s, cy)
        path.lineTo(cx, cy + s)
        path.lineTo(cx - s, cy)
        path.lineTo(cx, cy - s)
        self._qp.setPen(self._pen(color, 1.6))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        self._qp.drawPath(path)
        # Cross inside (the four diodes form an X plus)
        self._qp.drawLine(QPointF(cx - s, cy), QPointF(cx + s, cy))
        self._qp.drawLine(QPointF(cx, cy - s), QPointF(cx, cy + s))
        self.text((cx, cy + s + 14), label, color, size=9, weight=600)

    # ---- transistor (MOSFET symbol simplified) -----------------------
    def mosfet(self, centre: tuple[float, float], color: QColor,
               label: str = "Q1") -> None:
        cx, cy = centre
        self._qp.setPen(self._pen(color, 1.5))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        # Draw a transistor body: vertical line + two diagonal lines.
        self._qp.drawLine(QPointF(cx - 10, cy - 18), QPointF(cx - 10, cy + 18))
        self._qp.drawLine(QPointF(cx - 10, cy - 8), QPointF(cx + 12, cy - 18))
        self._qp.drawLine(QPointF(cx - 10, cy + 8), QPointF(cx + 12, cy + 18))
        # Gate stub
        self._qp.drawLine(QPointF(cx - 22, cy), QPointF(cx - 13, cy))
        self.text((cx + 16, cy - 22), label, color, size=9, weight=600)

    # ---- diode --------------------------------------------------------
    def diode(self, centre: tuple[float, float], color: QColor,
              label: str = "D") -> None:
        cx, cy = centre
        self._qp.setPen(self._pen(color, 1.5))
        self._qp.setBrush(QBrush(color))
        # Triangle
        path = QPainterPath()
        path.moveTo(cx - 8, cy - 8)
        path.lineTo(cx + 8, cy)
        path.lineTo(cx - 8, cy + 8)
        path.lineTo(cx - 8, cy - 8)
        self._qp.drawPath(path)
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        # Bar
        self._qp.drawLine(QPointF(cx + 8, cy - 8), QPointF(cx + 8, cy + 8))
        self.text((cx, cy - 18), label, color, size=9, weight=600)

    # ---- capacitor ----------------------------------------------------
    def capacitor(self, centre: tuple[float, float], color: QColor,
                  label: str = "C", polarised: bool = True) -> None:
        cx, cy = centre
        self._qp.setPen(self._pen(color, 1.5))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        # Flat plate
        self._qp.drawLine(QPointF(cx - 10, cy - 10), QPointF(cx + 10, cy - 10))
        # Curved or flat plate
        if polarised:
            path = QPainterPath()
            path.moveTo(cx - 10, cy + 6)
            path.quadTo(cx, cy + 18, cx + 10, cy + 6)
            self._qp.drawPath(path)
        else:
            self._qp.drawLine(QPointF(cx - 10, cy + 4),
                              QPointF(cx + 10, cy + 4))
        # Leads
        self._qp.drawLine(QPointF(cx, cy - 18), QPointF(cx, cy - 10))
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
        self.wire(p1, p2, color, width=2.4)
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
    # Vac source (left)
    p.voltage_source_ac((90, (y_top + y_bot) / 2), neutral, "Vac")
    # Connect AC source to bridge
    p.wire((104, y_top), (180, y_top), neutral)
    p.wire((104, y_bot), (180, y_bot), neutral)
    # Bridge
    p.bridge_4_diode((230, (y_top + y_bot) / 2), 50, neutral, "BR")
    p.wire((180, y_top), (230, 80), neutral)
    p.wire((180, y_bot), (230, 180), neutral)
    # Bridge DC outputs
    p.wire((280, 80), (340, 80), neutral)        # +DC out (top)
    p.wire((280, 180), (700, 180), neutral)      # −DC bus
    # Inductor on +DC rail
    p.inductor((400, 80), length=110, accent=accent, glow_bg=glow,
               highlighted=True)
    p.text((400, 50), "L", accent, size=11, weight=700)
    p.wire((455, 80), (520, 80), neutral)
    # MOSFET (drain at +Vbus rail, source to ground)
    p.mosfet((540, 110), neutral, "Q1")
    p.wire((540, 92), (540, 80), neutral)
    p.wire((540, 128), (540, 180), neutral)
    p.junction_dot((540, 80), neutral)
    # Diode after the inductor
    p.diode((620, 80), neutral, "D")
    p.wire((520, 80), (612, 80), neutral)
    p.wire((628, 80), (700, 80), neutral)
    # Output capacitor + DC bus
    p.capacitor((720, 130), neutral, "C_bus", polarised=True)
    p.wire((700, 80), (720, 80), neutral)
    p.wire((720, 80), (720, 112), neutral)
    p.wire((720, 148), (720, 180), neutral)
    p.junction_dot((720, 80), neutral)
    p.junction_dot((720, 180), neutral)
    p.dc_bus((760, 80), (910, 80), neutral, "+VDC")
    p.wire((760, 180), (910, 180), neutral)
    p.text((910, 130), "load", neutral, size=9, weight=500)


def _render_passive_choke(p: _SchematicPainter, accent: QColor,
                          neutral: QColor, glow: QColor) -> None:
    """Vac → bridge → L → Cbus → load."""
    y_top, y_bot = 80, 180
    p.voltage_source_ac((90, (y_top + y_bot) / 2), neutral, "Vac")
    p.wire((104, y_top), (180, y_top), neutral)
    p.wire((104, y_bot), (180, y_bot), neutral)
    p.bridge_4_diode((230, (y_top + y_bot) / 2), 50, neutral, "BR")
    p.wire((180, y_top), (230, 80), neutral)
    p.wire((180, y_bot), (230, 180), neutral)
    p.wire((280, 80), (350, 80), neutral)
    p.inductor((430, 80), length=160, accent=accent, glow_bg=glow,
               highlighted=True)
    p.text((430, 50), "L", accent, size=11, weight=700)
    p.wire((510, 80), (610, 80), neutral)
    p.wire((280, 180), (610, 180), neutral)
    p.capacitor((630, 130), neutral, "C_bus", polarised=True)
    p.wire((610, 80), (630, 80), neutral)
    p.wire((630, 80), (630, 112), neutral)
    p.wire((630, 148), (630, 180), neutral)
    p.junction_dot((630, 80), neutral)
    p.junction_dot((630, 180), neutral)
    p.dc_bus((670, 80), (910, 80), neutral, "+VDC")
    p.wire((670, 180), (910, 180), neutral)
    p.text((910, 130), "load", neutral, size=9, weight=500)


def _render_line_reactor_1ph(p: _SchematicPainter, accent: QColor,
                             neutral: QColor, glow: QColor) -> None:
    """Vac → L (AC side) → bridge → Cbus → load."""
    y_top, y_bot = 80, 180
    p.voltage_source_ac((80, (y_top + y_bot) / 2), neutral, "Vac")
    # Inductor on the top AC line
    p.wire((94, y_top), (160, y_top), neutral)
    p.inductor((230, y_top), length=120, accent=accent, glow_bg=glow,
               highlighted=True)
    p.text((230, 50), "L", accent, size=11, weight=700)
    p.wire((290, y_top), (380, y_top), neutral)
    p.wire((94, y_bot), (380, y_bot), neutral)
    # Bridge
    p.bridge_4_diode((430, (y_top + y_bot) / 2), 50, neutral, "BR")
    p.wire((380, y_top), (430, 80), neutral)
    p.wire((380, y_bot), (430, 180), neutral)
    # Output capacitor + bus
    p.wire((480, y_top), (700, y_top), neutral)
    p.wire((480, y_bot), (700, y_bot), neutral)
    p.capacitor((720, 130), neutral, "C_bus", polarised=True)
    p.wire((700, y_top), (720, y_top), neutral)
    p.wire((720, y_top), (720, 112), neutral)
    p.wire((720, 148), (720, y_bot), neutral)
    p.junction_dot((720, y_top), neutral)
    p.junction_dot((720, y_bot), neutral)
    p.dc_bus((760, y_top), (910, y_top), neutral, "+VDC")
    p.wire((760, y_bot), (910, y_bot), neutral)
    p.text((910, 130), "load", neutral, size=9, weight=500)


def _render_line_reactor_3ph(p: _SchematicPainter, accent: QColor,
                             neutral: QColor, glow: QColor) -> None:
    """L1/L2/L3 → 3 inductors → 6-pulse bridge → Cbus → load."""
    y_l1, y_l2, y_l3 = 60, 130, 200
    for y, label in zip((y_l1, y_l2, y_l3), ("L1", "L2", "L3")):
        p.text((30, y), label, neutral, size=10, weight=600)
        p.wire((50, y), (140, y), neutral)
    # Three inductors
    sub = ["L_a", "L_b", "L_c"]
    for y, lbl in zip((y_l1, y_l2, y_l3), sub):
        p.inductor((200, y), length=100, accent=accent, glow_bg=glow,
                   highlighted=True)
        p.text((200, y - 22), lbl, accent, size=9, weight=600)
    for y in (y_l1, y_l2, y_l3):
        p.wire((250, y), (370, y), neutral)
    # 6-pulse bridge
    p.bridge_4_diode((420, 130), 70, neutral, "BR (6-pulse)")
    p.wire((370, y_l1), (420, 60), neutral)
    p.wire((370, y_l2), (370, 130), neutral)
    p.wire((370, 130), (420, 130), neutral)
    p.wire((370, y_l3), (420, 200), neutral)
    # +DC / −DC bus
    p.wire((490, 60), (700, 60), neutral)
    p.wire((490, 200), (700, 200), neutral)
    p.capacitor((720, 130), neutral, "C_bus", polarised=True)
    p.wire((700, 60), (720, 60), neutral)
    p.wire((720, 60), (720, 112), neutral)
    p.wire((720, 148), (720, 200), neutral)
    p.junction_dot((720, 60), neutral)
    p.junction_dot((720, 200), neutral)
    p.dc_bus((760, 60), (920, 60), neutral, "+VDC")
    p.wire((760, 200), (920, 200), neutral)
    p.text((920, 130), "load", neutral, size=9, weight=500)


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
