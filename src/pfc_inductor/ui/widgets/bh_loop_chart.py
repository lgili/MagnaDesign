"""``BHLoopChart`` — embeddable B-H trajectory plot.

Wraps a small matplotlib canvas (no toolbar) that draws the same B-H
trajectory the legacy ``PlotPanel.tab_bh`` produced: static
anhysteretic curve, slow line envelope, HF ripple overlay (when the
ripple is non-trivial), Bsat dashed reference, and the peak operating
marker. Theme-aware via :func:`on_theme_changed`.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material
from pfc_inductor.ui.theme import get_theme, on_theme_changed
from pfc_inductor.visual import compute_bh_trajectory


def _figure_imports():
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
    from matplotlib.figure import Figure
    return Canvas, Figure


class BHLoopChart(QWidget):
    """Compact B-H operating-point chart."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        Canvas, Figure = _figure_imports()
        p = get_theme().palette
        self._fig = Figure(figsize=(5.4, 3.2), dpi=100,
                           facecolor=p.surface, tight_layout=True)
        self._ax = self._fig.add_subplot(1, 1, 1)
        self._canvas = Canvas(self._fig)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._canvas)

        self._last: Optional[tuple[DesignResult, Core, Material]] = None
        self._render_empty()
        on_theme_changed(self._refresh_palette)

    # ------------------------------------------------------------------
    def update_from_design(self, result: DesignResult, core: Core,
                           material: Material) -> None:
        self._last = (result, core, material)
        self._render()

    def clear(self) -> None:
        self._last = None
        self._render_empty()

    # ------------------------------------------------------------------
    def _refresh_palette(self) -> None:
        p = get_theme().palette
        self._fig.set_facecolor(p.surface)
        if self._last is None:
            self._render_empty()
        else:
            self._render()

    def _render_empty(self) -> None:
        p = get_theme().palette
        self._ax.clear()
        self._ax.set_facecolor(p.surface)
        self._ax.text(
            0.5, 0.5,
            "Aguardando cálculo…",
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
            self._render_empty()
            return
        result, core, material = self._last
        p = get_theme().palette
        ax = self._ax
        ax.clear()
        ax.set_facecolor(p.surface)
        try:
            tr = compute_bh_trajectory(result, core, material)
        except (ValueError, TypeError, AttributeError) as e:
            ax.text(
                0.5, 0.5, f"Não foi possível computar B–H:\n{e}",
                ha="center", va="center",
                color=p.danger, fontsize=10,
                transform=ax.transAxes,
            )
            self._canvas.draw_idle()
            return

        # Static reference curve
        ax.plot(tr["H_static_Oe"], tr["B_static_T"] * 1000.0,
                color=p.text_muted, linewidth=1.2, alpha=0.8,
                label="Curva estática")
        # Bsat dashed line
        ax.axhline(tr["Bsat_T"] * 1000.0, color=p.danger,
                   linestyle="--", alpha=0.6, linewidth=1.0,
                   label=f"Bsat (100 °C) = {tr['Bsat_T'] * 1000:.0f} mT")
        # Slow envelope (line cycle)
        ax.plot(tr["H_envelope_Oe"], tr["B_envelope_T"] * 1000.0,
                color=p.accent, linewidth=1.8, alpha=0.9,
                label="Envelope de rede")
        # Optional HF ripple overlay (only when ripple_pp > 1 % I_pk)
        if tr["H_ripple_Oe"] is not None:
            ax.plot(tr["H_ripple_Oe"], tr["B_ripple_T"] * 1000.0,
                    color=p.warning, linewidth=2.4, alpha=0.85,
                    label="Ripple fsw (no pico)")
        # Operating-point marker
        ax.scatter(
            [tr["H_pk_Oe"]], [tr["B_pk_T"] * 1000.0],
            color=p.danger, s=60, zorder=5,
            edgecolor=p.surface, linewidth=1.4,
            label=(f"Pico ({tr['H_pk_Oe']:.0f} Oe, "
                   f"{tr['B_pk_T'] * 1000:.0f} mT)"),
        )

        ax.set_xlabel("H [Oe]", fontsize=9, color=p.text_secondary)
        ax.set_ylabel("B [mT]", fontsize=9, color=p.text_secondary)
        ax.tick_params(colors=p.text_muted, labelsize=8)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_color(p.border)
        ax.grid(True, color=p.border, linewidth=0.4, alpha=0.6)
        ax.legend(loc="lower right", fontsize=7,
                  frameon=False, labelcolor=p.text_secondary)
        # Cap y a hair above Bsat for visual headroom
        ymax = max(tr["Bsat_T"] * 1100.0, tr["B_pk_T"] * 1100.0)
        ax.set_ylim(0, ymax)

        self._canvas.draw_idle()
