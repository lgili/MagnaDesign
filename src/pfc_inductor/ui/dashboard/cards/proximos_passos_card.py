"""Próximos Passos card — actionable workflow next-steps."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from pfc_inductor.models import Spec, Material, Core, Wire, DesignResult
from pfc_inductor.ui.widgets import (
    Card, NextStepsCard, ActionItem, ActionStatus,
)


def _wire_kind(wire: Wire) -> str:
    return getattr(wire, "kind", "round")


class ProximosPassosCard(Card):
    """Wraps :class:`NextStepsCard` with a fixed list of workflow actions.

    The parent dashboard provides the action callbacks via :meth:`set_callbacks`.
    Status is recomputed from the current design context whenever
    :meth:`update_from_design` is called.
    """

    fea_requested = Signal()
    compare_requested = Signal()
    litz_requested = Signal()
    report_requested = Signal()
    similar_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        self._steps_widget = NextStepsCard()
        super().__init__("Próximos Passos", self._steps_widget, parent=parent)

        # Default state: every action "todo".
        self._actions: dict[str, ActionStatus] = {
            "fea": "todo",
            "compare": "todo",
            "litz": "todo",
            "report": "todo",
            "similar": "todo",
        }
        self._refresh()

    # ------------------------------------------------------------------
    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        # Litz step is "done" if a Litz wire is selected, otherwise
        # "pending" (until the user touches it).
        kind = _wire_kind(wire)
        self._actions["litz"] = "done" if kind == "litz" else "pending"
        self._refresh()

    def mark_step_done(self, key: str) -> None:
        """Public hook so the parent can mark e.g. ``"report"`` done
        after the user generates a datasheet."""
        if key in self._actions:
            self._actions[key] = "done"
            self._refresh()

    def clear(self) -> None:
        for k in self._actions:
            self._actions[k] = "todo"
        self._refresh()

    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        items = [
            ActionItem("Validar com FEM",
                       self._actions["fea"], self.fea_requested.emit),
            ActionItem("Comparar com alternativos",
                       self._actions["compare"], self.compare_requested.emit),
            ActionItem("Otimizar Litz",
                       self._actions["litz"], self.litz_requested.emit),
            ActionItem("Buscar similares",
                       self._actions["similar"], self.similar_requested.emit),
            ActionItem("Gerar relatório",
                       self._actions["report"], self.report_requested.emit),
        ]
        self._steps_widget.set_items(items)
