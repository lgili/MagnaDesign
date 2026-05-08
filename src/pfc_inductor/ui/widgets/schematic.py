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

Design notes (v2)
-----------------

The first cut of this widget drew components hand-rolled at every
call site (``mosfet`` was a stack of small line-segments,
``diode bridge`` was 4 separate diodes touching each other, junction
dots were sprinkled liberally). It read as cluttered at the small
sizes the dashboard cards mount it at (≈ 600 × 110 device px).

The redesign:

- **Block symbols, not stick figures.** ``mosfet`` / ``bridge`` are
  drawn as small rectangles with a clean glyph + label inside, the
  way reference manuals (Texas Instruments, Infineon app notes,
  PSIM block diagrams) render them. Reads cleanly at thumbnail
  sizes; less ink-per-pixel ratio.
- **Generous, gridded layout.** Every wire snaps to integer logical
  coordinates and components sit at fixed grid columns. Eliminates
  the asymmetric drift the old layouts had.
- **One junction-dot policy.** Dots only at *true* T- or X-junctions
  (3+ wires meeting); never just to mark a corner. Halves the
  visual noise of the busier topologies.
- **Labels live above the symbol.** Below-the-wire labels collided
  with the negative DC rail in the old boost layout.
- **Inductor still owns the accent.** Soft glow rectangle behind
  the coil + accent stroke. Stays the visual centre of gravity —
  this is, after all, an inductor-design app.
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

    # Stroke widths chosen to read well at the dashboard card's typical
    # device size (~600 × 110 px). Wires are slightly thinner than
    # component outlines so the components dominate the eye.
    STROKE_WIRE = 1.6
    STROKE_COMPONENT = 1.8
    STROKE_INDUCTOR = 2.2

    # Component glyph dimensions (logical units).
    BLOCK_W = 48
    BLOCK_H = 36

    def __init__(self, qp: QPainter) -> None:
        self._qp = qp

    # ---- pen helpers --------------------------------------------------
    def _pen(self, color: QColor, width: float = STROKE_WIRE) -> QPen:
        pen = QPen(color)
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    # ---- primitives ---------------------------------------------------
    def wire(self, p1: tuple[float, float], p2: tuple[float, float],
             color: QColor, width: float = STROKE_WIRE) -> None:
        self._qp.setPen(self._pen(color, width))
        self._qp.drawLine(QPointF(*p1), QPointF(*p2))

    def junction_dot(self, p: tuple[float, float], color: QColor) -> None:
        """Solid dot for true T-/X-junctions only.

        Use sparingly. A 'plain corner' (90° turn between two wires)
        does NOT need a dot; a junction is where three or more wires
        meet at the same point.
        """
        self._qp.setPen(Qt.PenStyle.NoPen)
        self._qp.setBrush(QBrush(color))
        self._qp.drawEllipse(QPointF(*p), 2.6, 2.6)

    def label(self, p: tuple[float, float], text: str, color: QColor,
              *, weight: int = 600, size: int = 11,
              align: int = Qt.AlignmentFlag.AlignCenter) -> None:
        self._qp.setPen(self._pen(color, 1.0))
        font = QFont()
        font.setPixelSize(size)
        font.setWeight(QFont.Weight(weight))
        self._qp.setFont(font)
        rect = QRectF(p[0] - 80, p[1] - 9, 160, 18)
        self._qp.drawText(rect, int(align), text)

    def ground(self, p: tuple[float, float], color: QColor) -> None:
        """IEC chassis-ground glyph at point ``p``.

        Three short parallel horizontal lines, decreasing in length —
        the universal "circuit reference" symbol. Drawn pointing
        downward from ``p`` so the wire above it stops at ``p``.
        """
        self._qp.setPen(self._pen(color, self.STROKE_COMPONENT))
        x, y = p
        self._qp.drawLine(QPointF(x - 9, y),     QPointF(x + 9, y))
        self._qp.drawLine(QPointF(x - 6, y + 4), QPointF(x + 6, y + 4))
        self._qp.drawLine(QPointF(x - 3, y + 8), QPointF(x + 3, y + 8))

    # ---- inductor (the highlighted component) ------------------------
    def inductor(self, centre: tuple[float, float], length: float,
                 *, accent: QColor, glow_bg: QColor,
                 highlighted: bool = True,
                 vertical: bool = False) -> None:
        """Inductor coil symbol with optional accent glow background.

        Always drawn with 4 humps for the canonical "coiled wire" look
        regardless of length — better visual rhythm than the 3-hump
        version. ``vertical`` rotates the symbol 90° for the
        line-reactor 3-phase layout where inductors hang on vertical
        rails.
        """
        cx, cy = centre
        if vertical:
            # Draw with axes swapped — humps spread vertically.
            x0 = cx
            y0 = cy - length / 2
            if highlighted:
                self._qp.setPen(Qt.PenStyle.NoPen)
                self._qp.setBrush(QBrush(glow_bg))
                self._qp.drawRoundedRect(
                    QRectF(x0 - 18, y0 - 6, 36, length + 12), 9, 9,
                )
            color = accent if highlighted else QColor("#000000")
            self._qp.setPen(self._pen(color, self.STROKE_INDUCTOR))
            self._qp.setBrush(Qt.BrushStyle.NoBrush)
            n_humps = 4
            hump_h = length / n_humps
            path = QPainterPath()
            path.moveTo(x0, y0)
            for i in range(n_humps):
                cy_i = y0 + (i + 0.5) * hump_h
                path.arcTo(
                    QRectF(x0 - hump_h / 2, cy_i - hump_h / 2,
                           hump_h, hump_h),
                    90, -180,
                )
            self._qp.drawPath(path)
            return

        # Horizontal (default).
        x0 = cx - length / 2
        if highlighted:
            self._qp.setPen(Qt.PenStyle.NoPen)
            self._qp.setBrush(QBrush(glow_bg))
            self._qp.drawRoundedRect(
                QRectF(x0 - 6, cy - 18, length + 12, 36), 9, 9,
            )
        color = accent if highlighted else QColor("#000000")
        self._qp.setPen(self._pen(color, self.STROKE_INDUCTOR))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        n_humps = 4
        hump_w = length / n_humps
        path = QPainterPath()
        path.moveTo(x0, cy)
        for i in range(n_humps):
            cx_i = x0 + (i + 0.5) * hump_w
            path.arcTo(
                QRectF(cx_i - hump_w / 2, cy - hump_w / 2, hump_w, hump_w),
                180, -180,
            )
        self._qp.drawPath(path)

    # ---- transistor (block style, "Q1" labeled) ----------------------
    def mosfet(self, centre: tuple[float, float], color: QColor,
               label: str = "Q1") -> None:
        """Generic active switch: rounded rectangle with the device
        label inside + a small switch arrow.

        Picked over the IEC enhancement-mode 3-plate glyph because
        the latter is unreadable at the dashboard's thumbnail size
        (~140 px tall with 4 components on the same row). The block
        + label form is the convention reference manuals (TI, Infineon)
        use in their topology overview figures.
        """
        cx, cy = centre
        w, h = self.BLOCK_W, self.BLOCK_H
        rect = QRectF(cx - w / 2, cy - h / 2, w, h)
        self._qp.setPen(self._pen(color, self.STROKE_COMPONENT))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        self._qp.drawRoundedRect(rect, 4, 4)
        # Switch glyph: diagonal arrow inside the box (NO/NC switch
        # convention) — communicates "active controllable element"
        # without committing to a specific transistor flavour.
        self._qp.drawLine(
            QPointF(cx - w / 2 + 8, cy + h / 2 - 8),
            QPointF(cx + w / 2 - 8, cy - h / 2 + 8),
        )
        self.label((cx, cy - h / 2 - 12), label, color, size=10, weight=600)

    # ---- diode --------------------------------------------------------
    def diode(self, centre: tuple[float, float], color: QColor,
              label: Optional[str] = None,
              *, orientation: str = "right") -> None:
        """Standard triangle-and-bar diode symbol.

        ``orientation`` controls forward direction:
        ``right`` / ``left`` / ``up`` / ``down``. The diode is always
        drawn with leads extending 14 logical units to either side
        of ``centre``, so the caller can connect wires straight to
        ``centre ± lead_length``.
        """
        cx, cy = centre
        s = 8  # half-edge of the triangle
        self._qp.setPen(self._pen(color, self.STROKE_COMPONENT))
        self._qp.setBrush(QBrush(color))
        path = QPainterPath()
        bar_a: tuple[float, float]
        bar_b: tuple[float, float]
        lead_a: tuple[tuple[float, float], tuple[float, float]]
        lead_b: tuple[tuple[float, float], tuple[float, float]]
        if orientation == "right":
            path.moveTo(cx - s, cy - s)
            path.lineTo(cx - s, cy + s)
            path.lineTo(cx + s, cy)
            path.closeSubpath()
            bar_a = (cx + s, cy - s)
            bar_b = (cx + s, cy + s)
            lead_a = ((cx - 14, cy), (cx - s, cy))
            lead_b = ((cx + s, cy), (cx + 14, cy))
        elif orientation == "left":
            path.moveTo(cx + s, cy - s)
            path.lineTo(cx + s, cy + s)
            path.lineTo(cx - s, cy)
            path.closeSubpath()
            bar_a = (cx - s, cy - s)
            bar_b = (cx - s, cy + s)
            lead_a = ((cx + 14, cy), (cx + s, cy))
            lead_b = ((cx - s, cy), (cx - 14, cy))
        elif orientation == "down":
            path.moveTo(cx - s, cy - s)
            path.lineTo(cx + s, cy - s)
            path.lineTo(cx, cy + s)
            path.closeSubpath()
            bar_a = (cx - s, cy + s)
            bar_b = (cx + s, cy + s)
            lead_a = ((cx, cy - 14), (cx, cy - s))
            lead_b = ((cx, cy + s), (cx, cy + 14))
        else:  # up
            path.moveTo(cx - s, cy + s)
            path.lineTo(cx + s, cy + s)
            path.lineTo(cx, cy - s)
            path.closeSubpath()
            bar_a = (cx - s, cy - s)
            bar_b = (cx + s, cy - s)
            lead_a = ((cx, cy + 14), (cx, cy + s))
            lead_b = ((cx, cy - s), (cx, cy - 14))
        self._qp.drawPath(path)
        # Solid triangle filled; reset brush for the bar + leads.
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        self._qp.drawLine(QPointF(*bar_a), QPointF(*bar_b))
        self._qp.drawLine(QPointF(*lead_a[0]), QPointF(*lead_a[1]))
        self._qp.drawLine(QPointF(*lead_b[0]), QPointF(*lead_b[1]))
        if label:
            self.label((cx, cy - 22), label, color, size=10, weight=600)

    # ---- diode bridge (block-style) ----------------------------------
    def diode_bridge(self, centre: tuple[float, float], color: QColor,
                     *, label: str = "BR") -> tuple[
                         tuple[float, float],  # ac_top
                         tuple[float, float],  # ac_bot
                         tuple[float, float],  # dc_pos (top)
                         tuple[float, float],  # dc_neg (bottom)
                     ]:
        """Single rotated-square rectifier bridge glyph.

        Reference manuals (TI, ST, app notes) draw the diode bridge
        as one diamond with four little diode arrows pointing inward
        (AC inputs) and outward (DC outputs). It's far more legible
        at thumbnail size than four stacked triangles.

        Returns the four terminal coordinates so the caller can wire
        AC and DC rails without recomputing positions.
        """
        cx, cy = centre
        s = 30  # half-diagonal of the diamond
        # Diamond outline (rotated square).
        self._qp.setPen(self._pen(color, self.STROKE_COMPONENT))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        diamond = QPainterPath()
        diamond.moveTo(cx,     cy - s)
        diamond.lineTo(cx + s, cy)
        diamond.lineTo(cx,     cy + s)
        diamond.lineTo(cx - s, cy)
        diamond.closeSubpath()
        self._qp.drawPath(diamond)

        # Internal mini-diode arrows: small filled triangles in each
        # of the 4 segments pointing toward the DC outputs (top + bot)
        # from the AC inputs (left + right). 3 px high; pure visual
        # cue, not strictly schematic-correct in detail.
        self._qp.setBrush(QBrush(color))
        for tip, base_left, base_right in (
            # left-segment diode points UP (AC- → +DC)
            ((cx - s / 2 - 2, cy - s / 2 + 2),
             (cx - s / 2 - 5, cy - s / 2 + 7),
             (cx - s / 2 + 1, cy - s / 2 + 7)),
            # top-right diode points UP (DC+ → top)
            ((cx + s / 2 - 2, cy - s / 2 - 2),
             (cx + s / 2 - 5, cy - s / 2 + 3),
             (cx + s / 2 + 1, cy - s / 2 + 3)),
            # bottom-left diode points DOWN (bot → AC-)
            ((cx - s / 2 + 1, cy + s / 2 + 2),
             (cx - s / 2 - 2, cy + s / 2 - 3),
             (cx - s / 2 + 4, cy + s / 2 - 3)),
            # bottom-right diode points DOWN (DC- ← bot)
            ((cx + s / 2 + 1, cy + s / 2 - 2),
             (cx + s / 2 - 2, cy + s / 2 - 7),
             (cx + s / 2 + 4, cy + s / 2 - 7)),
        ):
            tri = QPainterPath()
            tri.moveTo(*base_left)
            tri.lineTo(*base_right)
            tri.lineTo(*tip)
            tri.closeSubpath()
            self._qp.drawPath(tri)
        self._qp.setBrush(Qt.BrushStyle.NoBrush)

        # Label below the symbol.
        self.label((cx, cy + s + 12), label, color, size=10, weight=600)

        # Terminals: top, right, bottom, left (clockwise from top).
        # Layout convention used in this widget:
        #   top    = +DC
        #   bottom = −DC
        #   left   = AC line A
        #   right  = AC line B
        return (
            (cx - s, cy),  # ac left
            (cx + s, cy),  # ac right
            (cx,     cy - s),  # dc+
            (cx,     cy + s),  # dc−
        )

    # ---- capacitor ----------------------------------------------------
    def capacitor(self, centre: tuple[float, float], color: QColor,
                  label: str = "C", polarised: bool = True,
                  *, vertical: bool = True) -> None:
        cx, cy = centre
        self._qp.setPen(self._pen(color, self.STROKE_COMPONENT))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        if vertical:
            # Plates horizontal; leads run vertically.
            self._qp.drawLine(QPointF(cx - 13, cy - 5), QPointF(cx + 13, cy - 5))
            if polarised:
                path = QPainterPath()
                path.moveTo(cx - 13, cy + 5)
                path.quadTo(cx, cy + 14, cx + 13, cy + 5)
                self._qp.drawPath(path)
            else:
                self._qp.drawLine(
                    QPointF(cx - 13, cy + 5), QPointF(cx + 13, cy + 5),
                )
            # leads
            self._qp.drawLine(QPointF(cx, cy - 18), QPointF(cx, cy - 5))
            self._qp.drawLine(QPointF(cx, cy + 5), QPointF(cx, cy + 18))
            # "+" mark for polarized cap
            if polarised:
                self.label(
                    (cx + 22, cy - 4), "+", color, size=10, weight=700,
                )
            self.label((cx + 24, cy + 6), label, color, size=10, weight=600)
        else:
            self._qp.drawLine(QPointF(cx - 5, cy - 13), QPointF(cx - 5, cy + 13))
            if polarised:
                path = QPainterPath()
                path.moveTo(cx + 5, cy - 13)
                path.quadTo(cx + 14, cy, cx + 5, cy + 13)
                self._qp.drawPath(path)
            else:
                self._qp.drawLine(
                    QPointF(cx + 5, cy - 13), QPointF(cx + 5, cy + 13),
                )
            self._qp.drawLine(QPointF(cx - 18, cy), QPointF(cx - 5, cy))
            self._qp.drawLine(QPointF(cx + 5, cy), QPointF(cx + 18, cy))
            self.label((cx, cy - 22), label, color, size=10, weight=600)

    # ---- AC source ---------------------------------------------------
    def voltage_source_ac(self, centre: tuple[float, float], color: QColor,
                          label: str = "Vac") -> None:
        cx, cy = centre
        self._qp.setPen(self._pen(color, self.STROKE_COMPONENT))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        self._qp.drawEllipse(QPointF(cx, cy), 16, 16)
        # Sine glyph inside the circle.
        path = QPainterPath()
        path.moveTo(cx - 9, cy)
        path.cubicTo(cx - 4, cy - 9, cx + 4, cy + 9, cx + 9, cy)
        self._qp.drawPath(path)
        self.label((cx, cy + 28), label, color, size=10, weight=600)

    # ---- load (rectangle with R-style hatching) ----------------------
    def load_block(self, centre: tuple[float, float], color: QColor,
                   *, label: str = "LOAD") -> None:
        cx, cy = centre
        w, h = 60, 50
        rect = QRectF(cx - w / 2, cy - h / 2, w, h)
        self._qp.setPen(self._pen(color, self.STROKE_COMPONENT))
        self._qp.setBrush(Qt.BrushStyle.NoBrush)
        self._qp.drawRoundedRect(rect, 4, 4)
        self.label((cx, cy), label, color, size=10, weight=600)

    # ---- DC bus rail (heavy line + label) ----------------------------
    def dc_bus_label(self, p: tuple[float, float], color: QColor,
                     label: str = "+VDC") -> None:
        self.label(p, label, color, size=9, weight=600)


# ---------------------------------------------------------------------------
# Topology renderers
# ---------------------------------------------------------------------------

def _render_boost_ccm(p: _SchematicPainter, accent: QColor,
                      neutral: QColor, glow: QColor) -> None:
    """Boost CCM PFC: Vac → bridge → L → Q/D → Cbus → load.

    Layout (logical px, 1000×250 canvas):

    - x = 80   AC source
    - x = 220  diode bridge (diamond)
    - x = 430  inductor centre (highlighted)  ← test pins this column
    - x = 600  switching node (Q drain / D anode)
    - x = 720  output capacitor
    - x = 880  load
    - y_top = 80, y_bot = 170

    Only one true T-junction on each rail — the switching node and
    the cap+load tap-off — gets a dot.
    """
    y_top, y_bot = 80, 170

    # AC source.
    p.voltage_source_ac((80, (y_top + y_bot) / 2), neutral, "Vac")

    # AC → bridge (we route the AC pair into the bridge's left/right
    # diamond terminals so the rectifier visual reads correctly).
    ac_l, ac_r, dc_pos, dc_neg = p.diode_bridge((220, 125), neutral)
    # Wire AC source to bridge's two AC terminals.
    p.wire((96, y_top), (180, y_top), neutral)
    p.wire((180, y_top), (180, ac_l[1]), neutral)
    p.wire((180, ac_l[1]), ac_l, neutral)
    p.wire((96, y_bot), (260, y_bot), neutral)
    p.wire((260, y_bot), (260, ac_r[1]), neutral)
    p.wire((260, ac_r[1]), ac_r, neutral)

    # Bridge → DC rails.
    p.wire(dc_pos, (dc_pos[0], y_top), neutral)
    p.wire(dc_neg, (dc_neg[0], y_bot), neutral)
    p.wire((dc_pos[0], y_top), (430 - 70, y_top), neutral)  # to L
    p.wire((dc_neg[0], y_bot), (760, y_bot), neutral)       # to cap

    # Inductor (highlighted).
    p.inductor((430, y_top), 130, accent=accent, glow_bg=glow,
               highlighted=True)
    p.label((430, y_top - 28), "L", accent, size=12, weight=700)

    # L → switching node.
    p.wire((430 + 70, y_top), (580, y_top), neutral)
    p.junction_dot((580, y_top), neutral)

    # Switch (Q1) hangs from switching node down to negative bus.
    p.mosfet((580, 125), neutral, "Q1")
    p.wire((580, y_top), (580, 125 - 18), neutral)
    p.wire((580, 125 + 18), (580, y_bot), neutral)
    p.junction_dot((580, y_bot), neutral)

    # Output diode: switching node → +DC bus, anode → cathode.
    # Lead-in wire from the switching node to the diode anode.
    p.wire((580, y_top), (660 - 14, y_top), neutral)
    p.diode((660, y_top), neutral, "D", orientation="right")
    p.wire((660 + 14, y_top), (760, y_top), neutral)

    # Output capacitor + load tap.
    p.junction_dot((760, y_top), neutral)
    p.junction_dot((760, y_bot), neutral)
    p.capacitor((760, 125), neutral, "C_bus", polarised=True, vertical=True)
    p.wire((760, y_top), (760, 125 - 18), neutral)
    p.wire((760, 125 + 18), (760, y_bot), neutral)

    # +VDC bus + load.
    p.wire((760, y_top), (890, y_top), neutral)
    p.label((815, y_top - 12), "+VDC", neutral, size=9, weight=600)
    p.wire((760, y_bot), (890, y_bot), neutral)
    p.load_block((890, 125), neutral)


def _render_passive_choke(p: _SchematicPainter, accent: QColor,
                          neutral: QColor, glow: QColor) -> None:
    """Passive PFC choke: Vac → bridge → L → Cbus → load.

    No switch — the inductor on the DC bus filters the rectified
    waveform passively. Same column layout as boost minus the
    Q/D pair, so the inductor takes more horizontal space and
    sits near logical x ≈ 430 (matches the test contract).
    """
    y_top, y_bot = 80, 170

    p.voltage_source_ac((80, (y_top + y_bot) / 2), neutral, "Vac")
    ac_l, ac_r, dc_pos, dc_neg = p.diode_bridge((220, 125), neutral)
    p.wire((96, y_top), (180, y_top), neutral)
    p.wire((180, y_top), (180, ac_l[1]), neutral)
    p.wire((180, ac_l[1]), ac_l, neutral)
    p.wire((96, y_bot), (260, y_bot), neutral)
    p.wire((260, y_bot), (260, ac_r[1]), neutral)
    p.wire((260, ac_r[1]), ac_r, neutral)
    p.wire(dc_pos, (dc_pos[0], y_top), neutral)
    p.wire(dc_neg, (dc_neg[0], y_bot), neutral)

    # +DC bus from bridge → inductor → cap. Inductor at x=430 to match
    # the test's pixel-sample contract (logical 430,80).
    p.wire((dc_pos[0], y_top), (430 - 80, y_top), neutral)
    p.inductor((430, y_top), 150, accent=accent, glow_bg=glow,
               highlighted=True)
    p.label((430, y_top - 28), "L", accent, size=12, weight=700)
    p.wire((430 + 80, y_top), (720, y_top), neutral)

    # Negative DC rail straight through.
    p.wire((dc_neg[0], y_bot), (720, y_bot), neutral)

    # Output cap + load tap.
    p.junction_dot((720, y_top), neutral)
    p.junction_dot((720, y_bot), neutral)
    p.capacitor((720, 125), neutral, "C_bus", polarised=True, vertical=True)
    p.wire((720, y_top), (720, 125 - 18), neutral)
    p.wire((720, 125 + 18), (720, y_bot), neutral)

    p.wire((720, y_top), (880, y_top), neutral)
    p.label((800, y_top - 12), "+VDC", neutral, size=9, weight=600)
    p.wire((720, y_bot), (880, y_bot), neutral)
    p.load_block((880, 125), neutral)


def _render_line_reactor_1ph(p: _SchematicPainter, accent: QColor,
                             neutral: QColor, glow: QColor) -> None:
    """Single-phase line reactor: Vac → L (AC line) → bridge → Cbus → load.

    The inductor lives on the AC side this time — it commutates with
    line current, not with rectified DC. We still highlight it as the
    sized component.
    """
    y_top, y_bot = 80, 170

    p.voltage_source_ac((80, (y_top + y_bot) / 2), neutral, "Vac")

    # Inductor on the top AC line.
    p.wire((96, y_top), (250 - 60, y_top), neutral)
    p.inductor((250, y_top), 110, accent=accent, glow_bg=glow,
               highlighted=True)
    p.label((250, y_top - 28), "L", accent, size=12, weight=700)
    p.wire((250 + 60, y_top), (370, y_top), neutral)

    # Bridge.
    ac_l, ac_r, dc_pos, dc_neg = p.diode_bridge((400, 125), neutral)
    p.wire((370, y_top), (370, ac_l[1]), neutral)
    p.wire((370, ac_l[1]), ac_l, neutral)
    p.wire((96, y_bot), (440, y_bot), neutral)
    p.wire((440, y_bot), (440, ac_r[1]), neutral)
    p.wire((440, ac_r[1]), ac_r, neutral)
    p.wire(dc_pos, (dc_pos[0], y_top), neutral)
    p.wire(dc_neg, (dc_neg[0], y_bot), neutral)

    # +DC + −DC out to the cap.
    p.wire((dc_pos[0], y_top), (720, y_top), neutral)
    p.wire((dc_neg[0], y_bot), (720, y_bot), neutral)

    p.junction_dot((720, y_top), neutral)
    p.junction_dot((720, y_bot), neutral)
    p.capacitor((720, 125), neutral, "C_bus", polarised=True, vertical=True)
    p.wire((720, y_top), (720, 125 - 18), neutral)
    p.wire((720, 125 + 18), (720, y_bot), neutral)

    p.wire((720, y_top), (880, y_top), neutral)
    p.label((800, y_top - 12), "+VDC", neutral, size=9, weight=600)
    p.wire((720, y_bot), (880, y_bot), neutral)
    p.load_block((880, 125), neutral)


def _render_line_reactor_3ph(p: _SchematicPainter, accent: QColor,
                             neutral: QColor, glow: QColor) -> None:
    """Three-phase line reactor: 3 × L on the line side → 6-pulse bridge
    → DC bus → load. Inductors hang horizontally, one per phase.
    """
    y_l1, y_l2, y_l3 = 60, 125, 195
    x_in_label = 50
    x_L = 200
    x_bridge = 410
    x_cap = 720
    x_load = 880

    # Phase labels + leads in.
    for y, lbl in zip((y_l1, y_l2, y_l3), ("L1", "L2", "L3"), strict=False):
        p.label((x_in_label, y), lbl, neutral, size=11, weight=700)
        p.wire((x_in_label + 22, y), (x_L - 55, y), neutral)

    # Three inductors (highlighted; one per phase).
    for y, lbl in zip((y_l1, y_l2, y_l3), ("L_a", "L_b", "L_c"),
                      strict=False):
        p.inductor((x_L, y), length=100, accent=accent, glow_bg=glow,
                   highlighted=True)
        p.label((x_L, y - 26), lbl, accent, size=10, weight=700)

    # 6-pulse bridge drawn as a labelled rectangle. The hexagon was
    # cute but the AC-rail wiring on its slanted edges produced
    # awkward Y-shaped junctions; a plain rectangle gives each
    # phase its own clean horizontal entry point.
    cx, cy = x_bridge, 125
    box_w, box_h = 110, 170
    rect = QRectF(cx - box_w / 2, cy - box_h / 2, box_w, box_h)
    self_qp = p._qp
    self_qp.setPen(p._pen(neutral, p.STROKE_COMPONENT))
    self_qp.setBrush(Qt.BrushStyle.NoBrush)
    self_qp.drawRoundedRect(rect, 6, 6)
    p.label((cx, cy + box_h / 2 + 12), "6-PULSE BRIDGE",
            neutral, size=10, weight=600)

    # Three AC inputs land on the left edge of the box at the same
    # y as their inductor — straight horizontal wires, no diagonals.
    bridge_left = cx - box_w / 2
    for y in (y_l1, y_l2, y_l3):
        p.wire((x_L + 50, y), (bridge_left, y), neutral)

    # DC outputs from the right edge of the box. Top output → +VDC,
    # bottom output → −VDC. We tap them at y=L1 and y=L3 so the
    # cap and load align cleanly with the outer phases.
    bridge_right = cx + box_w / 2
    p.wire((bridge_right, y_l1), (x_cap, y_l1), neutral)
    p.wire((bridge_right, y_l3), (x_cap, y_l3), neutral)

    # Output cap + load.
    p.junction_dot((x_cap, y_l1), neutral)
    p.junction_dot((x_cap, y_l3), neutral)
    p.capacitor((x_cap, 125), neutral, "C_bus", polarised=True,
                vertical=True)
    p.wire((x_cap, y_l1), (x_cap, 125 - 18), neutral)
    p.wire((x_cap, 125 + 18), (x_cap, y_l3), neutral)

    p.wire((x_cap, y_l1), (x_load, y_l1), neutral)
    p.label((x_cap + 80, y_l1 - 12), "+VDC", neutral, size=9, weight=600)
    p.wire((x_cap, y_l3), (x_load, y_l3), neutral)
    p.load_block((x_load, 125), neutral)


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

        # Map logical → device pixels, preserving aspect ratio so the
        # schematic never gets stretched into oblong shapes when the
        # parent column is wider than 4×height. We centre the canvas
        # horizontally and add equal padding on both sides.
        avail_w = float(self.width())
        avail_h = float(self.height())
        scale = min(avail_w / self.LOGICAL_W, avail_h / self.LOGICAL_H)
        used_w = self.LOGICAL_W * scale
        used_h = self.LOGICAL_H * scale
        ox = (avail_w - used_w) / 2.0
        oy = (avail_h - used_h) / 2.0
        qp.translate(ox, oy)
        qp.scale(scale, scale)

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
