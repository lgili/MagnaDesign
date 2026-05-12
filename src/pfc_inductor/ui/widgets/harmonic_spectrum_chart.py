"""Harmonic spectrum chart with IEC 61000-3-2 compliance check.

Used for **line-frequency** topologies whose value proposition is
harmonic suppression:

- ``passive_choke`` / ``pfc_passive``  — LC filter on the AC side
                                          of a capacitor-input rectifier.
- ``line_reactor``                     — series choke (typically 3 %
                                          impedance) for IEC 61000-3-2
                                          and 61000-3-12 compliance.

Plot anatomy:

- **Bar per harmonic order** (h = 3, 5, 7, ..., 39) showing
  current amplitude in absolute Amps.
- **IEC limit overlay** — Class A or Class D limit per
  harmonic order, drawn as a coloured horizontal segment over
  each bar. Bars whose tip exceeds the limit are tinted red;
  passing bars are tinted blue/green.
- **Compliance verdict** in the title: "PASSED · IEC 61000-3-2
  Class A" or "FAILED on h = 5" with the worst margin.
- **Fundamental annotation** (h = 1) listed separately on the
  left so the user has the reference value for the percentages.

Why we don't read harmonics from FEA:

The inductor's job is to shape the line current; the harmonics
are an analytical / circuit-simulator output, not a magnetics-
solver output. We accept the spectrum as a payload from the
caller (which may compute it via the topology's own ripple
formula or a SPICE simulation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional

from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from pfc_inductor.ui.theme import get_theme, on_theme_changed

# matplotlib pulls in numpy + a font cache rebuild on cold launch
# (~150–300 ms). The harmonic-spectrum card is only visible when the
# Compliance tab is selected on a PFC-active topology — most cold
# launches never need it. Imports moved to ``_figure_imports`` so the
# cost is paid lazily on first instantiation of the chart widget.
if TYPE_CHECKING:  # pragma: no cover — typing only
    from matplotlib.backends.backend_qtagg import (  # noqa: F401
        FigureCanvasQTAgg as FigureCanvas,
    )
    from matplotlib.figure import Figure  # noqa: F401


def _figure_imports():
    """Lazy matplotlib import — called from ``__init__`` so the
    cost only lands when the chart actually instantiates."""
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure

    return Figure, FigureCanvas


IECClass = Literal["A", "D"]

# IEC 61000-3-2 Class A absolute limits (Arms) for h = 2..40.
# From IEC 61000-3-2 Ed.5 Table 1. Class A applies to balanced
# 3-phase equipment, household appliances, tools, dimmers, audio
# equipment — the broad case for passive line chokes.
_IEC_CLASS_A_LIMITS_A: dict[int, float] = {
    2: 1.080,
    3: 2.300,
    4: 0.430,
    5: 1.140,
    6: 0.300,
    7: 0.770,
    9: 0.400,
    11: 0.330,
    13: 0.210,
    15: 0.150,
    17: 0.132,
    19: 0.118,
    21: 0.107,
    23: 0.098,
    25: 0.090,
    27: 0.083,
    29: 0.078,
    31: 0.073,
    33: 0.068,
    35: 0.064,
    37: 0.061,
    39: 0.058,
}

# IEC Class D — PFC class for ≤ 600 W single-phase equipment
# with a "special wave-shape" input current (capacitor-input
# rectifiers). Limits scale per watt of input power, expressed
# as mA / W.
_IEC_CLASS_D_LIMITS_MA_PER_W: dict[int, float] = {
    3: 3.40,
    5: 1.90,
    7: 1.00,
    9: 0.50,
    11: 0.35,
}


def _iec_limit_A(order: int, iec_class: IECClass, P_in_W: float) -> Optional[float]:
    """Return the limit (in Arms) for ``order`` under the given
    class. Falls back to the asymptotic formula for the higher
    orders not in the explicit table.
    """
    if iec_class == "A":
        if order in _IEC_CLASS_A_LIMITS_A:
            return _IEC_CLASS_A_LIMITS_A[order]
        # h = 15..39 even (rare in PFC content) and odd orders
        # follow 0.15·15/h asymptote per IEC text.
        if order >= 15:
            return 0.15 * 15.0 / order
        return None
    elif iec_class == "D":
        if P_in_W <= 0:
            return None
        if order in _IEC_CLASS_D_LIMITS_MA_PER_W:
            return _IEC_CLASS_D_LIMITS_MA_PER_W[order] * P_in_W * 1e-3
        if order >= 13 and order <= 39 and order % 2 == 1:
            # IEC asymptote 3.85 / h mA/W for h ≥ 13.
            return (3.85 / order) * P_in_W * 1e-3
        return None
    return None


@dataclass(frozen=True)
class HarmonicSpectrumPayload:
    """Plain-data spectrum.

    ``orders`` and ``amplitudes_A`` are parallel sequences;
    ``orders[0]`` should be the fundamental (h = 1) so the chart
    can use it as the reference. Subsequent orders may skip
    even harmonics (IEC limits are tabulated for odd orders only
    in single-phase systems).
    """

    orders: tuple[int, ...]
    amplitudes_A: tuple[float, ...]
    iec_class: IECClass = "A"
    P_in_W: float = 0.0
    """Required for IEC Class D (mA/W limits scale with input
    power). Ignored for Class A."""

    f_line_Hz: float = 60.0
    topology_name: str = ""

    @property
    def fundamental_A(self) -> float:
        for o, a in zip(self.orders, self.amplitudes_A, strict=False):
            if o == 1:
                return a
        return 0.0

    def thd_pct(self) -> float:
        """Total harmonic distortion as % of fundamental, IEEE
        519 definition (RMS sum of harmonics ≥ 2)."""
        I1 = self.fundamental_A
        if I1 <= 0:
            return 0.0
        s = 0.0
        for o, a in zip(self.orders, self.amplitudes_A, strict=False):
            if o >= 2:
                s += a * a
        return (s**0.5) / I1 * 100.0


class HarmonicSpectrumChart(QWidget):
    """Bar chart of current harmonics with per-order IEC limits."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        Figure, FigureCanvas = _figure_imports()
        self._fig = Figure(figsize=(8.0, 4.4), dpi=100)
        self._fig.set_facecolor(get_theme().palette.surface)
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setMinimumHeight(360)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._canvas, 1)

        self._last: Optional[HarmonicSpectrumPayload] = None
        self._paint_empty()
        on_theme_changed(self.refresh_theme)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def show_payload(self, payload: HarmonicSpectrumPayload) -> None:
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
            "Harmonic spectrum not computed yet.\n"
            "Run a passive-PFC or line-reactor design to populate.",
            ha="center",
            va="center",
            fontsize=10,
            color=get_theme().palette.text_muted,
            transform=ax.transAxes,
        )
        self._canvas.draw_idle()

    def _paint(self, p: HarmonicSpectrumPayload) -> None:
        pal = get_theme().palette
        self._fig.clear()
        ax = self._fig.add_subplot(111)

        if not p.orders or not p.amplitudes_A:
            self._paint_empty()
            return

        # Filter: draw only h ≥ 2 (skip the fundamental — it's
        # 50–100× larger and would crush the bar scale). The
        # fundamental's value goes in the title instead.
        bars = [(o, a) for o, a in zip(p.orders, p.amplitudes_A, strict=False) if o >= 2]
        if not bars:
            self._paint_empty()
            return

        # Per-bar IEC limit + pass/fail tint.
        worst_failure: tuple[int, float] = (0, 0.0)
        bar_colors = []
        bar_xs, bar_ys, limit_lines = [], [], []
        for order, amp in bars:
            lim = _iec_limit_A(order, p.iec_class, p.P_in_W)
            bar_xs.append(order)
            bar_ys.append(amp)
            if lim is None:
                bar_colors.append(pal.text_muted)
                limit_lines.append(None)
            else:
                ratio = amp / lim
                if ratio > 1.0:
                    bar_colors.append(pal.danger)
                    if ratio > worst_failure[1]:
                        worst_failure = (order, ratio)
                elif ratio > 0.8:
                    bar_colors.append(pal.warning)
                else:
                    bar_colors.append(pal.success)
                limit_lines.append(lim)

        # Draw the bars.
        ax.bar(
            bar_xs,
            bar_ys,
            color=bar_colors,
            width=1.4,
            edgecolor="white",
            linewidth=0.6,
            zorder=3,
        )

        # IEC limit overlay — short horizontal segment over each
        # bar. Drawn after the bars so the tint comparison is
        # obvious. Dashed red at the limit value.
        for x, lim in zip(bar_xs, limit_lines, strict=False):
            if lim is None:
                continue
            ax.plot(
                [x - 0.7, x + 0.7],
                [lim, lim],
                color=pal.danger,
                linewidth=1.6,
                linestyle="-",
                zorder=4,
                solid_capstyle="round",
            )

        # Axis chrome.
        ax.set_xlabel(
            f"Harmonic order h  (×{p.f_line_Hz:.0f} Hz)",
            color=pal.text,
        )
        ax.set_ylabel("Current amplitude [A rms]", color=pal.text)
        ax.tick_params(axis="both", labelcolor=pal.text)
        ax.set_xticks([o for o, _ in bars])
        ax.grid(True, alpha=0.20, linestyle=":", axis="y")
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_color(pal.border)
        ax.set_facecolor(pal.surface)

        # Title — verdict + fundamental + THD.
        if worst_failure[0] == 0:
            verdict = f"<<{'PASSED'}>>  IEC 61000-3-2 Class {p.iec_class}"
            verdict_color = pal.success
        else:
            verdict = (
                f"FAILED  ·  worst at h = {worst_failure[0]} "
                f"({(worst_failure[1] - 1) * 100:+.0f} % over limit)"
            )
            verdict_color = pal.danger

        meta = []
        if p.fundamental_A > 0:
            meta.append(f"I₁ = {p.fundamental_A:.2f} A")
        meta.append(f"THD = {p.thd_pct():.1f} %")
        if p.iec_class == "D" and p.P_in_W > 0:
            meta.append(f"P_in = {p.P_in_W:.0f} W")

        title_main = "Current harmonics  ·  " + verdict.replace("<<", "").replace(">>", "")
        ax.set_title(
            title_main,
            fontsize=11,
            fontweight="bold",
            color=verdict_color,
            loc="left",
            pad=12,
        )
        # Subtitle with reference values.
        ax.text(
            0.0,
            1.005,
            "  ·  ".join(meta),
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=9,
            color=pal.text_secondary,
        )

        # Legend explaining the bar colours.
        from matplotlib.patches import Patch

        legend_handles = [
            Patch(facecolor=pal.success, label="≤ 80 % of limit (comfortable)"),
            Patch(facecolor=pal.warning, label="80–100 % of limit (at margin)"),
            Patch(facecolor=pal.danger, label="> 100 % of limit (failing)"),
        ]
        ax.legend(
            handles=legend_handles,
            loc="upper right",
            fontsize=8,
            frameon=True,
            facecolor=pal.surface,
            edgecolor=pal.border,
            labelcolor=pal.text,
        )

        self._fig.tight_layout()
        self._canvas.draw_idle()
