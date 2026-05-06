"""Perdas card — donut + small breakdown table."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout

from pfc_inductor.models import Spec, Material, Core, Wire, DesignResult
from pfc_inductor.ui.widgets import Card, DonutChart, DataTable
from pfc_inductor.ui.theme import get_theme


class _PerdasBody(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        self._donut = DonutChart(centre_caption="W Total")
        self._table = DataTable(striped=False)
        v.addWidget(self._donut, 1)
        v.addWidget(self._table)

    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        p = get_theme().palette
        l = result.losses
        segments = [
            ("DC", l.P_cu_dc_W, p.accent),
            ("AC", l.P_cu_ac_W, p.warning),
            ("Núcleo", l.P_core_total_W, p.copper),
        ]
        self._donut.set_segments(segments)

        total = l.P_total_W or 1e-9
        rows = [
            ("Cu DC", f"{l.P_cu_dc_W:.2f}", f"W ({100*l.P_cu_dc_W/total:.0f}%)"),
            ("Cu AC", f"{l.P_cu_ac_W:.2f}", f"W ({100*l.P_cu_ac_W/total:.0f}%)"),
            ("Núcleo", f"{l.P_core_total_W:.2f}",
             f"W ({100*l.P_core_total_W/total:.0f}%)"),
        ]
        self._table.set_rows(rows)

    def clear(self) -> None:
        self._donut.set_segments([])
        self._table.set_rows([])


class PerdasCard(Card):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _PerdasBody()
        super().__init__("Perdas", body, parent=parent)
        self._pbody = body

    def update_from_design(self, *args, **kwargs) -> None:
        self._pbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._pbody.clear()
