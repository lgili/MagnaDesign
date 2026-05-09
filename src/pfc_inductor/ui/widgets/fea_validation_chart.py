"""FEA validation chart — turn the wall-of-numbers into a glanceable visual.

Replaces the previous text-only readout
(``"L_FEA = 348 µH vs L_analytic = 351 µH (+0.9 %)"``) with two
panels:

- **Top**: side-by-side bars comparing analytic vs FEA for both
  ``L`` and ``B_pk``. Each pair carries a coloured ``±X.X %``
  chip annotated above the FEA bar so the magnitude *and*
  direction of the divergence read at a glance. Bars share a
  Y-axis per metric (paired-bar layout) so the visual
  comparison is fair across very different units.

- **Bottom**: confidence gauge — a horizontal segmented bar
  with the worst-error band highlighted. Three zones (high /
  medium / low) match the existing ``FEAValidation.confidence``
  property's thresholds (≤5 %, ≤15 %, >15 %). The pointer's
  position is the worst absolute error across L and B; the
  segment colour matches the verdict.

Why a Qt widget and not a static png:
matplotlib's ``FigureCanvasQTAgg`` renders inline without
spawning a viewer, sizes with the dialog, and re-paints
cleanly when the user toggles between light / dark themes.

Re-rendering the panels on a theme toggle is opt-in: the
widget caches the last :class:`FEAValidation` payload and
exposes :meth:`refresh_theme` so the host can wire it to the
``on_theme_changed`` signal without holding a stale reference.
"""

from __future__ import annotations

from typing import Optional

import matplotlib

matplotlib.use("Agg")  # noqa: E402 — Agg before any pyplot import

from matplotlib.backends.backend_qtagg import (  # noqa: E402
    FigureCanvasQTAgg as FigureCanvas,
)
from matplotlib.figure import Figure  # noqa: E402
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget  # noqa: E402

from pfc_inductor.fea.models import FEAValidation  # noqa: E402
from pfc_inductor.ui.theme import get_theme, on_theme_changed  # noqa: E402

# Confidence thresholds — matched to ``FEAValidation.confidence``.
# Keep in sync with that property; if it ever moves to numeric
# bands, this constant goes with it.
_CONFIDENCE_BANDS = (5.0, 15.0)  # ≤5 = high, ≤15 = medium, >15 = low


class FEAValidationChart(QWidget):
    """Chart panel that visualises a :class:`FEAValidation` payload."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        # 6.5 × 3.2 inches at 100 dpi → ~650 × 320 px display, fills
        # the dialog's results column without dwarfing the form rows
        # underneath. Two stacked subplots: bars on top, gauge below.
        self._fig = Figure(figsize=(6.5, 2.6), dpi=100)
        self._fig.set_facecolor(get_theme().palette.surface)
        self._canvas = FigureCanvas(self._fig)
        # 220 px floor — bar chart + chip + gauge fit at this
        # height. The earlier 280 left blank top/bottom that
        # combined with the new LossStackedBar pushed the FEA
        # dialog past common laptop screen heights.
        self._canvas.setMinimumHeight(220)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._canvas, 1)

        # Cache the last validation so theme toggles can re-paint.
        self._last: Optional[FEAValidation] = None

        # Render the empty state at construction so the widget
        # doesn't pop in blank when first shown.
        self._paint_empty()

        on_theme_changed(self.refresh_theme)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def show_validation(self, validation: FEAValidation) -> None:
        """Render the bar chart + gauge from a fresh validation result."""
        self._last = validation
        self._paint(validation)

    def clear(self) -> None:
        """Drop any cached payload and revert to the empty state."""
        self._last = None
        self._paint_empty()

    def refresh_theme(self) -> None:
        """Re-render the active payload (or the empty state) with the
        current theme palette. Wired to ``on_theme_changed`` at
        construction; the host doesn't need to call this."""
        self._fig.set_facecolor(get_theme().palette.surface)
        if self._last is None:
            self._paint_empty()
        else:
            self._paint(self._last)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _paint_empty(self) -> None:
        """Pre-validation placeholder: a faint hint where the bars
        will appear so the layout doesn't shift when the result
        lands."""
        self._fig.clear()
        ax = self._fig.add_subplot(111)
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "FEA chart will appear here\nafter the solve completes.",
            ha="center",
            va="center",
            fontsize=10,
            color=get_theme().palette.text_muted,
            transform=ax.transAxes,
        )
        self._canvas.draw_idle()

    def _paint(self, v: FEAValidation) -> None:
        p = get_theme().palette
        self._fig.clear()
        # 2-row grid: top row 70 % for bars, bottom 30 % for gauge.
        # Tight layout works fine here; both subplots are
        # well-bounded and matplotlib's auto-spacing reads cleanly.
        gs = self._fig.add_gridspec(
            nrows=2,
            ncols=1,
            height_ratios=(7, 3),
            hspace=0.55,
        )

        # ---- Bars: L_analytic vs L_FEA, B_analytic vs B_FEA ---------
        ax_bars = self._fig.add_subplot(gs[0])
        self._paint_bars(ax_bars, v, p)

        # ---- Confidence gauge ---------------------------------------
        ax_gauge = self._fig.add_subplot(gs[1])
        self._paint_gauge(ax_gauge, v, p)

        self._canvas.draw_idle()

    def _paint_bars(self, ax, v: FEAValidation, p) -> None:
        """Two pairs of bars (L, B) with a ±err % annotation chip
        above each FEA bar. Bars are normalised: each pair is
        scaled so the bigger of the two reaches a unit height —
        avoids the L_uH (~hundreds) crushing the B_T (~0.3) into
        invisibility on a shared axis."""
        # Pair labels + values (analytic, FEA, unit, err %).
        pairs = [
            (
                "Inductance (L)",
                float(v.L_analytic_uH),
                float(v.L_FEA_uH),
                "µH",
                float(v.L_pct_error),
            ),
            (
                "Peak flux (B)",
                float(v.B_pk_analytic_T) * 1000.0,
                float(v.B_pk_FEA_T) * 1000.0,
                "mT",
                float(v.B_pct_error),
            ),
        ]

        # Layout: two groups of 2 bars each, with a small gap.
        bar_w = 0.36
        x_anchors = [0.0, 1.4]
        for ax_x, (label, an, fea, unit, err) in zip(x_anchors, pairs):
            # Per-pair normalisation so both bars share a meaningful
            # vertical scale.
            scale = max(an, fea, 1e-9)
            bar_an = ax.bar(
                ax_x - bar_w / 2,
                an / scale,
                width=bar_w,
                color=p.text_muted,
                edgecolor="none",
                label="Analytic" if ax_x == 0.0 else None,
            )
            err_color = self._color_for_pct(abs(err), p)
            bar_fea = ax.bar(
                ax_x + bar_w / 2,
                fea / scale,
                width=bar_w,
                color=err_color,
                edgecolor="none",
                label="FEA" if ax_x == 0.0 else None,
            )

            # Analytic value label — above its bar.
            ax.text(
                bar_an[0].get_x() + bar_an[0].get_width() / 2,
                bar_an[0].get_height() + 0.04,
                self._fmt(an, unit),
                ha="center",
                va="bottom",
                fontsize=8,
                color=p.text_secondary,
            )
            # FEA value label — INSIDE the bar (top, white text)
            # so the error chip can sit above without overlap. Bar
            # height is always ≥ 0.4 in the normalised scale, so the
            # label fits comfortably even on the smaller of the
            # two bars.
            ax.text(
                bar_fea[0].get_x() + bar_fea[0].get_width() / 2,
                bar_fea[0].get_height() - 0.08,
                self._fmt(fea, unit),
                ha="center",
                va="top",
                fontsize=8,
                color="white",
                fontweight="bold",
            )

            # Pair caption beneath the bars.
            ax.text(
                ax_x,
                -0.12,
                label,
                ha="center",
                va="top",
                fontsize=9,
                color=p.text,
                fontweight="bold",
            )

            # Error chip — bordered pill above the tallest bar in
            # the pair. Padded high enough to clear the analytic
            # value label that sits at ``+0.04`` above its bar.
            chip_y = max(an, fea) / scale + 0.28
            sign = "+" if err >= 0 else "−"
            ax.text(
                ax_x + bar_w / 2,
                chip_y,
                f"{sign}{abs(err):.1f}%",
                ha="center",
                va="center",
                fontsize=9,
                fontweight="bold",
                color="white",
                bbox=dict(
                    boxstyle="round,pad=0.32",
                    facecolor=err_color,
                    edgecolor="none",
                ),
            )

        ax.set_xlim(-0.6, 2.0)
        ax.set_ylim(0, 1.65)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ("top", "right", "bottom", "left"):
            ax.spines[spine].set_visible(False)
        ax.set_facecolor(p.surface)
        ax.legend(
            loc="upper right",
            frameon=False,
            fontsize=8,
            labelcolor=p.text_secondary,
        )

    def _paint_gauge(self, ax, v: FEAValidation, p) -> None:
        """Horizontal 3-segment confidence gauge with a pointer at
        the worst-of-L-B absolute error."""
        worst = max(abs(v.L_pct_error), abs(v.B_pct_error))
        # Display range — clip the pointer at 30 % so the gauge
        # stays meaningful when the solver diverges hard.
        max_pct = 30.0
        clamped = min(worst, max_pct)

        # Three coloured segments — the canonical confidence bands.
        segments = [
            (0.0, _CONFIDENCE_BANDS[0], p.success, "high  ≤ 5 %"),
            (_CONFIDENCE_BANDS[0], _CONFIDENCE_BANDS[1], p.warning, "medium  ≤ 15 %"),
            (_CONFIDENCE_BANDS[1], max_pct, p.danger, "low  > 15 %"),
        ]
        for left, right, color, _label in segments:
            ax.barh(
                0,
                right - left,
                left=left,
                height=0.5,
                color=color,
                edgecolor="none",
                alpha=0.85,
            )

        # Tick labels at band edges.
        for tick in (0.0, _CONFIDENCE_BANDS[0], _CONFIDENCE_BANDS[1], max_pct):
            ax.text(
                tick,
                -0.7,
                f"{tick:.0f} %",
                ha="center",
                va="top",
                fontsize=8,
                color=p.text_secondary,
            )

        # Pointer triangle.
        ax.plot(
            [clamped],
            [0.6],
            marker="v",
            markersize=14,
            color=p.text,
            markeredgecolor="white",
            markeredgewidth=1.4,
            zorder=5,
        )
        # Inline pointer label.
        label = f"{worst:.1f}%  worst-of-L-B"
        if worst > max_pct:
            label = f">{max_pct:.0f}%  (clamped)"
        ax.text(
            clamped,
            1.05,
            label,
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
            color=p.text,
        )

        # Caption under the gauge.
        ax.text(
            max_pct / 2,
            -1.45,
            "Confidence band  ·  worst-case |%error| of L and B vs analytic",
            ha="center",
            va="top",
            fontsize=8,
            color=p.text_muted,
        )

        ax.set_xlim(-1.0, max_pct + 1.0)
        ax.set_ylim(-1.6, 1.5)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ("top", "right", "bottom", "left"):
            ax.spines[spine].set_visible(False)
        ax.set_facecolor(p.surface)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _color_for_pct(abs_pct: float, palette) -> str:
        """Map an absolute error percentage to one of the three
        semantic palette colours."""
        if abs_pct <= _CONFIDENCE_BANDS[0]:
            return palette.success
        if abs_pct <= _CONFIDENCE_BANDS[1]:
            return palette.warning
        return palette.danger

    @staticmethod
    def _fmt(value: float, unit: str) -> str:
        """Format a numeric value with sensible precision for the
        bar-label position. ``µH`` and ``mT`` both read cleanly
        with 1 decimal at this scale; widen the rule when adding
        new units."""
        if abs(value) >= 100:
            return f"{value:.0f} {unit}"
        return f"{value:.1f} {unit}"
