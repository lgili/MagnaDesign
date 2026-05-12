"""Per-fsw band plots — Analysis tab card.

When the active spec carries an ``fsw_modulation`` band, this
card reveals three small line charts:

- ``P_total(fsw)`` — total losses across the band.
- ``B_pk(fsw)``  — peak flux density across the band.
- ``ΔT(fsw)``    — winding temperature rise across the band.

Each chart annotates the worst-case point so the engineer
sees at a glance which fsw drove the envelope.

Hidden by default — only when ``update_from_design`` is called
with a ``BandedDesignResult`` does the card become visible.
Single-point ``DesignResult`` paths leave it hidden, preserving
the legacy Analysis tab layout for non-VFD specs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models.banded_result import BandedDesignResult, BandPoint
from pfc_inductor.ui.theme import get_theme, on_theme_changed

# matplotlib cold-import is ~150–300 ms. The modulation-band chart is
# only visible on specs that carry an ``fsw_modulation`` band — most
# cold launches never need it. Deferred to ``_figure_imports`` so the
# matplotlib pull lands lazily.
if TYPE_CHECKING:  # pragma: no cover — typing only
    from matplotlib.backends.backend_qtagg import (  # noqa: F401
        FigureCanvasQTAgg,
    )
    from matplotlib.figure import Figure  # noqa: F401


def _figure_imports():
    """Lazy matplotlib import for the modulation-band chart."""
    import matplotlib

    matplotlib.use("QtAgg")
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    return Figure, FigureCanvasQTAgg


# Per-metric (label, units, accessor, scale) — single source of
# truth for the three subplots. Adding a fourth metric later is
# one tuple here + one ax in `_build_figure`.
_METRICS: tuple[tuple[str, str, str, float], ...] = (
    ("Total losses", "W", "P_total_W", 1.0),
    ("Peak B", "mT", "B_pk_T", 1000.0),
    ("ΔT rise", "°C", "T_rise_C", 1.0),
)


class ModulationBandChart(QWidget):
    """Three side-by-side line plots: metric vs. fsw across the band."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self._outer = outer

        self._caption = QLabel("")
        self._caption.setProperty("role", "muted")
        self._caption.setWordWrap(True)
        outer.addWidget(self._caption)

        # Deferred Figure construction — see other chart widgets
        # for the rationale (keeps matplotlib off the boot path).
        self._placeholder = QWidget()
        self._placeholder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._placeholder.setMinimumHeight(220)
        outer.addWidget(self._placeholder)
        self._figure = None
        self._canvas = None
        self._canvas_built = False
        self._pending_banded: Optional[BandedDesignResult] = None
        on_theme_changed(self._refresh_theme)

    def _ensure_canvas_built(self) -> None:
        if self._canvas_built:
            return
        Figure, FigureCanvasQTAgg = _figure_imports()
        self._figure = Figure(figsize=(8.0, 2.4), tight_layout=True)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._canvas.setMinimumHeight(220)
        idx = self._outer.indexOf(self._placeholder)
        self._outer.removeWidget(self._placeholder)
        self._placeholder.deleteLater()
        self._placeholder = None  # type: ignore[assignment]
        self._outer.insertWidget(idx, self._canvas)
        self._canvas_built = True
        if self._pending_banded is not None:
            self.show_band(self._pending_banded)
            self._pending_banded = None
        else:
            self._render_empty()

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        self._ensure_canvas_built()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def show_band(self, banded: BandedDesignResult) -> None:
        """Replace the chart with one line per metric across the
        band. Annotates the worst-case fsw on each subplot."""
        # ---- Caption: always update, regardless of canvas state ----
        # The caption is a plain ``QLabel`` (no matplotlib dep), so we
        # set its text up-front. Tests assert against the caption
        # right after ``show_band`` without needing the canvas to
        # have built itself; deferring the caption with the rest of
        # the rendering was the cause of the v0.4.12 CI failure on
        # ``test_band_chart_show_band_renders_caption``.
        if banded.band:
            spec = banded.spec
            fsw_points = [bp.fsw_kHz for bp in banded.band if bp.result is not None]
            if fsw_points:
                n_failed = len(banded.flagged_points)
                modulation: Optional[str] = None
                if spec.fsw_modulation is not None:
                    modulation = spec.fsw_modulation.profile
                caption = (
                    f"Band: {fsw_points[0]:.1f} → {fsw_points[-1]:.1f} kHz · "
                    f"{len(banded.band)} points · profile={modulation}"
                )
                if n_failed > 0:
                    caption += f"  ⚠  {n_failed} engine failure(s)"
                self._caption.setText(caption)

        # ---- Canvas rendering: deferred if not built yet ----
        if not self._canvas_built:
            self._pending_banded = banded
            return
        if not banded.band:
            self._render_empty()
            return

        spec = banded.spec
        fsw_points = [bp.fsw_kHz for bp in banded.band if bp.result is not None]
        if not fsw_points:
            self._render_empty(message="Every band point failed.")
            return

        assert self._figure is not None and self._canvas is not None
        self._figure.clear()
        axes = self._figure.subplots(1, len(_METRICS))
        if len(_METRICS) == 1:
            axes = [axes]

        p = get_theme().palette
        line_color = p.accent
        marker_color = p.accent_violet
        warn_color = p.danger

        for idx, (label, units, accessor, scale) in enumerate(_METRICS):
            ax = axes[idx]
            xs: list[float] = []
            ys: list[float] = []
            for bp in banded.band:
                if bp.result is None:
                    continue
                value = self._read(bp, accessor)
                if value is None:
                    continue
                xs.append(bp.fsw_kHz)
                ys.append(value * scale)

            if not xs:
                ax.text(
                    0.5,
                    0.5,
                    "no data",
                    ha="center",
                    va="center",
                    color=p.text_muted,
                    transform=ax.transAxes,
                )
                ax.set_xticks([])
                ax.set_yticks([])
                continue

            ax.plot(
                xs,
                ys,
                color=line_color,
                linewidth=1.6,
                marker="o",
                markersize=5,
                markerfacecolor=marker_color,
                markeredgecolor=marker_color,
            )
            # Worst-case marker — pulled from `worst_per_metric`
            # so we annotate the exact corner the aggregator
            # selected, which may differ from the local
            # max in the chart's metric (e.g. when a metric was
            # tied across the band).
            worst_bp = banded.worst(accessor)
            if worst_bp is not None and worst_bp.result is not None:
                worst_v = self._read(worst_bp, accessor)
                if worst_v is not None:
                    ax.scatter(
                        [worst_bp.fsw_kHz],
                        [worst_v * scale],
                        color=warn_color,
                        s=70,
                        zorder=5,
                        edgecolor=p.surface,
                        linewidth=1.2,
                        label="worst",
                    )

            ax.set_title(f"{label} [{units}]", fontsize=9, color=p.text)
            ax.set_xlabel("fsw [kHz]", fontsize=8, color=p.text_secondary)
            ax.tick_params(colors=p.text_muted, labelsize=7)
            ax.grid(True, color=p.border, linewidth=0.4, alpha=0.6)
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
            for spine in ("left", "bottom"):
                ax.spines[spine].set_color(p.border)

        self._figure.set_facecolor(p.surface)
        for ax in axes:
            ax.set_facecolor(p.surface)
        self._canvas.draw_idle()

    def clear(self) -> None:
        self._pending_banded = None
        if self._canvas_built:
            self._render_empty()
        self._caption.setText("")

    # ------------------------------------------------------------------
    @staticmethod
    def _read(bp: BandPoint, accessor: str) -> Optional[float]:
        if bp.result is None:
            return None
        v = getattr(bp.result, accessor, None)
        if v is None and hasattr(bp.result, "losses"):
            v = getattr(bp.result.losses, accessor, None)
        if not isinstance(v, (int, float)):
            return None
        import math

        if not math.isfinite(v):
            return None
        return float(v)

    def _render_empty(self, *, message: str = "No band evaluated yet.") -> None:
        assert self._figure is not None and self._canvas is not None
        self._figure.clear()
        ax = self._figure.add_subplot(111)
        p = get_theme().palette
        ax.text(
            0.5,
            0.5,
            message,
            ha="center",
            va="center",
            color=p.text_muted,
            transform=ax.transAxes,
            fontsize=10,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_facecolor(p.surface)
        self._figure.set_facecolor(p.surface)
        self._canvas.draw_idle()

    def _refresh_theme(self) -> None:
        # Theme toggle — re-render with the current palette so
        # the chart flips colours together with the rest of the
        # app. Without this hook the canvas keeps the original-
        # theme background until the next ``show_band`` call.
        if self._canvas_built:
            self._render_empty()
