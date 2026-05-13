"""Next Steps card — actionable workflow next-steps."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from pfc_inductor.models import Core, DesignOverrides, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.widgets import (
    ActionItem,
    ActionStatus,
    Card,
    NextStepsCard,
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
    tweak_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        self._steps_widget = NextStepsCard()
        super().__init__("Next Steps", self._steps_widget, parent=parent)

        # Default state: every action "todo".
        self._actions: dict[str, ActionStatus] = {
            "fea": "todo",
            "compare": "todo",
            "litz": "todo",
            "report": "todo",
            "similar": "todo",
            "tweak": "todo",
        }
        # Current overrides — feeds the "Ajustar protótipo" title so the
        # user sees the active N / T_amb without opening the dialog.
        self._overrides: DesignOverrides = DesignOverrides()
        self._refresh()

    # ------------------------------------------------------------------
    def update_from_design(
        self, result: DesignResult, spec: Spec, core: Core, wire: Wire, material: Material
    ) -> None:
        # Litz step is "done" if a Litz wire is selected, otherwise
        # "pending" (until the user touches it).
        kind = _wire_kind(wire)
        self._actions["litz"] = "done" if kind == "litz" else "pending"
        self._refresh()

    def set_overrides(self, overrides: DesignOverrides) -> None:
        """Update the "Ajustar protótipo" action so its title reflects
        the currently active overrides (if any)."""
        self._overrides = overrides
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
        self._overrides = DesignOverrides()
        self._refresh()

    # ------------------------------------------------------------------
    def _tweak_title(self) -> str:
        """Build the "Ajustar protótipo" action label.

        Shows the active override summary inline ("Ajustar protótipo
        — N=32, T_amb=60 °C") so the user reads the current state at a
        glance and clicks to edit.
        """
        if self._overrides.is_empty():
            return "Ajustar protótipo"
        bits: list[str] = []
        if self._overrides.N_turns is not None:
            bits.append(f"N={self._overrides.N_turns}")
        if self._overrides.T_amb_C is not None:
            bits.append(f"T_amb={self._overrides.T_amb_C:.0f} °C")
        if self._overrides.n_stacks is not None and self._overrides.n_stacks > 1:
            bits.append(f"{self._overrides.n_stacks}× stack")
        if self._overrides.gap_mm is not None:
            bits.append(f"gap={self._overrides.gap_mm:.2f} mm")
        if self._overrides.wire_id:
            bits.append(f"fio={self._overrides.wire_id}")
        if self._overrides.core_id:
            bits.append(f"núcleo={self._overrides.core_id}")
        return "Ajustar protótipo — " + ", ".join(bits)

    def _refresh(self) -> None:
        items = [
            ActionItem(self._tweak_title(), self._actions["tweak"], self.tweak_requested.emit),
            ActionItem("Validate with FEM", self._actions["fea"], self.fea_requested.emit),
            ActionItem(
                "Compare with alternatives", self._actions["compare"], self.compare_requested.emit
            ),
            ActionItem("Optimize Litz", self._actions["litz"], self.litz_requested.emit),
            ActionItem("Find similar parts", self._actions["similar"], self.similar_requested.emit),
            ActionItem("Generate report", self._actions["report"], self.report_requested.emit),
        ]
        self._steps_widget.set_items(items)
