"""Bobinamento card — compact data table of winding facts."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout

from pfc_inductor.models import Spec, Material, Core, Wire, DesignResult
from pfc_inductor.ui.widgets import Card, DataTable


class _BobinamentoBody(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self._table = DataTable()
        v.addWidget(self._table)

    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        # Wire info — accept partial fields gracefully (legacy DBs).
        awg = getattr(wire, "AWG", None) or getattr(wire, "awg", None) or "—"
        d_mm = getattr(wire, "OD_mm", None) or getattr(wire, "diameter_mm", None) or 0.0
        strands = getattr(wire, "strands", 1) or 1
        rows = [
            ("Espiras (N)", f"{result.N_turns}", None),
            ("Preenchimento", f"{result.Ku_actual * 100:.1f}", "%"),
            ("AWG", str(awg), None),
            ("Diâmetro fio", f"{d_mm:.3f}" if isinstance(d_mm, (int, float)) else str(d_mm), "mm"),
            ("Estrandes", f"{strands}", None),
            ("R_DC", f"{result.R_dc_ohm * 1000:.1f}", "mΩ"),
            ("R_AC@fsw", f"{result.R_ac_ohm * 1000:.1f}", "mΩ"),
        ]
        self._table.set_rows(rows)

    def clear(self) -> None:
        self._table.set_rows([])


class BobinamentoCard(Card):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _BobinamentoBody()
        super().__init__("Bobinamento", body, parent=parent)
        self._bbody = body

    def update_from_design(self, *args, **kwargs) -> None:
        self._bbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._bbody.clear()
