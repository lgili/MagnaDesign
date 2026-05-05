"""Main application window."""
from __future__ import annotations
from typing import Optional
import numpy as np

from PySide6.QtCore import Qt, QSettings, QSize
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QWidget, QVBoxLayout, QHBoxLayout, QStatusBar,
    QLabel, QMessageBox, QToolBar, QApplication, QToolButton,
)

from pfc_inductor.data_loader import (
    load_materials, load_cores, load_wires, find_material, ensure_user_data,
)
from pfc_inductor.models import Spec, Material, Core, Wire
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
from pfc_inductor.ui.icons import icon as ui_icon


SETTINGS_ORG = "indutor"
SETTINGS_APP = "PFCInductorDesigner"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PFC Inductor Designer")
        self.resize(1500, 900)

        ensure_user_data()
        self._materials = load_materials()
        self._cores = load_cores()
        self._wires = load_wires()

        self.spec_panel = SpecPanel(self._materials, self._cores, self._wires)
        self.result_panel = ResultPanel()
        self.plot_panel = PlotPanel()

        # Layout: left=spec, center=plots, right=results.
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.addWidget(self.spec_panel)
        splitter.addWidget(self.plot_panel)
        splitter.addWidget(self.result_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([380, 720, 420])

        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(splitter)
        self.setCentralWidget(container)

        self._build_toolbar()
        self._build_status_bar()

        # Recalc happens on demand: the "Calcular" button on the spec
        # panel is the single trigger. Auto-recalc on every change kept
        # the UI feeling laggy — pyvista + matplotlib + the design
        # engine over a 1430-wire / 1020-core DB take ~200–500 ms per
        # cycle, and any signal hiccup (visibility toggle, combo
        # repopulation) compounds. Explicit click is fast and
        # predictable.
        self.spec_panel.calculate_requested.connect(self._on_calculate)
        self._auto_calc = False

        self._on_calculate()
        self._maybe_offer_fea_setup()

    # ------------------------------------------------------------------
    # Chrome
    # ------------------------------------------------------------------
    def _build_toolbar(self):
        tb = QToolBar("Ferramentas")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        p = get_theme().palette
        ic = lambda name: ui_icon(name, p.text_secondary, 16)

        for icon_name, label, slot in [
            ("sliders",  "Otimizador",          self._open_optimizer),
            ("compare",  "Comparar",            self._open_compare),
            ("search",   "Similares",           self._open_similar_parts),
            ("braid",    "Litz",                self._open_litz),
            ("cube",     "Validar (FEA)",       self._open_fea),
        ]:
            act = QAction(ic(icon_name), label, self)
            act.triggered.connect(slot)
            tb.addAction(act)

        tb.addSeparator()

        act_db = QAction(ic("database"), "Base de dados", self)
        act_db.triggered.connect(self._open_db_editor)
        tb.addAction(act_db)

        act_catalog = QAction(ic("download_cloud"), "Atualizar catálogo", self)
        act_catalog.setToolTip(
            "Importa materiais e fios do catálogo OpenMagnetics MAS"
        )
        act_catalog.triggered.connect(self._open_catalog_update)
        tb.addAction(act_catalog)

        act_setup = QAction(ic("download_cloud"), "Instalar FEA", self)
        act_setup.setToolTip(
            "Reinstalar/atualizar dependências FEA (ONELAB + FEMMT)"
        )
        act_setup.triggered.connect(self._open_setup_deps)
        tb.addAction(act_setup)

        act_report = QAction(ic("file"), "Relatório", self)
        act_report.triggered.connect(self._export_report)
        tb.addAction(act_report)

        act_about = QAction(ic("zap"), "Sobre", self)
        act_about.triggered.connect(self._open_about)
        tb.addAction(act_about)

        # Stretch + theme toggle on far right.
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicyExpanding(), QSizePolicyExpanding())
        tb.addWidget(spacer)

        self._theme_action = QAction(self)
        self._theme_action.setToolTip("Alternar tema claro/escuro")
        self._theme_action.triggered.connect(self._toggle_theme)
        self._refresh_theme_action_icon()
        tb.addAction(self._theme_action)

        self._toolbar = tb

    def _refresh_theme_action_icon(self):
        p = get_theme().palette
        name = "sun" if is_dark() else "moon"
        self._theme_action.setIcon(ui_icon(name, p.text_secondary, 16))
        self._theme_action.setText("Tema escuro" if not is_dark() else "Tema claro")

    def _toggle_theme(self):
        new = "dark" if not is_dark() else "light"
        set_theme(new)
        QApplication.instance().setStyleSheet(make_stylesheet(get_theme()))
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue("theme", new)
        self._refresh_theme_action_icon()
        # Re-tint toolbar icons.
        self._retint_toolbar_icons()
        # Refresh result colours that aren't covered by QSS.
        self.result_panel.refresh_theme()
        self._on_calculate()

    def _retint_toolbar_icons(self):
        p = get_theme().palette
        actions = self._toolbar.actions()
        names = ["sliders", "compare", "search", "braid", "cube",
                 None, "database", "download_cloud", "download_cloud",
                 "file", "zap", None]
        # Skip separators and the spacer; theme button has its own logic.
        for act, name in zip(actions, names + [None] * (len(actions) - len(names))):
            if name is None:
                continue
            act.setIcon(ui_icon(name, p.text_secondary, 16))

    def _build_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)

        # Left: status text.
        self._sb_label = QLabel("Pronto.")
        self._sb_label.setProperty("role", "muted")
        sb.addWidget(self._sb_label, 1)

        # Right: app version pill.
        version_pill = QLabel("v0.1")
        version_pill.setProperty("pill", "neutral")
        sb.addPermanentWidget(version_pill)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------
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
        """Open the install dialog on boot when ONELAB is missing.

        Only fires once per MainWindow construction — closing the dialog
        keeps it closed for the remainder of the session.
        """
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
        # The FEA dialog runs `select_backend_for_shape` and surfaces the
        # chosen backend + fidelity rating in its status header — toroid
        # picks FEMM when available, EE/ETD/PQ pick FEMMT, etc.
        dlg = FEAValidationDialog(
            slot.spec, slot.core, slot.wire, slot.material, slot.result,
            parent=self,
        )
        dlg.exec()

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
        # Repopulate via the spec panel's own helper so combos stay
        # sorted + searchable consistently.
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

    # ------------------------------------------------------------------
    # Lookups + recalc
    # ------------------------------------------------------------------
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
        """No-op — auto-recalc removed. Recalc is triggered exclusively
        by the user clicking <b>Calcular</b> on the spec panel.

        Kept for compatibility in case any caller still emits
        ``changed`` (none currently connect to it).
        """
        return

    def _on_calculate(self):
        try:
            spec: Spec = self.spec_panel.get_spec()
            core = self._find_core(self.spec_panel.get_core_id())
            wire = self._find_wire(self.spec_panel.get_wire_id())
            material = find_material(self._materials, self.spec_panel.get_material_id())
            result = design(spec, core, wire, material)
        except Exception as e:
            self._sb_label.setText(f"Erro: {e}")
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

        if result.warnings:
            msg = (f"⚠ {len(result.warnings)} aviso(s)  ·  "
                   f"L={result.L_actual_uH:.0f} µH  ·  N={result.N_turns}  ·  "
                   f"P={result.losses.P_total_W:.2f} W  ·  T={result.T_winding_C:.0f} °C")
        else:
            msg = (f"OK  ·  L={result.L_actual_uH:.0f} µH  ·  N={result.N_turns}  ·  "
                   f"P={result.losses.P_total_W:.2f} W  ·  T={result.T_winding_C:.0f} °C")
        self._sb_label.setText(msg)


def QSizePolicyExpanding():
    """Helper to avoid importing QSizePolicy at module top."""
    from PySide6.QtWidgets import QSizePolicy
    return QSizePolicy.Policy.Expanding
