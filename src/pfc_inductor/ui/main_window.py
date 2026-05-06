"""Main application window — MagnaDesign v3 shell.

Layout (left → right, top → bottom):

    +------+------------------------------------------------+
    | Side | QStackedWidget (4 pages)                       |
    | bar  |                                                |
    | (4   |   page 0 = ProjetoPage                         |
    | itms |              ├─ SpecDrawer (left, collapsible) |
    |  )   |              └─ Workspace column               |
    |      |                  ├─ WorkspaceHeader             |
    |      |                  ├─ ProgressIndicator           |
    |      |                  ├─ QTabWidget                  |
    |      |                  │   • Design   (DashboardPage) |
    |      |                  │   • Validar (ValidarTab)     |
    |      |                  │   • Exportar (ExportarTab)   |
    |      |                  └─ Scoreboard                  |
    |      |   page 1 = OtimizadorPage  (new)               |
    |      |   page 2 = CatalogoPage     (new)              |
    |      |   page 3 = ConfiguracoesPage (new)             |
    +------+------------------------------------------------+

The legacy 3-column splitter (`SpecPanel | PlotPanel | ResultPanel`)
is *no longer mounted*. ``SpecPanel`` is reused unchanged inside the
``SpecDrawer``; ``PlotPanel`` and ``ResultPanel`` modules stay
importable for tests but do not appear on screen.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from pfc_inductor.compare import CompareSlot
from pfc_inductor.data_loader import (
    ensure_user_data,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.design import design
from pfc_inductor.errors import DesignError, ReportGenerationError
from pfc_inductor.models import Core, Material, Spec, Wire
from pfc_inductor.report import generate_datasheet
from pfc_inductor.settings import SETTINGS_APP, SETTINGS_ORG
from pfc_inductor.setup_deps import check_fea_setup
from pfc_inductor.ui.about_dialog import AboutDialog
from pfc_inductor.ui.catalog_dialog import CatalogUpdateDialog
from pfc_inductor.ui.compare_dialog import CompareDialog
from pfc_inductor.ui.controllers import CalculationController
from pfc_inductor.ui.db_editor import DbEditorDialog
from pfc_inductor.ui.dialogs import TopologyPickerDialog
from pfc_inductor.ui.fea_dialog import FEAValidationDialog
from pfc_inductor.ui.litz_dialog import LitzOptimizerDialog
from pfc_inductor.ui.optimize_dialog import OptimizerDialog
from pfc_inductor.ui.setup_dialog import SetupDepsDialog
from pfc_inductor.ui.shell import Sidebar
from pfc_inductor.ui.similar_parts_dialog import SimilarPartsDialog
from pfc_inductor.ui.state import WorkflowState
from pfc_inductor.ui.style import make_stylesheet
from pfc_inductor.ui.theme import get_theme, is_dark, set_theme
from pfc_inductor.ui.workspace import (
    CatalogoPage,
    ConfiguracoesPage,
    OtimizadorPage,
    ProjetoPage,
)

# Sidebar area_ids in stack order. ``dashboard`` is kept as the first
# id for QSettings back-compat (the displayed label is "Projeto").
AREA_PAGES: tuple[str, ...] = (
    "dashboard",
    "otimizador",
    "catalogo",
    "configuracoes",
)


class MainWindow(QMainWindow):
    """The application's main window.

    Emits :attr:`design_completed` after every successful recompute so
    the workspace pages (and any future subscribers) can update from a
    single signal."""

    from PySide6.QtCore import Signal as _Signal
    design_completed = _Signal(object, object, object, object, object)
    """``Signal(DesignResult, Spec, Core, Wire, Material)``."""

    class _StateProvider:
        """Adapter that satisfies the ``SpecPanelLike`` protocol for the
        ``CalculationController``.

        Pulls spec from the real panel, but selection IDs from the host
        ``MainWindow``'s state — the key seam for this refactoring.
        """
        def __init__(self, win: MainWindow):
            self._win = win
        def get_spec(self) -> Spec:
            return self._win.projeto_page.spec_panel.get_spec()
        def get_core_id(self) -> str:
            return self._win._current_core_id
        def get_wire_id(self) -> str:
            return self._win._current_wire_id
        def get_material_id(self) -> str:
            return self._win._current_material_id

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

        # ---- Projeto page (owns SpecDrawer + DashboardPage + tabs) -----
        self.projeto_page = ProjetoPage(
            self._materials, self._cores, self._wires,
        )

        # ---- Selection state (the new source of truth) -----------------
        # Set a safe, hardcoded default selection on startup.
        self._current_material_id: str = "magnetics-60_highflux"
        self._current_core_id: str = "magnetics-0058181a2-60_highflux"
        self._current_wire_id: str = "AWG14"

        # ---- Calculation controller ------------------------------------
        # The controller talks to our adapter, not the real spec panel.
        self._state_provider = self._StateProvider(self)
        self._calc = CalculationController(
            self._state_provider,
            self._materials, self._cores, self._wires,
        )

        # ---- Other workspace pages -------------------------------------
        self.otimizador_page = OtimizadorPage()
        self.catalogo_page = CatalogoPage()
        self.configuracoes_page = ConfiguracoesPage()

        self._build_shell()
        self._wire_signals()

        # Cached compare dialog (kept open between invocations so the
        # accumulated slots survive).
        self._compare_dialog: CompareDialog | None = None

        # Initial calculation + FEA setup probe.
        self._on_calculate()
        self._maybe_offer_fea_setup()

    # ==================================================================
    # Shell construction
    # ==================================================================
    def _build_shell(self) -> None:
        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ---- Sidebar (4 items) ----------------------------------------
        self.sidebar = Sidebar(parent=central, dark_theme=is_dark())
        self.sidebar.navigation_requested.connect(self._on_nav_requested)
        self.sidebar.theme_toggle_requested.connect(self._toggle_theme)
        self.sidebar.overflow_action_requested.connect(self._on_overflow_action)
        h.addWidget(self.sidebar)

        # ---- Stack with 4 pages ---------------------------------------
        self.stack = QStackedWidget()
        self.stack.addWidget(self.projeto_page)       # 0 dashboard
        self.stack.addWidget(self.otimizador_page)    # 1 otimizador
        self.stack.addWidget(self.catalogo_page)      # 2 catalogo
        self.stack.addWidget(self.configuracoes_page) # 3 configuracoes
        h.addWidget(self.stack, 1)

        self.setCentralWidget(central)

        # Initial sidebar selection.
        self.sidebar.set_active_area("dashboard")
        self.stack.setCurrentIndex(0)

    def _wire_signals(self) -> None:
        # ---- Projeto page (Recalcular / Comparar / Relatório / etc) --
        self.projeto_page.recalculate_requested.connect(self._on_calculate)
        self.projeto_page.compare_requested.connect(self._open_compare)
        self.projeto_page.report_requested.connect(self._export_report)
        self.projeto_page.name_changed.connect(
            self._workflow_state.set_project_name,
        )
        self.projeto_page.topology_change_requested.connect(
            self._open_topology_picker,
        )
        self.projeto_page.fea_requested.connect(self._open_fea)
        self.projeto_page.similar_requested.connect(self._open_similar_parts)
        self.projeto_page.litz_requested.connect(self._open_litz)
        self.projeto_page.export_html_requested.connect(self._export_report)
        self.projeto_page.export_compare_requested.connect(
            self._export_compare,
        )
        self.projeto_page.selection_applied.connect(
            self._apply_optimizer_choice,
        )

        # ---- Otimizador page (embed) ----------------------------------
        # The Pareto sweep is now a first-class page surface; "Aplicar"
        # bubbles up via selection_applied just like the Núcleo card.
        self.otimizador_page.selection_applied.connect(
            self._apply_optimizer_choice,
        )

        # ---- Catalogo page --------------------------------------------
        # The DB editor is now embedded directly in the page; ``saved``
        # fires when the user clicks "Salvar tudo" inside the embed.
        self.catalogo_page.saved.connect(self._reload_databases)
        self.catalogo_page.mas_import_requested.connect(
            self._open_catalog_update,
        )
        self.catalogo_page.similar_requested.connect(self._open_similar_parts)

        # ---- Configurações page ---------------------------------------
        self.configuracoes_page.theme_toggle_requested.connect(
            self._toggle_theme,
        )
        self.configuracoes_page.fea_install_requested.connect(
            self._open_setup_deps,
        )
        self.configuracoes_page.litz_optimizer_requested.connect(
            self._open_litz,
        )
        self.configuracoes_page.about_requested.connect(self._open_about)

    # ==================================================================
    # Navigation
    # ==================================================================
    def _on_nav_requested(self, area_id: str) -> None:
        try:
            idx = AREA_PAGES.index(area_id)
        except ValueError:
            return
        self.stack.setCurrentIndex(idx)

    def _on_overflow_action(self, key: str) -> None:
        handlers = {
            "compare": self._open_compare,
            "about":   self._open_about,
        }
        h = handlers.get(key)
        if h is not None:
            h()

    # ==================================================================
    # WorkflowState fan-out (only save status survives in v3)
    # ==================================================================
    def _on_state_changed(self) -> None:
        s = self._workflow_state.snapshot()
        self.projeto_page.set_project_name(s.project_name)
        self.projeto_page.set_save_status(
            unsaved=s.unsaved, last_saved_at=s.last_saved_at,
        )

    # ==================================================================
    # Theme
    # ==================================================================
    def _toggle_theme(self) -> None:
        new = "dark" if not is_dark() else "light"
        set_theme(new)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(make_stylesheet(get_theme()))
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue("theme", new)
        self.sidebar.set_dark_theme(is_dark())

    # ==================================================================
    # Action handlers
    # ==================================================================
    def _open_topology_picker(self) -> None:
        try:
            spec = self.projeto_page.spec_panel.get_spec()
            current = spec.topology
            n_phases = getattr(spec, "n_phases", 1)
        except (ValueError, TypeError):
            current = "boost_ccm"
            n_phases = 1
        dlg = TopologyPickerDialog(
            current=current, n_phases=int(n_phases), parent=self,
        )
        if dlg.exec() != TopologyPickerDialog.DialogCode.Accepted:
            return
        new_key = dlg.selected_key()
        new_phases = dlg.selected_n_phases()
        sp = self.projeto_page.spec_panel
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

    def _open_optimizer(self) -> None:
        try:
            spec, _core, _wire, _material = self._collect_inputs()
        except DesignError as e:
            QMessageBox.warning(self, "Spec inválido", e.user_message())
            return
        dlg = OptimizerDialog(
            spec, self._materials, self._cores, self._wires,
            current_material_id=self._current_material_id,
            parent=self,
        )
        dlg.selection_applied.connect(self._apply_optimizer_choice)
        dlg.exec()

    def _export_report(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        try:
            spec, core, wire, material = self._collect_inputs()
            result = design(spec, core, wire, material)
        except DesignError as e:
            QMessageBox.warning(self, "Erro", e.user_message())
            return
        default_name = (
            f"datasheet_{core.part_number}_{material.name}.html"
        ).replace(" ", "_").replace("/", "-")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save datasheet", default_name, "HTML files (*.html)",
        )
        if not path:
            return
        try:
            out = generate_datasheet(spec, core, material, wire, result, path)
        except (OSError, ValueError, KeyError) as e:
            err = ReportGenerationError(
                f"Falha ao gerar o datasheet: {e}",
                hint=f"Verifique permissão de escrita em\n{path}",
            )
            QMessageBox.critical(
                self, "Datasheet generation failed", err.user_message(),
            )
            return
        # Mark saved + flip Próximos Passos.
        self._workflow_state.mark_saved()
        self.projeto_page.mark_action_done("report")
        QMessageBox.information(
            self, "Datasheet saved",
            f"Saved to:\n{out}\n\nOpen in a browser and use Print → Save as PDF.",
        )

    def _export_compare(self) -> None:
        """Export the current comparative table to HTML or CSV.

        Behaviour:

        - If the user has never opened the compare dialog yet (no
          accumulated slots), open it and prompt them to add the
          current design + alternatives. They can re-trigger the
          export from the dialog itself (which has its own
          HTML/CSV buttons).
        - If at least 2 slots are accumulated, ask for a file path
          and write directly — no dialog needed. The format is
          chosen from the file extension (``.csv`` → CSV, anything
          else → HTML).
        """
        from PySide6.QtWidgets import QFileDialog

        dlg = self._compare_dialog
        slots = dlg.slots() if dlg is not None else []

        if dlg is None or len(slots) < 2:
            QMessageBox.information(
                self, "Comparativo vazio",
                "Adicione ao menos 2 designs ao comparativo antes de "
                "exportar. Vou abrir a janela agora — use \"Adicionar "
                "atual\" para popular.",
            )
            self._open_compare()
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar comparativo",
            "comparacao.html", "HTML (*.html);;CSV (*.csv)",
        )
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                out = dlg.export_csv_to(path)
            else:
                out = dlg.export_html_to(path)
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.critical(self, "Erro ao exportar", str(e))
            return
        QMessageBox.information(
            self, "Exportado", f"Comparativo salvo em:\n{out}",
        )

    def _open_db_editor(self) -> None:
        dlg = DbEditorDialog(parent=self)
        dlg.saved.connect(self._reload_databases)
        dlg.exec()

    def _open_catalog_update(self) -> None:
        dlg = CatalogUpdateDialog(parent=self)
        dlg.completed.connect(self._reload_databases)
        dlg.exec()

    def _open_setup_deps(self) -> None:
        dlg = SetupDepsDialog(parent=self)
        dlg.exec()

    def _maybe_offer_fea_setup(self) -> None:
        try:
            v = check_fea_setup()
        except (OSError, RuntimeError):
            return
        if v.fea_ready:
            return
        dlg = SetupDepsDialog(parent=self)
        dlg.exec()

    def _open_about(self) -> None:
        dlg = AboutDialog(parent=self)
        dlg.exec()

    def current_compare_slot(self) -> CompareSlot:
        spec, core, wire, material = self._collect_inputs()
        result = design(spec, core, wire, material)
        return CompareSlot(
            spec=spec, core=core, wire=wire, material=material, result=result,
        )

    def _open_compare(self) -> None:
        if self._compare_dialog is None:
            self._compare_dialog = CompareDialog(parent=self)
            self._compare_dialog.selection_applied.connect(
                self._apply_compare_choice,
            )
        self._compare_dialog.show()
        self._compare_dialog.raise_()

    def _apply_compare_choice(self, material_id: str, core_id: str,
                              wire_id: str) -> None:
        self._apply_optimizer_choice(material_id, core_id, wire_id)

    def _open_litz(self) -> None:
        try:
            spec, core, _wire, material = self._collect_inputs()
        except DesignError as e:
            QMessageBox.warning(self, "Seleção inválida", e.user_message())
            return
        dlg = LitzOptimizerDialog(spec, core, material, self._wires, parent=self)
        dlg.wire_saved.connect(lambda _wid: self._reload_databases())
        dlg.exec()

    def _open_fea(self) -> None:
        try:
            slot = self.current_compare_slot()
        except DesignError as e:
            QMessageBox.warning(self, "Seleção inválida", e.user_message())
            return
        dlg = FEAValidationDialog(
            slot.spec, slot.core, slot.wire, slot.material, slot.result,
            parent=self,
        )
        dlg.exec()

    def _open_similar_parts(self) -> None:
        try:
            target_core = self._calc.find_core(self._current_core_id)
            target_material = self._calc.find_material(self._current_material_id)
        except DesignError as e:
            QMessageBox.warning(self, "Seleção inválida", e.user_message())
            return
        dlg = SimilarPartsDialog(
            target_core, target_material, self._cores, self._materials,
            parent=self,
        )
        dlg.selection_applied.connect(self._apply_similar_selection)
        dlg.exec()

    def _apply_similar_selection(self, material_id: str,
                                 core_id: str) -> None:
        self._current_material_id = material_id
        self._current_core_id = core_id
        self._on_calculate()

    def _reload_databases(self) -> None:
        self._materials = load_materials()
        self._cores = load_cores()
        self._wires = load_wires()
        self._calc.replace_catalogs(
            self._materials, self._cores, self._wires,
        )
        # TODO: re-validate that the current selection is still valid,
        # or pick a new default. For now, just trigger a recalc.
        self._on_calculate()

    def _apply_optimizer_choice(self, material_id: str, core_id: str,
                                wire_id: str) -> None:
        self._current_material_id = material_id
        self._current_core_id = core_id
        self._current_wire_id = wire_id
        self._on_calculate()

    # ==================================================================
    # Lookups + recalc
    # ==================================================================
    def _collect_inputs(self) -> tuple[Spec, Core, Wire, Material]:
        i = self._calc.collect_inputs()
        return i.spec, i.core, i.wire, i.material

    def _find_core(self, core_id: str) -> Core:
        return self._calc.find_core(core_id)

    def _find_wire(self, wire_id: str) -> Wire:
        return self._calc.find_wire(wire_id)

    def _on_calculate(self) -> None:
        try:
            spec, core, wire, material = self._collect_inputs()
            result = design(spec, core, wire, material)
        except DesignError as e:
            QMessageBox.warning(self, "Erro no cálculo", e.user_message())
            return

        # Update the project workspace with the new result.
        self.projeto_page.update_from_design(
            result, spec, core, wire, material,
        )
        self.projeto_page.populate_nucleo(
            spec, self._materials, self._cores, self._wires,
            material, core, wire,
        )
        self.projeto_page.set_current_selection(material, core, wire)
        self.otimizador_page.set_inputs(
            spec, self._materials, self._cores, self._wires,
            material.id,
        )

        # Emit for subscribers (tests, future plug-ins).
        self.design_completed.emit(result, spec, core, wire, material)
