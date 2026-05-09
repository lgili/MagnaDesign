"""B-H operating-point chart.

Shows where the design sits on the material's static B(H) curve,
how much AC headroom is left to ``Bsat``, and the size of the
switching-cycle B-swing the core actually sees.

Why this view is its own widget:

- The summary tab compares **analytic vs FEA** numbers — that's
  about validation accuracy, not magnetic loading.
- The swept FEA tab shows **L(I)** rolloff — that's about how
  inductance shrinks under bias.
- This view shows **B vs H** with the static curve as the
  reference. It's the canonical "am I about to saturate?"
  diagnostic, the single picture that magnetics-textbook
  intuition was built on.

Plot anatomy:

- **Static B(H) curve**  ─ smooth tanh approximation parametrised
  by the catalog ``mu_initial`` (slope at H=0) and the operating-
  temperature ``Bsat`` (asymptote). The catalog rolloff curve
  gives a more accurate µ(H), but tanh captures the shape well
  enough to read margin to saturation visually.
- **Bsat reference**     ─ dashed red line at ``Bsat`` with text
  marker. Tile in light red the band above ``(1 − margin)·Bsat``
  to mark "no transient headroom" territory.
- **Operating point**    ─ filled dot at ``(H_pk, B_pk)`` with
  numerical readout (mT, Oe, µ_r at point).
- **AC loop**            ─ when ``waveform_B_T`` is supplied,
  trace the (H(t), B(t)) trajectory over one switching period
  as a small loop centred on the operating point. The loop's
  enclosed area visually approximates one cycle of core loss.
"""

from __future__ import annotations

import math
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

# H is canonically reported in Oersteds in the magnetics
# catalogues we consume, but we plot in A/m — engineers think in
# both. 1 Oe ≈ 79.5774715 A/m.
_OE_TO_A_PER_M = 79.5774715459


@dataclass(frozen=True)
class BHLoopPayload:
    """Plain-data inputs for the BH chart."""

    mu_initial: float = 60.0
    """Catalog initial permeability (zero-bias µᵣ)."""

    Bsat_T: float = 0.5
    """Saturation flux density at the relevant operating
    temperature (Magnetics quotes 25 °C and 100 °C; pick 100 °C
    if the design is for sustained load)."""

    Bsat_margin: float = 0.20
    """Fraction below Bsat to mark as the "no headroom" band.
    Default 20 % matches the rule the dialog's other charts use."""

    B_pk_T: float = 0.0
    """Operating-point peak flux density (analytic or FEA-validated)."""

    H_pk_A_per_m: float = 0.0
    """Operating-point peak magnetising force [A/m]. We accept
    A/m so the input is unit-canonical; the widget converts to
    Oersteds for the secondary X-axis."""

    waveform_H_A_per_m: Optional[tuple[float, ...]] = None
    waveform_B_T: Optional[tuple[float, ...]] = None
    """Optional dynamic trajectory over one switching period.
    Both tuples must have the same length; we draw the loop as
    ``plot(H, B)``. ``None`` skips the AC overlay."""

    material_name: str = ""
    core_part: str = ""

    @classmethod
    def from_models(cls, material, result, hot: bool = True) -> "BHLoopPayload":
        """Build a payload from the project's pydantic models.

        ``hot=True`` uses ``Bsat_100C_T`` (continuous-load case);
        flip to ``False`` for ambient-spec cores."""
        Bsat_attr = "Bsat_100C_T" if hot else "Bsat_25C_T"
        Bsat_T = float(getattr(material, Bsat_attr, 0.0) or 0.0)
        if Bsat_T <= 0:  # fall back to the other if missing
            Bsat_T = float(
                getattr(material, "Bsat_25C_T", 0.0)
                or getattr(material, "Bsat_100C_T", 0.0)
                or 0.5
            )
        H_pk_Oe = float(getattr(result, "H_dc_peak_Oe", 0.0) or 0.0)
        H_pk_A_per_m = H_pk_Oe * _OE_TO_A_PER_M
        # Use waveform_iL × N / le to compute H(t) if available?
        # No — we'd need N and le; cleaner to pass H trajectory
        # explicitly when callers need the dynamic loop.
        return cls(
            mu_initial=float(getattr(material, "mu_initial", 60.0) or 60.0),
            Bsat_T=Bsat_T,
            Bsat_margin=0.20,
            B_pk_T=float(getattr(result, "B_pk_T", 0.0) or 0.0),
            H_pk_A_per_m=H_pk_A_per_m,
            material_name=str(getattr(material, "name", "")),
            core_part=str(getattr(result, "core_part", "")),
        )


class BHLoopChart(QWidget):
    """Static B(H) curve + operating-point overlay."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._fig = Figure(figsize=(7.0, 4.4), dpi=100)
        self._fig.set_facecolor(get_theme().palette.surface)
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setMinimumHeight(360)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._canvas, 1)

        self._last: Optional[BHLoopPayload] = None
        self._paint_empty()
        on_theme_changed(self.refresh_theme)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def show_payload(self, payload: BHLoopPayload) -> None:
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
            "Run a design to see the operating point on the material B-H curve.",
            ha="center", va="center", fontsize=10,
            color=get_theme().palette.text_muted,
            transform=ax.transAxes,
        )
        self._canvas.draw_idle()

    def _paint(self, p: BHLoopPayload) -> None:
        pal = get_theme().palette
        self._fig.clear()
        ax = self._fig.add_subplot(111)

        # ── Static B(H) curve ──
        # B = Bsat · tanh(µ₀·µ_r·H / Bsat). Captures the linear
        # initial slope (= µ₀·µ_r) and the asymptote at Bsat
        # without needing the full catalog rolloff curve. Off by
        # ~5–15 % vs measured B(H) in the saturation knee — fine
        # for a visual reference.
        Bsat = max(p.Bsat_T, 1e-6)
        mu0 = 4 * math.pi * 1e-7
        slope = mu0 * p.mu_initial
        # Adaptive X-axis range. Two competing goals:
        #
        #   1. Show enough of the curve that the saturation knee
        #      is visible (so the user can read "I'm halfway up"
        #      vs "I'm in the knee").
        #   2. Don't over-extend so much that the operating point
        #      and AC trajectory shrink to a single dot.
        #
        # Heuristic: extend to whichever is larger of (a) ~80 %
        # of Bsat on the curve (where rolloff becomes obvious),
        # or (b) 2.5 × the operating point. For PFC inductors at
        # low-to-mid H_pk this puts the dot ~⅓ of the way out
        # and leaves room for the AC loop next to it.
        H_at_80pct_Bsat = math.atanh(0.80) * Bsat / slope
        H_max = H_at_80pct_Bsat
        if p.H_pk_A_per_m:
            H_max = max(H_max, p.H_pk_A_per_m * 2.5)
        n = 400
        H = [-H_max + 2 * H_max * i / (n - 1) for i in range(n)]
        B = [Bsat * math.tanh(slope * h / Bsat) for h in H]
        ax.plot(H, B, color=pal.accent_violet, linewidth=2.0,
                label=f"Static B(H), µᵣ = {p.mu_initial:.0f}",
                zorder=4)

        # ── Bsat reference + danger band ──
        Blimit = Bsat * (1.0 - p.Bsat_margin)
        ax.axhspan(Blimit, Bsat * 1.05, facecolor=pal.danger,
                   alpha=0.10, zorder=1)
        ax.axhspan(-Bsat * 1.05, -Blimit, facecolor=pal.danger,
                   alpha=0.10, zorder=1)
        for sign in (+1, -1):
            ax.axhline(sign * Bsat, color=pal.danger, linewidth=1.2,
                       linestyle=":", alpha=0.85, zorder=2)
        ax.text(H_max * 0.98, Bsat,
                f"  Bsat {Bsat * 1000:.0f} mT",
                ha="right", va="bottom", fontsize=8,
                color=pal.danger, fontweight="bold")
        ax.text(H_max * 0.98, Blimit,
                f"  −{p.Bsat_margin*100:.0f} % headroom band",
                ha="right", va="top", fontsize=8,
                color=pal.warning)

        # ── AC trajectory (optional) ──
        if (p.waveform_H_A_per_m and p.waveform_B_T
                and len(p.waveform_H_A_per_m) == len(p.waveform_B_T)
                and len(p.waveform_H_A_per_m) > 1):
            ax.plot(p.waveform_H_A_per_m, p.waveform_B_T,
                    color=pal.warning, linewidth=1.5, alpha=0.9,
                    label="AC trajectory (one cycle)",
                    zorder=5)

        # ── Operating point dot + readout ──
        if p.H_pk_A_per_m and p.B_pk_T:
            ax.scatter([p.H_pk_A_per_m], [p.B_pk_T],
                       color=pal.success, s=110, zorder=6,
                       edgecolors="white", linewidths=1.6,
                       label="Operating point (peak)")
            margin_pct = (1.0 - p.B_pk_T / Bsat) * 100 if Bsat > 0 else 0
            ax.annotate(
                (f"B_pk = {p.B_pk_T * 1000:.0f} mT\n"
                 f"H_pk = {p.H_pk_A_per_m / _OE_TO_A_PER_M:.0f} Oe\n"
                 f"margin = {margin_pct:.0f} % to Bsat"),
                xy=(p.H_pk_A_per_m, p.B_pk_T),
                xytext=(15, -10), textcoords="offset points",
                fontsize=9, color=pal.text,
                bbox=dict(boxstyle="round,pad=0.4",
                          fc=pal.surface, ec=pal.border, lw=0.8),
                arrowprops=dict(arrowstyle="-",
                                color=pal.text_muted, lw=0.6),
            )

        # ── Axis chrome ──
        ax.axhline(0, color=pal.border, linewidth=0.6, zorder=0)
        ax.axvline(0, color=pal.border, linewidth=0.6, zorder=0)
        ax.set_xlim(-H_max, H_max)
        ax.set_ylim(-Bsat * 1.15, Bsat * 1.15)
        ax.set_xlabel("Magnetising force H [A/m]", color=pal.text)
        ax.set_ylabel("Flux density B [T]", color=pal.text)
        ax.tick_params(axis="both", labelcolor=pal.text)
        ax.grid(True, alpha=0.18, linestyle=":")
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_color(pal.border)
        ax.set_facecolor(pal.surface)

        # Secondary X-axis in Oersteds for catalog consistency.
        # Magnetics / Micrometals datasheets quote H in Oe.
        sec = ax.secondary_xaxis(
            "top",
            functions=(
                lambda x: x / _OE_TO_A_PER_M,  # type: ignore[operator]
                lambda x: x * _OE_TO_A_PER_M,  # type: ignore[operator]
            ),
        )
        sec.set_xlabel("Magnetising force H [Oe]", color=pal.text_muted,
                       fontsize=9)
        sec.tick_params(axis="x", labelcolor=pal.text_muted, labelsize=8)

        # ── Title ──
        bits = ["B-H — operating point on static curve"]
        if p.material_name:
            bits.append(f"({p.material_name})")
        ax.set_title("  ".join(bits), fontsize=11, fontweight="bold",
                     color=pal.text, loc="left", pad=14)

        # ── Legend ──
        ax.legend(loc="lower right", fontsize=8, frameon=True,
                  facecolor=pal.surface, edgecolor=pal.border,
                  labelcolor=pal.text)

        self._fig.tight_layout()
        self._canvas.draw_idle()
