"""Datasheet-style cross-section schematic of the designed inductor.

Renders an annotated 2-D drawing of the core + winding + air gap
straight from :class:`~pfc_inductor.models.core.Core` and
:class:`~pfc_inductor.models.result.DesignResult`. No FEA needed —
this view is always available, even before the user runs any
validation.

Why this widget exists:

The FEA field plots show *what the simulator solved on*. They
don't show *what the design is* in a way the engineer can sanity-
check at a glance. A datasheet-style drawing — outline of the
core, winding-window with N turn dots arranged in layers, gap
location, key dimensions — fills that gap.

Shapes supported:

- ``toroid``   — concentric annulus, gap (if any) shown as a
                 shaded sector on the inner radius.
- ``pq``, ``etd``, ``efd``, ``rm``, ``e``, ``ec``, ``ee`` —
                 axisymmetric E-core / pot-core cross-section
                 with two outer legs and a centre leg carrying
                 the gap.

Unknown shapes fall back to a generic box-with-window sketch so
the widget never errors out on exotic catalog entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # noqa: E402

from matplotlib.backends.backend_qtagg import (  # noqa: E402
    FigureCanvasQTAgg as FigureCanvas,
)
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import (  # noqa: E402
    Circle,
    FancyArrowPatch,
    Rectangle,
    Wedge,
)
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget  # noqa: E402

from pfc_inductor.ui.theme import get_theme, on_theme_changed  # noqa: E402


@dataclass(frozen=True)
class GeometryPayload:
    """Plain-data view of the geometry to draw.

    Decoupled from ``Core``/``DesignResult`` so the widget can be
    fed from a quick optimiser preview as well as the final
    validated design.
    """

    shape: str  # "toroid", "pq", "e", ... (case-insensitive)
    OD_mm: float = 0.0
    ID_mm: float = 0.0
    HT_mm: float = 0.0
    le_mm: float = 0.0
    lgap_mm: float = 0.0
    """Total gap length [mm]. For a toroid this would be 0 unless
    the catalog specifies a discrete gap; for E-cores it's the
    centre-leg gap."""
    N_turns: int = 0
    wire_d_iso_mm: float = 0.0
    """Outer (insulated) wire diameter — sets the size of the
    turn dots in the winding window."""
    Bobbin_fill_pct: float = 0.0
    core_part: str = ""
    material_name: str = ""

    @classmethod
    def from_models(cls, core, wire, result) -> "GeometryPayload":
        return cls(
            shape=str(getattr(core, "shape", "")).lower(),
            OD_mm=float(getattr(core, "OD_mm", 0.0) or 0.0),
            ID_mm=float(getattr(core, "ID_mm", 0.0) or 0.0),
            HT_mm=float(getattr(core, "HT_mm", 0.0) or 0.0),
            le_mm=float(getattr(core, "le_mm", 0.0) or 0.0),
            lgap_mm=float(getattr(core, "lgap_mm", 0.0) or 0.0),
            N_turns=int(getattr(result, "N_turns", 0) or 0),
            wire_d_iso_mm=float(getattr(wire, "d_iso_mm", 0.0) or 0.0),
            Bobbin_fill_pct=float(getattr(result, "Ku_actual", 0.0) or 0.0) * 100,
            core_part=str(getattr(core, "part_number", "") or ""),
            material_name=str(getattr(result, "material_name", "") or ""),
        )


class GeometryView(QWidget):
    """2-D annotated cross-section."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._fig = Figure(figsize=(7.0, 5.0), dpi=100)
        self._fig.set_facecolor(get_theme().palette.surface)
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setMinimumHeight(420)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._canvas, 1)

        self._last: Optional[GeometryPayload] = None
        self._paint_empty()
        on_theme_changed(self.refresh_theme)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def show_payload(self, payload: GeometryPayload) -> None:
        self._last = payload
        self._paint(payload)

    def refresh_theme(self) -> None:
        self._fig.set_facecolor(get_theme().palette.surface)
        if self._last is None:
            self._paint_empty()
        else:
            self._paint(self._last)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _paint_empty(self) -> None:
        self._fig.clear()
        ax = self._fig.add_subplot(111)
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "Run a design to see the cross-section schematic.",
            ha="center",
            va="center",
            fontsize=10,
            color=get_theme().palette.text_muted,
            transform=ax.transAxes,
        )
        self._canvas.draw_idle()

    def _paint(self, p: GeometryPayload) -> None:
        self._fig.clear()
        if p.shape == "toroid":
            self._paint_toroid(p)
        elif p.shape in ("pq", "etd", "efd", "rm", "e", "ec", "ee"):
            self._paint_e_core(p)
        else:
            self._paint_generic(p)
        self._fig.tight_layout()
        self._canvas.draw_idle()

    # ── Toroid: top-down view ──
    # Annulus with N turn dots arranged on the bobbin radius. Air
    # gap (if any) shown as a shaded sector on the inner radius.
    def _paint_toroid(self, p: GeometryPayload) -> None:
        pal = get_theme().palette
        ax = self._fig.add_subplot(111)
        # HT not used — toroid view is top-down so height doesn't
        # appear in the drawing. ID/OD are the only dimensions
        # the cross-section needs.
        OD, ID = p.OD_mm, p.ID_mm
        if OD <= 0 or ID <= 0:
            self._paint_generic(p)
            return
        r_out = OD / 2
        r_in = ID / 2

        # Core: filled annulus.
        outer = Circle((0, 0), r_out, color=pal.text_muted, alpha=0.85,
                       zorder=2)
        inner = Circle((0, 0), r_in, color=pal.surface, zorder=3)
        ax.add_patch(outer)
        ax.add_patch(inner)
        ax.add_patch(Circle((0, 0), r_out, fill=False, edgecolor=pal.text,
                            linewidth=1.5, zorder=4))
        ax.add_patch(Circle((0, 0), r_in, fill=False, edgecolor=pal.text,
                            linewidth=1.5, zorder=4))

        # Air gap (sector on the inner radius). Catalog toroids
        # rarely have one but distributed-gap powder cores are
        # often quoted with an effective lgap; we represent that
        # as a 12° sector for visual reference.
        if p.lgap_mm > 0:
            theta_gap = 12.0
            ax.add_patch(Wedge((0, 0), r_in + (r_out - r_in) * 0.20,
                                90 - theta_gap / 2, 90 + theta_gap / 2,
                                width=(r_out - r_in) * 0.20,
                                facecolor=pal.danger, alpha=0.45,
                                edgecolor=pal.danger, linewidth=1.0,
                                zorder=5))

        # Winding turn dots on the bobbin radius. Show min(N, 96)
        # so very high-N designs don't fill the plot with noise.
        N_show = min(p.N_turns, 96)
        if N_show > 0 and p.wire_d_iso_mm > 0:
            r_b = (r_out + r_in) / 2
            d = p.wire_d_iso_mm
            from math import cos, pi, sin
            for k in range(N_show):
                ang = 2 * pi * k / N_show
                cx, cy = r_b * cos(ang), r_b * sin(ang)
                ax.add_patch(Circle((cx, cy), d / 2,
                                    facecolor=pal.warning, alpha=0.85,
                                    edgecolor=pal.text, linewidth=0.4,
                                    zorder=6))
            if p.N_turns > N_show:
                ax.text(0, -r_out * 1.05,
                        f"showing {N_show} of {p.N_turns} turns",
                        ha="center", va="top", fontsize=8,
                        color=pal.text_muted)

        # Dimension annotations (OD, ID).
        self._dim_arrow(ax, (-r_out, -r_out * 1.10),
                        (r_out, -r_out * 1.10),
                        f"OD = {OD:.1f} mm", pal)
        self._dim_arrow(ax, (-r_in, -r_in * 0.50),
                        (r_in, -r_in * 0.50),
                        f"ID = {ID:.1f} mm", pal,
                        offset_y=-r_out * 0.04)

        ax.set_xlim(-r_out * 1.18, r_out * 1.18)
        ax.set_ylim(-r_out * 1.30, r_out * 1.18)
        ax.set_aspect("equal")
        ax.set_axis_off()
        self._title_block(ax, p, "Toroid — top view (cross-section, in mm)")

    # ── E / PQ / ETD: r-z cross-section ──
    # Two outer legs + centre leg with the gap. Symmetric about
    # z=0; we draw the right half and mirror.
    def _paint_e_core(self, p: GeometryPayload) -> None:
        pal = get_theme().palette
        ax = self._fig.add_subplot(111)
        OD, HT = p.OD_mm, p.HT_mm
        if OD <= 0 or HT <= 0:
            self._paint_generic(p)
            return
        # Synthesise leg / window geometry from OD/HT — this is
        # an illustrative sketch, not a CAD-accurate render. The
        # ratios match a typical PQ / E-core: centre leg ~0.35·OD,
        # window width ~0.30·OD per side, outer leg ~0.10·OD.
        cl = 0.35 * OD
        ww = 0.30 * OD
        ol = 0.10 * OD
        # Outer leg (right half).
        x0 = cl / 2 + ww
        ax.add_patch(Rectangle((x0, -HT / 2), ol, HT,
                                facecolor=pal.text_muted, alpha=0.85,
                                edgecolor=pal.text, linewidth=1.5, zorder=2))
        # Mirror.
        ax.add_patch(Rectangle((-x0 - ol, -HT / 2), ol, HT,
                                facecolor=pal.text_muted, alpha=0.85,
                                edgecolor=pal.text, linewidth=1.5, zorder=2))
        # Centre leg.
        ax.add_patch(Rectangle((-cl / 2, -HT / 2), cl, HT,
                                facecolor=pal.text_muted, alpha=0.85,
                                edgecolor=pal.text, linewidth=1.5, zorder=2))
        # Top/bottom yokes.
        ax.add_patch(Rectangle((-cl / 2 - ww - ol, HT / 2 - ol),
                                cl + 2 * ww + 2 * ol, ol,
                                facecolor=pal.text_muted, alpha=0.85,
                                edgecolor=pal.text, linewidth=1.5, zorder=2))
        ax.add_patch(Rectangle((-cl / 2 - ww - ol, -HT / 2),
                                cl + 2 * ww + 2 * ol, ol,
                                facecolor=pal.text_muted, alpha=0.85,
                                edgecolor=pal.text, linewidth=1.5, zorder=2))
        # Gap on the centre leg.
        if p.lgap_mm > 0:
            g_h = max(p.lgap_mm, OD * 0.012)  # min visible gap
            ax.add_patch(Rectangle((-cl / 2, -g_h / 2), cl, g_h,
                                    facecolor=pal.danger, alpha=0.55,
                                    edgecolor=pal.danger, linewidth=1.0,
                                    zorder=4))
            ax.text(cl / 2 + ww * 0.05, 0, f"gap {p.lgap_mm:.2f} mm",
                    color=pal.danger, fontsize=9, fontweight="bold",
                    va="center", zorder=5)

        # Winding dots in the right window (horizontal layers).
        if p.N_turns > 0 and p.wire_d_iso_mm > 0:
            d = p.wire_d_iso_mm
            x_min = cl / 2 + d * 0.6
            x_max = x0 - d * 0.6
            y_min = -HT / 2 + ol + d * 0.6
            y_max = HT / 2 - ol - d * 0.6
            n_per_layer = max(1, int((x_max - x_min) / d))
            n_layers = max(1, int((y_max - y_min) / d))
            placed = 0
            target = min(p.N_turns, n_per_layer * n_layers)
            for ly in range(n_layers):
                if placed >= target:
                    break
                for lx in range(n_per_layer):
                    if placed >= target:
                        break
                    cx = x_min + (lx + 0.5) * d
                    cy = y_min + (ly + 0.5) * d
                    ax.add_patch(Circle((cx, cy), d / 2,
                                        facecolor=pal.warning, alpha=0.85,
                                        edgecolor=pal.text, linewidth=0.4,
                                        zorder=6))
                    # Mirror to left window.
                    ax.add_patch(Circle((-cx, cy), d / 2,
                                        facecolor=pal.warning, alpha=0.85,
                                        edgecolor=pal.text, linewidth=0.4,
                                        zorder=6))
                    placed += 1
            if p.N_turns > target:
                ax.text(0, -HT / 2 - HT * 0.08,
                        f"showing {target * 2} of {p.N_turns * 2} cross-sections",
                        ha="center", va="top", fontsize=8,
                        color=pal.text_muted)

        # Dimensions.
        x_full = cl / 2 + ww + ol
        self._dim_arrow(ax, (-x_full, -HT / 2 - HT * 0.10),
                        (x_full, -HT / 2 - HT * 0.10),
                        f"OD ≈ {OD:.1f} mm", pal)
        self._dim_arrow(ax, (-x_full * 1.08, -HT / 2),
                        (-x_full * 1.08, HT / 2),
                        f"HT = {HT:.1f} mm", pal,
                        rotate_text=True)

        ax.set_xlim(-x_full * 1.20, x_full * 1.20)
        ax.set_ylim(-HT / 2 - HT * 0.30, HT / 2 + HT * 0.18)
        ax.set_aspect("equal")
        ax.set_axis_off()
        self._title_block(ax, p, f"{p.shape.upper()} core — r-z cross-section (mm)")

    # ── Generic fallback ──
    # Plain box with a window and turn dots, when shape is unknown.
    def _paint_generic(self, p: GeometryPayload) -> None:
        pal = get_theme().palette
        ax = self._fig.add_subplot(111)
        # Use OD as a side, HT as height; otherwise fall to 1.0
        # arbitrary units.
        side = p.OD_mm or 30.0
        h = p.HT_mm or 20.0
        ax.add_patch(Rectangle((-side / 2, -h / 2), side, h,
                                facecolor=pal.text_muted, alpha=0.85,
                                edgecolor=pal.text, linewidth=1.5))
        # Window (centred).
        wx, wy = side * 0.55, h * 0.55
        ax.add_patch(Rectangle((-wx / 2, -wy / 2), wx, wy,
                                facecolor=pal.surface,
                                edgecolor=pal.text, linewidth=1.0))
        # Turn dots in the window.
        if p.N_turns > 0 and p.wire_d_iso_mm > 0:
            d = p.wire_d_iso_mm
            n_per_layer = max(1, int(wx / d))
            placed = 0
            target = min(p.N_turns, 64)
            for ly in range(int(wy / d) or 1):
                for lx in range(n_per_layer):
                    if placed >= target:
                        break
                    cx = -wx / 2 + (lx + 0.5) * d
                    cy = -wy / 2 + (ly + 0.5) * d
                    ax.add_patch(Circle((cx, cy), d / 2,
                                        facecolor=pal.warning, alpha=0.85,
                                        edgecolor=pal.text, linewidth=0.4))
                    placed += 1
                if placed >= target:
                    break
        ax.set_xlim(-side * 0.75, side * 0.75)
        ax.set_ylim(-h * 0.85, h * 0.85)
        ax.set_aspect("equal")
        ax.set_axis_off()
        self._title_block(ax, p, f"{p.shape.upper() or 'Core'} — schematic")

    # ── Helpers ──
    def _dim_arrow(self, ax, p1, p2, label: str, pal,
                   offset_y: float = 0.0, rotate_text: bool = False) -> None:
        """Draw a horizontal/vertical dimension arrow with label."""
        ax.add_patch(FancyArrowPatch(p1, p2,
                                      arrowstyle="<|-|>",
                                      mutation_scale=10,
                                      color=pal.text_secondary,
                                      linewidth=0.8))
        cx = (p1[0] + p2[0]) / 2
        cy = (p1[1] + p2[1]) / 2 + offset_y
        if rotate_text:
            ax.text(cx, cy, label, color=pal.text_secondary,
                    fontsize=8, ha="center", va="center",
                    rotation=90)
        else:
            ax.text(cx, cy - 0.6, label, color=pal.text_secondary,
                    fontsize=8, ha="center", va="top")

    def _title_block(self, ax, p: GeometryPayload, title: str) -> None:
        pal = get_theme().palette
        # Title: short, technical.
        ax.set_title(title, fontsize=11, fontweight="bold",
                     color=pal.text, loc="left", pad=10)
        # Bottom-right "datasheet-style" stamp.
        bits = []
        if p.core_part:
            bits.append(p.core_part)
        if p.material_name:
            bits.append(p.material_name)
        if p.N_turns:
            bits.append(f"N = {p.N_turns}")
        if p.lgap_mm > 0:
            bits.append(f"gap {p.lgap_mm:.2f} mm")
        if bits:
            ax.text(0.99, 0.02, "  ·  ".join(bits),
                    transform=ax.transAxes,
                    ha="right", va="bottom",
                    fontsize=8, color=pal.text_muted,
                    family="monospace")
