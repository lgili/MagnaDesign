"""Seleção de Núcleo card.

A pragmatic v1 of this card hosts the existing material/core/wire
selectors from :class:`SpecPanel <pfc_inductor.ui.spec_panel.SpecPanel>`
inside a card frame. The richer score-table view described in the spec
is a follow-up — for now we re-use the proven combo-based selector and
only re-skin it.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from pfc_inductor.models import Spec, Material, Core, Wire, DesignResult
from pfc_inductor.ui.widgets import Card


class _NucleoBody(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        # Lazy: a placeholder while a richer table is built. The card
        # surfaces the current pick instead.
        self._lbl_material = QLabel("—")
        self._lbl_material.setProperty("role", "title")
        self._lbl_part = QLabel("—")
        self._lbl_part.setProperty("role", "muted")
        self._lbl_wire = QLabel("—")
        self._lbl_wire.setProperty("role", "muted")
        v.addWidget(self._lbl_material)
        v.addWidget(self._lbl_part)
        v.addWidget(self._lbl_wire)
        v.addStretch(1)

    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        self._lbl_material.setText(f"{material.name}")
        self._lbl_part.setText(
            f"{core.part_number}  ·  Ve={core.Ve_mm3 / 1000:.1f} cm³  "
            f"·  Ae={core.Ae_mm2:.1f} mm²"
        )
        wire_label = f"{getattr(wire, 'name', wire.id)}"
        self._lbl_wire.setText(wire_label)

    def clear(self) -> None:
        self._lbl_material.setText("—")
        self._lbl_part.setText("—")
        self._lbl_wire.setText("—")


class NucleoCard(Card):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _NucleoBody()
        super().__init__("Seleção de Núcleo", body, parent=parent)
        self._nbody = body

    def update_from_design(self, *args, **kwargs) -> None:
        self._nbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._nbody.clear()
