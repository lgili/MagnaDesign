"""Phase-shifted current overlay for interleaved boost PFC.

Visualises the per-phase inductor currents and their sum (the
total input current the bus capacitor sees) over one switching
period. The dB cancellation between the per-phase ripple and
the total is the design's selling point: ~12 dB at 2 phases,
~14.5 dB at 3 phases, ~16 dB at 4 phases (Hwu-Yau analytical).

Plot anatomy:

- **Per-phase currents**  ─ N traces shifted by 360°/N within
  the switching period. Faint colours so they read as the
  background.
- **Total input current** ─ heavy line with markers at the
  ripple extrema. The ripple is N × the switching frequency
  (frequency multiplication), peak-to-peak much smaller than
  any single phase.
- **dB cancellation chip** ─ ratio of the total ripple to a
  single-phase ripple, in dB. Positive means cancellation;
  zero means in-phase (no benefit, design error).
- **Cap stress annotation** ─ "input cap sees N×fsw at ΔI_pp
  amps" — the take-away the EMI / cap-selection engineer wants.

Pure analytical — same triangular waveform per phase the
``interleaved_boost_pfc`` topology already builds. Used in the
Análise card for that topology and as the visual confirmation
of the analytical 12 / 14.5 / 16 dB calculations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from pfc_inductor.ui.theme import get_theme, on_theme_changed

# matplotlib costs ~150–300 ms on cold import (numpy + font cache).
# The phase-overlay card lives in the Compliance tab — most launches
# never need it. Deferred to ``_figure_imports`` so the cost lands
# only when the chart actually instantiates.
if TYPE_CHECKING:  # pragma: no cover — typing only
    from matplotlib.backends.backend_qtagg import (  # noqa: F401
        FigureCanvasQTAgg as FigureCanvas,
    )
    from matplotlib.figure import Figure  # noqa: F401


def _figure_imports():
    """Lazy matplotlib import; mirrors the pattern used in
    ``harmonic_spectrum_chart`` and ``bh_loop_chart``."""
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure

    return Figure, FigureCanvas


@dataclass(frozen=True)
class PhaseOverlayPayload:
    """Plain-data view of N-phase interleaved boost waveform.

    Two construction paths:

    1. **Synthesise** from analytical params — pass
       ``n_phases``, ``I_avg_per_phase_A``, ``delta_iL_pp_A``,
       ``fsw_Hz``, ``D`` (duty); the widget builds the N
       triangular waveforms internally.
    2. **Pass arrays** — supply ``time_s`` and a list of
       per-phase ``currents_A`` arrays; the widget plots them
       directly. Useful for SPICE-imported waveforms.

    Path 1 is the default for the Análise card; path 2 covers
    measurement / sim playback.
    """

    n_phases: int = 2
    I_avg_per_phase_A: float = 0.0
    """Per-phase average current. Total input avg = N × this."""
    delta_iL_pp_A: float = 0.0
    """Single-phase peak-to-peak ripple."""
    fsw_Hz: float = 100_000
    duty: float = 0.5
    """Boost duty cycle. For an ideal cancellation pattern,
    interleaved boost wants duty = 1/N (peaks of the per-phase
    ripples align with the troughs of the others). For a generic
    duty the cancellation is partial — the widget computes the
    actual dB."""

    # Override path: pass arrays directly.
    time_s: Optional[tuple[float, ...]] = None
    phase_currents_A: Optional[tuple[tuple[float, ...], ...]] = None
    """Per-phase i_L(t) arrays, length-matched to ``time_s``."""

    topology_name: str = "Interleaved boost PFC"


class PhaseOverlayChart(QWidget):
    """N-phase interleaved current overlay + total."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self._outer = v

        # Deferred Figure: see other chart widgets for rationale.
        self._placeholder = QWidget()
        self._placeholder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._placeholder.setMinimumHeight(380)
        v.addWidget(self._placeholder, 1)
        self._fig = None
        self._canvas = None
        self._canvas_built = False
        self._last: Optional[PhaseOverlayPayload] = None
        on_theme_changed(self.refresh_theme)

    def _ensure_canvas_built(self) -> None:
        if self._canvas_built:
            return
        Figure, FigureCanvas = _figure_imports()
        self._fig = Figure(figsize=(8.0, 4.6), dpi=100)
        self._fig.set_facecolor(get_theme().palette.surface)
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setMinimumHeight(380)
        idx = self._outer.indexOf(self._placeholder)
        self._outer.removeWidget(self._placeholder)
        self._placeholder.deleteLater()
        self._placeholder = None  # type: ignore[assignment]
        self._outer.insertWidget(idx, self._canvas, 1)
        self._canvas_built = True
        if self._last is not None:
            self._paint(self._last)
        else:
            self._paint_empty()

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        self._ensure_canvas_built()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def show_payload(self, payload: PhaseOverlayPayload) -> None:
        self._last = payload
        if self._canvas_built:
            self._paint(payload)

    def refresh_theme(self) -> None:
        if not self._canvas_built or self._fig is None:
            return
        self._fig.set_facecolor(get_theme().palette.surface)
        if self._last is None:
            self._paint_empty()
        else:
            self._paint(self._last)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _paint_empty(self) -> None:
        assert self._fig is not None and self._canvas is not None
        self._fig.clear()
        ax = self._fig.add_subplot(111)
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "Run an interleaved-boost design to see the phase-current overlay.",
            ha="center",
            va="center",
            fontsize=10,
            color=get_theme().palette.text_muted,
            transform=ax.transAxes,
        )
        self._canvas.draw_idle()

    def _paint(self, p: PhaseOverlayPayload) -> None:
        assert self._fig is not None and self._canvas is not None
        pal = get_theme().palette
        self._fig.clear()
        ax = self._fig.add_subplot(111)

        # Build the time array + per-phase currents.
        if p.time_s and p.phase_currents_A:
            t = list(p.time_s)
            phases = [list(c) for c in p.phase_currents_A]
        else:
            t, phases = self._synthesise(p)

        if not t or not phases:
            self._paint_empty()
            return

        # Total current — element-wise sum.
        total = [sum(ph[i] for ph in phases) for i in range(len(t))]

        # ── Per-phase traces (faded background) ──
        # Use a deterministic palette: violet → amber → cyan-ish → green
        # so the user can identify φ1 / φ2 / φ3 / φ4 by colour.
        phase_palette = [
            pal.accent_violet,
            pal.warning,
            pal.success,
            pal.text_secondary,
            pal.danger,
            pal.text_muted,
        ]
        t_us = [s * 1e6 for s in t]  # µs for x-axis readability
        for k, ph in enumerate(phases):
            color = phase_palette[k % len(phase_palette)]
            ax.plot(t_us, ph, color=color, linewidth=1.0, alpha=0.55, label=f"φ{k + 1}", zorder=2)

        # ── Total current (heavy line) ──
        ax.plot(t_us, total, color=pal.text, linewidth=2.4, label="i_total", zorder=4)

        # ── Ripple metrics + dB cancellation chip ──
        # Duty-cycle-dependent: at the analytical sweet-spot
        # (D = 1/N) the per-phase ripples cancel exactly and
        # ``tot_pp`` collapses to floating-point noise, which
        # would explode the ``20·log10(...)`` formula. We clamp
        # the readout at 40 dB and report "≫ 40 dB" — engineers
        # don't care whether the cancellation is 60 dB or 80 dB
        # at the ideal duty, only that it's "complete enough".
        ph0_pp = max(phases[0]) - min(phases[0])
        tot_pp = max(total) - min(total)
        DB_CLAMP = 40.0
        if ph0_pp <= 0:
            db = 0.0
            db_label = "0 dB"
        elif tot_pp <= ph0_pp * 1e-3:
            db = DB_CLAMP
            db_label = f"≫ {DB_CLAMP:.0f} dB"
        else:
            db = 20.0 * math.log10(p.n_phases * ph0_pp / tot_pp)
            db_label = f"{db:.1f} dB"
        # The "ideal" cancellation reference for this N (with
        # duty = 1/N) — Hwu-Yau formula gives ~12 dB at N=2.
        ideal_db = {2: 12.0, 3: 14.5, 4: 16.0, 5: 17.4}.get(p.n_phases)

        # Annotate ripple peak/trough on the total trace —
        # only when the residual ripple is large enough to read
        # (≥ 5 % of per-phase). Otherwise the markers + label
        # land at indistinguishable Y values and clutter the plot.
        if tot_pp > ph0_pp * 0.05:
            i_max = total.index(max(total))
            i_min = total.index(min(total))
            ax.scatter(
                [t_us[i_max], t_us[i_min]],
                [total[i_max], total[i_min]],
                color=pal.danger,
                s=50,
                zorder=5,
                edgecolors="white",
                linewidths=1.2,
            )
            # Anchor the annotation to the trough (which is below
            # the marker we drew) and offset down-right so it
            # never collides with the subtitle along the top of
            # the plot.
            ax.annotate(
                f"ΔI_pp,total = {tot_pp:.2f} A",
                xy=(t_us[i_min], total[i_min]),
                xytext=(10, -22),
                textcoords="offset points",
                fontsize=9,
                color=pal.text,
                bbox=dict(boxstyle="round,pad=0.35", fc=pal.surface, ec=pal.border, lw=0.7),
                arrowprops=dict(arrowstyle="-", color=pal.text_muted, lw=0.6),
            )

        # Effective ripple frequency on the cap = N × fsw.
        f_ripple_kHz = p.n_phases * p.fsw_Hz / 1000.0

        # ── Axis chrome ──
        ax.set_xlabel("Time within switching period [µs]", color=pal.text)
        ax.set_ylabel("Inductor current [A]", color=pal.text)
        ax.tick_params(axis="both", labelcolor=pal.text)
        ax.grid(True, alpha=0.20, linestyle=":")
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_color(pal.border)
        ax.set_facecolor(pal.surface)

        # Title — N phases, dB cancellation, effective ripple freq.
        title_l = f"{p.n_phases}-phase interleaved — {db_label} ripple cancellation"
        if ideal_db is not None:
            title_l += f"  (ideal {ideal_db:.1f} dB at D = 1/{p.n_phases})"
        ax.set_title(
            title_l,
            fontsize=11,
            fontweight="bold",
            color=pal.text,
            loc="left",
            pad=14,
        )
        ax.text(
            0.0,
            1.005,
            f"Per-phase ΔI_pp = {ph0_pp:.2f} A  ·  "
            f"effective cap-side ripple at {f_ripple_kHz:.0f} kHz "
            f"({p.n_phases}×fsw)",
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=9,
            color=pal.text_secondary,
        )

        ax.legend(
            loc="lower right",
            fontsize=8,
            ncol=p.n_phases + 1,
            frameon=True,
            facecolor=pal.surface,
            edgecolor=pal.border,
            labelcolor=pal.text,
        )

        self._fig.tight_layout()
        self._canvas.draw_idle()

    # ------------------------------------------------------------------
    # Synthesis helper
    # ------------------------------------------------------------------
    def _synthesise(self, p: PhaseOverlayPayload) -> tuple[list[float], list[list[float]]]:
        """Build N triangular waveforms shifted by 360°/N.

        Each phase's current rises with slope V/L during the
        on-time (D·Tsw) and falls during the off-time. The
        analytical formula is in any boost-PFC text; here we
        just need the shape, so we use a normalised triangle
        with the supplied ΔI_pp peak-to-peak.
        """
        if p.fsw_Hz <= 0 or p.n_phases <= 0:
            return [], []
        Tsw = 1.0 / p.fsw_Hz
        n_pts = max(200, p.n_phases * 80)
        t = [Tsw * k / (n_pts - 1) for k in range(n_pts)]
        D = max(min(p.duty, 0.99), 0.01)
        I_avg = p.I_avg_per_phase_A
        di = p.delta_iL_pp_A

        phases = []
        for k in range(p.n_phases):
            phi = k * Tsw / p.n_phases  # phase shift
            current = []
            for tk in t:
                # Local time within the phase's switching period.
                tau = ((tk - phi) % Tsw) / Tsw
                if tau < D:
                    # Rising slope from -di/2 + I_avg up to +di/2 + I_avg.
                    val = I_avg - di / 2 + di * (tau / D)
                else:
                    val = I_avg + di / 2 - di * ((tau - D) / (1 - D))
                current.append(val)
            phases.append(current)
        return t, phases
