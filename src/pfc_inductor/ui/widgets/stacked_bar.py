"""``HorizontalStackedBar`` — narrow horizontal proportion bar.

A purpose-built replacement for ``DonutChart`` when the card column is
too narrow for a circular pie to read clearly. Renders a single
horizontal bar split into N coloured segments, with a legend below
listing each segment's label, value, and percentage.

Designed to look right at any width from ~180 px upward — uses
``QFrame`` rectangles tinted by inline QSS instead of matplotlib so
there is no fixed ``figsize`` to fight with the parent layout.
"""
from __future__ import annotations

import math
from typing import NamedTuple, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.ui.theme import get_theme, on_theme_changed


class Segment(NamedTuple):
    """One coloured slice of the stacked bar.

    Named so callers stop indexing into anonymous 3-tuples
    (``seg[0]`` vs ``seg.label``). Tuple unpacking still works for the
    legacy callsites that destructure ``(label, value, color)``.
    """
    label: str
    value: float
    color: Optional[str] = None


class HorizontalStackedBar(QWidget):
    """Horizontal stacked bar + label/value/percent legend.

    Use when a 3- or 4-segment composition needs to be shown in a
    narrow card column. Total is rendered as a small caption above the
    bar; the bar itself is a fixed 12 px tall track with rounded ends.
    """

    BAR_HEIGHT = 12

    def __init__(
        self,
        segments: Optional[Sequence[Segment]] = None,
        *,
        total_format: str = "{:.2f}",
        total_caption: str = "Total",
        unit: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)
        self._total_format = total_format
        self._total_caption = total_caption
        self._unit = unit
        self._segments: list[Segment] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # ---- header row: total + caption ------------------------------
        self._header_row = QHBoxLayout()
        self._header_row.setContentsMargins(0, 0, 0, 0)
        self._header_row.setSpacing(6)
        self._lbl_total = QLabel("—")
        self._lbl_total.setObjectName("StackedBarTotal")
        self._lbl_unit = QLabel(unit)
        self._lbl_unit.setProperty("role", "muted")
        self._lbl_caption = QLabel(total_caption)
        self._lbl_caption.setProperty("role", "caption")
        self._header_row.addWidget(self._lbl_total, 0, Qt.AlignmentFlag.AlignBaseline)
        self._header_row.addWidget(self._lbl_unit, 0, Qt.AlignmentFlag.AlignBaseline)
        self._header_row.addStretch(1)
        self._header_row.addWidget(self._lbl_caption, 0, Qt.AlignmentFlag.AlignBaseline)
        outer.addLayout(self._header_row)

        # ---- the bar itself -------------------------------------------
        self._track = QFrame()
        self._track.setFixedHeight(self.BAR_HEIGHT)
        self._track.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Fixed)
        self._track_lay = QHBoxLayout(self._track)
        self._track_lay.setContentsMargins(0, 0, 0, 0)
        self._track_lay.setSpacing(0)
        outer.addWidget(self._track)

        # ---- legend grid (label · pct · value) ------------------------
        self._legend_holder = QWidget()
        self._legend = QGridLayout(self._legend_holder)
        self._legend.setContentsMargins(0, 0, 0, 0)
        self._legend.setHorizontalSpacing(10)
        self._legend.setVerticalSpacing(4)
        self._legend.setColumnStretch(0, 0)  # swatch
        self._legend.setColumnStretch(1, 1)  # label
        self._legend.setColumnStretch(2, 0)  # value
        self._legend.setColumnStretch(3, 0)  # pct
        outer.addWidget(self._legend_holder)

        self._refresh_styles()
        self.set_segments(segments or [])
        on_theme_changed(self._refresh_styles)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_segments(self, segments: Sequence[Segment]) -> None:
        self._segments = list(segments)
        self._render()

    def total(self) -> float:
        return sum(max(0.0, v) for _, v, _ in self._segments)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _render(self) -> None:
        # --- bar ---
        # Clear existing segments
        while self._track_lay.count():
            item = self._track_lay.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.setParent(None)
        # Clear legend
        while self._legend.count():
            item = self._legend.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.setParent(None)

        p = get_theme().palette
        total = self.total()
        # Treat non-finite or absurd magnitudes (> 100 kW for power
        # bars, the only caller today) as "no valid data" — the engine
        # can spit nonsense for an uninitialised spec and the user
        # would see a 7-digit total before any real design ran.
        if total <= 0 or not math.isfinite(total) or total > 1e5:
            self._lbl_total.setText("—")
            # Empty track placeholder so the bar doesn't disappear.
            ph = QFrame()
            ph.setStyleSheet(
                f"background:{p.bg}; border-radius:{self.BAR_HEIGHT // 2}px;"
            )
            self._track_lay.addWidget(ph, 1)
            return

        self._lbl_total.setText(self._total_format.format(total))
        default_colors = [p.accent, p.warning, p.success, p.info, p.danger]

        # Render bar segments; round ends only on the outer edges.
        n = len(self._segments)
        for i, (_label, value, color) in enumerate(self._segments):
            v_clamped = max(0.0, value)
            if v_clamped <= 0:
                continue
            seg = QFrame()
            seg_color = color if color is not None else default_colors[i % len(default_colors)]
            radius_l = self.BAR_HEIGHT // 2 if i == 0 else 0
            radius_r = self.BAR_HEIGHT // 2 if i == n - 1 else 0
            seg.setStyleSheet(
                f"background:{seg_color};"
                f"border-top-left-radius:{radius_l}px;"
                f"border-bottom-left-radius:{radius_l}px;"
                f"border-top-right-radius:{radius_r}px;"
                f"border-bottom-right-radius:{radius_r}px;"
            )
            # Stretch is proportional to the value — Qt's int stretch
            # rounds down, so multiply by 1000 to keep precision.
            self._track_lay.addWidget(seg, max(1, int(v_clamped / total * 1000)))

        # Render legend
        t = get_theme().type
        for row, (label, value, color) in enumerate(self._segments):
            seg_color = color if color is not None else default_colors[row % len(default_colors)]
            swatch = QFrame()
            swatch.setFixedSize(8, 8)
            swatch.setStyleSheet(f"background:{seg_color}; border-radius:2px;")
            # Centre-align the swatch with the label baseline.
            swatch_wrap = QWidget()
            sw_l = QHBoxLayout(swatch_wrap)
            sw_l.setContentsMargins(0, 4, 0, 4)
            sw_l.addWidget(swatch, 0, Qt.AlignmentFlag.AlignVCenter)

            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"color:{p.text_secondary}; font-size:{t.body}px;"
            )
            val = QLabel(self._total_format.format(value))
            val.setStyleSheet(
                f"color:{p.text}; font-size:{t.body_md}px;"
                f" font-family:{t.numeric_family}; font-weight:{t.semibold};"
            )
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            pct_text = (
                f"{100.0 * max(0.0, value) / total:.0f}%"
                if total > 0 else "—"
            )
            pct = QLabel(pct_text)
            pct.setStyleSheet(
                f"color:{p.text_muted}; font-size:{t.caption}px;"
            )
            self._legend.addWidget(swatch_wrap, row, 0)
            self._legend.addWidget(lbl, row, 1)
            self._legend.addWidget(val, row, 2)
            self._legend.addWidget(pct, row, 3)

    def _refresh_styles(self) -> None:
        p = get_theme().palette
        t = get_theme().type
        # Total face: large monospace numeric for parity with MetricCard.
        self._lbl_total.setStyleSheet(
            f"color:{p.text}; font-size:{t.title_lg + 2}px;"
            f" font-family:{t.numeric_family}; font-weight:{t.bold};"
        )
        # Bar track background acts as the "rest" segment when total is 0.
        self._track.setStyleSheet(
            f"background:{p.bg}; border-radius:{self.BAR_HEIGHT // 2}px;"
        )
        # Re-render so segment QSS uses the latest palette.
        self._render()
