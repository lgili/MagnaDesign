"""Topologia Selecionada card.

Top: schematic placeholder (a real ``TopologySchematicWidget`` is provided
by :mod:`pfc_inductor.ui.widgets.schematic` once
``add-topology-schematic-card`` lands; until then the card shows a
caption stating the topology name).

Below the schematic: 4 pills summarising the topology — type
(active/passive), output power, switching frequency, and compliance.

Footer: an "Alterar Topologia" secondary button (hidden behind the
``topology_change_requested`` signal so the parent page can decide what
to do — e.g. open a topology picker dialog).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QSizePolicy,
)

from pfc_inductor.models import Spec, Material, Core, Wire, DesignResult
from pfc_inductor.ui.widgets import Card, TopologySchematicWidget
from pfc_inductor.ui.theme import get_theme, on_theme_changed


_TOPOLOGY_LABELS = {
    "boost_ccm":     "Boost CCM Active",
    "passive_choke": "Passive PFC Choke",
    "line_reactor":  "Line Reactor",
}


class _TopologyBody(QWidget):
    topology_change_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # ---- schematic ------------------------------------------------
        self._schematic = TopologySchematicWidget()
        v.addWidget(self._schematic)
        # The placeholder caption stays around for empty state.
        self._schematic_caption = QLabel("")
        self._schematic_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._schematic_caption.setProperty("role", "muted")
        self._schematic_caption.setVisible(False)
        v.addWidget(self._schematic_caption)

        # ---- pills row ------------------------------------------------
        row = QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(0, 0, 0, 0)
        self._pills = [self._make_pill("—", "neutral") for _ in range(4)]
        for pl in self._pills:
            row.addWidget(pl)
        row.addStretch(1)
        v.addLayout(row)

        # ---- footer button -------------------------------------------
        self._btn_change = QPushButton("Alterar Topologia")
        self._btn_change.setProperty("class", "Secondary")
        self._btn_change.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_change.clicked.connect(self.topology_change_requested.emit)
        v.addWidget(self._btn_change, 0, Qt.AlignmentFlag.AlignLeft)

    # ------------------------------------------------------------------
    def schematic_widget(self) -> "TopologySchematicWidget":
        """Expose the embedded schematic for tests / wiring."""
        return self._schematic

    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        topo_label = _TOPOLOGY_LABELS.get(spec.topology, spec.topology)
        # Map Spec.topology to schematic key, picking 3ph variant when
        # the spec asks for it.
        sch_key = spec.topology
        if spec.topology == "line_reactor":
            sch_key = "line_reactor_3ph" if getattr(spec, "n_phases", 1) == 3 \
                      else "line_reactor_1ph"
        try:
            self._schematic.set_topology(sch_key)
        except ValueError:
            pass

        if spec.topology == "boost_ccm":
            f_label = f"{spec.f_sw_kHz:.0f} kHz"
        else:
            f_label = f"{spec.f_line_Hz:.0f} Hz"
        # Active power proxy. ``Pout_W`` is the canonical power field —
        # for a line reactor it represents the rated load power.
        pwr_w = spec.Pout_W
        if pwr_w >= 1000:
            pwr_label = f"{pwr_w / 1000:.1f} kW"
        else:
            pwr_label = f"{pwr_w:.0f} W"

        # Compliance status: warn ⇒ yellow, none ⇒ green.
        if result.warnings:
            compliance = ("Verificar", "warning")
        else:
            compliance = ("OK", "success")

        self._set_pill(0, topo_label, "violet")
        self._set_pill(1, pwr_label, "info")
        self._set_pill(2, f_label, "neutral")
        self._set_pill(3, compliance[0], compliance[1])

    def clear(self) -> None:
        for pl in self._pills:
            self._set_pill(self._pills.index(pl), "—", "neutral")

    # ------------------------------------------------------------------
    def _make_pill(self, text: str, variant: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("class", "Pill")
        lbl.setProperty("pill", variant)
        return lbl

    def _set_pill(self, idx: int, text: str, variant: str) -> None:
        lbl = self._pills[idx]
        lbl.setText(text)
        lbl.setProperty("pill", variant)
        st = lbl.style()
        st.unpolish(lbl)
        st.polish(lbl)

    @staticmethod
    def _slot_qss() -> str:
        p = get_theme().palette
        return (
            f"QFrame#SchematicSlot {{"
            f"  background: {p.bg};"
            f"  border: 1px dashed {p.border_strong};"
            f"  border-radius: 12px;"
            f"  min-height: 120px;"
            f"}}"
        )


class TopologiaCard(Card):
    """Top-row card showing the active topology + key spec pills."""

    topology_change_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _TopologyBody()
        super().__init__("Topologia Selecionada", body, parent=parent)
        # Connect the inner-body signal AFTER ``super().__init__`` so the
        # outer ``QObject`` (this Card / QFrame) is fully initialised and
        # the Python wrapper for ``self.topology_change_requested`` is
        # alive.
        body.topology_change_requested.connect(self.topology_change_requested.emit)
        self._tbody = body

    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        self._tbody.update_from_design(result, spec, core, wire, material)

    def clear(self) -> None:
        self._tbody.clear()

    def schematic_widget(self):
        return self._tbody.schematic_widget()
