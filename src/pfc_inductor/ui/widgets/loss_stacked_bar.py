"""Loss stacked bar — visual breakdown of inductor power dissipation.

The project's :class:`~pfc_inductor.models.result.LossBreakdown`
splits dissipation into four buckets:

- ``P_cu_dc_W``      DC-resistance copper loss (line frequency).
- ``P_cu_ac_W``      AC copper loss (skin + proximity at fsw).
- ``P_core_line_W``  Steinmetz core loss at the line frequency
                     (60 / 50 Hz envelope).
- ``P_core_ripple_W``Steinmetz core loss from the switching-
                     frequency ripple (the small AC trajectory
                     riding on the line-frequency B excursion).

The "Perdas" card in the design page already shows these four
numbers tabular. This widget gives the *proportional* view: a
single horizontal stacked bar where each bucket's width is its
share of the total. Engineers reading this chart instantly see
which loss family dominates and where to invest design effort —
larger Cu_AC ⇒ revisit wire / litz; larger core_ripple ⇒
ferrite-grade / ΔB_pp issue, not turns count.

Pure analytical — no FEA needed. Topology-agnostic. Used both
in the FEA dialog Summary tab (proximity to the comparison
chart) and in the main design page's "Perdas" section as a
companion to the existing tabular readout.
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
class LossBreakdownPayload:
    """Plain-data view of the loss split.

    All values are in watts. ``thermal_limit_W`` is the
    design-target maximum loss (used to draw a vertical
    threshold marker); pass 0 to skip the marker.
    """

    P_cu_dc_W: float = 0.0
    P_cu_ac_W: float = 0.0
    P_core_line_W: float = 0.0
    P_core_ripple_W: float = 0.0
    thermal_limit_W: float = 0.0
    """If > 0, draw a vertical dashed line at this loss level
    so the user can compare the actual total against the spec."""

    eta_pct: float = 0.0
    """Efficiency at the operating point — used in the title to
    contextualise total loss against output power."""

    @classmethod
    def from_result(
        cls,
        result,
        thermal_limit_W: float = 0.0,
    ) -> "LossBreakdownPayload":
        """Build from a :class:`DesignResult`. Works whether
        ``result.losses`` is the :class:`LossBreakdown` model
        instance or a duck-typed substitute."""
        losses = getattr(result, "losses", None)
        if losses is None:
            return cls()
        # Efficiency: estimate from total loss + Pout when
        # ``Pout_W`` is on the result; otherwise leave at 0
        # (header just doesn't show the η chip).
        Pout = float(getattr(result, "Pout_W", 0.0) or 0.0)
        if not Pout:
            spec = getattr(result, "spec", None)
            Pout = float(getattr(spec, "Pout_W", 0.0) or 0.0)
        Pcu_dc = float(getattr(losses, "P_cu_dc_W", 0.0) or 0.0)
        Pcu_ac = float(getattr(losses, "P_cu_ac_W", 0.0) or 0.0)
        Pcore_l = float(getattr(losses, "P_core_line_W", 0.0) or 0.0)
        Pcore_r = float(getattr(losses, "P_core_ripple_W", 0.0) or 0.0)
        Ptot = Pcu_dc + Pcu_ac + Pcore_l + Pcore_r
        eta = (Pout / (Pout + Ptot) * 100.0) if (Pout > 0 and Ptot > 0) else 0.0
        return cls(
            P_cu_dc_W=Pcu_dc,
            P_cu_ac_W=Pcu_ac,
            P_core_line_W=Pcore_l,
            P_core_ripple_W=Pcore_r,
            thermal_limit_W=float(thermal_limit_W),
            eta_pct=eta,
        )

    @property
    def P_total_W(self) -> float:
        return (
            self.P_cu_dc_W
            + self.P_cu_ac_W
            + self.P_core_line_W
            + self.P_core_ripple_W
        )


class LossStackedBar(QWidget):
    """Horizontal stacked-bar of the four loss families."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._fig = Figure(figsize=(7.0, 2.4), dpi=100)
        self._fig.set_facecolor(get_theme().palette.surface)
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setFixedHeight(190)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._canvas, 1)

        self._last: Optional[LossBreakdownPayload] = None
        self._paint_empty()
        on_theme_changed(self.refresh_theme)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def show_payload(self, payload: LossBreakdownPayload) -> None:
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
            0.5, 0.5, "Run a design to see the loss breakdown.",
            ha="center", va="center", fontsize=10,
            color=get_theme().palette.text_muted,
            transform=ax.transAxes,
        )
        self._canvas.draw_idle()

    def _paint(self, p: LossBreakdownPayload) -> None:
        pal = get_theme().palette
        self._fig.clear()
        ax = self._fig.add_subplot(111)

        total = p.P_total_W
        if total <= 0:
            self._paint_empty()
            return

        # Bucket order — Cu first (left of bar), core second.
        # Same convention engineers use when reading the
        # tabular breakdown ("Cu losses, then core losses").
        buckets = [
            ("Cu DC",        p.P_cu_dc_W,      pal.accent_violet),
            ("Cu AC",        p.P_cu_ac_W,      "#A78BFA"),  # lighter violet
            ("Core line",    p.P_core_line_W,  pal.warning),
            ("Core ripple",  p.P_core_ripple_W, "#F97316"),  # amber-orange
        ]

        # Single horizontal bar, segments side by side.
        left = 0.0
        for label, value, color in buckets:
            if value <= 0:
                continue
            ax.barh(
                [0], [value], left=left, color=color,
                edgecolor="white", linewidth=1.5,
                height=0.55, label=f"{label}: {value:.2f} W",
            )
            # In-segment label when the segment is wide enough
            # to read without truncation (≥ 12 % of total). The
            # narrower-than-12 % case promotes the label to the
            # right-side legend so multi-line text doesn't get
            # clipped on small bars.
            if value / total >= 0.12:
                pct = value / total * 100.0
                ax.text(
                    left + value / 2, 0,
                    f"{label}\n{value:.2f} W  ({pct:.0f} %)",
                    ha="center", va="center",
                    fontsize=9, color="white", fontweight="bold",
                )
            left += value

        # Thermal limit marker (vertical dashed line).
        if p.thermal_limit_W > 0:
            ax.axvline(
                p.thermal_limit_W,
                color=pal.danger, linestyle="--", linewidth=1.4,
                alpha=0.85,
            )
            margin = (p.thermal_limit_W - total) / max(total, 1e-9) * 100
            ax.text(
                p.thermal_limit_W, 0.5,
                f"  thermal cap {p.thermal_limit_W:.2f} W "
                f"({'+' if margin >= 0 else ''}{margin:.0f} % margin)",
                ha="left", va="center", fontsize=8,
                color=pal.danger, fontweight="bold",
            )

        # Y axis chrome (suppress — single-row bar).
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["top"].set_visible(False)
        ax.spines["bottom"].set_color(pal.border)
        ax.tick_params(axis="x", labelcolor=pal.text)
        ax.set_xlabel("Power dissipation [W]", color=pal.text)
        ax.grid(True, alpha=0.18, linestyle=":", axis="x")

        # Title carries totals + efficiency for instant readout.
        eta_chip = (
            f"  ·  η = {p.eta_pct:.2f} %" if p.eta_pct > 0 else ""
        )
        ax.set_title(
            f"Loss breakdown — total {total:.2f} W{eta_chip}",
            fontsize=11, fontweight="bold", color=pal.text,
            loc="left", pad=8,
        )

        ax.set_xlim(0, max(total, p.thermal_limit_W) * 1.18)
        ax.set_ylim(-0.5, 0.5)
        ax.set_facecolor(pal.surface)

        # Legend with proper colours — only shows segments that
        # were too narrow to label inline (matches the 12 %
        # threshold used in the inline placement above).
        narrow = [
            (lbl, val, col) for (lbl, val, col) in buckets
            if 0 < val and val / total < 0.12
        ]
        if narrow:
            from matplotlib.patches import Patch
            handles = [
                Patch(facecolor=col, edgecolor="white",
                      label=f"{lbl}: {val:.2f} W")
                for lbl, val, col in narrow
            ]
            ax.legend(
                handles=handles, loc="upper right",
                fontsize=8, frameon=True,
                facecolor=pal.surface, edgecolor=pal.border,
                labelcolor=pal.text,
            )

        self._fig.tight_layout()
        self._canvas.draw_idle()
