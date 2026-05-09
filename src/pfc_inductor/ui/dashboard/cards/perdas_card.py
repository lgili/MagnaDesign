"""Losses card — horizontal stacked bar with inline legend.

Replaces the v2 ``DonutChart + DataTable`` body, which couldn't render
clearly in the bottom-strip column width (~155 px). The new
``HorizontalStackedBar`` reads at any width down to ~180 px and brings
total + per-segment value/percent together in a single, compact block.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QVBoxLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.theme import get_theme
from pfc_inductor.ui.widgets import Card, HorizontalStackedBar
from pfc_inductor.ui.widgets.stacked_bar import Segment


class _PerdasBody(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        sp = get_theme().spacing
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(sp.compact_gap)

        self._bar = HorizontalStackedBar(
            total_format="{:.2f}",
            total_caption="W Total",
            unit="W",
        )
        v.addWidget(self._bar, 1)

    def update_from_design(
        self, result: DesignResult, spec: Spec, core: Core, wire: Wire, material: Material
    ) -> None:
        p = get_theme().palette
        losses = result.losses
        # Segment colours pinned to semantic palette tokens so the bar
        # reads consistently in both themes.
        # 4-segment split — Cu DC / Cu AC / Core @ line (60 Hz) /
        # Core @ ripple (fsw). Previously collapsed into 3 ("Core"
        # was P_core_total), which hid the engineer's most
        # diagnostic loss split: low-frequency hysteresis-ish core
        # losses vs switching-ripple losses.
        self._bar.set_segments(
            [
                Segment("Cu DC", losses.P_cu_dc_W, p.data_series_1),
                Segment("Cu AC", losses.P_cu_ac_W, p.data_series_2),
                Segment("Core @ line", losses.P_core_line_W, p.data_series_3),
                Segment("Core @ ripple", losses.P_core_ripple_W, p.copper_bright),
            ]
        )

    def clear(self) -> None:
        self._bar.set_segments([])


class PerdasCard(Card):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _PerdasBody()
        super().__init__("Losses", body, parent=parent)
        self._pbody = body

    def update_from_design(self, *args, **kwargs) -> None:
        self._pbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._pbody.clear()
