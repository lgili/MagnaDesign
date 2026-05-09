"""Swept-FEA chart — L(I) and B(I) curves from Tier-4 sample arrays.

Tier 4 of the cascade orchestrator runs the same magnetostatic
FEA solver Tier 3 uses, but at N bias points across the
half-cycle. The result carries three parallel arrays
(``sample_currents_A`` × ``sample_L_uH`` × ``sample_B_T``) that
describe how inductance and flux density evolve as the
operating point moves up the rolloff curve.

This widget renders those arrays as a two-axis line chart:

- **Left Y-axis** — inductance L(I) in µH, the metric the
  designer cares most about (sized for nominal L, watches for
  rolloff at peak current).
- **Right Y-axis** — flux density B(I) in mT, anchored to the
  saturation envelope so the user can see how close the design
  runs to ``Bsat``.
- **X-axis** — current I in A.

Annotations:

- **Operating point marker** — vertical dashed line at the
  Tier-1 design's peak current, drawn in muted text colour so
  it reads as "this is where the design lives".
- **Saturation knee** — when L drops by > 30 % from its
  zero-bias value, mark the crossing with a red triangle on the
  L curve. Tier 4's ``saturation_t4`` flag uses ``Bsat ·
  (1 − margin)`` against the simulated B, but the L-rolloff
  knee is the more honest "you're losing inductance" signal
  for the designer.
- **Bsat horizontal line** — when ``Bsat_T`` is supplied, draw
  a dashed danger line on the B-axis; tile in red the region
  above it.

The widget is **passive** — it just consumes a payload and
draws. The host (FEAValidationDialog) decides when to populate
it: either by running ``tier4.evaluate_candidate`` on demand
via a worker, or by reading the most recent Tier-4 row from
the cascade store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # noqa: E402

from matplotlib.backends.backend_qtagg import (  # noqa: E402
    FigureCanvasQTAgg as FigureCanvas,
)
from matplotlib.figure import Figure  # noqa: E402
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget  # noqa: E402

from pfc_inductor.ui.theme import get_theme, on_theme_changed  # noqa: E402


@dataclass(frozen=True)
class SweptFEAPayload:
    """Plain-data view of a Tier-4 swept-FEA result.

    Decoupled from ``models.cascade.Tier4Result`` so non-cascade
    callers (e.g. a future "run swept FEA" button on the dialog
    that doesn't go through the orchestrator) can construct one
    without pulling cascade metadata. ``saturation_t4`` is
    informational; the L-rolloff knee detection is independent.
    """

    currents_A: tuple[float, ...]
    L_uH: tuple[float, ...]
    B_T: tuple[float, ...]
    operating_point_A: float = 0.0
    """Tier-1 peak current — drawn as a vertical dashed marker."""
    Bsat_T: float = 0.0
    """Material's hot Bsat. ``0`` skips the danger line."""
    Bsat_margin: float = 0.20
    """Fraction below Bsat to draw the warning region."""
    saturation_t4: bool = False
    """Tier-4's own saturation flag — surfaces in the chart
    title when True so the user can't miss it."""
    n_points: int = 0
    backend: str = ""

    @classmethod
    def from_tier4(
        cls,
        result,  # Tier4Result
        operating_point_A: float = 0.0,
        Bsat_T: float = 0.0,
        Bsat_margin: float = 0.20,
    ) -> "SweptFEAPayload":
        return cls(
            currents_A=tuple(result.sample_currents_A),
            L_uH=tuple(result.sample_L_uH),
            B_T=tuple(result.sample_B_T),
            operating_point_A=float(operating_point_A),
            Bsat_T=float(Bsat_T),
            Bsat_margin=float(Bsat_margin),
            saturation_t4=bool(result.saturation_t4),
            n_points=int(result.n_points_simulated),
            backend=str(result.backend),
        )


class SweptFEAChart(QWidget):
    """Two-axis line chart for the Tier-4 swept-FEA payload."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self._fig = Figure(figsize=(7.0, 3.4), dpi=100)
        self._fig.set_facecolor(get_theme().palette.surface)
        self._canvas = FigureCanvas(self._fig)
        # 280 px floor — fits the L(I) curve, the dual axis, the
        # Bsat band and the operating-point markers without
        # dwarfing the dialog's other surfaces.
        self._canvas.setMinimumHeight(280)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._canvas, 1)

        self._last: Optional[SweptFEAPayload] = None
        self._paint_empty()
        on_theme_changed(self.refresh_theme)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def show_payload(self, payload: SweptFEAPayload) -> None:
        self._last = payload
        self._paint(payload)

    def clear(self) -> None:
        self._last = None
        self._paint_empty()

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
            (
                "Run a swept FEA to see how L and B change as\n"
                "the bias current rises through the half-cycle.\n"
                "Click \"Run swept FEA\" below."
            ),
            ha="center",
            va="center",
            fontsize=10,
            color=get_theme().palette.text_muted,
            transform=ax.transAxes,
        )
        self._canvas.draw_idle()

    def _paint(self, payload: SweptFEAPayload) -> None:
        p = get_theme().palette
        self._fig.clear()
        ax_L = self._fig.add_subplot(111)
        ax_B = ax_L.twinx()

        I = list(payload.currents_A)
        L = list(payload.L_uH)
        B_mT = [b * 1000.0 for b in payload.B_T]

        if not I:
            self._paint_empty()
            return

        # ── L(I) curve (left axis) ──
        accent = p.accent_violet
        ax_L.plot(
            I,
            L,
            color=accent,
            marker="o",
            markersize=5,
            linewidth=2.0,
            label="L(I)  [µH]",
            zorder=4,
        )

        # ── L₀ reference + −30 % rolloff threshold ──
        # Two horizontal helpers on the L axis:
        #   * dashed grey line at L₀ (the zero-bias inductance) —
        #     anchors the eye so the rolloff is read as a delta,
        #     not an absolute curve.
        #   * dotted amber line at 0.7·L₀ — the conventional
        #     "saturation knee" threshold the chart already flags
        #     with a triangle marker. Drawing the threshold
        #     turns the knee detection into "is the curve below
        #     this line?", which matches how engineers reason
        #     about sat margin in DC bias derating tables.
        if len(L) >= 1 and L[0] > 0:
            L0 = L[0]
            ax_L.axhline(
                L0,
                color=p.text_muted,
                linewidth=1.0,
                linestyle="--",
                alpha=0.55,
                zorder=2,
            )
            ax_L.text(
                I[-1],
                L0,
                f"  L₀ = {L0:.0f} µH",
                ha="right", va="bottom",
                fontsize=8, color=p.text_muted,
            )
            ax_L.axhline(
                0.7 * L0,
                color=p.warning,
                linewidth=1.0,
                linestyle=":",
                alpha=0.65,
                zorder=2,
            )
            ax_L.text(
                I[0],
                0.7 * L0,
                f"  −30 % threshold ({0.7 * L0:.0f} µH)",
                ha="left", va="bottom",
                fontsize=8, color=p.warning,
            )

        # ── B(I) curve (right axis) ──
        b_line_color = p.text_secondary
        ax_B.plot(
            I,
            B_mT,
            color=b_line_color,
            marker="s",
            markersize=4,
            linewidth=1.6,
            linestyle="--",
            label="B(I)  [mT]",
            alpha=0.85,
            zorder=3,
        )

        # ── Bsat warning region (right axis) ──
        if payload.Bsat_T > 0:
            Bsat_mT = payload.Bsat_T * 1000.0
            Blimit_mT = Bsat_mT * (1.0 - payload.Bsat_margin)
            xlim = (min(I) - 0.5, max(I) + 0.5)
            ax_B.axhspan(
                Blimit_mT,
                Bsat_mT * 1.05,
                facecolor=p.danger,
                alpha=0.10,
                zorder=1,
            )
            ax_B.axhline(
                Bsat_mT,
                color=p.danger,
                linewidth=1.2,
                linestyle=":",
                alpha=0.85,
                zorder=2,
            )
            ax_B.text(
                xlim[1],
                Bsat_mT,
                f"  Bsat {Bsat_mT:.0f} mT",
                ha="right",
                va="bottom",
                fontsize=8,
                color=p.danger,
                fontweight="bold",
            )

        # ── L-rolloff sat-knee (red triangle) ──
        # Knee = the first sample where L has dropped by ≥ 30 %
        # from its low-bias value. Honest "you've lost L" signal —
        # complementary to ``saturation_t4`` which uses B vs Bsat.
        if len(L) >= 2:
            L0 = L[0]
            knee_idx: Optional[int] = None
            for i, l in enumerate(L):
                if L0 > 0 and l < 0.7 * L0:
                    knee_idx = i
                    break
            if knee_idx is not None:
                ax_L.scatter(
                    [I[knee_idx]],
                    [L[knee_idx]],
                    color=p.danger,
                    marker="v",
                    s=85,
                    zorder=5,
                    edgecolors="white",
                    linewidths=1.4,
                    label="L-rolloff knee (−30 %)",
                )

        # ── Operating point marker (vertical line) ──
        if payload.operating_point_A > 0:
            ax_L.axvline(
                payload.operating_point_A,
                color=p.text_muted,
                linestyle="-.",
                linewidth=1.2,
                alpha=0.7,
                zorder=2,
            )
            ax_L.text(
                payload.operating_point_A,
                ax_L.get_ylim()[1] if False else max(L) * 1.04,
                f"  I_pk = {payload.operating_point_A:.1f} A",
                ha="left",
                va="bottom",
                fontsize=8,
                color=p.text_secondary,
                fontweight="bold",
            )

        # ── Axis chrome ──
        ax_L.set_xlabel("Bias current I [A]", color=p.text)
        ax_L.set_ylabel("Inductance L [µH]", color=accent)
        ax_B.set_ylabel("Flux density B [mT]", color=b_line_color)
        ax_L.tick_params(axis="y", labelcolor=accent)
        ax_B.tick_params(axis="y", labelcolor=b_line_color)
        ax_L.tick_params(axis="x", labelcolor=p.text)
        ax_L.grid(True, alpha=0.18, linestyle=":")
        for spine in ("top",):
            ax_L.spines[spine].set_visible(False)
            ax_B.spines[spine].set_visible(False)
        for spine in ("right", "left", "bottom"):
            ax_L.spines[spine].set_color(p.border)
            ax_B.spines[spine].set_color(p.border)
        ax_L.set_facecolor(p.surface)

        # Title — carries the saturation verdict so the user
        # doesn't have to scan the curves to spot trouble.
        title_parts = [
            f"Swept FEA — {payload.n_points} points",
        ]
        if payload.backend:
            title_parts.append(f"({payload.backend})")
        if payload.saturation_t4:
            title_parts.append("⚠ saturation flag set")
        title_color = p.danger if payload.saturation_t4 else p.text
        ax_L.set_title(
            "  ".join(title_parts),
            fontsize=10,
            color=title_color,
            fontweight="bold",
            loc="left",
            pad=10,
        )

        # Legends — combined so both Y axes share one box.
        handles_L, labels_L = ax_L.get_legend_handles_labels()
        handles_B, labels_B = ax_B.get_legend_handles_labels()
        ax_L.legend(
            handles_L + handles_B,
            labels_L + labels_B,
            loc="lower left",
            fontsize=8,
            frameon=True,
            facecolor=p.surface,
            edgecolor=p.border,
            labelcolor=p.text,
        )

        self._fig.tight_layout()
        self._canvas.draw_idle()
