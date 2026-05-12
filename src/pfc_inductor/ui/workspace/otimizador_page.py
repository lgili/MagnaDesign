"""Otimizador workspace page.

Hosts :class:`OptimizerEmbed
<pfc_inductor.ui.optimize_dialog.OptimizerEmbed>` directly — no modal.
The Pareto sweep + ranked table + "Aplicar selecionado" button are
the entire page; the engineer can run sweeps, inspect candidates and
apply choices without leaving the workspace.

The page is **stateless on construction**: the embed starts in
"empty" mode (run button disabled, prompt to compute first). The host
(``MainWindow``) calls :meth:`set_inputs` after every successful
``_on_calculate`` so the optimizer always reflects the latest spec
and catalog.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, Material, Spec, Wire
from pfc_inductor.ui.optimize_dialog import OptimizerEmbed
from pfc_inductor.ui.widgets import Card


class OtimizadorPage(QWidget):
    """Sidebar destination for the optimizer."""

    selection_applied = Signal(str, str, str)  # material_id, core_id, wire_id
    compare_requested = Signal(list)  # list[SweepResult] — forwarded from embed

    # Kept for back-compat with v3.0 wiring; emitted by no widget but
    # still re-exported as a no-op so consumers that connect to it
    # continue to compile.
    open_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)  # header runs edge-to-edge
        outer.setSpacing(0)

        from pfc_inductor.ui.shell.page_header import WorkspacePageHeader

        outer.addWidget(
            WorkspacePageHeader(
                "Optimizer",
                "Pareto sweep — multi-objective core × material × wire "
                "exploration (loss, volume, cost).",
            )
        )

        body = QFrame()
        body_v = QVBoxLayout(body)
        body_v.setContentsMargins(24, 16, 24, 24)
        body_v.setSpacing(12)
        outer.addWidget(body, 1)

        # Embedded optimizer body — same widget the modal dialog wraps.
        self._embed = OptimizerEmbed()
        self._embed.selection_applied.connect(self.selection_applied.emit)
        # Forward the multi-row Compare request up to the host
        # (MainWindow). The optimizer itself never owns the Compare
        # dialog — that's a workspace-level concern handled by the
        # global CompareDialog.
        self._embed.compare_requested.connect(self.compare_requested.emit)

        embed_holder = QFrame()
        v = QVBoxLayout(embed_holder)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._embed)
        # English label — matches the page header ("Optimizer") so the
        # heading and the card title speak the same language. The
        # earlier mixed-language ("Pareto sweep multi-objetivo")
        # was a translation oversight from the v3 page rebuild.
        body_v.addWidget(Card("Multi-objective Pareto sweep", embed_holder), 1)

    # ------------------------------------------------------------------
    def set_inputs(
        self,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        current_material_id: str = "",
    ) -> None:
        """Forward to the embed. Called by the host after recompute."""
        self._embed.set_inputs(
            spec,
            materials,
            cores,
            wires,
            current_material_id,
        )
