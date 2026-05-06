"""Main application window — MagnaDesign shell.

Layout (left → right, top → bottom):

    +-----------------------------------------------------+
    | [Sidebar 250px navy]  | WorkspaceHeader (project + CTAs)
    |                       +------------------------------
    |                       | WorkflowStepper (8 segments)
    |                       +------------------------------
    |                       | QStackedWidget                |
    |                       |   page 0 = legacy splitter    |
    |                       |   page 1+ = placeholders      |
    |                       +------------------------------
    |                       | BottomStatusBar (pills)      |
    +-----------------------------------------------------+

The legacy 3-column splitter (spec/plot/result) lives inside the stack as
page 0 — every existing feature keeps working while the dashboard grid
(``refactor-ui-dashboard-cards``) is being built. Other sidebar areas
mount stub pages that can later be replaced by their dedicated views.
"""
from __future__ import annotations
import numpy as np

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QMessageBox, QApplication, QStackedWidget, QFrame,
)

from pfc_inductor.data_loader import (
    load_materials, load_cores, load_wires, find_material, ensure_user_data,
)
from pfc_inductor.models import Spec, Core, Wire
from pfc_inductor.design import design
from pfc_inductor.physics import rolloff as rf
from pfc_inductor.physics import estimate_cost
from pfc_inductor.ui.spec_panel import SpecPanel
from pfc_inductor.ui.result_panel import ResultPanel
from pfc_inductor.ui.plot_panel import PlotPanel
from pfc_inductor.ui.optimize_dialog import OptimizerDialog
from pfc_inductor.ui.db_editor import DbEditorDialog
from pfc_inductor.ui.similar_parts_dialog import SimilarPartsDialog
from pfc_inductor.ui.compare_dialog import CompareDialog
from pfc_inductor.ui.litz_dialog import LitzOptimizerDialog
from pfc_inductor.ui.fea_dialog import FEAValidationDialog
from pfc_inductor.ui.about_dialog import AboutDialog
from pfc_inductor.ui.catalog_dialog import CatalogUpdateDialog
from pfc_inductor.ui.setup_dialog import SetupDepsDialog
from pfc_inductor.setup_deps import check_fea_setup
from pfc_inductor.compare import CompareSlot
from pfc_inductor.report import generate_datasheet
from pfc_inductor.ui.theme import get_theme, set_theme, is_dark
from pfc_inductor.ui.style import make_stylesheet
from pfc_inductor.ui.shell import (
    Sidebar, WorkspaceHeader, WorkflowStepper, BottomStatusBar,
)
from pfc_inductor.ui.state import WorkflowState
from pfc_inductor.ui.dashboard import DashboardPage
from pfc_inductor.ui.dialogs import TopologyPickerDialog


SETTINGS_ORG = "indutor"
SETTINGS_APP = "PFCInductorDesigner"

# Map sidebar area_id → stack-page index. Page 0 hosts the legacy
# splitter for now; the remaining areas show stub placeholders that can
# be replaced by their dedicated views in later changes.
AREA_PAGES: tuple[str, ...] = (
    "dashboard", "topologia", "nucleos", "bobinamento",
    "simulacao", "mecanico", "relatorios", "configuracoes",
)

# Steps-by-area for the workflow stepper. The active step is derived
# from which sidebar area is currently selected, so the stepper feels
# alive even though it isn't user-clickable yet.
AREA_TO_STEP: dict[str, int] = {
    "topologia": 0,
    "dashboard": 2,        # "Cálculo" — the dashboard *is* the design view
    "nucleos": 3,
    "bobinamento": 4,
    "simulacao": 5,
    "mecanico": 6,
    "relatorios": 7,
    "configuracoes": 0,
}


class MainWindow(QMainWindow):
    """The main application window. Emits :attr:`design_completed` after
    every successful recompute so the dashboard cards (and any future
    subscribers) can update from a single signal."""

    from PySide6.QtCore import Signal as _Signal
    design_completed = _Signal(object, object, object, object, object)
    """``Signal(DesignResult, Spec, Core, Wire, Material)``."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MagnaDesign — Inductor Design Suite")
        self.resize(1500, 900)

        ensure_user_data()
        self._materials = load_materials()
        self._cores = load_cores()
        self._wires = load_wires()

        # ---- shell state -----------------------------------------------
        self._workflow_state = WorkflowState(self)
        self._workflow_state.from_settings(QSettings(SETTINGS_ORG, SETTINGS_APP))
        self._workflow_state.state_changed.connect(self._on_state_changed)

        # ---- legacy panels (still used by the dashboard page) ----------
        self.spec_panel = SpecPanel(self._materials, self._cores, self._wires)
        self.result_panel = ResultPanel()
        self.plot_panel = PlotPanel()

        # Build chrome + workspace (with the legacy splitter inside).
        self._build_shell()

        # Auto-recalc disabled — only the spec-panel "Calcular" button
        # triggers a recompute. See spec_panel docstring.
        self.spec_panel.calculate_requested.connect(self._on_calculate)
        self._auto_calc = False

        self._on_calculate()
        self._maybe_offer_fea_setup()

    # ==================================================================
    # Shell construction
    # ==================================================================
    def _build_shell(self) -> None:
        """Compose Sidebar + Workspace into the central widget."""
        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ---- Sidebar ---------------------------------------------------
        self.sidebar = Sidebar(parent=central, dark_theme=is_dark())
        self.sidebar.navigation_requested.connect(self._on_nav_requested)
        self.sidebar.theme_toggle_requested.connect(self._toggle_theme)
        self.sidebar.overflow_action_requested.connect(self._on_overflow_action)

        # ---- Workspace -------------------------------------------------
        workspace = QFrame()
        workspace.setObjectName("Workspace")
        workspace.setStyleSheet(
            f"QFrame#Workspace {{ background: {get_theme().palette.bg}; }}"
        )
        v = QVBoxLayout(workspace)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self.header = WorkspaceHeader(parent=workspace)
        self.header.set_project_name(self._workflow_state.project_name)
        self.header.compare_requested.connect(self._open_compare)
        self.header.report_requested.connect(self._export_report)
        self.header.name_changed.connect(self._workflow_state.set_project_name)

        self.stepper = WorkflowStepper(parent=workspace)
        self.stepper.set_state(
            self._workflow_state.current_step,
            self._workflow_state.completed_steps,
        )
        self.stepper.step_clicked.connect(self._on_stepper_clicked)

        self.stack = QStackedWidget(workspace)
        self._build_stack_pages()

        self.status_bar = BottomStatusBar(parent=workspace)

        v.addWidget(self.header)
        v.addWidget(self.stepper)
        v.addWidget(self.stack, 1)
        v.addWidget(self.status_bar)

        h.addWidget(self.sidebar)
        h.addWidget(workspace, 1)
        self.setCentralWidget(central)

        # Push first state-derived UI snapshot.
        self._on_state_changed()

    def _build_stack_pages(self) -> None:
        """Page 0 = MagnaDesign DashboardPage. Pages 1..6 = stub
        placeholders. The legacy 3-column splitter (spec/plot/result)
        lives behind a "Modo clássico" toggle in Configurações — page 7
        switches between the placeholder and the legacy splitter
        depending on the persisted preference.
        """
        # ---- page 0: DashboardPage -------------------------------------
        self.dashboard_page = DashboardPage()
        self.dashboard_page.fea_requested.connect(self._open_fea)
        self.dashboard_page.compare_requested.connect(self._open_compare)
        self.dashboard_page.litz_requested.connect(self._open_litz)
        self.dashboard_page.report_requested.connect(self._export_report)
        self.dashboard_page.similar_requested.connect(self._open_similar_parts)
        # Topology change: opens the picker dialog and applies the
        # selection back into the spec panel.
        self.dashboard_page.topology_change_requested.connect(
            self._open_topology_picker
        )
        self.stack.addWidget(self.dashboard_page)

        # ---- pages 1..6: placeholders ----------------------------------
        for area in AREA_PAGES[1:7]:
            self.stack.addWidget(self._make_placeholder_page(area))

        # ---- page 7: configurações (with classic-mode toggle) ---------
        self._classic_page = self._make_classic_page()
        self.stack.addWidget(self._classic_page)

    def _make_classic_page(self) -> QWidget:
        """Configurações page hosting the classic-mode toggle + (when on)
        the legacy 3-column splitter."""
        from PySide6.QtWidgets import QCheckBox

        page = QFrame()
        v = QVBoxLayout(page)
        v.setContentsMargins(48, 64, 48, 48)
        v.setSpacing(16)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("Configurações")
        title.setProperty("role", "title")
        v.addWidget(title)

        chk_classic = QCheckBox(
            "Modo clássico (3 colunas) — usa o layout v1 com SpecPanel / "
            "PlotPanel / ResultPanel"
        )
        qs = QSettings(SETTINGS_ORG, SETTINGS_APP)
        chk_classic.setChecked(bool(qs.value("classic_mode", False, type=bool)))
        v.addWidget(chk_classic)

        legacy_holder = QFrame()
        ll = QVBoxLayout(legacy_holder)
        ll.setContentsMargins(0, 16, 0, 0)
        ll.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.addWidget(self.spec_panel)
        splitter.addWidget(self.plot_panel)
        splitter.addWidget(self.result_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([380, 720, 420])
        ll.addWidget(splitter)
        legacy_holder.setVisible(chk_classic.isChecked())

        def _on_toggle(state: bool) -> None:
            qs.setValue("classic_mode", bool(state))
            legacy_holder.setVisible(bool(state))

        chk_classic.toggled.connect(_on_toggle)
        v.addWidget(legacy_holder, 1)
        return page

    def _make_placeholder_page(self, area_id: str) -> QWidget:
        page = QFrame()
        page.setObjectName(f"PagePlaceholder_{area_id}")
        v = QVBoxLayout(page)
        v.setContentsMargins(48, 64, 48, 48)
        v.setSpacing(8)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        label = QLabel(f"Área «{area_id}»")
        label.setProperty("role", "title")
        caption = QLabel(
            "Esta área ainda não tem layout dedicado. "
            "Por enquanto, use o menu \"…\" da barra lateral para acessar "
            "as ferramentas legadas."
        )
        caption.setProperty("role", "muted")
        caption.setWordWrap(True)
        v.addWidget(label)
        v.addWidget(caption)
        v.addStretch(1)
        return page

    # ==================================================================
    # Theme + navigation
    # ==================================================================
    def _toggle_theme(self) -> None:
        new = "dark" if not is_dark() else "light"
        set_theme(new)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(make_stylesheet(get_theme()))
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue("theme", new)
        self.sidebar.set_dark_theme(is_dark())
        self.result_panel.refresh_theme()
        self._on_calculate()

    def _on_stepper_clicked(self, step_idx: int) -> None:
        """Translate a stepper-segment click into a sidebar navigation
        request — the inverse of ``AREA_TO_STEP``.

        Multiple areas may map to the same step (Topologia and
        Configurações both map to step 0). We pick the first canonical
        match in :data:`AREA_PAGES` order, so e.g. clicking step 0
        always lands on "topologia" rather than "configuracoes".
        """
        for area in AREA_PAGES:
            if AREA_TO_STEP.get(area) == step_idx:
                self.sidebar.set_active_area(area)
                self._on_nav_requested(area)
                return

    def _on_nav_requested(self, area_id: str) -> None:
        try:
            idx = AREA_PAGES.index(area_id)
        except ValueError:
            return
        self.stack.setCurrentIndex(idx)
        # Move the workflow stepper to the matching step.
        if area_id in AREA_TO_STEP:
            self._workflow_state.set_current_step(AREA_TO_STEP[area_id])

    def _on_overflow_action(self, key: str) -> None:
        """Sidebar footer "..." menu dispatcher."""
        handlers = {
            "optimizer": self._open_optimizer,
            "compare":   self._open_compare,
            "similar":   self._open_similar_parts,
            "litz":      self._open_litz,
            "fea":       self._open_fea,
            "db_editor": self._open_db_editor,
            "catalog":   self._open_catalog_update,
            "setup_fea": self._open_setup_deps,
            "about":     self._open_about,
        }
        h = handlers.get(key)
        if h is not None:
            h()

    # ==================================================================
    # WorkflowState fan-out
    # ==================================================================
    def _on_state_changed(self) -> None:
        s = self._workflow_state.snapshot()
        self.header.set_project_name(s.project_name)
        self.header.set_save_status(
            unsaved=s.unsaved, last_saved_at=s.last_saved_at,
        )
        self.stepper.set_state(s.current_step, s.completed_steps)
        self.status_bar.set_warnings(s.warnings)
        self.status_bar.set_errors(s.errors)
        self.status_bar.set_validations(s.validations_passed)
        self.status_bar.set_save_status(
            unsaved=s.unsaved, last_saved_at=s.last_saved_at,
        )

    # ==================================================================
    # Action handlers (preserved from v1)
    # ==================================================================
    def _open_topology_picker(self) -> None:
        """Show the topology picker dialog and apply the selection back
        to the spec panel. Triggers a recompute when the user changes
        topology."""
        try:
            spec = self.spec_panel.get_spec()
            current = spec.topology
            n_phases = getattr(spec, "n_phases", 1)
        except Exception:
            current = "boost_ccm"
            n_phases = 1
        dlg = TopologyPickerDialog(
            current=current, n_phases=int(n_phases), parent=self,
        )
        if dlg.exec() != TopologyPickerDialog.DialogCode.Accepted:
            return
        new_key = dlg.selected_key()
        new_phases = dlg.selected_n_phases()
        # Apply by updating the existing combo boxes — keeps every other
        # spec field intact and re-uses the existing _on_topology_changed
        # show/hide logic.
        sp = self.spec_panel
        for i in range(sp.cmb_topology.count()):
            if sp.cmb_topology.itemData(i) == new_key:
                sp.cmb_topology.setCurrentIndex(i)
                break
        if new_key == "line_reactor":
            for i in range(sp.cmb_phases.count()):
                if int(sp.cmb_phases.itemData(i) or 0) == new_phases:
                    sp.cmb_phases.setCurrentIndex(i)
                    break
        self._on_calculate()

    def _open_optimizer(self):
        try:
            spec = self.spec_panel.get_spec()
        except Exception as e:
            QMessageBox.warning(self, "Spec inválido", str(e))
            return
        dlg = OptimizerDialog(
            spec, self._materials, self._cores, self._wires,
            current_material_id=self.spec_panel.get_material_id(),
            parent=self,
        )
        dlg.selection_applied.connect(self._apply_optimizer_choice)
        dlg.exec()

    def _export_report(self):
        from PySide6.QtWidgets import QFileDialog
        try:
            spec = self.spec_panel.get_spec()
            core = self._find_core(self.spec_panel.get_core_id())
            wire = self._find_wire(self.spec_panel.get_wire_id())
            material = find_material(self._materials, self.spec_panel.get_material_id())
            result = design(spec, core, wire, material)
        except Exception as e:
            QMessageBox.warning(self, "Erro", str(e))
            return
        default_name = f"datasheet_{core.part_number}_{material.name}.html".replace(
            " ", "_"
        ).replace("/", "-")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save datasheet", default_name, "HTML files (*.html)"
        )
        if not path:
            return
        try:
            out = generate_datasheet(spec, core, material, wire, result, path)
        except Exception as e:
            QMessageBox.critical(self, "Datasheet generation failed", str(e))
            return
        # Mark the "Relatório" workflow step done + flash a save-state.
        self._workflow_state.mark_step_done(7)
        self._workflow_state.mark_saved()
        if hasattr(self, "dashboard_page"):
            self.dashboard_page.mark_action_done("report")
        QMessageBox.information(
            self, "Datasheet saved",
            f"Saved to:\n{out}\n\nOpen in a browser and use Print → Save as PDF.",
        )

    def _open_db_editor(self):
        dlg = DbEditorDialog(parent=self)
        dlg.saved.connect(self._reload_databases)
        dlg.exec()

    def _open_catalog_update(self):
        dlg = CatalogUpdateDialog(parent=self)
        dlg.completed.connect(self._reload_databases)
        dlg.exec()

    def _open_setup_deps(self):
        dlg = SetupDepsDialog(parent=self)
        dlg.exec()

    def _maybe_offer_fea_setup(self) -> None:
        try:
            v = check_fea_setup()
        except Exception:
            return
        if v.fea_ready:
            return
        dlg = SetupDepsDialog(parent=self)
        dlg.exec()

    def _open_about(self):
        dlg = AboutDialog(parent=self)
        dlg.exec()

    def current_compare_slot(self) -> CompareSlot:
        spec = self.spec_panel.get_spec()
        core = self._find_core(self.spec_panel.get_core_id())
        wire = self._find_wire(self.spec_panel.get_wire_id())
        material = find_material(self._materials, self.spec_panel.get_material_id())
        result = design(spec, core, wire, material)
        return CompareSlot(spec=spec, core=core, wire=wire, material=material, result=result)

    def _open_compare(self):
        if not hasattr(self, "_compare_dialog") or self._compare_dialog is None:
            self._compare_dialog = CompareDialog(parent=self)
            self._compare_dialog.selection_applied.connect(self._apply_compare_choice)
        self._compare_dialog.show()
        self._compare_dialog.raise_()

    def _apply_compare_choice(self, material_id: str, core_id: str, wire_id: str):
        self._apply_optimizer_choice(material_id, core_id, wire_id)

    def _open_litz(self):
        try:
            spec = self.spec_panel.get_spec()
            core = self._find_core(self.spec_panel.get_core_id())
            material = find_material(self._materials, self.spec_panel.get_material_id())
        except Exception as e:
            QMessageBox.warning(self, "Seleção inválida", str(e))
            return
        dlg = LitzOptimizerDialog(spec, core, material, self._wires, parent=self)
        dlg.wire_saved.connect(lambda _wid: self._reload_databases())
        dlg.exec()

    def _open_fea(self):
        try:
            slot = self.current_compare_slot()
        except Exception as e:
            QMessageBox.warning(self, "Seleção inválida", str(e))
            return
        dlg = FEAValidationDialog(
            slot.spec, slot.core, slot.wire, slot.material, slot.result,
            parent=self,
        )
        dlg.exec()
        # FEA round-trip ⇒ "Simulação FEM" step done.
        self._workflow_state.mark_step_done(5)

    def _open_similar_parts(self):
        try:
            target_core = self._find_core(self.spec_panel.get_core_id())
            target_material = find_material(self._materials, self.spec_panel.get_material_id())
        except Exception as e:
            QMessageBox.warning(self, "Seleção inválida", str(e))
            return
        dlg = SimilarPartsDialog(
            target_core, target_material, self._cores, self._materials,
            parent=self,
        )
        dlg.selection_applied.connect(self._apply_similar_selection)
        dlg.exec()

    def _apply_similar_selection(self, material_id: str, core_id: str):
        sp = self.spec_panel
        for i in range(sp.cmb_material.count()):
            if sp.cmb_material.itemData(i) == material_id:
                sp.cmb_material.setCurrentIndex(i)
                break
        for i in range(sp.cmb_core.count()):
            if sp.cmb_core.itemData(i) == core_id:
                sp.cmb_core.setCurrentIndex(i)
                break
        self._on_calculate()

    def _reload_databases(self):
        self._materials = load_materials()
        self._cores = load_cores()
        self._wires = load_wires()
        sp = self.spec_panel
        sp._materials = self._materials
        sp._cores = self._cores
        sp._wires = self._wires
        sp._refresh_visible_options()
        sp._set_initial_selection()
        self._on_calculate()

    def _apply_optimizer_choice(self, material_id: str, core_id: str, wire_id: str):
        sp = self.spec_panel
        for i in range(sp.cmb_material.count()):
            if sp.cmb_material.itemData(i) == material_id:
                sp.cmb_material.setCurrentIndex(i)
                break
        for i in range(sp.cmb_core.count()):
            if sp.cmb_core.itemData(i) == core_id:
                sp.cmb_core.setCurrentIndex(i)
                break
        for i in range(sp.cmb_wire.count()):
            if sp.cmb_wire.itemData(i) == wire_id:
                sp.cmb_wire.setCurrentIndex(i)
                break
        self._on_calculate()

    # ==================================================================
    # Lookups + recalc
    # ==================================================================
    def _find_core(self, core_id: str) -> Core:
        for c in self._cores:
            if c.id == core_id:
                return c
        raise KeyError(core_id)

    def _find_wire(self, wire_id: str) -> Wire:
        for w in self._wires:
            if w.id == wire_id:
                return w
        raise KeyError(wire_id)

    def _on_param_changed(self):
        """No-op — auto-recalc removed."""
        return

    def _on_calculate(self):
        try:
            spec: Spec = self.spec_panel.get_spec()
            core = self._find_core(self.spec_panel.get_core_id())
            wire = self._find_wire(self.spec_panel.get_wire_id())
            material = find_material(self._materials, self.spec_panel.get_material_id())
            result = design(spec, core, wire, material)
        except Exception as e:
            self._workflow_state.set_errors(self._workflow_state.errors + 1)
            QMessageBox.warning(self, "Erro no cálculo", str(e))
            return

        self.result_panel.update_result(result)
        cost = estimate_cost(core, wire, material, result.N_turns)
        self.result_panel.set_cost(cost)

        rolloff_curve = None
        if material.rolloff is not None:
            H_arr = np.logspace(0, 3, 200)
            mu_arr = np.array([rf.mu_pct(material, h) for h in H_arr])
            rolloff_curve = (H_arr, mu_arr)

        self.plot_panel.update_plots(
            result, rolloff_curve, H_op_Oe=result.H_dc_peak_Oe,
            core=core, wire=wire, material=material,
        )

        # Wire results into the workflow status counters.
        n_warn = len(result.warnings) if hasattr(result, "warnings") else 0
        # 12 validation checkpoints in the engine — count those that
        # came back without a matching warning string.
        n_validations = max(0, 12 - n_warn)
        self._workflow_state.set_warnings(n_warn)
        self._workflow_state.set_errors(0)
        self._workflow_state.set_validations(n_validations)
        # A successful calc means: Topologia ✓, Entrada ✓, Cálculo ✓,
        # Núcleo ✓ are all "done" — Bobinamento depends on a wire pick
        # which may be auto-default, leave that to user action.
        for s in (0, 1, 2, 3):
            self._workflow_state.mark_step_done(s)

        # Update dashboard cards.
        if hasattr(self, "dashboard_page"):
            self.dashboard_page.update_from_design(
                result, spec, core, wire, material,
            )

        # Emit for subscribers (tests, future plug-ins).
        self.design_completed.emit(result, spec, core, wire, material)
