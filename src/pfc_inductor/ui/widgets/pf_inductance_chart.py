"""``PFInductanceChart`` — embeddable PF vs inductance widget.

Live counterpart to the PDF datasheet's ``_fig_pf_vs_inductance``
helper. Sweeps the choke / reactor inductance from very small to
~2.5 × the design value and traces:

- the predicted input power factor on the left axis (blue)
- the apparent power S = P_active / PF on the right axis (red,
  dashed) — the source-side rating burden the choice of L imposes

Boost-PFC topologies render an empty placeholder because the
active control loop sets PF ≈ 1 regardless of L; the plot would
be a flat line at 0.99.

Theme-aware via ``on_theme_changed``.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.physics import power_factor as pfm
from pfc_inductor.ui.theme import get_theme, on_theme_changed


def _figure_imports():
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
    from matplotlib.figure import Figure

    return Canvas, Figure


class PFInductanceChart(QWidget):
    """PF + apparent power as a function of inductance."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self._outer = v
        self._placeholder = QWidget()
        self._placeholder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        v.addWidget(self._placeholder)
        self._fig = None
        self._ax_pf = None
        self._ax_S = None
        self._canvas = None
        self._canvas_built = False
        self._last: Optional[tuple[Spec, DesignResult]] = None
        on_theme_changed(self._refresh_palette)

    def _ensure_canvas_built(self) -> None:
        if self._canvas_built:
            return
        Canvas, Figure = _figure_imports()
        p = get_theme().palette
        self._fig = Figure(figsize=(5.4, 2.8), dpi=100, facecolor=p.surface, tight_layout=True)
        self._ax_pf = self._fig.add_subplot(1, 1, 1)
        self._ax_S = self._ax_pf.twinx()
        self._canvas = Canvas(self._fig)
        idx = self._outer.indexOf(self._placeholder)
        self._outer.removeWidget(self._placeholder)
        self._placeholder.deleteLater()
        self._placeholder = None  # type: ignore[assignment]
        self._outer.insertWidget(idx, self._canvas)
        self._canvas_built = True
        if self._last is not None:
            self._render()
        else:
            self._render_empty("Waiting for calculation…")

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        self._ensure_canvas_built()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update_from_design(
        self, result: DesignResult, spec: Spec, core: Core, wire: Wire, material: Material
    ) -> None:
        self._last = (spec, result)
        if self._canvas_built:
            self._render()

    def clear(self) -> None:
        self._last = None
        if self._canvas_built:
            self._render_empty("Waiting for calculation…")

    # ------------------------------------------------------------------
    def _refresh_palette(self) -> None:
        if not self._canvas_built or self._fig is None:
            return
        p = get_theme().palette
        self._fig.set_facecolor(p.surface)
        if self._last is None:
            self._render_empty("Waiting for calculation…")
        else:
            self._render()

    def _render_empty(self, message: str) -> None:
        assert (
            self._ax_pf is not None
            and self._ax_S is not None
            and self._fig is not None
            and self._canvas is not None
        )
        p = get_theme().palette
        for ax in (self._ax_pf, self._ax_S):
            ax.clear()
            ax.set_facecolor(p.surface)
            for spine in ax.spines.values():
                spine.set_visible(False)
            ax.set_xticks([])
            ax.set_yticks([])
        self._ax_pf.text(
            0.5,
            0.5,
            message,
            ha="center",
            va="center",
            color=p.text_muted,
            fontsize=10,
            transform=self._ax_pf.transAxes,
        )
        self._canvas.draw_idle()

    def _render(self) -> None:
        if self._last is None:
            self._render_empty("Waiting for calculation…")
            return
        spec, result = self._last

        # Boost-PFC (and interleaved boost-PFC): PF ≈ 1 by
        # active-control design, plot is uninformative. Show a
        # friendly note.
        if spec.topology in ("boost_ccm", "interleaved_boost_pfc"):
            self._render_empty(
                "Active boost-PFC sets PF ≈ 1 by design.\n"
                "PF vs L is uninformative for this topology."
            )
            return
        if result.L_actual_uH <= 0:
            self._render_empty("Insufficient data to plot PF(L).")
            return

        assert (
            self._ax_pf is not None
            and self._ax_S is not None
            and self._fig is not None
            and self._canvas is not None
        )
        p = get_theme().palette
        # Sweep L. Use the same range as the PDF helper so the live
        # view matches the printed datasheet.
        L_design = float(result.L_actual_uH)
        L_min = max(L_design * 0.05, 50.0)
        L_max = L_design * 2.5
        L_arr = np.linspace(L_min, L_max, 200)
        PF_arr = np.array([pfm.pf_at_L(spec, float(L)) for L in L_arr])
        S_arr = np.array([pfm.apparent_power_VA(spec, float(L)) for L in L_arr])
        PF_design = pfm.pf_at_L(spec, L_design)
        S_design = pfm.apparent_power_VA(spec, L_design)

        # Pick the L unit that keeps the axis numbers human-sized.
        # Reactors land in mH; chokes in µH.
        use_mH = spec.topology == "line_reactor"
        L_plot = L_arr / 1000.0 if use_mH else L_arr
        L_design_plot = L_design / 1000.0 if use_mH else L_design
        L_unit = "mH" if use_mH else "µH"

        ax_pf = self._ax_pf
        ax_S = self._ax_S
        for ax in (ax_pf, ax_S):
            ax.clear()
            ax.set_facecolor(p.surface)
            for spine in ax.spines.values():
                spine.set_visible(True)
                spine.set_color(p.border)

        ax_pf.plot(L_plot, PF_arr, color=p.accent, linewidth=1.8, label=f"PF ({spec.topology})")
        ax_pf.set_xlabel(f"Inductance L [{L_unit}]", color=p.text)
        ax_pf.set_ylabel("Power factor [—]", color=p.accent)
        ax_pf.set_ylim(0.5, 1.02)
        ax_pf.tick_params(axis="x", colors=p.text)
        ax_pf.tick_params(axis="y", colors=p.accent)
        ax_pf.grid(True, alpha=0.25, color=p.border)

        ax_S.plot(
            L_plot,
            S_arr / 1000.0,
            color=p.danger,
            linewidth=1.4,
            linestyle="--",
            label="Apparent power S",
        )
        ax_S.set_ylabel("Apparent power S [kVA]", color=p.danger)
        ax_S.tick_params(axis="y", colors=p.danger)
        if S_arr.size:
            ax_S.set_ylim(bottom=0, top=float(S_arr.max() / 1000.0) * 1.15)

        # Mark the design point.
        ax_pf.axvline(
            L_design_plot,
            color=p.success,
            linestyle=":",
            linewidth=1.4,
            alpha=0.85,
            label=f"Design L = {L_design_plot:.2f} {L_unit}",
        )
        ax_pf.plot([L_design_plot], [PF_design], "o", color=p.success, markersize=7, zorder=6)

        # Combined legend so the PF and S traces share one box —
        # placed in the upper-left so it sits opposite the design
        # point (which lives near the right edge of the rising PF
        # curve) for clean separation from the data.
        h_pf, l_pf = ax_pf.get_legend_handles_labels()
        h_S, l_S = ax_S.get_legend_handles_labels()
        leg = ax_pf.legend(
            h_pf + h_S,
            l_pf + l_S,
            loc="lower right",
            fontsize=8,
            framealpha=0.9,
        )
        leg.get_frame().set_facecolor(p.surface)
        leg.get_frame().set_edgecolor(p.border)
        for txt in leg.get_texts():
            txt.set_color(p.text)

        self._fig.suptitle(
            f"PF = {PF_design:.2f}  ·  S = {S_design / 1000.0:.1f} kVA",
            fontsize=10,
            color=p.text,
        )
        self._canvas.draw_idle()
