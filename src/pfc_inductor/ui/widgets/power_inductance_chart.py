"""``PowerInductanceChart`` — embeddable P vs L parametric saturation chart.

Live counterpart to the PDF datasheet's ``_fig_power_vs_inductance``
helper. As the bias current sweeps from zero past the design's
``I_pk`` into deep saturation, both the effective inductance L(I)
and the active power P(I) = V·(I/√2)·PF·n_phases evolve together.
The chart traces them parametrically — X = L (high on the left,
falling toward saturation on the right), Y = P (rising) — so the
engineer sees in one trace how saturation translates to throughput.

For boost-PFC topologies the curve degenerates (PF ≈ 1 by active
control, P scales linearly with I, no saturation tapering) so the
widget shows a friendly placeholder instead.

Theme-aware via ``on_theme_changed``.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.physics import power_factor as pfm
from pfc_inductor.physics import rolloff as rf
from pfc_inductor.ui.theme import get_theme, on_theme_changed


def _figure_imports():
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
    from matplotlib.figure import Figure
    return Canvas, Figure


class PowerInductanceChart(QWidget):
    """P(L) parametric trace driven by the L(I) saturation sweep."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        Canvas, Figure = _figure_imports()
        p = get_theme().palette
        self._fig = Figure(figsize=(5.4, 2.8), dpi=100,
                            facecolor=p.surface, tight_layout=True)
        self._ax = self._fig.add_subplot(1, 1, 1)
        self._canvas = Canvas(self._fig)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                            QSizePolicy.Policy.Expanding)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._canvas)

        self._last: Optional[
            tuple[Spec, Core, Material, DesignResult, float]
        ] = None
        self._render_empty("Waiting for calculation…")
        on_theme_changed(self._refresh_palette)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update_from_design(self, result: DesignResult, spec: Spec,
                            core: Core, wire: Wire,
                            material: Material) -> None:
        I_pk = float(result.I_pk_max_A) if result.I_pk_max_A else 0.0
        self._last = (spec, core, material, result, I_pk)
        self._render()

    def clear(self) -> None:
        self._last = None
        self._render_empty("Waiting for calculation…")

    # ------------------------------------------------------------------
    def _refresh_palette(self) -> None:
        p = get_theme().palette
        self._fig.set_facecolor(p.surface)
        if self._last is None:
            self._render_empty("Waiting for calculation…")
        else:
            self._render()

    def _render_empty(self, message: str) -> None:
        p = get_theme().palette
        self._ax.clear()
        self._ax.set_facecolor(p.surface)
        self._ax.text(
            0.5, 0.5, message,
            ha="center", va="center",
            color=p.text_muted, fontsize=10,
            transform=self._ax.transAxes,
        )
        for spine in self._ax.spines.values():
            spine.set_visible(False)
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        self._canvas.draw_idle()

    def _render(self) -> None:
        if self._last is None:
            self._render_empty("Waiting for calculation…")
            return
        spec, core, material, result, I_pk = self._last

        if spec.topology == "boost_ccm":
            self._render_empty(
                "Active boost-PFC sets PF ≈ 1 by design.\n"
                "P scales linearly with I — saturation tapering\n"
                "does not apply to this topology."
            )
            return
        if I_pk <= 0 or result.N_turns <= 0:
            self._render_empty("Insufficient data to plot P(L).")
            return

        p = get_theme().palette
        ax = self._ax
        ax.clear()
        ax.set_facecolor(p.surface)
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_color(p.border)

        N = int(result.N_turns)
        # Same sweep range as L(I) so the two charts read coherently.
        if material.rolloff is None:
            Ae_m2 = max(core.Ae_mm2 * 1e-6, 1e-12)
            L_lin_uH = rf.inductance_uH(N, core.AL_nH, 1.0)
            B_at_Ipk = (L_lin_uH * 1e-6) * I_pk / max(N * Ae_m2, 1e-12)
            I_max = (
                I_pk * min(
                    max(3.0 * material.Bsat_100C_T / max(B_at_Ipk, 1e-9),
                         2.0),
                    20.0,
                )
                if B_at_Ipk > 0 else I_pk * 5.0
            )
        else:
            I_max = I_pk * 2.0

        I = np.linspace(0.01, I_max, 250)
        L_uH = np.array([
            rf.L_at_current_uH(
                material, N=N, I_A=float(Ii),
                AL_nH=core.AL_nH, le_mm=core.le_mm,
                Ae_mm2=core.Ae_mm2,
            )
            for Ii in I
        ])
        P_W = np.array([
            pfm.active_power_at_inst_current_W(
                spec, float(L_uH[k]), float(I[k]),
            )
            for k in range(I.size)
        ])
        L_op = float(result.L_actual_uH)
        P_op = pfm.active_power_at_inst_current_W(spec, L_op, I_pk)

        ax.plot(L_uH, P_W / 1000.0, color=p.accent, linewidth=1.6,
                 label=f"P(L) parametrised by I (N = {N})")
        ax.axvline(L_op, color=p.text_muted, linestyle=":",
                    alpha=0.7, linewidth=1.0,
                    label=f"L_op = {L_op:.0f} µH")
        ax.axhline(P_op / 1000.0, color=p.warning, linestyle=":",
                    alpha=0.7, linewidth=1.0,
                    label=f"P_op = {P_op / 1000.0:.1f} kW")
        ax.plot([L_op], [P_op / 1000.0], "o", color=p.success,
                 markersize=7, zorder=5,
                 label="Operating point (I = I_pk)")
        ax.set_xlabel("Inductance L [µH]", color=p.text)
        ax.set_ylabel("Active power P [kW]", color=p.text)
        # Invert X — high L on the left, deep saturation on the right
        # (matches the L(I) curve's left-to-right "I rising" reading).
        ax.set_xlim(left=max(L_uH.max() * 1.05, L_op * 1.1), right=0)
        ax.set_ylim(bottom=0)
        ax.tick_params(colors=p.text)
        for spine in ax.spines.values():
            spine.set_color(p.border)
        ax.grid(True, alpha=0.25, color=p.border)
        leg = ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
        leg.get_frame().set_facecolor(p.surface)
        leg.get_frame().set_edgecolor(p.border)
        for txt in leg.get_texts():
            txt.set_color(p.text)
        self._canvas.draw_idle()
