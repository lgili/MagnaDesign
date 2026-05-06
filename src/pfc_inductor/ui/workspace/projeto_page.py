"""Projeto workspace page — SpecDrawer + tab strip + Scoreboard.

Layout:

    +----------+----------+-------------------------+
    | sidebar  | SpecDrwr | header                  |
    | (extern) | (drawer) +-------------------------+
    |          |          | ProgressIndicator       |
    |          |          +-------------------------+
    |          |          | [Design][Validar][Exportar]
    |          |          +-------------------------+
    |          |          | tab content             |
    |          |          +-------------------------+
    |          |          | Scoreboard              |
    +----------+----------+-------------------------+

Only the right side (everything from the header down) is owned here;
the sidebar is mounted by ``MainWindow``. The drawer **is** owned here
because it is conceptually part of the *project workspace* — it
disappears when the user navigates to Otimizador / Catálogo /
Configurações.
"""
from __future__ import annotations

from typing import Literal, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.dashboard import DashboardPage
from pfc_inductor.ui.shell.progress_indicator import ProgressIndicator, StepKey
from pfc_inductor.ui.shell.scoreboard import Scoreboard
from pfc_inductor.ui.shell.spec_drawer import SpecDrawer
from pfc_inductor.ui.shell.header import WorkspaceHeader
from pfc_inductor.ui.theme import get_theme, on_theme_changed


TabKey = Literal["design", "validar", "exportar"]


class ProjetoPage(QWidget):
    """Main project workspace page."""

    # Bubble-up signals (the page itself does not own dialog plumbing).
    recalculate_requested = Signal()
    compare_requested = Signal()
    report_requested = Signal()
    name_changed = Signal(str)
    topology_change_requested = Signal()
    fea_requested = Signal()
    bh_loop_requested = Signal()
    similar_requested = Signal()
    litz_requested = Signal()
    export_html_requested = Signal()
    export_compare_requested = Signal()
    selection_applied = Signal(str, str, str)  # material_id, core_id, wire_id

    def __init__(
        self,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- Spec drawer (left) ---------------------------------------
        self.drawer = SpecDrawer(materials, cores, wires)
        self.drawer.calculate_requested.connect(self.recalculate_requested.emit)
        self.drawer.topology_change_requested.connect(
            self.topology_change_requested.emit,
        )
        outer.addWidget(self.drawer)

        # ---- Workspace column (header + progress + tabs + scoreboard) -
        column = QFrame()
        column.setObjectName("ProjetoColumn")
        col_v = QVBoxLayout(column)
        col_v.setContentsMargins(0, 0, 0, 0)
        col_v.setSpacing(0)

        # Header
        self.header = WorkspaceHeader(parent=column)
        self.header.compare_requested.connect(self.compare_requested.emit)
        self.header.report_requested.connect(self._on_report_pressed)
        self.header.recalculate_requested.connect(self.recalculate_requested.emit)
        self.header.name_changed.connect(self.name_changed.emit)
        col_v.addWidget(self.header)

        # Progress
        self.progress = ProgressIndicator(parent=column)
        col_v.addWidget(self.progress)

        # Tabs
        self.tabs = QTabWidget(parent=column)
        self.tabs.setDocumentMode(True)
        col_v.addWidget(self.tabs, 1)

        # Lazy import so circular routes resolve.
        from pfc_inductor.ui.workspace.validar_tab import ValidarTab
        from pfc_inductor.ui.workspace.exportar_tab import ExportarTab

        # Tab 0 — Design (the slim DashboardPage)
        self.design_tab = DashboardPage()
        self.design_tab.fea_requested.connect(self.fea_requested.emit)
        self.design_tab.compare_requested.connect(self.compare_requested.emit)
        self.design_tab.litz_requested.connect(self.litz_requested.emit)
        self.design_tab.report_requested.connect(self._on_report_pressed)
        self.design_tab.similar_requested.connect(self.similar_requested.emit)
        # ``card_nucleo`` may not exist if DashboardPage hasn't been
        # initialised yet — its lifecycle uses the deferred
        # ``_apply_palette_bg``. Connect when the attribute appears.
        if hasattr(self.design_tab, "card_nucleo"):
            self.design_tab.card_nucleo.selection_applied.connect(
                self.selection_applied.emit,
            )
        self.tabs.addTab(self.design_tab, "Design")

        # Tab 1 — Validar
        self.validar_tab = ValidarTab()
        self.validar_tab.fea_requested.connect(self.fea_requested.emit)
        self.validar_tab.bh_loop_requested.connect(self.bh_loop_requested.emit)
        self.validar_tab.compare_requested.connect(self.compare_requested.emit)
        self.tabs.addTab(self.validar_tab, "Validar")

        # Tab 2 — Exportar
        self.exportar_tab = ExportarTab()
        self.exportar_tab.export_html_requested.connect(
            self.export_html_requested.emit,
        )
        self.exportar_tab.export_compare_requested.connect(
            self.export_compare_requested.emit,
        )
        self.tabs.addTab(self.exportar_tab, "Exportar")

        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Scoreboard
        self.scoreboard = Scoreboard(parent=column)
        self.scoreboard.recalculate_requested.connect(
            self.recalculate_requested.emit,
        )
        col_v.addWidget(self.scoreboard)

        outer.addWidget(column, 1)

        # Initial state: Design current, Spec done (the user has spec
        # input visible, so it's "done" by virtue of being filled).
        self.progress.set_done({"spec"})
        self.progress.set_current("design")

        on_theme_changed(self._refresh_qss)
        self._refresh_qss()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def spec_panel(self):
        """Bare SpecPanel for back-compat with controllers expecting it."""
        return self.drawer.spec_panel

    def set_project_name(self, name: str) -> None:
        self.header.set_project_name(name)

    def set_save_status(self, *, unsaved, last_saved_at=None) -> None:
        self.header.set_save_status(unsaved=unsaved, last_saved_at=last_saved_at)
        self.scoreboard.set_save_status(
            unsaved=unsaved, last_saved_at=last_saved_at,
        )

    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        self.design_tab.update_from_design(result, spec, core, wire, material)
        self.validar_tab.update_from_design(result, spec, core, wire, material)
        self.exportar_tab.update_from_design(result, spec, core, wire, material)
        self.scoreboard.update_from_result(result, spec)
        # Mark Design done once a result is available.
        self.progress.mark_done("design")

    def populate_nucleo(
        self,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        material: Material,
        core: Core,
        wire: Wire,
    ) -> None:
        if hasattr(self.design_tab, "card_nucleo"):
            self.design_tab.card_nucleo.populate(
                spec, materials, cores, wires, material, core, wire,
            )

    def switch_to(self, key: TabKey) -> None:
        idx = {"design": 0, "validar": 1, "exportar": 2}[key]
        self.tabs.setCurrentIndex(idx)

    def mark_action_done(self, key: str) -> None:
        if hasattr(self.design_tab, "mark_action_done"):
            self.design_tab.mark_action_done(key)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _on_tab_changed(self, idx: int) -> None:
        if idx == 0:
            self.progress.set_current("design")
        elif idx == 1:
            self.progress.set_current("validar")
            self.progress.mark_done("design")
        elif idx == 2:
            self.progress.set_current("exportar")
            self.progress.mark_done("design")
            self.progress.mark_done("validar")

    def _on_report_pressed(self) -> None:
        # Header / dashboard "Gerar Relatório" button: instead of going
        # straight to the file dialog, switch to Exportar so the user
        # sees what they're about to export.
        self.switch_to("exportar")
        self.report_requested.emit()

    def _refresh_qss(self) -> None:
        p = get_theme().palette
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ background: {p.bg};"
            f"  border: 0; border-top: 1px solid {p.border}; }}"
        )
