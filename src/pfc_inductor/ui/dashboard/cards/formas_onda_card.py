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

================  =====================================================
Topology          Traces (top → bottom)
================  =====================================================
boost_ccm         iL(t) — v_in(t) rect — FFT spectrum (h = 1..20)
passive_choke     iL(t) — v_in(t) rect — FFT spectrum (h = 1..20)
line_reactor_1ph  iL(t) — v_phase(t) — FFT spectrum (h = 1..20)
line_reactor_3ph  iL_a/b/c overlay — v_a/b/c overlay — FFT spectrum
================  =====================================================

The bottom subplot was originally a B(t) trace, but the engine never
sampled ``waveform_B_T`` for any topology — the axis sat empty.
v3 repurposes it as the harmonic-spectrum bar chart, fed by the
same FFT that drives the THD metric tile, so the user sees both the
shape *and* its frequency content.

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
        self._fig = Figure(dpi=100, facecolor=p.surface, constrained_layout=True)
        self._canvas = Canvas(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
        self._last: Optional[
            tuple[
                DesignResult,
                Spec,
                Core,
                Wire,
                Material,
            ]
        ] = None

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
    def update_from_design(
        self, result: DesignResult, spec: Spec, core: Core, wire: Wire, material: Material
    ) -> None:
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
        # THD priority: engine's calibrated value first (line_reactor
        # only — the engine fits IEEE-519's 75/√%Z curve there), then
        # the FFT-derived value from the synthesised waveform (the
        # only source for boost / passive, where the engine doesn't
        # produce a THD). The previous ordering preferred the FFT
        # everywhere, which made line_reactor cards report ~196 %
        # while the engine path said ~130 % — confusing engineers
        # who saw two different "official" THD numbers per design.
        if result.thd_estimate_pct is not None and result.thd_estimate_pct > 0:
            self.m_THD.set_value(f"{result.thd_estimate_pct:.0f}")
        elif synth is not None and synth.thd_pct > 0:
            self.m_THD.set_value(f"{synth.thd_pct:.0f}")
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
    def _badge_text(topology: str, n_phases: int, synth: Optional[RealisticWaveform] = None) -> str:
        prefix = ""
        if topology == "boost_ccm":
            prefix = "Topologia: PFC ativo (boost CCM) — iL · v_in · FFT"
        elif topology == "passive_choke":
            prefix = "Topologia: choke passivo — iL · v_in · FFT"
        elif topology == "line_reactor":
            phase = "3φ" if n_phases == 3 else "1φ"
            prefix = f"Topologia: reator de linha {phase} — iL · v_phase · FFT"
        elif topology == "buck_ccm":
            prefix = "Topologia: buck CCM (sync DC-DC) — iL · v_sw · FFT @ f_sw"
        elif topology == "flyback":
            prefix = "Topologia: flyback (coupled inductor) — iL_p + iL_s · v_drain · FFT @ f_sw"
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
    def _render(
        self,
        result: DesignResult,
        spec: Spec,
        topology: str,
        n_phases: int,
        synth: Optional[RealisticWaveform],
    ) -> None:
        p = get_theme().palette
        self._fig.clear()
        self._fig.set_facecolor(p.surface)

        # Time axis — shared across all subplots. When the
        # synthesiser succeeded we use its time axis (one full line
        # cycle for boost / two for AC reactors / a few f_sw periods
        # for buck); otherwise we fall back to the engine's sampled
        # t array.
        if synth is not None:
            t_s = synth.t_s
        elif result.waveform_t_s:
            t_s = np.array(result.waveform_t_s, dtype=float)
        else:
            t_s = _FALLBACK_T_MS / 1000.0
        # Auto-scale the time-axis unit: if the entire window is
        # under 1 ms (buck @ 500 kHz × 6 periods = 12 µs), use
        # microseconds — otherwise milliseconds reads cleaner.
        span_s = float(t_s.max() - t_s.min()) if t_s.size else 0.0
        if 0 < span_s < 1e-3:
            t_disp = t_s * 1e6
            time_unit_label = "µs"
        else:
            t_disp = t_s * 1e3
            time_unit_label = "ms"
        if t_disp.size == 0:
            t_disp = _FALLBACK_T_MS
            time_unit_label = "ms"
        # Keep ``t_ms`` as the legacy local name so downstream
        # plotters don't need to rename. (It holds whatever display
        # unit ``t_disp`` is in — the helpers don't read it as
        # absolute milliseconds; they just plot against it.)
        t_ms = t_disp

        # 3 stacked axes. The top two (iL + source-voltage) share a
        # time x-axis so they read as a multi-trace scope. The bottom
        # axis is independent — it shows the **harmonic spectrum**
        # of the iL waveform (frequency / harmonic-number x-axis,
        # not time). Replaces the v1 B(t) plot, which the engine
        # never populated for any topology.
        gs = self._fig.add_gridspec(3, 1, height_ratios=[1.2, 0.9, 0.9])
        ax_i = self._fig.add_subplot(gs[0])
        ax_v = self._fig.add_subplot(gs[1], sharex=ax_i)
        # Hide the iL axis's x-tick labels — only ax_v carries the
        # time-axis label so the top two stack reads as a single
        # multi-trace scope. ``sharex`` synchronises limits but not
        # tick visibility, hence the explicit ``labelbottom=False``.
        ax_i.tick_params(axis="x", labelbottom=False)
        ax_s = self._fig.add_subplot(gs[2])

        for ax in (ax_i, ax_v, ax_s):
            ax.set_facecolor(p.surface)
            ax.tick_params(colors=p.text_muted, labelsize=8)
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
            for spine in ("left", "bottom"):
                ax.spines[spine].set_color(p.border)
            ax.grid(True, color=p.border, linewidth=0.4, alpha=0.6)

        # Time-domain axes get a zero baseline; spectrum bars sit on
        # the x-axis so a separate horizontal rule would look noisy.
        for ax in (ax_i, ax_v):
            ax.axhline(0, color=p.border, linewidth=0.6, linestyle="--", alpha=0.7)

        # ---- Top axis: inductor current (or 3-phase overlay) -----------
        if topology == "line_reactor" and n_phases == 3:
            self._plot_three_phase_currents(
                ax_i,
                t_ms,
                result,
                spec,
                p,
                synth,
            )
        elif topology == "flyback":
            self._plot_flyback_currents(ax_i, t_ms, p, synth)
        else:
            self._plot_inductor_current(ax_i, t_ms, result, p, synth)

        # ---- Middle axis: source/voltage waveform ----------------------
        self._plot_source_voltage(ax_v, t_ms, spec, topology, n_phases, p)
        ax_v.set_xlabel(
            f"t ({time_unit_label})",
            fontsize=10,
            color=p.text_secondary,
        )

        # ---- Bottom axis: harmonic spectrum (FFT) ----------------------
        self._plot_harmonic_spectrum(ax_s, synth, p, result)

        self._canvas.draw_idle()

    def _plot_inductor_current(
        self, ax, t_ms: np.ndarray, result: DesignResult, p, synth: Optional[RealisticWaveform]
    ) -> None:
        # Prefer the synthesised waveform — it carries the proper
        # state-space-derived shape per topology (PFC sinusoid +
        # PWM ripple for boost, slow triangle for passive choke,
        # rectifier pulses for the line reactor).
        if synth is not None:
            ax.plot(t_ms, synth.iL_A, color=p.accent, linewidth=1.4, label="iL(t) sintetizado")
        elif result.waveform_iL_A and result.waveform_t_s:
            y = np.array(result.waveform_iL_A, dtype=float)
            ax.plot(t_ms, y, color=p.accent, linewidth=1.6, label="iL(t)")
        else:
            ax.text(
                0.5,
                0.5,
                "iL(t) — sem dados",
                ha="center",
                va="center",
                color=p.text_muted,
                fontsize=10,
                transform=ax.transAxes,
            )
        ax.set_ylabel("iL (A)", fontsize=10, color=p.text_secondary)

    def _plot_three_phase_currents(
        self,
        ax,
        t_ms: np.ndarray,
        result: DesignResult,
        spec: Spec,
        p,
        synth: Optional[RealisticWaveform],
    ) -> None:
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
            ax.text(
                0.5,
                0.5,
                "iL(t) — sem dados",
                ha="center",
                va="center",
                color=p.text_muted,
                fontsize=10,
                transform=ax.transAxes,
            )
            return

        ax.plot(t_ms, i_a, color=p.accent, linewidth=1.4, label="A")
        ax.plot(t_ms, i_b, color=p.accent_violet, linewidth=1.3, alpha=0.85, label="B")
        ax.plot(t_ms, i_c, color=p.warning, linewidth=1.3, alpha=0.85, label="C")
        ax.set_ylabel("iL (A)", fontsize=10, color=p.text_secondary)
        ax.legend(loc="upper right", fontsize=7, frameon=False, labelcolor=p.text_secondary, ncol=3)

    def _plot_flyback_currents(
        self,
        ax,
        t_ms: np.ndarray,
        p,
        synth: Optional[RealisticWaveform],
    ) -> None:
        """Stack ``Ip(t)`` (primary) and ``Is(t)`` (secondary) on the
        top axis with the dot-convention colours: primary in the
        brand accent, secondary in violet. The two pulses are
        non-overlapping in DCM (primary during ``D · Tsw``,
        secondary during ``D₂ · Tsw``); CCM has both currents
        non-zero through the entire cycle. The axis label switches
        from "iL (A)" (single-winding topologies) to "i_p / i_s
        (A)" so the engineer can tell at a glance that two traces
        share the axis.
        """
        if synth is None or not synth.iL_extra:
            ax.text(
                0.5,
                0.5,
                "Flyback waveform — recompute to populate",
                ha="center",
                va="center",
                color=p.text_muted,
                fontsize=10,
                transform=ax.transAxes,
            )
            return
        i_p = synth.iL_A
        i_s = synth.iL_extra[0]
        ax.plot(t_ms, i_p, color=p.accent, linewidth=1.5, label="i_p (primary)")
        ax.plot(
            t_ms,
            i_s,
            color=p.accent_violet,
            linewidth=1.4,
            alpha=0.85,
            label="i_s (secondary)",
        )
        ax.set_ylabel("i_p / i_s (A)", fontsize=10, color=p.text_secondary)
        ax.legend(
            loc="upper right",
            fontsize=7,
            frameon=False,
            labelcolor=p.text_secondary,
            ncol=2,
        )

    def _plot_source_voltage(
        self, ax, t_ms: np.ndarray, spec: Spec, topology: str, n_phases: int, p
    ) -> None:
        """Synthesised source-side voltage trace.

        - ``boost_ccm`` / ``passive_choke``: full-wave rectified
          ``|sin|`` envelope @ f_line. The same v_in(t) the bridge
          presents to the inductor.
        - ``line_reactor_1ph``: line-to-neutral sinusoid, no
          rectification.
        - ``line_reactor_3ph``: three sinusoids 120° apart (we draw
          all three so the user sees the balanced source).
        - ``buck_ccm``: switching-node voltage ``v_sw(t)`` — square
          pulses between 0 V and Vin_dc with duty ``D = Vout/Vin``.
          The inductor sees ``v_L = v_sw − Vout``, but plotting
          v_sw directly is more familiar to a power-stage engineer
          (they read it on a probe at the SW node).
        """
        # Buck-CCM gets its own branch — the AC sanity guards
        # below would reject it (no f_line, no Vin_Vrms).
        if topology == "buck_ccm":
            self._plot_buck_switching_node(ax, t_ms, spec, p)
            return

        v_min = float(spec.Vin_min_Vrms or 0.0)
        f_line = float(spec.f_line_Hz or 50.0)
        if v_min <= 0 or f_line <= 0 or t_ms.size == 0:
            ax.text(
                0.5,
                0.5,
                "v_source — sem dados",
                ha="center",
                va="center",
                color=p.text_muted,
                fontsize=10,
                transform=ax.transAxes,
            )
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
            ax.plot(t_ms, v_a, color=p.accent, linewidth=1.4, label="vA")
            ax.plot(t_ms, v_b, color=p.accent_violet, linewidth=1.2, alpha=0.85, label="vB")
            ax.plot(t_ms, v_c, color=p.warning, linewidth=1.2, alpha=0.85, label="vC")
            ax.set_ylabel("v_phase (V)", fontsize=10, color=p.text_secondary)
        elif topology == "line_reactor":
            v_t = v_pk * np.sin(omega * t_s)
            ax.plot(t_ms, v_t, color=p.accent, linewidth=1.4)
            ax.set_ylabel("v_phase (V)", fontsize=10, color=p.text_secondary)
        else:
            # Boost / passive choke: rectified sinusoid.
            v_t = v_pk * np.abs(np.sin(omega * t_s))
            ax.plot(t_ms, v_t, color=p.accent_violet, linewidth=1.4)
            ax.set_ylabel("v_in rect (V)", fontsize=10, color=p.text_secondary)

    def _plot_buck_switching_node(self, ax, t_disp: np.ndarray, spec: Spec, p) -> None:
        """Switching-node voltage v_sw(t) for buck-CCM.

        Pulses between 0 V and Vin_dc with duty ``D = Vout / (Vin·η)``
        at f_sw — the same square wave a scope probe at the SW node
        would show. The inductor sees ``v_L = v_sw − Vout``, which we
        annotate as a faint dashed line so the engineer can visually
        confirm the volt-second balance (positive area during
        D·T_sw equals negative area during (1 − D)·T_sw).
        """
        from pfc_inductor.topology import buck_ccm

        f_sw_kHz = float(spec.f_sw_kHz or 0.0)
        Vin = buck_ccm._vin_nom(spec)
        Vout = float(spec.Vout_V or 0.0)
        if f_sw_kHz <= 0 or Vin <= 0 or Vout <= 0 or t_disp.size == 0:
            ax.text(
                0.5,
                0.5,
                "v_sw — sem dados",
                ha="center",
                va="center",
                color=p.text_muted,
                fontsize=10,
                transform=ax.transAxes,
            )
            ax.set_ylabel("V", fontsize=10, color=p.text_secondary)
            return

        # Derive duty + the displayed period directly from ``t_disp``:
        # since the synthesised iL covers exactly the same time window
        # as v_sw should, we just need ``t_disp`` to give us the same
        # phase modulo. The total displayed span equals ``n_periods``
        # of T_sw — we read it back as ``span / n_periods`` without
        # caring whether the unit is µs or ms.
        D = buck_ccm.duty_cycle(spec, Vin)
        span_disp = float(t_disp.max() - t_disp.min())
        # The synth uses 6 periods (see _buck_ccm in realistic_waveforms).
        # Pulling that constant in directly is brittle but the
        # alternative (re-deriving via the µs/ms unit) is more so.
        n_periods = 6
        T_sw_disp = span_disp / max(n_periods, 1)
        if T_sw_disp <= 0:
            return
        phase = (t_disp / T_sw_disp) % 1.0
        v_sw = np.where(phase < D, Vin, 0.0)
        v_L = v_sw - Vout

        ax.plot(t_disp, v_sw, color=p.accent_violet, linewidth=1.4, label="v_sw (SW node)")
        ax.plot(
            t_disp,
            v_L,
            color=p.accent,
            linewidth=1.0,
            linestyle="--",
            alpha=0.75,
            label="v_L = v_sw − Vout",
        )
        ax.set_ylabel("v (V)", fontsize=10, color=p.text_secondary)
        ax.legend(loc="upper right", fontsize=7, frameon=False, labelcolor=p.text_secondary, ncol=2)
        # Headroom so the square pulses don't kiss the axis edge.
        margin = 0.10 * max(Vin, 1.0)
        ax.set_ylim(min(-Vout, 0.0) - margin, Vin + margin)

    def _plot_harmonic_spectrum(
        self, ax, synth: Optional[RealisticWaveform], p, result: Optional[DesignResult] = None
    ) -> None:
        """Bar chart of the iL harmonic spectrum.

        X-axis: harmonic number (h = 1, 2, …, 20).
        Y-axis: amplitude as a percentage of the fundamental.
        Annotation: the same THD number the metric tile shows —
        ``result.thd_estimate_pct`` (engine-calibrated, line-reactor
        path) when available, otherwise the synthesis FFT's
        ``synth.thd_pct``. Reading the same number twice (chart +
        tile) lets the engineer cross-check that the visualisation is
        coherent with the engine.

        Empty-state when ``synth`` is unavailable: a friendly hint
        instead of an axis full of zero bars.
        """
        if synth is None or synth.harmonic_pct is None:
            ax.text(
                0.5,
                0.5,
                "Spectrum unavailable — recompute to generate the FFT",
                ha="center",
                va="center",
                color=p.text_muted,
                fontsize=10,
                transform=ax.transAxes,
            )
            ax.set_xticks([])
            ax.set_yticks([])
            return

        h = synth.harmonic_h
        pct = synth.harmonic_pct
        # Colour the fundamental in accent + harmonics in violet so
        # the eye separates "the signal" from "the distortion" at a
        # glance.
        colors = [p.accent if int(hi) == 1 else p.accent_violet for hi in h]
        ax.bar(h, pct, width=0.7, color=colors, edgecolor=p.surface, linewidth=0.4)

        ax.set_xlabel(
            f"Harmonic · fundamental = {synth.fundamental_Hz:.0f} Hz",
            fontsize=10,
            color=p.text_secondary,
        )
        ax.set_ylabel("% of fundamental", fontsize=10, color=p.text_secondary)
        ax.set_xticks(list(h))
        ax.set_xticklabels(
            [str(int(hi)) for hi in h],
            fontsize=8,
            color=p.text_muted,
        )
        # Cap the visible range a hair above 100 % so the fundamental
        # bar isn't pinned to the top edge. Tall harmonics (e.g.
        # 1φ reactor with h3 ≈ 97 %) still fit.
        ax.set_ylim(0, max(105.0, float(pct.max()) * 1.05))

        # Pick the canonical THD: engine value (line_reactor) when
        # populated, otherwise the synthesis FFT's. Same priority the
        # metric tile uses, so the bar-chart annotation and the tile
        # always agree.
        thd_pct = synth.thd_pct
        thd_source = "FFT"
        if (
            result is not None
            and result.thd_estimate_pct is not None
            and result.thd_estimate_pct > 0
        ):
            thd_pct = float(result.thd_estimate_pct)
            thd_source = "engine"
        # THD annotation in the upper-right.
        ax.text(
            0.98,
            0.92,
            f"THD = {thd_pct:.0f} %  ({thd_source})",
            ha="right",
            va="top",
            transform=ax.transAxes,
            color=p.text,
            fontsize=10,
            fontweight="bold",
            bbox=dict(
                facecolor=p.surface, edgecolor=p.border, boxstyle="round,pad=0.3", alpha=0.85
            ),
        )


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
