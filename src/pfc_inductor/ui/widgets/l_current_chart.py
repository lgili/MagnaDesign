"""``LCurrentChart`` — embeddable inductance-vs-current saturation curve.

Same physics the ``_fig_inductance_vs_current`` helper renders into the
PDF datasheet / project report, this time as a live matplotlib canvas
embedded in the Analysis tab. The trace shows how L drops from L₀
(zero-bias) toward saturation as the DC bias current rises through and
past the design's I_pk; the operating point is marked with the
percentage rolloff from L₀ in the legend.

Returns a "no rolloff data" placeholder when the material doesn't
publish a μ%(H) curve (silicon-steel laminations) — for those the
trace would be flat-then-cliff and adds little.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.physics import rolloff as rf
from pfc_inductor.ui.theme import get_theme, on_theme_changed


def _figure_imports():
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
    from matplotlib.figure import Figure

    return Canvas, Figure


class LCurrentChart(QWidget):
    """Compact L(I) saturation rolloff chart.

    Caches the last (result, core, material) tuple so theme toggles
    can re-render with the new palette without the engine re-running.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        Canvas, Figure = _figure_imports()
        p = get_theme().palette
        self._fig = Figure(figsize=(5.4, 2.8), dpi=100, facecolor=p.surface, tight_layout=True)
        self._ax = self._fig.add_subplot(1, 1, 1)
        self._canvas = Canvas(self._fig)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._canvas)

        # Cache the last design so theme toggles re-render correctly.
        self._last: Optional[tuple[DesignResult, Core, Material, float]] = None
        self._render_empty("Waiting for calculation…")
        on_theme_changed(self._refresh_palette)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update_from_design(
        self, result: DesignResult, spec: Spec, core: Core, wire: Wire, material: Material
    ) -> None:
        # ``I_pk_max_A`` is on every topology's result and includes
        # ripple half for the boost case — the right "peak the
        # inductor actually sees" number for the saturation envelope.
        I_pk = float(result.I_pk_max_A) if result.I_pk_max_A else 0.0
        self._last = (result, core, material, I_pk)
        self._render()

    def clear(self) -> None:
        self._last = None
        self._render_empty("Waiting for calculation…")

    # ------------------------------------------------------------------
    # Render
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
            0.5,
            0.5,
            message,
            ha="center",
            va="center",
            color=p.text_muted,
            fontsize=10,
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
        result, core, material, I_pk = self._last

        # Materials without a published rolloff curve (silicon-steel
        # laminations) — the L(I) trace would be essentially flat
        # until the saturation cliff, which doesn't help an engineer
        # reading the design point. Show a friendly note instead.
        if material.rolloff is None:
            self._render_empty(
                f"Material {material.name} has no rolloff curve\n"
                "(silicon-steel laminations are essentially flat\n"
                "until B = Bsat)."
            )
            return
        if I_pk <= 0 or result.N_turns <= 0:
            self._render_empty("Insufficient data to plot L(I).")
            return

        p = get_theme().palette
        ax = self._ax
        ax.clear()
        ax.set_facecolor(p.surface)
        for spine in ax.spines.values():
            spine.set_visible(True)

        # Sweep current from ε to ~2 × I_pk so the saturation knee
        # past the design point is visible.
        N = int(result.N_turns)
        I = np.linspace(0.01, I_pk * 2.0, 250)
        L_uH = np.zeros_like(I)
        for i, Ii in enumerate(I):
            H_Oe = rf.H_from_NI(N, float(Ii), core.le_mm, units="Oe")
            mu = rf.mu_pct(material, H_Oe)
            L_uH[i] = rf.inductance_uH(N, core.AL_nH, mu)

        L0 = float(L_uH[0])
        L_op = float(result.L_actual_uH)
        rolloff_pct = (1.0 - L_op / L0) * 100.0 if L0 > 0 else 0.0

        ax.plot(I, L_uH, color=p.accent, linewidth=1.6, label=f"L(I) at N = {N}")
        ax.axhline(
            L0,
            color=p.text_muted,
            linestyle=":",
            alpha=0.7,
            linewidth=1.0,
            label=f"L₀ = {L0:.0f} µH (zero bias)",
        )
        ax.axvline(
            I_pk,
            color=p.danger,
            linestyle="--",
            alpha=0.7,
            linewidth=1.0,
            label=f"I_pk = {I_pk:.2f} A",
        )
        ax.plot(
            [I_pk],
            [L_op],
            "o",
            color=p.danger,
            markersize=6,
            zorder=5,
            label=f"Operating: L = {L_op:.0f} µH (−{rolloff_pct:.0f}% from L₀)",
        )
        ax.set_xlabel("DC bias current I [A]", color=p.text)
        ax.set_ylabel("Inductance L [µH]", color=p.text)
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)
        ax.tick_params(colors=p.text)
        for spine in ax.spines.values():
            spine.set_color(p.border)
        ax.grid(True, alpha=0.25, color=p.border)
        leg = ax.legend(loc="upper right", fontsize=8, framealpha=0.85)
        leg.get_frame().set_facecolor(p.surface)
        leg.get_frame().set_edgecolor(p.border)
        for txt in leg.get_texts():
            txt.set_color(p.text)
        self._canvas.draw_idle()
