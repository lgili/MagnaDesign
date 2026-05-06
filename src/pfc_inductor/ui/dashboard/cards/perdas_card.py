"""Perdas card — horizontal stacked bar with inline legend.

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


class _PerdasBody(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        self._bar = HorizontalStackedBar(
            total_format="{:.2f}",
            total_caption="W Total",
            unit="W",
        )
        v.addWidget(self._bar, 1)

    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        p = get_theme().palette
        losses = result.losses
        # Segment colours pinned to semantic palette tokens so the bar
        # reads consistently in both themes.
        self._bar.set_segments([
            ("Cu DC", losses.P_cu_dc_W, p.accent),
            ("Cu AC", losses.P_cu_ac_W, p.warning),
            ("Núcleo", losses.P_core_total_W, p.copper),
        ])

    def clear(self) -> None:
        self._bar.set_segments([])


class PerdasCard(Card):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _PerdasBody()
        super().__init__("Perdas", body, parent=parent)
        self._pbody = body

    def update_from_design(self, *args, **kwargs) -> None:
        self._pbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._pbody.clear()
