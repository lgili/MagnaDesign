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

matplotlib.use("Agg")

from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg as FigureCanvas,
)
from matplotlib.figure import Figure
from matplotlib.patches import (
    Circle,
    FancyArrowPatch,
    Rectangle,
    Wedge,
)
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from pfc_inductor.ui.theme import get_theme, on_theme_changed


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

    # ── Coupled-pair (flyback / forward) extension ──
    # When ``Np_turns`` and ``Ns_turns`` are both > 0 the widget
    # draws two distinct windings on the same core: primary in
    # the project's accent_violet, secondary in accent_amber.
    # The widget infers stack-side layout (primary on the left
    # half of the window, secondary on the right) — engineers
    # reading the schematic immediately see "this is a coupled
    # inductor / transformer, not a single-winding choke".
    Np_turns: int = 0
    Ns_turns: int = 0
    primary_d_iso_mm: float = 0.0
    secondary_d_iso_mm: float = 0.0

    @classmethod
    def from_models(cls, core, wire, result) -> GeometryPayload:
        Np = int(getattr(result, "Np_turns", 0) or 0)
        Ns = int(getattr(result, "Ns_turns", 0) or 0)
        # For coupled-pair designs the project model usually
        # carries primary wire info on the main ``Wire`` slot and
        # the secondary as a separate field; if absent, fall
        # back to the primary's diameter so both windings still
        # render. Engineering signal lives in the colour split,
        # not the exact wire-size delta.
        d_iso = float(getattr(wire, "d_iso_mm", 0.0) or 0.0)
        # Resolve the shape via the project's canonical inferer
        # rather than ``core.shape.lower()`` directly. The MAS
        # catalog uses single-letter codes (``"T"`` for toroid,
        # ``"PQ"`` for PQ, etc.) that don't exact-match the
        # widget's painters; the inferer maps both the legacy
        # human-readable forms and the MAS short codes to the
        # same canonical kind ("toroid", "pq", "ee", "etd",
        # "generic").
        try:
            from pfc_inductor.visual.core_3d import infer_shape

            shape_kind = infer_shape(core)
        except Exception:
            shape_kind = str(getattr(core, "shape", "")).lower()

        # Many catalog entries (Magnetics, Micrometals, Thornton…)
        # ship Ae / le / Wa / AL but leave OD / ID / HT empty —
        # the schematic painters need physical dimensions, so
        # derive them from the electrical parameters when the
        # catalog didn't populate them. ``_toroid_dims`` /
        # ``_bobbin_dims`` already encode the closed-form maths:
        #   toroid:  ID = 2√(Wa/π);  OD = 2·le/π − ID;  HT = 2·Ae/(OD−ID)
        #   bobbin:  W ≈ ∛(1.4·Ve);  D = Ae/(0.32W);  H = 2·yoke + window
        OD = float(getattr(core, "OD_mm", 0.0) or 0.0)
        ID = float(getattr(core, "ID_mm", 0.0) or 0.0)
        HT = float(getattr(core, "HT_mm", 0.0) or 0.0)
        if OD <= 0 or HT <= 0 or (shape_kind == "toroid" and ID <= 0):
            try:
                from pfc_inductor.visual.core_3d import (
                    _bobbin_dims,
                    _toroid_dims,
                )

                if shape_kind == "toroid":
                    dims = _toroid_dims(core)
                    if dims is not None:
                        OD, ID, HT = dims
                else:
                    OD, HT, _D = _bobbin_dims(core)
                    # Bobbin returns (W, H, D); we keep W as OD,
                    # H as HT, and leave ID at 0 (no donut hole).
            except Exception:
                pass

        return cls(
            shape=shape_kind,
            OD_mm=OD,
            ID_mm=ID,
            HT_mm=HT,
            le_mm=float(getattr(core, "le_mm", 0.0) or 0.0),
            lgap_mm=float(getattr(core, "lgap_mm", 0.0) or 0.0),
            N_turns=int(getattr(result, "N_turns", 0) or 0),
            wire_d_iso_mm=d_iso,
            Bobbin_fill_pct=float(getattr(result, "Ku_actual", 0.0) or 0.0) * 100,
            core_part=str(getattr(core, "part_number", "") or ""),
            material_name=str(getattr(result, "material_name", "") or ""),
            Np_turns=Np,
            Ns_turns=Ns,
            primary_d_iso_mm=d_iso,
            secondary_d_iso_mm=d_iso,
        )

    @property
    def is_coupled_pair(self) -> bool:
        """``True`` when both windings have at least one turn —
        triggers the dual-colour render path in the widgets."""
        return self.Np_turns > 0 and self.Ns_turns > 0


class GeometryView(QWidget):
    """2-D annotated cross-section."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._fig = Figure(figsize=(7.0, 4.0), dpi=100)
        self._fig.set_facecolor(get_theme().palette.surface)
        self._canvas = FigureCanvas(self._fig)
        # 320 px is enough for a readable cross-section at this
        # font scale; the earlier 420 was sized for a fullscreen
        # dialog and clipped the dialog's button row on 720p
        # laptops.
        self._canvas.setMinimumHeight(320)

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
        outer = Circle((0, 0), r_out, color=pal.text_muted, alpha=0.85, zorder=2)
        inner = Circle((0, 0), r_in, color=pal.surface, zorder=3)
        ax.add_patch(outer)
        ax.add_patch(inner)
        ax.add_patch(Circle((0, 0), r_out, fill=False, edgecolor=pal.text, linewidth=1.5, zorder=4))
        ax.add_patch(Circle((0, 0), r_in, fill=False, edgecolor=pal.text, linewidth=1.5, zorder=4))

        # Air gap (sector on the inner radius). Catalog toroids
        # rarely have one but distributed-gap powder cores are
        # often quoted with an effective lgap; we represent that
        # as a 12° sector for visual reference.
        if p.lgap_mm > 0:
            theta_gap = 12.0
            ax.add_patch(
                Wedge(
                    (0, 0),
                    r_in + (r_out - r_in) * 0.20,
                    90 - theta_gap / 2,
                    90 + theta_gap / 2,
                    width=(r_out - r_in) * 0.20,
                    facecolor=pal.danger,
                    alpha=0.45,
                    edgecolor=pal.danger,
                    linewidth=1.0,
                    zorder=5,
                )
            )

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
                ax.add_patch(
                    Circle(
                        (cx, cy),
                        d / 2,
                        facecolor=pal.warning,
                        alpha=0.85,
                        edgecolor=pal.text,
                        linewidth=0.4,
                        zorder=6,
                    )
                )
            if p.N_turns > N_show:
                # Place the count badge INSIDE the inner radius so
                # it doesn't crowd the OD dimension arrow under the
                # ring. ID label moves up a bit when the badge is
                # present.
                ax.text(
                    0,
                    r_in * 0.45,
                    f"showing {N_show} of {p.N_turns} turns",
                    ha="center",
                    va="center",
                    fontsize=8,
                    color=pal.text_muted,
                    style="italic",
                )

        # Dimension annotations (OD, ID).
        self._dim_arrow(
            ax, (-r_out, -r_out * 1.10), (r_out, -r_out * 1.10), f"OD = {OD:.1f} mm", pal
        )
        self._dim_arrow(
            ax,
            (-r_in, -r_in * 0.50),
            (r_in, -r_in * 0.50),
            f"ID = {ID:.1f} mm",
            pal,
            offset_y=-r_out * 0.04,
        )

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
        ax.add_patch(
            Rectangle(
                (x0, -HT / 2),
                ol,
                HT,
                facecolor=pal.text_muted,
                alpha=0.85,
                edgecolor=pal.text,
                linewidth=1.5,
                zorder=2,
            )
        )
        # Mirror.
        ax.add_patch(
            Rectangle(
                (-x0 - ol, -HT / 2),
                ol,
                HT,
                facecolor=pal.text_muted,
                alpha=0.85,
                edgecolor=pal.text,
                linewidth=1.5,
                zorder=2,
            )
        )
        # Centre leg.
        ax.add_patch(
            Rectangle(
                (-cl / 2, -HT / 2),
                cl,
                HT,
                facecolor=pal.text_muted,
                alpha=0.85,
                edgecolor=pal.text,
                linewidth=1.5,
                zorder=2,
            )
        )
        # Top/bottom yokes.
        ax.add_patch(
            Rectangle(
                (-cl / 2 - ww - ol, HT / 2 - ol),
                cl + 2 * ww + 2 * ol,
                ol,
                facecolor=pal.text_muted,
                alpha=0.85,
                edgecolor=pal.text,
                linewidth=1.5,
                zorder=2,
            )
        )
        ax.add_patch(
            Rectangle(
                (-cl / 2 - ww - ol, -HT / 2),
                cl + 2 * ww + 2 * ol,
                ol,
                facecolor=pal.text_muted,
                alpha=0.85,
                edgecolor=pal.text,
                linewidth=1.5,
                zorder=2,
            )
        )
        # Gap on the centre leg.
        if p.lgap_mm > 0:
            g_h = max(p.lgap_mm, OD * 0.012)  # min visible gap
            ax.add_patch(
                Rectangle(
                    (-cl / 2, -g_h / 2),
                    cl,
                    g_h,
                    facecolor=pal.danger,
                    alpha=0.55,
                    edgecolor=pal.danger,
                    linewidth=1.0,
                    zorder=4,
                )
            )
            ax.text(
                cl / 2 + ww * 0.05,
                0,
                f"gap {p.lgap_mm:.2f} mm",
                color=pal.danger,
                fontsize=9,
                fontweight="bold",
                va="center",
                zorder=5,
            )

        # Winding dots in the windows.
        # ── Coupled-pair (flyback / forward) ──
        # When Np > 0 and Ns > 0 we split the right window
        # vertically: primary fills the BOTTOM half, secondary
        # the TOP. Mirrors to the left window stay synced. Two
        # colours so the engineer sees at a glance that this is
        # a transformer-style design, not a single-winding choke.
        # ── Single-winding choke ──
        # Falls through to the original placement: one colour,
        # both windows used.
        d = p.wire_d_iso_mm
        if p.is_coupled_pair and d > 0:
            self._draw_coupled_pair_e_core(
                ax,
                p,
                cl,
                ww,
                x0,
                ol,
                HT,
                d,
                pal,  # ww kept for signature symmetry
            )
        elif p.N_turns > 0 and d > 0:
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
                    ax.add_patch(
                        Circle(
                            (cx, cy),
                            d / 2,
                            facecolor=pal.warning,
                            alpha=0.85,
                            edgecolor=pal.text,
                            linewidth=0.4,
                            zorder=6,
                        )
                    )
                    # Mirror to left window.
                    ax.add_patch(
                        Circle(
                            (-cx, cy),
                            d / 2,
                            facecolor=pal.warning,
                            alpha=0.85,
                            edgecolor=pal.text,
                            linewidth=0.4,
                            zorder=6,
                        )
                    )
                    placed += 1
            if p.N_turns > target:
                ax.text(
                    0,
                    HT / 2 + HT * 0.06,
                    f"showing {target * 2} of {p.N_turns * 2} cross-sections",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                    color=pal.text_muted,
                    style="italic",
                )

        # Dimensions.
        x_full = cl / 2 + ww + ol
        self._dim_arrow(
            ax,
            (-x_full, -HT / 2 - HT * 0.10),
            (x_full, -HT / 2 - HT * 0.10),
            f"OD ≈ {OD:.1f} mm",
            pal,
        )
        self._dim_arrow(
            ax,
            (-x_full * 1.08, -HT / 2),
            (-x_full * 1.08, HT / 2),
            f"HT = {HT:.1f} mm",
            pal,
            rotate_text=True,
        )

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
        ax.add_patch(
            Rectangle(
                (-side / 2, -h / 2),
                side,
                h,
                facecolor=pal.text_muted,
                alpha=0.85,
                edgecolor=pal.text,
                linewidth=1.5,
            )
        )
        # Window (centred).
        wx, wy = side * 0.55, h * 0.55
        ax.add_patch(
            Rectangle(
                (-wx / 2, -wy / 2), wx, wy, facecolor=pal.surface, edgecolor=pal.text, linewidth=1.0
            )
        )
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
                    ax.add_patch(
                        Circle(
                            (cx, cy),
                            d / 2,
                            facecolor=pal.warning,
                            alpha=0.85,
                            edgecolor=pal.text,
                            linewidth=0.4,
                        )
                    )
                    placed += 1
                if placed >= target:
                    break
        ax.set_xlim(-side * 0.75, side * 0.75)
        ax.set_ylim(-h * 0.85, h * 0.85)
        ax.set_aspect("equal")
        ax.set_axis_off()
        self._title_block(ax, p, f"{p.shape.upper() or 'Core'} — schematic")

    def _draw_coupled_pair_e_core(
        self,
        ax,
        p: GeometryPayload,
        cl: float,
        _ww: float,
        x0: float,
        ol: float,
        HT: float,
        d: float,
        pal,
    ) -> None:
        """Two-colour winding render for flyback / coupled-pair.

        Layout choice — primary on the BOTTOM half, secondary on
        the TOP half of the right-side window (mirrored to the
        left). Stacked-bobbin construction is the most common in
        the 50–500 W flyback range; side-by-side construction is
        more common at higher power but harder to read on a
        small schematic. We pick stacked.

        Each winding gets its own colour (primary = accent_violet,
        secondary = accent_cyan-ish via warning) and its turn
        count is rendered in the corresponding region with the
        usual "showing X of Y" annotation when capped.
        """
        # Window bounds (right side; left is the mirror).
        x_min = cl / 2 + d * 0.6
        x_max = x0 - d * 0.6
        y_full_min = -HT / 2 + ol + d * 0.6
        y_full_max = HT / 2 - ol - d * 0.6
        y_split = (y_full_min + y_full_max) / 2.0

        # Primary on bottom half.
        target_p = self._fill_winding(
            ax,
            p.Np_turns,
            d,
            x_min,
            x_max,
            y_full_min,
            y_split,
            color=pal.accent_violet,
            edge_color=pal.text,
        )
        # Secondary on top half — different colour.
        target_s = self._fill_winding(
            ax,
            p.Ns_turns,
            d,
            x_min,
            x_max,
            y_split + d * 0.2,
            y_full_max,
            color=pal.warning,
            edge_color=pal.text,
        )

        # Note caps if either winding got truncated.
        notes = []
        if p.Np_turns > target_p:
            notes.append(f"P showing {target_p}/{p.Np_turns}")
        if p.Ns_turns > target_s:
            notes.append(f"S showing {target_s}/{p.Ns_turns}")
        if notes:
            # Place above the geometry, not below — the bottom is
            # reserved for the OD dimension arrow on PQ/E painters.
            ax.text(
                0,
                HT / 2 + HT * 0.06,
                "  ·  ".join(notes),
                ha="center",
                va="bottom",
                fontsize=8,
                color=pal.text_muted,
                style="italic",
            )

        # Horizontal divider so the split is unambiguous.
        ax.plot(
            [x_min - d * 0.2, x_max + d * 0.2],
            [y_split, y_split],
            color=pal.text_muted,
            linestyle=":",
            linewidth=0.8,
            zorder=7,
        )
        ax.plot(
            [-x_max - d * 0.2, -x_min + d * 0.2],
            [y_split, y_split],
            color=pal.text_muted,
            linestyle=":",
            linewidth=0.8,
            zorder=7,
        )

        # Inline winding-key in the top-left corner of the plot.
        legend_x = -x0 - ol * 1.5
        ax.scatter(
            [legend_x],
            [y_full_max + d * 0.5],
            color=pal.accent_violet,
            s=90,
            zorder=8,
            edgecolors=pal.text,
            linewidths=0.5,
        )
        ax.text(
            legend_x + d * 1.2,
            y_full_max + d * 0.5,
            f"primary  Np = {p.Np_turns}",
            fontsize=8,
            color=pal.text,
            va="center",
        )
        ax.scatter(
            [legend_x],
            [y_full_max - d * 0.5],
            color=pal.warning,
            s=90,
            zorder=8,
            edgecolors=pal.text,
            linewidths=0.5,
        )
        ax.text(
            legend_x + d * 1.2,
            y_full_max - d * 0.5,
            f"secondary  Ns = {p.Ns_turns}",
            fontsize=8,
            color=pal.text,
            va="center",
        )

    @staticmethod
    def _fill_winding(
        ax,
        n_turns: int,
        d: float,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
        color,
        edge_color,
    ) -> int:
        """Pack ``n_turns`` insulated round conductors into the
        rectangle. Mirror-to-left so both windows show. Returns
        the number of turns actually drawn (capped by the
        rectangle's capacity)."""
        from matplotlib.patches import Circle

        n_per_layer = max(1, int((x_max - x_min) / d))
        n_layers = max(1, int((y_max - y_min) / d))
        target = min(n_turns, n_per_layer * n_layers)
        placed = 0
        for ly in range(n_layers):
            if placed >= target:
                break
            for lx in range(n_per_layer):
                if placed >= target:
                    break
                cx = x_min + (lx + 0.5) * d
                cy = y_min + (ly + 0.5) * d
                ax.add_patch(
                    Circle(
                        (cx, cy),
                        d / 2,
                        facecolor=color,
                        alpha=0.85,
                        edgecolor=edge_color,
                        linewidth=0.4,
                        zorder=6,
                    )
                )
                ax.add_patch(
                    Circle(
                        (-cx, cy),
                        d / 2,
                        facecolor=color,
                        alpha=0.85,
                        edgecolor=edge_color,
                        linewidth=0.4,
                        zorder=6,
                    )
                )
                placed += 1
        return placed

    # ── Helpers ──
    def _dim_arrow(
        self, ax, p1, p2, label: str, pal, offset_y: float = 0.0, rotate_text: bool = False
    ) -> None:
        """Draw a horizontal/vertical dimension arrow with label."""
        ax.add_patch(
            FancyArrowPatch(
                p1,
                p2,
                arrowstyle="<|-|>",
                mutation_scale=10,
                color=pal.text_secondary,
                linewidth=0.8,
            )
        )
        cx = (p1[0] + p2[0]) / 2
        cy = (p1[1] + p2[1]) / 2 + offset_y
        if rotate_text:
            ax.text(
                cx,
                cy,
                label,
                color=pal.text_secondary,
                fontsize=8,
                ha="center",
                va="center",
                rotation=90,
            )
        else:
            ax.text(
                cx, cy - 0.6, label, color=pal.text_secondary, fontsize=8, ha="center", va="top"
            )

    def _title_block(self, ax, p: GeometryPayload, title: str) -> None:
        pal = get_theme().palette
        # Title: short, technical.
        ax.set_title(title, fontsize=11, fontweight="bold", color=pal.text, loc="left", pad=10)
        # Datasheet-style stamp — top-right corner, stacked
        # vertically. The previous bottom-right placement collided
        # with the OD dimension-arrow label on the toroid path
        # (both gravitated to the centre-bottom of the figure
        # because the part-number string is long); putting it at
        # the top-right corner keeps it clear of every dimension
        # annotation, and stacking each field on its own line
        # avoids horizontal sprawl across the figure width.
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
            ax.text(
                0.99,
                0.99,
                "\n".join(bits),
                transform=ax.transAxes,
                ha="right",
                va="top",
                fontsize=8,
                color=pal.text_muted,
                family="monospace",
                linespacing=1.4,
            )
