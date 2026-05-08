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

from typing import Optional

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMenu,
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
from pfc_inductor.project import (
    PROJECT_FILE_EXTENSION,
    ProjectFile,
    empty_state,
    filter_existing,
    load_project,
    push_recent,
    save_project,
)
from pfc_inductor.report import generate_datasheet
from pfc_inductor.settings import SETTINGS_APP, SETTINGS_ORG
from pfc_inductor.setup_deps import check_fea_setup
from pfc_inductor.topology.material_filter import materials_for_topology
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
    CascadePage,
    CatalogoPage,
    ConfiguracoesPage,
    OtimizadorPage,
    ProjetoPage,
)

# Sidebar area_ids in stack order. ``dashboard`` is kept as the first
# id for QSettings back-compat (the displayed label is "Project").
AREA_PAGES: tuple[str, ...] = (
    "dashboard",
    "otimizador",
    "cascade",
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
        # Cap the default size to the available screen so the window
        # never opens larger than the desktop on small laptops (e.g.
        # 1366×768) — that was hiding the bottom Scoreboard on first
        # launch. We leave a 32 px margin for the OS taskbar / dock.
        try:
            from PySide6.QtGui import QGuiApplication
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                w = min(1500, max(960, avail.width() - 64))
                h = min(900, max(640, avail.height() - 64))
                self.resize(w, h)
            else:
                self.resize(1500, 900)
        except Exception:
            # Headless / offscreen: fall back to the canonical size.
            self.resize(1500, 900)

        # Cap the absolute minimum so child widgets' minimumSizeHints
        # don't cumulatively grow the window past the screen edge.
        # Without this, the ResumoStrip (6 metric tiles) + workspace
        # header (3 CTAs) summed to ~1540 px of mandatory width and
        # the right edge fell off any 1366- or 1440-wide laptop.
        # The (1100, 640) floor keeps all child layouts shrinkable
        # via QScrollArea wrappers when the user *does* go narrower
        # than 1100.
        self.setMinimumSize(1100, 640)

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
        self.cascade_page = CascadePage()
        self.catalogo_page = CatalogoPage()
        self.configuracoes_page = ConfiguracoesPage()

        self._build_shell()
        self._wire_signals()
        self._build_menu_bar()
        self._build_command_palette()

        # Project file state — track current path + dirtiness so File →
        # Save knows whether to prompt for a path or write in place.
        # ``None`` path means the session has never been saved yet.
        self._project_path: Optional[str] = None

        # Cached compare dialog (kept open between invocations so the
        # accumulated slots survive).
        self._compare_dialog: CompareDialog | None = None

        # Initial calculation + FEA setup probe.
        self._on_calculate()
        self._maybe_offer_fea_setup()

    # ==================================================================
    # Command palette — Cmd/Ctrl+K (P2.Q)
    # ==================================================================
    def _build_command_palette(self) -> None:
        """Mount the Cmd+K command palette + register every action.

        The palette is the single most-discoverable entry-point for
        power users: instead of hunting through the sidebar / header
        / menu bar / drawer, they hit ``Cmd+K`` and type the first
        few characters of what they want. Each command's handler is
        the same callable already wired to its UI button — no
        duplicated behaviour, just duplicated discovery.
        """
        from PySide6.QtGui import QShortcut
        from pfc_inductor.ui.widgets.command_palette import (
            Command,
            CommandPalette,
        )
        self._cmd_palette = CommandPalette(self)
        self._cmd_palette.register_many([
            # Project lifecycle
            Command("project.new",     "New project",          "Ctrl+N",
                    self._on_project_new,
                    hint="Clears the current session after confirmation."),
            Command("project.open",    "Open project…",        "Ctrl+O",
                    self._on_project_open,
                    hint="Reads a .pfc file from disk."),
            Command("project.save",    "Save project",         "Ctrl+S",
                    self._on_project_save),
            Command("project.save_as", "Save project as…",     "Ctrl+Shift+S",
                    self._on_project_save_as),

            # Inner-loop actions
            Command("calc",            "Recalculate",          "Ctrl+R",
                    self._on_calculate,
                    hint="Runs the engine with the current spec + selection."),
            Command("export.report",   "Export datasheet",     "",
                    self._export_report,
                    hint="Generates a 3-page HTML datasheet (base64-embedded)."),
            Command("export.compare",  "Export comparison",    "",
                    self._export_compare,
                    hint="Saves the comparison table as HTML or CSV."),
            Command("compare.open",    "Open comparison",      "",
                    self._open_compare,
                    hint="Stack up to 4 designs side by side."),

            # Validation / dialogs
            Command("validate.fea",    "Run FEM validation",   "",
                    self._open_fea,
                    hint="FEMM / FEMMT on the operating point — takes minutes."),
            Command("similar",         "Find similar components", "",
                    self._open_similar_parts),
            Command("litz",            "Optimize Litz",        "",
                    self._open_litz),

            # Shell
            Command("theme.toggle",    "Toggle theme (light / dark)", "",
                    self._toggle_theme),
            Command("about",           "About the application", "",
                    self._open_about),

            # Navigation — quick jumps so users don't reach for the
            # mouse mid-flow.
            Command("nav.projeto",     "Go to Project",        "",
                    lambda: self._goto_area("dashboard")),
            Command("nav.otimizador",  "Go to Optimizer",      "",
                    lambda: self._goto_area("otimizador")),
            Command("nav.cascade",     "Go to Full optimizer", "",
                    lambda: self._goto_area("cascade")),
            Command("nav.catalogo",    "Go to Catalog",        "",
                    lambda: self._goto_area("catalogo")),
            Command("nav.config",      "Go to Settings",       "",
                    lambda: self._goto_area("configuracoes")),
        ])
        # Bind the activator. Standard ``QKeySequence.StandardKey.Find``
        # is ``Cmd+F`` on macOS — we want a separate chord. Hardcode
        # ``Ctrl+K`` so it works the same on every platform; on macOS
        # Qt translates ``Ctrl`` → ``Cmd`` automatically.
        from PySide6.QtGui import QKeySequence
        sc = QShortcut(QKeySequence("Ctrl+K"), self)
        sc.activated.connect(self._cmd_palette.show)

    def _goto_area(self, area_id: str) -> None:
        """Navigate to a sidebar area programmatically.

        Used by the command palette so the "Go to …" entries land on
        the same page the sidebar / Navigate menu would, including
        updating the sidebar helper's checked state.
        """
        try:
            self.sidebar.set_active_area(area_id)
        except Exception:
            pass
        try:
            idx = AREA_PAGES.index(area_id)
            self.stack.setCurrentIndex(idx)
        except ValueError:
            pass

    # ==================================================================
    # File menu — project save / load / recent (P0.A)
    # ==================================================================
    _RECENTS_KEY = "project/recents"

    def _build_menu_bar(self) -> None:
        """Mount the native menu bar.

        On macOS Qt promotes the QMainWindow's menu bar to the system
        bar at the top of the screen; on Windows/Linux it sits at the
        top of the window. The menu replaces the legacy left sidebar:
        every navigation slot, every dialog launcher, theme toggle and
        About entry is reachable from here, leaving the workspace
        full-bleed.

        Sections (left → right):

        - **File** — project lifecycle (New / Open / Save / Recents).
        - **Navigate** — page switch (Ctrl+1…5), mirrors what used to
          be the sidebar nav.
        - **Tools** — cross-area dialogs (compare, FEM, similar parts,
          Litz, MAS import, FEA setup).
        - **View** — theme toggle + command palette.
        - **Help** — About.
        """
        bar = self.menuBar()
        # macOS promotes this to the system bar; on Windows/Linux it
        # sits at the top of the window.
        bar.setNativeMenuBar(True)

        # ---- File ------------------------------------------------------
        file_menu = bar.addMenu("&File")

        act_new = QAction("New project", self)
        act_new.setShortcut(QKeySequence.StandardKey.New)
        act_new.triggered.connect(self._on_project_new)
        file_menu.addAction(act_new)

        act_open = QAction("Open...", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self._on_project_open)
        file_menu.addAction(act_open)

        file_menu.addSeparator()

        act_save = QAction("Save", self)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.triggered.connect(self._on_project_save)
        file_menu.addAction(act_save)

        act_save_as = QAction("Save as...", self)
        act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        act_save_as.triggered.connect(self._on_project_save_as)
        file_menu.addAction(act_save_as)

        file_menu.addSeparator()

        # Recent submenu — populated on ``aboutToShow`` so the list
        # reflects on-disk reality each time the menu opens (entries
        # whose files were deleted off-disk are filtered out).
        self._recents_menu: QMenu = file_menu.addMenu("Recent projects")
        self._recents_menu.aboutToShow.connect(self._populate_recents_menu)

        file_menu.addSeparator()

        act_quit = QAction("Quit", self)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        act_quit.triggered.connect(QApplication.quit)
        file_menu.addAction(act_quit)

        # ---- Navigate --------------------------------------------------
        # Same five destinations the old sidebar carried, but addressable
        # via Ctrl+1..5 so the engineer never has to leave the keyboard
        # to switch surfaces. The tooltips disambiguate the two
        # optimizer entries — "Optimizer" is the fast Pareto sweep,
        # "Full optimizer" is the deep cascade.
        nav_menu = bar.addMenu("&Navigate")
        nav_entries = (
            ("dashboard",     "Project",          "Ctrl+1",
             "Main workspace — spec, core, analysis, validation, export."),
            ("otimizador",    "Optimizer",        "Ctrl+2",
             "Fast Pareto sweep (≈30 s) — losses × volume × cost."),
            ("cascade",       "Full optimizer",   "Ctrl+3",
             "Multi-tier cascade with RK4 + FEM (≈5–15 min)."),
            ("catalogo",      "Catalog",          "Ctrl+4",
             "Edit materials, cores and wires. MAS import."),
            ("configuracoes", "Settings",         "Ctrl+5",
             "Theme, FEA, Litz, project information."),
        )
        for area_id, label, sc, tip in nav_entries:
            act = QAction(label, self)
            act.setShortcut(QKeySequence(sc))
            act.setStatusTip(tip)
            act.setToolTip(tip)
            act.triggered.connect(
                lambda _checked=False, a=area_id: self._goto_area(a),
            )
            nav_menu.addAction(act)

        # ---- Tools -----------------------------------------------------
        # Cross-area actions that used to live in the sidebar overflow,
        # the workspace header CTAs, or the dashboard cards. Surfacing
        # them here gives users a single discoverable home — the
        # workspace-header CTAs remain for the inner-loop actions
        # (Recalculate / Compare / Report) but everything else is
        # reachable from this menu.
        tools_menu = bar.addMenu("&Tools")

        act_compare = QAction("Compare designs", self)
        act_compare.setShortcut(QKeySequence("Ctrl+D"))
        act_compare.setStatusTip("Stack up to 4 designs side by side.")
        act_compare.triggered.connect(self._open_compare)
        tools_menu.addAction(act_compare)

        act_fea = QAction("Run FEM validation...", self)
        act_fea.setStatusTip(
            "FEMM / FEMMT on the operating point — takes minutes.",
        )
        act_fea.triggered.connect(self._open_fea)
        tools_menu.addAction(act_fea)

        act_similar = QAction("Find similar components...", self)
        act_similar.setStatusTip(
            "Find cores / materials equivalent to the current selection.",
        )
        act_similar.triggered.connect(self._open_similar_parts)
        tools_menu.addAction(act_similar)

        act_litz = QAction("Optimize Litz...", self)
        act_litz.setStatusTip(
            "Sweep strands × diameter to minimize AC loss.",
        )
        act_litz.triggered.connect(self._open_litz)
        tools_menu.addAction(act_litz)

        tools_menu.addSeparator()

        act_mas = QAction("Update catalog (MAS)...", self)
        act_mas.setStatusTip("Import cores and materials from OpenMagnetics MAS.")
        act_mas.triggered.connect(self._open_catalog_update)
        tools_menu.addAction(act_mas)

        act_setup = QAction("Configure FEA...", self)
        act_setup.setStatusTip("Check or install FEMM and FEMMT.")
        act_setup.triggered.connect(self._open_setup_deps)
        tools_menu.addAction(act_setup)

        # ---- View ------------------------------------------------------
        view_menu = bar.addMenu("&View")

        act_theme = QAction("Toggle theme (light / dark)", self)
        act_theme.setShortcut(QKeySequence("Ctrl+Shift+T"))
        act_theme.setStatusTip("Switch between light and dark themes.")
        act_theme.triggered.connect(self._toggle_theme)
        view_menu.addAction(act_theme)

        view_menu.addSeparator()

        act_palette = QAction("Command palette", self)
        act_palette.setShortcut(QKeySequence("Ctrl+K"))
        act_palette.setStatusTip(
            "Fuzzy-search every action in the app (Ctrl+K).",
        )
        # The palette is also bound to Ctrl+K via QShortcut in
        # ``_build_command_palette``; this menu entry just makes the
        # binding discoverable without forcing the user to memorise it.
        act_palette.triggered.connect(self._show_command_palette)
        view_menu.addAction(act_palette)

        # ---- Help ------------------------------------------------------
        help_menu = bar.addMenu("&Help")

        act_about = QAction("About MagnaDesign", self)
        act_about.triggered.connect(self._open_about)
        help_menu.addAction(act_about)

    def _show_command_palette(self) -> None:
        """Open the Cmd+K command palette from the menu entry.

        Wraps ``self._cmd_palette.show()`` so the menu can connect
        even before ``_build_command_palette`` ran (Qt would still
        resolve ``self._cmd_palette`` lazily, but the wrapper makes
        the contract obvious for anyone reading the menu wiring).
        """
        try:
            self._cmd_palette.show()
        except AttributeError:
            # Defensive: should never trigger because the palette is
            # built inside ``__init__`` before the menu actions are
            # ever clicked.
            pass

    def _populate_recents_menu(self) -> None:
        self._recents_menu.clear()
        recents = self._get_recents()
        if not recents:
            empty = self._recents_menu.addAction("(empty)")
            empty.setEnabled(False)
            return
        for path in recents:
            label = self._shorten_path(path)
            act = self._recents_menu.addAction(label)
            act.setToolTip(path)
            act.triggered.connect(
                lambda _checked=False, p=path: self._open_project_path(p),
            )
        self._recents_menu.addSeparator()
        clear_act = self._recents_menu.addAction("Clear list")
        clear_act.triggered.connect(self._clear_recents)

    @staticmethod
    def _shorten_path(path: str) -> str:
        from pathlib import Path
        p = Path(path)
        try:
            home = Path.home()
            rel = p.relative_to(home)
            return f"~/{rel}"
        except ValueError:
            return str(p)

    # ------------------------------------------------------------------
    def _capture_project(self) -> ProjectFile:
        spec = self.projeto_page.spec_panel.get_spec()
        return ProjectFile.from_session(
            name=self._workflow_state.snapshot().project_name,
            spec=spec,
            material_id=self._current_material_id,
            core_id=self._current_core_id,
            wire_id=self._current_wire_id,
        )

    def _apply_project(self, state: ProjectFile) -> None:
        self.projeto_page.spec_panel.set_spec(state.spec)
        self._workflow_state.set_project_name(state.name)
        if state.selection.material_id:
            self._current_material_id = state.selection.material_id
        if state.selection.core_id:
            self._current_core_id = state.selection.core_id
        if state.selection.wire_id:
            self._current_wire_id = state.selection.wire_id
        self._on_calculate()
        self._workflow_state.mark_saved()

    def _on_project_new(self) -> None:
        if not self._confirm_discard("New project"):
            return
        self._apply_project(empty_state())
        self._project_path = None

    def _on_project_open(self) -> None:
        if not self._confirm_discard("Open project"):
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "",
            f"PFC project (*{PROJECT_FILE_EXTENSION});;All files (*.*)",
        )
        if not path:
            return
        self._open_project_path(path)

    def _open_project_path(self, path: str) -> None:
        try:
            state = load_project(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self, "Failed to open project",
                f"Could not read {path}:\n\n{exc}",
            )
            return
        self._apply_project(state)
        self._project_path = path
        self._push_recent(path)

    def _on_project_save(self) -> None:
        if self._project_path is None:
            self._on_project_save_as()
            return
        self._save_to(self._project_path)

    def _on_project_save_as(self) -> None:
        suggested = (
            self._project_path
            or f"{self._workflow_state.snapshot().project_name}{PROJECT_FILE_EXTENSION}"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project as", suggested,
            f"PFC project (*{PROJECT_FILE_EXTENSION})",
        )
        if not path:
            return
        self._save_to(path)

    def _save_to(self, path: str) -> None:
        try:
            final = save_project(path, self._capture_project())
        except OSError as exc:
            QMessageBox.warning(
                self, "Failed to save",
                f"Could not write {path}:\n\n{exc}",
            )
            return
        self._project_path = str(final)
        self._push_recent(self._project_path)
        self._workflow_state.mark_saved()

    def _confirm_discard(self, title: str) -> bool:
        if not self._workflow_state.snapshot().unsaved:
            return True
        reply = QMessageBox.question(
            self, title,
            "The current project has unsaved changes. Continue anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _get_recents(self) -> list[str]:
        import json
        qs = QSettings(SETTINGS_ORG, SETTINGS_APP)
        raw = qs.value(self._RECENTS_KEY, "[]", type=str)
        try:
            paths = json.loads(raw)
        except (ValueError, TypeError):
            return []
        if not isinstance(paths, list):
            return []
        return filter_existing([str(p) for p in paths])

    def _push_recent(self, path: str) -> None:
        import json
        recents = push_recent(self._get_recents(), path)
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(
            self._RECENTS_KEY, json.dumps(recents),
        )

    def _clear_recents(self) -> None:
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(
            self._RECENTS_KEY, "[]",
        )

    # ==================================================================
    # Shell construction
    # ==================================================================
    def _build_shell(self) -> None:
        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ---- Sidebar — kept as a logical helper, not mounted ----------
        # The 220-px navy sidebar used to live to the left of the page
        # stack; it has been retired in favour of a top menu bar
        # (``_build_menu_bar`` adds Navegar / Ferramentas / Exibir /
        # Ajuda alongside Arquivo). The widget instance lingers for
        # two reasons:
        #
        # 1. It owns ``set_active_area`` / ``set_dark_theme`` — small
        #    pieces of state that other code (``_apply_cascade_candidate``,
        #    ``_toggle_theme``) and the existing test suite reach into.
        # 2. Its ``navigation_requested`` signal is what
        #    ``test_main_window_shell`` and ``test_cascade_page_in_main_window``
        #    fire to prove the route. Wiring it to ``_on_nav_requested``
        #    keeps the contract intact while reclaiming 220 px of
        #    horizontal real estate for the workspace.
        #
        # When the sidebar widget is fully retired (and the tests
        # migrated to drive the QAction triggers instead), the entire
        # ``Sidebar`` class can be deleted.
        self.sidebar = Sidebar(parent=None, dark_theme=is_dark())
        self.sidebar.navigation_requested.connect(self._on_nav_requested)
        self.sidebar.theme_toggle_requested.connect(self._toggle_theme)
        self.sidebar.overflow_action_requested.connect(self._on_overflow_action)
        # Hide explicitly — should already be invisible because it has
        # no parent layout, but ``hide`` makes the intent unambiguous
        # for anyone debugging the widget tree.
        self.sidebar.hide()

        # ---- Stack with 5 pages — now occupies the full width --------
        self.stack = QStackedWidget()
        self.stack.addWidget(self.projeto_page)        # 0 dashboard
        self.stack.addWidget(self.otimizador_page)     # 1 otimizador
        self.stack.addWidget(self.cascade_page)        # 2 cascade
        self.stack.addWidget(self.catalogo_page)       # 3 catalogo
        self.stack.addWidget(self.configuracoes_page)  # 4 configuracoes
        h.addWidget(self.stack, 1)

        self.setCentralWidget(central)

        # Initial sidebar (helper) selection + visible page.
        self.sidebar.set_active_area("dashboard")
        self.stack.setCurrentIndex(0)

    def _wire_signals(self) -> None:
        # ---- Project page (Recalculate / Compare / Report / etc) -----
        self.projeto_page.recalculate_requested.connect(self._on_calculate)
        self.projeto_page.compare_requested.connect(self._open_compare)
        self.projeto_page.report_requested.connect(self._export_report)
        self.projeto_page.name_changed.connect(
            self._workflow_state.set_project_name,
        )
        # Mark the project dirty whenever the engineer touches a spec
        # field — without this hook the "● Salvo" pill never flips
        # back to "● Unsaved" after the first save, and the File →
        # Save shortcut had no signal to act on. Spec panel emits
        # ``changed`` on every spinbox / topology change.
        self.projeto_page.spec_panel.changed.connect(
            self._workflow_state.mark_dirty,
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
        # bubbles up via selection_applied just like the Core card.
        self.otimizador_page.selection_applied.connect(
            self._apply_optimizer_choice,
        )

        # ---- Cascade page (deep multi-tier sweep) ---------------------
        # Double-clicking a row in the top-N table emits the
        # candidate's key; we parse it and route to the same
        # `_apply_optimizer_choice` handler the Pareto and Core
        # surfaces use.
        self.cascade_page.open_in_design_requested.connect(
            self._apply_cascade_candidate,
        )
        # The "Aplicar selecionado" button on the cascade page emits
        # the same (material_id, core_id, wire_id) tuple the
        # Optimizer and Core card already wire — so the engineer
        # can promote a cascade winner to the design view with one
        # click and stay on the cascade page if they want to keep
        # comparing.
        self.cascade_page.selection_applied.connect(
            self._apply_optimizer_choice,
        )

        # ---- Catalogo page --------------------------------------------
        # The DB editor is now embedded directly in the page; ``saved``
        # fires when the user clicks "Save all" inside the embed.
        self.catalogo_page.saved.connect(self._reload_databases)
        self.catalogo_page.mas_import_requested.connect(
            self._open_catalog_update,
        )
        self.catalogo_page.similar_requested.connect(self._open_similar_parts)

        # ---- Settings page --------------------------------------------
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
        sp = self.projeto_page.spec_panel
        try:
            current = sp.topology()
            n_phases = sp.n_phases()
        except (ValueError, TypeError, AttributeError):
            current = "boost_ccm"
            n_phases = 1
        dlg = TopologyPickerDialog(
            current=current, n_phases=int(n_phases), parent=self,
        )
        if dlg.exec() != TopologyPickerDialog.DialogCode.Accepted:
            return
        new_key = dlg.selected_key()
        new_phases = dlg.selected_n_phases()
        # ``set_topology`` is the single SpecPanel-side setter — it
        # toggles the line-reactor block visibility and emits
        # ``changed`` / ``topology_changed`` (the drawer button label
        # listens to the latter).
        sp.set_topology(new_key, n_phases=new_phases)
        self._on_calculate()

    def _open_optimizer(self) -> None:
        try:
            spec, _core, _wire, _material = self._collect_inputs()
        except DesignError as e:
            QMessageBox.warning(self, "Invalid spec", e.user_message())
            return
        # Same per-topology filter the inline pages use — the modal
        # optimizer should not surface line-frequency reactor candidates
        # built on switching-frequency powder cores (or vice-versa).
        eligible_materials = materials_for_topology(
            self._materials, spec.topology,
        )
        dlg = OptimizerDialog(
            spec, eligible_materials, self._cores, self._wires,
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
            QMessageBox.warning(self, "Error", e.user_message())
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
                f"Failed to generate the datasheet: {e}",
                hint=f"Check write permission for\n{path}",
            )
            QMessageBox.critical(
                self, "Datasheet generation failed", err.user_message(),
            )
            return
        # Mark saved + flip Next Steps.
        self._workflow_state.mark_saved()
        self.projeto_page.mark_action_done("report")
        # Replace the modal "Datasheet saved / OK" dialog with a
        # transient toast pinned bottom-right + an "Open" action that
        # opens the HTML in the user's default browser. Engineers
        # generate a datasheet many times per session — the modal was
        # a friction point that demanded a click for every confirmation.
        from pfc_inductor.ui.widgets.toast import Toast
        Toast.show_message(
            self,
            f"Datasheet saved to {out}",
            action_label="Open",
            action=lambda p=str(out): self._open_path_externally(p),
        )

    @staticmethod
    def _open_path_externally(path: str) -> None:
        """Open ``path`` with the OS default handler.

        Used by the post-export Toast's "Open" action. ``QDesktopServices``
        picks the right protocol per OS (``open`` on macOS, ``xdg-open``
        on Linux, ``ShellExecute`` on Windows).
        """
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

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
                self, "Comparison empty",
                "Add at least 2 designs to the comparison before "
                "exporting. I'll open the window now — use \"Add "
                "current\" to populate it.",
            )
            self._open_compare()
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export comparison",
            "comparison.html", "HTML (*.html);;CSV (*.csv)",
        )
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                out = dlg.export_csv_to(path)
            else:
                out = dlg.export_html_to(path)
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        QMessageBox.information(
            self, "Exported", f"Comparison saved to:\n{out}",
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
        """Schedule the FEA-setup prompt without blocking ``__init__``.

        A blocking ``dlg.exec()`` here would (a) freeze the constructor
        until the user dismisses the dialog — surfacing the setup prompt
        *before* the main window is even visible — and (b) deadlock
        headless/offscreen sessions (CI, tests) where there is no user
        to dismiss it. We defer to the next event-loop iteration so the
        window paints first, and short-circuit on non-interactive Qt
        platforms.
        """
        if QGuiApplication.platformName() in ("offscreen", "minimal"):
            return
        QTimer.singleShot(0, self._offer_fea_setup_now)

    def _offer_fea_setup_now(self) -> None:
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
            QMessageBox.warning(self, "Invalid selection", e.user_message())
            return
        dlg = LitzOptimizerDialog(spec, core, material, self._wires, parent=self)
        dlg.wire_saved.connect(lambda _wid: self._reload_databases())
        dlg.exec()

    def _open_fea(self) -> None:
        try:
            slot = self.current_compare_slot()
        except DesignError as e:
            QMessageBox.warning(self, "Invalid selection", e.user_message())
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
            QMessageBox.warning(self, "Invalid selection", e.user_message())
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
        # Selection swap is a spec-level change as far as the user is
        # concerned — flip the save pill so File → Save has a meaning.
        changed = (
            material_id != self._current_material_id
            or core_id != self._current_core_id
            or wire_id != self._current_wire_id
        )
        self._current_material_id = material_id
        self._current_core_id = core_id
        self._current_wire_id = wire_id
        if changed:
            self._workflow_state.mark_dirty()
        self._on_calculate()

    def _apply_cascade_candidate(self, candidate_key: str) -> None:
        """Hydrate a cascade row into the design view.

        The cascade emits its `Candidate.key()` — a `|`-separated
        tuple of `(core_id, material_id, wire_id, N, gap_mm)`. We
        only need the first three fields to set the current
        selection; N / gap come from the engine on the next
        recalc. Routes to the same `_apply_optimizer_choice`
        handler the Pareto / Core / Compare surfaces use, then
        switches the visible page back to Project so the engineer
        sees the freshly hydrated design immediately.
        """
        parts = candidate_key.split("|")
        if len(parts) < 3:
            return
        core_id, material_id, wire_id = parts[0], parts[1], parts[2]
        self._apply_optimizer_choice(material_id, core_id, wire_id)
        self.sidebar.set_active_area("dashboard")
        self.stack.setCurrentIndex(AREA_PAGES.index("dashboard"))

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
            QMessageBox.warning(self, "Calculation error", e.user_message())
            return

        # Filter the material catalogue by the current topology so
        # downstream pages (core selection, optimizer, cascade)
        # don't waste time evaluating materials that make no
        # engineering sense for the chosen converter — e.g. a line
        # reactor at 60 Hz has no business iterating over 241 powder
        # cores designed for 20–200 kHz switching.
        eligible_materials = materials_for_topology(
            self._materials, spec.topology,
        )

        # Update the project workspace with the new result.
        self.projeto_page.update_from_design(
            result, spec, core, wire, material,
        )
        self.projeto_page.populate_nucleo(
            spec, eligible_materials, self._cores, self._wires,
            material, core, wire,
        )
        self.projeto_page.set_current_selection(material, core, wire)
        self.otimizador_page.set_inputs(
            spec, eligible_materials, self._cores, self._wires,
            material.id,
        )
        # Cascade page mirrors the same DB + spec; running a deep
        # sweep doesn't depend on the engineer's current core /
        # wire / material selection — the cascade explores the
        # whole catalogue.
        self.cascade_page.set_inputs(
            spec, eligible_materials, self._cores, self._wires,
        )

        # Emit for subscribers (tests, future plug-ins).
        self.design_completed.emit(result, spec, core, wire, material)
