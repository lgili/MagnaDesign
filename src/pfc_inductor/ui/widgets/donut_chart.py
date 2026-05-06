"""``DonutChart`` — small matplotlib pie with centre total.

Wraps ``FigureCanvasQTAgg`` (no toolbar). Used by the Perdas card and
anywhere a 3- or 4-segment composition needs to be shown densely.
"""
from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtWidgets import QVBoxLayout, QWidget

from pfc_inductor.ui.theme import get_theme, on_theme_changed

# Lazy-import matplotlib so test discovery doesn't pay the cost.
def _figure_imports():
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
    from matplotlib.figure import Figure
    return Canvas, Figure


# (label, value, color) — color may be ``None`` to use a defaulted palette.
Segment = tuple[str, float, Optional[str]]


class DonutChart(QWidget):
    """Donut chart with a centre label."""

    def __init__(
        self,
        segments: Optional[Sequence[Segment]] = None,
        *,
        centre_total_format: str = "{:.1f}",
        centre_caption: str = "Total",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        Canvas, Figure = _figure_imports()
        p = get_theme().palette
        self._fig = Figure(figsize=(2.4, 2.4), dpi=100,
                           facecolor=p.surface, tight_layout=True)
        self._ax = self._fig.add_subplot(1, 1, 1)
        self._canvas = Canvas(self._fig)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._canvas)

        self._centre_total_format = centre_total_format
        self._centre_caption = centre_caption
        self._segments: list[Segment] = []
        self.set_segments(segments or [])
        on_theme_changed(self._refresh_palette)

    def _refresh_palette(self) -> None:
        """Re-render so axes/labels pick up the new palette."""
        p = get_theme().palette
        self._fig.set_facecolor(p.surface)
        self._render()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_segments(self, segments: Sequence[Segment]) -> None:
        self._segments = list(segments)
        self._render()

    def total(self) -> float:
        return sum(v for _, v, _ in self._segments)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _render(self) -> None:
        p = get_theme().palette
        self._ax.clear()
        self._ax.set_facecolor(p.surface)
        if not self._segments:
            self._canvas.draw_idle()
            return

        labels = [s[0] for s in self._segments]
        values = [max(0.0, s[1]) for s in self._segments]
        # Default colours from the palette (semantic palette wraps around).
        default_colors = [p.accent, p.warning, p.success, p.info, p.danger]
        colors = [
            (s[2] if s[2] is not None else default_colors[i % len(default_colors)])
            for i, s in enumerate(self._segments)
        ]
        if sum(values) <= 0:
            self._canvas.draw_idle()
            return

        # ``ax.pie`` returns ``(wedges, texts)`` when no autopct is given,
        # ``(wedges, texts, autotexts)`` when one is given. We always omit
        # autopct, so unpack just the first two.
        pie_out = self._ax.pie(
            values, colors=colors, startangle=90,
            wedgeprops={
                "width": 0.30,         # donut hole
                "edgecolor": p.surface,
                "linewidth": 1.5,
            },
        )
        wedges = pie_out[0]
        # Centre label.
        total = sum(values)
        self._ax.text(
            0, 0.06, self._centre_total_format.format(total),
            ha="center", va="center",
            fontsize=14, fontweight="bold", color=p.text,
        )
        self._ax.text(
            0, -0.18, self._centre_caption,
            ha="center", va="center",
            fontsize=9, color=p.text_muted,
        )
        # Compact legend below the donut.
        self._ax.legend(
            wedges, [f"{l}  {v:.1f}" for l, v in zip(labels, values)],
            loc="lower center", bbox_to_anchor=(0.5, -0.18),
            frameon=False, fontsize=8, ncols=min(3, len(labels)),
            labelcolor=p.text_secondary,
        )
        self._ax.axis("equal")
        self._canvas.draw_idle()
