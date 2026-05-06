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
        # Cards mounted on per-area pages (besides the main Dashboard) —
        # tracked here so ``design_completed`` can fan out to all of them.
        self._extra_cards: list[tuple[str, QWidget]] = []
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
        self._workspace = workspace
        self._refresh_workspace_bg()
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
        """Page 0 = MagnaDesign DashboardPage. Pages 1..7 = real
        per-area pages (Topologia, Núcleos, Bobinamento, Simulação,
        Mecânico, Relatórios, Configurações), each composed of one or
        two dashboard-grade cards plus a header.
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
        # Núcleo card "Aplicar seleção" routes through the same handler
        # the optimizer dialog uses, so combos / recompute path stay
        # in lock-step regardless of the entry point.
        self.dashboard_page.card_nucleo.selection_applied.connect(
            self._apply_optimizer_choice
        )
        self.stack.addWidget(self.dashboard_page)

        # ---- pages 1..7: real area pages -------------------------------
        for area in AREA_PAGES[1:]:
            self.stack.addWidget(self._build_area_page(area))

    def _make_placeholder_page(self, area_id: str) -> QWidget:
        """Build a real area page for ``area_id``.

        Each area gets a header (title + caption) plus a body composed
        of dashboard-grade cards or a single full-bleed widget. Areas
        that already have a richer view in the Dashboard (e.g.
        Bobinamento, Entreferro) reuse the same card class so we don't
        re-implement the data binding.
        """
        return self._build_area_page(area_id)

    # ------------------------------------------------------------------
    # Area page builders
    # ------------------------------------------------------------------
    def _build_area_page(self, area_id: str) -> QWidget:
        from PySide6.QtWidgets import QScrollArea
        sp = get_theme().spacing

        outer = QFrame()
        outer.setStyleSheet(
            f"QFrame {{ background: {get_theme().palette.bg}; }}"
        )
        v = QVBoxLayout(outer)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {get_theme().palette.bg}; border: 0; }}"
        )
        inner = QWidget()
        inner.setStyleSheet(f"background: {get_theme().palette.bg};")
        scroll.setWidget(inner)
        v.addWidget(scroll, 1)

        body = QVBoxLayout(inner)
        body.setContentsMargins(sp.page, sp.page, sp.page, sp.page)
        body.setSpacing(sp.card_gap)

        title_text, caption_text, content = self._area_content(area_id)
        title = QLabel(title_text)
        title.setProperty("role", "title")
        caption = QLabel(caption_text)
        caption.setProperty("role", "muted")
        caption.setWordWrap(True)
        body.addWidget(title)
        body.addWidget(caption)

        if content is not None:
            body.addWidget(content, 1)
        else:
            body.addStretch(1)

        return outer

    def _area_content(self, area_id: str) -> tuple[str, str, QWidget | None]:
        """Return (title, caption, body widget) for a non-Dashboard area."""
        from pfc_inductor.ui.dashboard.cards import (
            TopologiaCard, NucleoCard, BobinamentoCard, EntreferroCard,
            PerdasCard, FormasOndaCard, Viz3DCard, ResumoCard,
        )

        if area_id == "topologia":
            card = TopologiaCard()
            card.topology_change_requested.connect(self._open_topology_picker)
            self._extra_cards.append(("topologia", card))
            return (
                "Topologia",
                "Escolha a topologia PFC e ajuste os parâmetros de "
                "entrada e potência. A escolha define a matemática do "
                "indutor (forma de onda, perdas, dimensionamento).",
                card,
            )
        if area_id == "nucleos":
            box = QFrame()
            row = QHBoxLayout(box)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(get_theme().spacing.card_gap)
            n = NucleoCard()
            r = ResumoCard()
            self._extra_cards.append(("nucleos", n))
            self._extra_cards.append(("nucleos", r))
            row.addWidget(n, 1)
            row.addWidget(r, 1)
            return (
                "Núcleos",
                "Material magnético, geometria do núcleo e fio. "
                "A seleção atual e seus principais KPIs.",
                box,
            )
        if area_id == "bobinamento":
            box = QFrame()
            row = QHBoxLayout(box)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(get_theme().spacing.card_gap)
            b = BobinamentoCard()
            e = EntreferroCard()
            self._extra_cards.append(("bobinamento", b))
            self._extra_cards.append(("bobinamento", e))
            row.addWidget(b, 1)
            row.addWidget(e, 1)
            return (
                "Bobinamento",
                "Detalhes do enrolamento, entreferro e resistência DC/AC. "
                "Use o menu \"…\" da barra lateral para abrir o "
                "otimizador de Litz.",
                box,
            )
        if area_id == "simulacao":
            box = QFrame()
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(get_theme().spacing.card_gap)
            f = FormasOndaCard()
            p = PerdasCard()
            self._extra_cards.append(("simulacao", f))
            self._extra_cards.append(("simulacao", p))
            col.addWidget(f, 1)
            col.addWidget(p, 1)
            return (
                "Simulação",
                "Forma de onda da corrente no indutor, perdas e validação "
                "FEM. Use \"…\" → Validar (FEA) para comparar com FEMM/FEMMT.",
                box,
            )
        if area_id == "mecanico":
            v = Viz3DCard()
            self._extra_cards.append(("mecanico", v))
            return (
                "Mecânico",
                "Visualização 3D do núcleo e enrolamento. Use as chips "
                "no canto superior para alternar Frente / Cima / Lateral / Iso.",
                v,
            )
        if area_id == "relatorios":
            box = QFrame()
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(get_theme().spacing.card_gap)
            from pfc_inductor.ui.widgets import Card
            from PySide6.QtWidgets import QPushButton
            inner_body = QFrame()
            ib = QVBoxLayout(inner_body)
            ib.setContentsMargins(0, 0, 0, 0)
            ib.setSpacing(8)
            desc = QLabel(
                "Gera um datasheet HTML auto-contido (3 páginas) com "
                "vistas ortográficas, especificações e tabela BOM. "
                "Imprima como PDF a partir do navegador."
            )
            desc.setWordWrap(True)
            desc.setProperty("role", "muted")
            btn = QPushButton("Gerar Relatório (HTML)")
            btn.setProperty("class", "Primary")
            btn.clicked.connect(self._export_report)
            ib.addWidget(desc)
            ib.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
            ib.addStretch(1)
            card = Card("Datasheet", inner_body)
            col.addWidget(card)
            col.addStretch(1)
            return (
                "Relatórios",
                "Datasheet do design corrente + comparativos.",
                box,
            )
        if area_id == "configuracoes":
            return (
                "Configurações",
                "Modo clássico (3 colunas) restaura o layout v1 com "
                "SpecPanel / PlotPanel / ResultPanel.",
                self._make_classic_page_body(),
            )
        return ("", "", None)

    def _make_classic_page_body(self) -> QWidget:
        """Standalone body of the Configurações page — checkbox + the
        legacy splitter (visibility-toggled)."""
        from PySide6.QtWidgets import QCheckBox

        box = QFrame()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(16)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        chk = QCheckBox(
            "Modo clássico (3 colunas) — usa o layout v1 com SpecPanel / "
            "PlotPanel / ResultPanel"
        )
        qs = QSettings(SETTINGS_ORG, SETTINGS_APP)
        chk.setChecked(bool(qs.value("classic_mode", False, type=bool)))
        v.addWidget(chk)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.addWidget(self.spec_panel)
        splitter.addWidget(self.plot_panel)
        splitter.addWidget(self.result_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([380, 720, 420])
        splitter.setVisible(chk.isChecked())

        def _on_toggle(state: bool) -> None:
            qs.setValue("classic_mode", bool(state))
            splitter.setVisible(bool(state))

        chk.toggled.connect(_on_toggle)
        v.addWidget(splitter, 1)
        return box

    # ==================================================================
    # Theme + navigation
    # ==================================================================
    def _refresh_workspace_bg(self) -> None:
        if hasattr(self, "_workspace"):
            self._workspace.setStyleSheet(
                f"QFrame#Workspace {{ background: {get_theme().palette.bg}; }}"
            )

    def _toggle_theme(self) -> None:
        new = "dark" if not is_dark() else "light"
        set_theme(new)  # emits theme_changed → all subscribers refresh
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(make_stylesheet(get_theme()))
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue("theme", new)
        self.sidebar.set_dark_theme(is_dark())
        self._refresh_workspace_bg()
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

        # Update area-page cards (Topologia / Núcleos / Bobinamento /
        # Simulação / Mecânico / Relatórios).
        for _area, card in getattr(self, "_extra_cards", []):
            try:
                card.update_from_design(result, spec, core, wire, material)
            except Exception:
                pass

        # Populate the Núcleo score-table candidate lists. We do it
        # *after* the main calculation so the tables reflect the
        # current spec — the score functions take the spec into
        # account and a topology change should re-rank.
        try:
            self.dashboard_page.card_nucleo.populate(
                spec, self._materials, self._cores, self._wires,
                material, core, wire,
            )
        except Exception:
            pass

        # Emit for subscribers (tests, future plug-ins).
        self.design_completed.emit(result, spec, core, wire, material)
