"""Project workspace page — SpecDrawer + persistent KPI + 4 tabs.

Layout:

    +----------+----------+-----------------------------+
    | sidebar  | SpecDrwr | header                      |
    | (extern) | (drawer) +-----------------------------+
    |          |          | ProgressIndicator (compact) |
    |          |          +-----------------------------+
    |          |          | ResumoStrip (always visible)|
    |          |          +-----------------------------+
    |          |          | [Core][Analysis][Validate][Export]
    |          |          +-----------------------------+
    |          |          | tab content                 |
    |          |          +-----------------------------+
    |          |          | Scoreboard                  |
    +----------+----------+-----------------------------+

v3.1 redesign (replaces the v3 ``Design`` super-tab):

- **Tab 0 ``Core``**: dedicated material/core/wire selection.
  Hosts both manual table-driven choice and the inline optimizer (the
  ``OptimizerDialog`` modal is now a back-compat wrapper).
- **Tab 1 ``Analysis``**: waveforms, losses, winding/gap detail. No
  selection UI — purely "how does the chosen design behave?".
- **Tab 2 ``Validate``**: FEA validation (unchanged).
- **Tab 3 ``Export``**: datasheet / report export (unchanged).

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
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.shell.header import WorkspaceHeader

# ProgressIndicator was retired here — the QTabWidget below already
# communicates the active phase (highlighted tab + tab order = the
# 4-step workflow). A second strip duplicated the message and was
# never plumbed reliably across all flows. The widget itself stays
# in ``ui.shell.progress_indicator`` for any future surface that
# needs a non-tab phase indicator.
from pfc_inductor.ui.shell.scoreboard import Scoreboard
from pfc_inductor.ui.shell.spec_drawer import SpecDrawer
from pfc_inductor.ui.theme import get_theme, on_theme_changed
from pfc_inductor.ui.widgets import ResumoStrip
from pfc_inductor.ui.workspace.analise_page import AnalisePage
from pfc_inductor.ui.workspace.nucleo_selection_page import NucleoSelectionPage

TabKey = Literal[
    "nucleo",
    "analise",
    "validar",
    "worst_case",
    "compliance",
    "exportar",
]


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
    # Native PDF datasheet — see ExportarTab.export_pdf_requested.
    export_pdf_requested = Signal()
    # Engineering project report — see
    # ExportarTab.export_project_pdf_requested.
    export_project_pdf_requested = Signal()
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
        column.setObjectName("ProjectColumn")
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

        # ---- ResumoStrip — PERSISTENT above the tabs ------------------
        # Wrapped in a slim padded frame so it visually sits on the
        # surface and not on the page bg, with subtle separator from
        # the tab strip below. Padding is intentionally tight so the
        # whole chrome (header + KPI + tabs + scoreboard) fits on a
        # 768 px laptop without pushing the bottom off-screen.
        kpi_holder = QFrame()
        kpi_holder.setObjectName("KpiHolder")
        sp = get_theme().spacing
        kh = QVBoxLayout(kpi_holder)
        kh.setContentsMargins(sp.lg, sp.md, sp.lg, 0)
        kh.setSpacing(0)
        self.kpi_strip = ResumoStrip()
        # Empty-state CTA on the badge → opens the SpecDrawer. Until
        # the first successful recalc the badge reads "Fill in the
        # specification" and clicking it wakes the drawer.
        self.kpi_strip.spec_drawer_requested.connect(
            lambda: self.drawer.set_collapsed(False),
        )
        # Failure path (P1.H): when the badge shows
        # Failed / Check and the user clicks it, switch to the
        # Analysis tab so the failing card is in front of them.
        # Future iteration can route to the specific metric tile.
        self.kpi_strip.failed_metric_clicked.connect(
            self._on_failed_metric_clicked,
        )
        kh.addWidget(self.kpi_strip)
        col_v.addWidget(kpi_holder)

        # Tabs
        self.tabs = QTabWidget(parent=column)
        self.tabs.setDocumentMode(True)
        col_v.addWidget(self.tabs, 1)

        # Lazy import keeps circular routes simple.
        from pfc_inductor.ui.workspace.exportar_tab import ExportarTab
        from pfc_inductor.ui.workspace.validar_tab import ValidarTab

        # Tab 0 — Core (selection + inline optimizer)
        self.nucleo_tab = NucleoSelectionPage(materials, cores, wires)
        self.nucleo_tab.selection_applied.connect(self.selection_applied.emit)
        # When the inline optimizer signals "I just applied — go look
        # at the waveforms", switch to the Analysis tab so the new
        # design's effects are immediately visible.
        self.nucleo_tab.suggest_analise_navigation.connect(
            lambda: self.switch_to("analise"),
        )
        self.tabs.addTab(self.nucleo_tab, "Core")

        # Tab 1 — Analysis (waveforms + losses + winding/gap)
        self.analise_tab = AnalisePage()
        self.tabs.addTab(self.analise_tab, "Analysis")

        # Tab 2 — Validate
        # Wrap in a QScrollArea so the tab's tall content (≈ 800 px
        # min from the FEA panes) doesn't push the whole window past
        # the screen on 1366×768 laptops.
        self.validar_tab = ValidarTab()
        self.validar_tab.fea_requested.connect(self.fea_requested.emit)
        self.validar_tab.compare_requested.connect(self.compare_requested.emit)
        self.tabs.addTab(self._wrap_scrollable(self.validar_tab), "Validate")

        # Tab 3 — Worst-case (corner DOE + Monte-Carlo yield).
        # Closes the production-tolerance loop the v3 split opened —
        # an engineer signing off for production needs to defend
        # "every unit shipped will pass" across line × ambient ×
        # tolerance × load. Lives between Validate and Compliance
        # so the four post-design tabs read in audit order:
        # Validate → Worst-case → Compliance → Export.
        from pfc_inductor.ui.workspace.worst_case_tab import WorstCaseTab

        self.worst_case_tab = WorstCaseTab()
        self.tabs.addTab(self._wrap_scrollable(self.worst_case_tab), "Worst-case")

        # Tab 4 — Compliance (IEC 61000-3-2 + future UL / EN 55032).
        from pfc_inductor.ui.workspace.compliance_tab import ComplianceTab

        self.compliance_tab = ComplianceTab()
        self.tabs.addTab(self._wrap_scrollable(self.compliance_tab), "Compliance")

        # Tab 5 — Export (wrap for the same reason).
        self.exportar_tab = ExportarTab()
        self.exportar_tab.export_html_requested.connect(
            self.export_html_requested.emit,
        )
        self.exportar_tab.export_pdf_requested.connect(
            self.export_pdf_requested.emit,
        )
        self.exportar_tab.export_project_pdf_requested.connect(
            self.export_project_pdf_requested.emit,
        )
        self.exportar_tab.export_compare_requested.connect(
            self.export_compare_requested.emit,
        )
        self.tabs.addTab(self._wrap_scrollable(self.exportar_tab), "Export")

        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Scoreboard (slim status bar at the bottom)
        self.scoreboard = Scoreboard(parent=column)
        self.scoreboard.recalculate_requested.connect(
            self.recalculate_requested.emit,
        )
        col_v.addWidget(self.scoreboard)

        outer.addWidget(column, 1)

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
            unsaved=unsaved,
            last_saved_at=last_saved_at,
        )

    def set_current_selection(self, material: Material, core: Core, wire: Wire):
        self.scoreboard.set_current_selection(material, core, wire)

    def update_from_design(
        self, result: DesignResult, spec: Spec, core: Core, wire: Wire, material: Material
    ) -> None:
        self.kpi_strip.update_from_design(result, spec, core, wire, material)
        self.nucleo_tab.update_from_design(result, spec, core, wire, material)
        self.analise_tab.update_from_design(result, spec, core, wire, material)
        self.validar_tab.update_from_design(result, spec, core, wire, material)
        self.worst_case_tab.update_from_design(
            result,
            spec,
            core,
            wire,
            material,
        )
        self.compliance_tab.update_from_design(
            result,
            spec,
            core,
            wire,
            material,
        )
        self.exportar_tab.update_from_design(result, spec, core, wire, material)
        self.scoreboard.update_from_result(result, spec)
        # Flash the persistent KPI strip so the user has an unambiguous
        # signal that the recalc / apply landed — without it, the
        # values shift silently and small spec tweaks can feel like
        # nothing happened.
        self.kpi_strip.flash_applied()

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
            spec,
            materials,
            cores,
            wires,
            material,
            core,
            wire,
        )

    def switch_to(self, key: TabKey) -> None:
        idx = {
            "nucleo": 0,
            "analise": 1,
            "validar": 2,
            "worst_case": 3,
            "compliance": 4,
            "exportar": 5,
        }[key]
        self.tabs.setCurrentIndex(idx)

    def _on_failed_metric_clicked(self, metric_name: str) -> None:
        """Handle a click on the ResumoStrip's "Failed" badge.

        Today's behaviour: switch to the Analysis tab so the failing
        card is in front of the user. Future iteration can scroll to
        the specific metric tile within Analysis based on
        ``metric_name`` (e.g. "ΔT" → flash the EntreferroCard's
        margin tile). The signal payload is plumbed through so the
        next pass doesn't need to re-architect.
        """
        self.switch_to("analise")
        # Re-flash the strip so the user sees a clear "I heard you"
        # response — same animation already used post-recalc.
        self.kpi_strip.flash_applied()

    def mark_action_done(self, key: str) -> None:
        # ProximosPassosCard was retired in v3.1; this method is kept
        # as a no-op so external callers (MainWindow's report flow,
        # tests) don't crash.
        return

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _on_tab_changed(self, idx: int) -> None:
        # Hook kept for future per-tab reactions (telemetry, defer-
        # mounting heavy tabs, etc.) — the now-removed ProgressIndicator
        # used to advance here. The active QTabWidget tab is itself the
        # phase indicator.
        return

    def _on_report_pressed(self) -> None:
        # Header / Analysis "Generate report" button: switch to Export
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

    @staticmethod
    def _wrap_scrollable(widget: QWidget) -> QScrollArea:
        """Wrap a tab body in a vertical-only QScrollArea.

        The Project page mounts four tabs of varying density —
        Validate in particular (FEA + supporting plots) reports a
        minimumSizeHint of ~810 px tall, which on a 1366×768 laptop
        forces Qt to grow the window past the screen edge and hides
        the bottom Scoreboard. Wrapping each tab body in a scroll
        area keeps the page's minimum manageable: the tab itself
        scrolls when the window is short.

        Thin alias around :func:`wrap_scrollable
        <pfc_inductor.ui.widgets.scroll.wrap_scrollable>` so the
        Project page keeps its long-standing static-method API while
        the shared helper drives the actual configuration.
        """
        from pfc_inductor.ui.widgets import wrap_scrollable

        return wrap_scrollable(widget)
