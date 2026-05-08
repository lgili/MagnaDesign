"""Formas de Onda card — multi-trace, topology-aware waveform plots.

The v1 card showed *one* waveform at a time (iL or B, via toggle). For
a serious analysis surface that's not enough — the engineer needs to
read the inductor current, the source the converter sees, AND the
flux density side-by-side to diagnose:

- *Is the ripple where I expect it to be?* (PWM ripple in boost CCM
  vs. line ripple in passive choke vs. commutation notch in a line
  reactor.)
- *Is the flux waveform centred or offset?* (DC bias flag.)
- *Where in the line cycle does the peak land?* (anchors the loss
  estimate to a physical event.)

v2 stacks 2-3 traces on a shared x-axis (matplotlib ``subplots(N, 1,
sharex=True)``) and adapts the trace set per topology:

================  ===========================================
Topology          Traces (top → bottom)
================  ===========================================
boost_ccm         iL(t) — v_in(t) rect — B(t)
passive_choke     iL(t) — v_in(t) rect — B(t)
line_reactor_1ph  iL(t) — v_phase(t) — B(t)
line_reactor_3ph  iL(t)  + i_b(t) + i_c(t) overlay — v_a/b/c — B(t)
================  ===========================================

For the source/flux/duty traces that the engine doesn't sample (yet),
we *synthesise them analytically* from the spec — boost / passive
chokes see ``v_in(t) = √2·V_rms·|sin(2πf·t)|`` and 3-phase reactors
see three sine waves 120° apart. This is faithful to the converter's
mathematical model and fast (no extra solver work). Once the Tier-2
transient simulator extends to populate higher-resolution waveforms,
the synthesised arrays slot in directly without touching the UI.

The 4 metric tiles below the plot (Irms, Ipk, THD, Crest factor) are
unchanged — they were the most-cited bit of the v1 card.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.simulate.realistic_waveforms import (
    RealisticWaveform,
    synthesize_il_waveform,
)
from pfc_inductor.ui.theme import get_theme
from pfc_inductor.ui.widgets import Card, MetricCard


def _figure_imports():
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
    from matplotlib.figure import Figure
    return Canvas, Figure


# Canonical default — used when the engine hasn't populated waveforms
# AND the spec is half-configured (Pout=0 etc.). Lets the card still
# paint something on first launch instead of showing an empty axis.
_FALLBACK_T_MS = np.linspace(0.0, 20.0, 400)


class _FormasOndaBody(QWidget):
    """Multi-axis waveform body. Layout adapts per topology at every
    ``update_from_design`` call."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        Canvas, Figure = _figure_imports()
        p = get_theme().palette
        # ``constrained_layout=True`` packs the stacked subplots more
        # tightly than the legacy ``tight_layout``; 3 stacked axes with
        # ``hspace=0.0`` look like a single multi-trace scope.
        self._fig = Figure(dpi=100, facecolor=p.surface,
                           constrained_layout=True)
        self._canvas = Canvas(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding,
                                   QSizePolicy.Policy.Expanding)
        self._canvas.setMinimumHeight(280)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # Topology badge — small label so the user knows the trace
        # set is matched to the active spec.topology. Gets rewritten
        # on every update_from_design.
        self._badge = QLabel("Topologia: —")
        self._badge.setProperty("role", "muted")
        outer.addWidget(self._badge)

        outer.addWidget(self._canvas, 1)

        # Cached last result for theme-toggle re-renders.
        self._last: Optional[tuple[
            DesignResult, Spec, Core, Wire, Material,
        ]] = None

        # ---- 4 small metric tiles (unchanged from v1) -----------------
        row = QHBoxLayout()
        row.setSpacing(8)
        self.m_Irms = MetricCard("Irms", "—", "A", compact=True)
        self.m_Ipk = MetricCard("Ipk", "—", "A", compact=True)
        self.m_THD = MetricCard("THD", "—", "%", compact=True)
        self.m_CF = MetricCard("Crest", "—", "", compact=True)
        for mc in (self.m_Irms, self.m_Ipk, self.m_THD, self.m_CF):
            row.addWidget(mc)
        outer.addLayout(row)

    # ------------------------------------------------------------------
    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        self._last = (result, spec, core, wire, material)

        topology = getattr(spec, "topology", "boost_ccm")
        n_phases = int(getattr(spec, "n_phases", 1) or 1)

        # Synthesised iL waveform from the converter's textbook
        # state-space / small-signal model. Preferred over the
        # engine's sampled arrays because it carries the right
        # high-frequency signature for each topology — PWM ripple
        # for boost CCM, rectifier pulses for the line reactor,
        # 2·f_line ripple for the passive choke. Falls through to
        # ``None`` if the spec is half-baked, in which case the
        # plotter uses the engine's ``waveform_iL_A`` as a backstop.
        synth = synthesize_il_waveform(spec, result)
        self._badge.setText(self._badge_text(topology, n_phases, synth))

        self._render(result, spec, topology, n_phases, synth)

        # Metric tiles — same source as v1 so the numbers match the
        # plotted waveforms.
        self.m_Irms.set_value(f"{result.I_rms_total_A:.2f}")
        self.m_Ipk.set_value(f"{result.I_pk_max_A:.2f}")
        if result.thd_estimate_pct is not None:
            self.m_THD.set_value(f"{result.thd_estimate_pct:.0f}")
        else:
            self.m_THD.set_value("—")
        if result.I_rms_total_A > 1e-9:
            cf = result.I_pk_max_A / result.I_rms_total_A
            self.m_CF.set_value(f"{cf:.2f}")
        else:
            self.m_CF.set_value("—")

    def clear(self) -> None:
        self._fig.clear()
        self._canvas.draw_idle()
        self._last = None
        self._badge.setText("Topologia: —")
        for mc in (self.m_Irms, self.m_Ipk, self.m_THD, self.m_CF):
            mc.set_value("—")

    # ------------------------------------------------------------------
    @staticmethod
    def _badge_text(topology: str, n_phases: int,
                    synth: Optional[RealisticWaveform] = None) -> str:
        prefix = ""
        if topology == "boost_ccm":
            prefix = "Topologia: PFC ativo (boost CCM) — iL · v_in · B"
        elif topology == "passive_choke":
            prefix = "Topologia: choke passivo — iL · v_in · B"
        elif topology == "line_reactor":
            phase = "3φ" if n_phases == 3 else "1φ"
            prefix = (
                f"Topologia: reator de linha {phase} — "
                f"iL · v_phase · B"
            )
        else:
            prefix = f"Topologia: {topology}"
        if synth is not None and synth.label:
            # The synthesised waveform's label documents the
            # mathematical model in plain text — surfacing it makes
            # the plot self-explanatory without tooltips.
            return f"{prefix}    ·    {synth.label}"
        return prefix

    # ------------------------------------------------------------------
    # Plotting
    # ------------------------------------------------------------------
    def _render(self, result: DesignResult, spec: Spec,
                topology: str, n_phases: int,
                synth: Optional[RealisticWaveform]) -> None:
        p = get_theme().palette
        self._fig.clear()
        self._fig.set_facecolor(p.surface)

        # Time axis (in ms) — shared across all subplots. When the
        # synthesiser succeeded we use its time axis (one full line
        # cycle for boost / two for AC reactors); otherwise we fall
        # back to the engine's sampled t array.
        if synth is not None:
            t_s = synth.t_s
        elif result.waveform_t_s:
            t_s = np.array(result.waveform_t_s, dtype=float)
        else:
            t_s = _FALLBACK_T_MS / 1000.0
        t_ms = t_s * 1e3
        if t_ms.size == 0:
            t_ms = _FALLBACK_T_MS

        # 3 stacked axes — same layout for every topology so the
        # eye learns where to look. ``height_ratios`` slightly
        # favours the current trace (the headline diagnostic).
        axes = self._fig.subplots(
            3, 1, sharex=True,
            gridspec_kw={"height_ratios": [1.2, 0.9, 0.9]},
        )
        ax_i, ax_v, ax_b = axes

        for ax in axes:
            ax.set_facecolor(p.surface)
            ax.tick_params(colors=p.text_muted, labelsize=8)
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
            for spine in ("left", "bottom"):
                ax.spines[spine].set_color(p.border)
            ax.grid(True, color=p.border, linewidth=0.4, alpha=0.6)
            ax.axhline(0, color=p.border, linewidth=0.6,
                       linestyle="--", alpha=0.7)

        # ---- Top axis: inductor current (or 3-phase overlay) -----------
        if topology == "line_reactor" and n_phases == 3:
            self._plot_three_phase_currents(
                ax_i, t_ms, result, spec, p, synth,
            )
        else:
            self._plot_inductor_current(ax_i, t_ms, result, p, synth)

        # ---- Middle axis: source/voltage waveform ----------------------
        self._plot_source_voltage(ax_v, t_ms, spec, topology, n_phases, p)

        # ---- Bottom axis: flux density ---------------------------------
        self._plot_flux_density(ax_b, t_ms, result, p)

        # Only the bottom axis carries the time label so the stack
        # reads as a single multi-trace scope.
        ax_b.set_xlabel("t (ms)", fontsize=10, color=p.text_secondary)

        self._canvas.draw_idle()

    def _plot_inductor_current(self, ax, t_ms: np.ndarray,
                               result: DesignResult, p,
                               synth: Optional[RealisticWaveform]) -> None:
        # Prefer the synthesised waveform — it carries the proper
        # state-space-derived shape per topology (PFC sinusoid +
        # PWM ripple for boost, slow triangle for passive choke,
        # rectifier pulses for the line reactor).
        if synth is not None:
            ax.plot(t_ms, synth.iL_A, color=p.accent, linewidth=1.4,
                    label="iL(t) sintetizado")
        elif result.waveform_iL_A and result.waveform_t_s:
            y = np.array(result.waveform_iL_A, dtype=float)
            ax.plot(t_ms, y, color=p.accent, linewidth=1.6,
                    label="iL(t)")
        else:
            ax.text(0.5, 0.5, "iL(t) — sem dados",
                    ha="center", va="center",
                    color=p.text_muted, fontsize=10,
                    transform=ax.transAxes)
        ax.set_ylabel("iL (A)", fontsize=10, color=p.text_secondary)

    def _plot_three_phase_currents(self, ax, t_ms: np.ndarray,
                                   result: DesignResult, spec: Spec,
                                   p,
                                   synth: Optional[RealisticWaveform]) -> None:
        """For 3-phase line reactors, overlay the three phase currents.

        Prefer the analytical 6-pulse synthesis (one shaped pulse per
        phase per half-cycle, properly time-aligned at ±120°).
        Falls back to phase-rotating the engine's worst-phase sample
        if synthesis is unavailable.
        """
        if synth is not None and len(synth.iL_extra) >= 2:
            i_a = synth.iL_A
            i_b = synth.iL_extra[0]
            i_c = synth.iL_extra[1]
        elif result.waveform_iL_A and result.waveform_t_s:
            i_a = np.array(result.waveform_iL_A, dtype=float)
            f_line = float(spec.f_line_Hz or 50.0)
            i_pk = float(np.max(np.abs(i_a)))
            omega = 2.0 * math.pi * f_line
            t_s = t_ms / 1e3
            i_b = i_pk * np.sin(omega * t_s - 2.0 * math.pi / 3.0)
            i_c = i_pk * np.sin(omega * t_s + 2.0 * math.pi / 3.0)
        else:
            ax.text(0.5, 0.5, "iL(t) — sem dados",
                    ha="center", va="center",
                    color=p.text_muted, fontsize=10,
                    transform=ax.transAxes)
            return

        ax.plot(t_ms, i_a, color=p.accent, linewidth=1.4, label="A")
        ax.plot(t_ms, i_b, color=p.accent_violet, linewidth=1.3,
                alpha=0.85, label="B")
        ax.plot(t_ms, i_c, color=p.warning, linewidth=1.3,
                alpha=0.85, label="C")
        ax.set_ylabel("iL (A)", fontsize=10, color=p.text_secondary)
        ax.legend(loc="upper right", fontsize=7, frameon=False,
                  labelcolor=p.text_secondary, ncol=3)

    def _plot_source_voltage(self, ax, t_ms: np.ndarray, spec: Spec,
                             topology: str, n_phases: int, p) -> None:
        """Synthesised source-side voltage trace.

        - ``boost_ccm`` / ``passive_choke``: full-wave rectified
          ``|sin|`` envelope @ f_line. The same v_in(t) the bridge
          presents to the inductor.
        - ``line_reactor_1ph``: line-to-neutral sinusoid, no
          rectification.
        - ``line_reactor_3ph``: three sinusoids 120° apart (we draw
          all three so the user sees the balanced source).
        """
        v_min = float(spec.Vin_min_Vrms or 0.0)
        f_line = float(spec.f_line_Hz or 50.0)
        if v_min <= 0 or f_line <= 0 or t_ms.size == 0:
            ax.text(0.5, 0.5, "v_source — sem dados",
                    ha="center", va="center",
                    color=p.text_muted, fontsize=10,
                    transform=ax.transAxes)
            ax.set_ylabel("V", fontsize=10, color=p.text_secondary)
            return

        # Worst-case low-line peak — matches what the engine sizes
        # against. Higher-line cases would be a pessimistic bound.
        v_pk = math.sqrt(2.0) * v_min
        t_s = t_ms / 1e3
        omega = 2.0 * math.pi * f_line

        if topology == "line_reactor" and n_phases == 3:
            v_a = v_pk * np.sin(omega * t_s)
            v_b = v_pk * np.sin(omega * t_s - 2.0 * math.pi / 3.0)
            v_c = v_pk * np.sin(omega * t_s + 2.0 * math.pi / 3.0)
            ax.plot(t_ms, v_a, color=p.accent, linewidth=1.4,
                    label="vA")
            ax.plot(t_ms, v_b, color=p.accent_violet, linewidth=1.2,
                    alpha=0.85, label="vB")
            ax.plot(t_ms, v_c, color=p.warning, linewidth=1.2,
                    alpha=0.85, label="vC")
            ax.set_ylabel("v_phase (V)", fontsize=10,
                          color=p.text_secondary)
        elif topology == "line_reactor":
            v_t = v_pk * np.sin(omega * t_s)
            ax.plot(t_ms, v_t, color=p.accent, linewidth=1.4)
            ax.set_ylabel("v_phase (V)", fontsize=10,
                          color=p.text_secondary)
        else:
            # Boost / passive choke: rectified sinusoid.
            v_t = v_pk * np.abs(np.sin(omega * t_s))
            ax.plot(t_ms, v_t, color=p.accent_violet, linewidth=1.4)
            ax.set_ylabel("v_in rect (V)", fontsize=10,
                          color=p.text_secondary)

    def _plot_flux_density(self, ax, t_ms: np.ndarray,
                           result: DesignResult, p) -> None:
        if result.waveform_B_T and result.waveform_t_s:
            y = np.array(result.waveform_B_T, dtype=float) * 1000.0  # mT
            ax.plot(t_ms, y, color=p.warning, linewidth=1.6,
                    label="B(t)")
            # Bsat reference — engineer's "how close are we?" check.
            if result.B_sat_limit_T > 0:
                ax.axhline(
                    result.B_sat_limit_T * 1000.0,
                    color=p.danger, linewidth=0.9, linestyle=":",
                    alpha=0.7, label="Bsat",
                )
        else:
            ax.text(0.5, 0.5, "B(t) — engine sem amostragem",
                    ha="center", va="center",
                    color=p.text_muted, fontsize=10,
                    transform=ax.transAxes)
        ax.set_ylabel("B (mT)", fontsize=10, color=p.text_secondary)


class FormasOndaCard(Card):
    """Dashboard card with topology-aware multi-trace waveforms."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _FormasOndaBody()
        super().__init__("Formas de Onda", body, parent=parent)
        self._wbody = body

    def update_from_design(self, *args, **kwargs) -> None:
        self._wbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._wbody.clear()
