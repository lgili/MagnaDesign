"""Projeto workspace page — SpecDrawer + persistent KPI + 4 tabs.

Layout:

    +----------+----------+-----------------------------+
    | sidebar  | SpecDrwr | header                      |
    | (extern) | (drawer) +-----------------------------+
    |          |          | ProgressIndicator (compact) |
    |          |          +-----------------------------+
    |          |          | ResumoStrip (always visible)|
    |          |          +-----------------------------+
    |          |          | [Núcleo][Análise][Validar][Exportar]
    |          |          +-----------------------------+
    |          |          | tab content                 |
    |          |          +-----------------------------+
    |          |          | Scoreboard                  |
    +----------+----------+-----------------------------+

v3.1 redesign (replaces the v3 ``Design`` super-tab):

- **Tab 0 ``Núcleo``**: dedicated material/core/wire selection.
  Hosts both manual table-driven choice and the inline optimizer (the
  ``OtimizadorDialog`` modal is now a back-compat wrapper).
- **Tab 1 ``Análise``**: waveforms, losses, winding/gap detail. No
  selection UI — purely "how does the chosen design behave?".
- **Tab 2 ``Validar``**: FEA validation (unchanged).
- **Tab 3 ``Exportar``**: datasheet / report export (unchanged).

The ``ResumoStrip`` (6-tile KPI bar + aggregate badge) is mounted
above the tab widget so the engineer never loses sight of L, ΔT,
losses and the overall pass/warn/fail status while drilling into any
tab. This trades a small chunk of vertical real estate for permanent
situational awareness — the same pattern Linear / Notion / Figma use.
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
from pfc_inductor.ui.shell.header import WorkspaceHeader
from pfc_inductor.ui.shell.progress_indicator import ProgressIndicator
from pfc_inductor.ui.shell.scoreboard import Scoreboard
from pfc_inductor.ui.shell.spec_drawer import SpecDrawer
from pfc_inductor.ui.theme import get_theme, on_theme_changed
from pfc_inductor.ui.widgets import ResumoStrip
from pfc_inductor.ui.workspace.analise_page import AnalisePage
from pfc_inductor.ui.workspace.nucleo_selection_page import NucleoSelectionPage

TabKey = Literal["nucleo", "analise", "validar", "exportar"]


class ProjetoPage(QWidget):
    """Main project workspace page — 4 tabs with persistent KPI strip."""

    # Bubble-up signals (the page itself does not own dialog plumbing).
    recalculate_requested = Signal()
    compare_requested = Signal()
    report_requested = Signal()
    name_changed = Signal(str)
    topology_change_requested = Signal()
    fea_requested = Signal()
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
        self.drawer = SpecDrawer()
        self.drawer.calculate_requested.connect(self.recalculate_requested.emit)
        self.drawer.topology_change_requested.connect(
            self.topology_change_requested.emit,
        )
        outer.addWidget(self.drawer)

        # ---- Workspace column ------------------------------------------
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

        # Progress (compact 36 px strip)
        self.progress = ProgressIndicator(parent=column)
        col_v.addWidget(self.progress)

        # ---- ResumoStrip — PERSISTENT above the tabs ------------------
        # Wrapped in a slim padded frame so it visually sits on the
        # surface and not on the page bg, with subtle separator from
        # the tab strip below.
        kpi_holder = QFrame()
        kpi_holder.setObjectName("KpiHolder")
        kh = QVBoxLayout(kpi_holder)
        kh.setContentsMargins(get_theme().spacing.page,
                              get_theme().spacing.lg,
                              get_theme().spacing.page,
                              0)
        kh.setSpacing(0)
        self.kpi_strip = ResumoStrip()
        kh.addWidget(self.kpi_strip)
        col_v.addWidget(kpi_holder)

        # Tabs
        self.tabs = QTabWidget(parent=column)
        self.tabs.setDocumentMode(True)
        col_v.addWidget(self.tabs, 1)

        # Lazy import keeps circular routes simple.
        from pfc_inductor.ui.workspace.exportar_tab import ExportarTab
        from pfc_inductor.ui.workspace.validar_tab import ValidarTab

        # Tab 0 — Núcleo (selection + inline optimizer)
        self.nucleo_tab = NucleoSelectionPage(materials, cores, wires)
        self.nucleo_tab.selection_applied.connect(self.selection_applied.emit)
        self.tabs.addTab(self.nucleo_tab, "Núcleo")

        # Tab 1 — Análise (waveforms + losses + winding/gap)
        self.analise_tab = AnalisePage()
        self.tabs.addTab(self.analise_tab, "Análise")

        # Tab 2 — Validar
        self.validar_tab = ValidarTab()
        self.validar_tab.fea_requested.connect(self.fea_requested.emit)
        self.validar_tab.compare_requested.connect(self.compare_requested.emit)
        self.tabs.addTab(self.validar_tab, "Validar")

        # Tab 3 — Exportar
        self.exportar_tab = ExportarTab()
        self.exportar_tab.export_html_requested.connect(
            self.export_html_requested.emit,
        )
        self.exportar_tab.export_compare_requested.connect(
            self.export_compare_requested.emit,
        )
        self.tabs.addTab(self.exportar_tab, "Exportar")

        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Scoreboard (slim status bar at the bottom)
        self.scoreboard = Scoreboard(parent=column)
        self.scoreboard.recalculate_requested.connect(
            self.recalculate_requested.emit,
        )
        col_v.addWidget(self.scoreboard)

        outer.addWidget(column, 1)

        # Initial state: Núcleo tab is the entry point; Spec is "done"
        # because the drawer is filled by definition. ProgressIndicator
        # uses its v3 keys (spec/design/validar/exportar); both Núcleo
        # and Análise map to "design".
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

    def set_current_selection(self, material: Material, core: Core, wire: Wire):
        self.scoreboard.set_current_selection(material, core, wire)


    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        self.kpi_strip.update_from_design(result, spec, core, wire, material)
        self.nucleo_tab.update_from_design(result, spec, core, wire, material)
        self.analise_tab.update_from_design(result, spec, core, wire, material)
        self.validar_tab.update_from_design(result, spec, core, wire, material)
        self.exportar_tab.update_from_design(result, spec, core, wire, material)
        self.scoreboard.update_from_result(result, spec)
        # Mark "design" done once a result is available.
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
        """Refresh the NucleoSelectionPage's score tables and the
        inline OptimizerEmbed's spec/catalog inputs after a recalc."""
        self.nucleo_tab.populate(
            spec, materials, cores, wires, material, core, wire,
        )

    def switch_to(self, key: TabKey) -> None:
        idx = {"nucleo": 0, "analise": 1, "validar": 2, "exportar": 3}[key]
        self.tabs.setCurrentIndex(idx)

    def mark_action_done(self, key: str) -> None:
        # ProximosPassosCard was retired in v3.1; this method is kept
        # as a no-op so external callers (MainWindow's report flow,
        # tests) don't crash.
        return

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _on_tab_changed(self, idx: int) -> None:
        # Map all 4 tabs onto the 4-state ProgressIndicator. Núcleo and
        # Análise both belong to the "design" phase.
        if idx in (0, 1):
            self.progress.set_current("design")
        elif idx == 2:
            self.progress.set_current("validar")
            self.progress.mark_done("design")
        elif idx == 3:
            self.progress.set_current("exportar")
            self.progress.mark_done("design")
            self.progress.mark_done("validar")

    def _on_report_pressed(self) -> None:
        # Header / Análise "Gerar Relatório" button: switch to Exportar
        # so the user sees the export options before writing to disk.
        self.switch_to("exportar")
        self.report_requested.emit()

    def _refresh_qss(self) -> None:
        p = get_theme().palette
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ background: {p.bg};"
            f"  border: 0; border-top: 1px solid {p.border}; }}"
        )
        # The KpiHolder sits on the surface so the strip below it has
        # the same background colour and reads as part of the chrome.
        if hasattr(self, "kpi_strip"):
            self.kpi_strip.parent().setStyleSheet(
                f"QFrame#KpiHolder {{ background: {p.bg}; border: 0; }}"
            )
