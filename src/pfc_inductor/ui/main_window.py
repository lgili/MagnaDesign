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

import atexit
import weakref
from typing import TYPE_CHECKING, ClassVar, Optional

# ``CompareDialog`` is imported lazily inside ``_open_compare`` so the
# matplotlib + reportlab font-registration cost only fires when the
# user opens the dialog. The ``TYPE_CHECKING`` block lets static
# checkers still see the concrete type for the cached attribute
# without paying the runtime import cost.
if TYPE_CHECKING:
    from pfc_inductor.ui.compare_dialog import CompareDialog

from PySide6.QtCore import (
    QObject,
    QSettings,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QAction, QCursor, QGuiApplication, QKeySequence
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

# Dialog classes and the report module are deliberately NOT
# imported at module load time — they pull matplotlib +
# reportlab + the dialog widgets, which together added ~1.5 s
# to MainWindow construction (and that's on a warm cache; the
# frozen .app's cold start was visibly worse — the main reason
# users reported "the app takes too long to open"). They're
# only needed inside specific menu/action handlers, so each
# method imports its dialog locally; the first user click pays
# the cost once and subsequent ones get the cached import.
# ``pfc_inductor.report`` is the same story (matplotlib plus
# reportlab font registration) — moved into the export
# handlers.
from pfc_inductor.settings import SETTINGS_APP, SETTINGS_ORG
from pfc_inductor.topology.material_filter import materials_for_topology
from pfc_inductor.ui.controllers import CalculationController
from pfc_inductor.ui.shell import Sidebar
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


class _DesignWorker(QObject):
    """``QObject`` that runs ``design()`` off the main thread.

    Lives in a dedicated ``QThread`` (constructed by ``MainWindow``)
    for the entire lifetime of the window. The single long-lived
    worker pattern (vs. spawn-one-per-calc) avoids paying the thread
    startup cost on every spec change, and keeps cleanup simple at
    window close — one ``thread.quit() + wait()`` call.

    Communication is signal-based both ways:

    - Main thread → worker: ``MainWindow._calc_requested`` is
      connected to ``compute`` via ``QueuedConnection``; emitting
      it enqueues a calc on the worker's event loop. We use a
      signal instead of ``QMetaObject.invokeMethod`` because the
      latter requires every argument to have a registered
      ``QMetaType``, which raises ``RuntimeError: qArgDataFromPyType:
      Unable to find a QMetaType for "object"`` for arbitrary
      Python objects (Pydantic models in our case). Signals marshal
      ``object`` payloads natively via ``QueuedConnection``.
    - Worker → main thread: ``finished`` or ``failed`` signals,
      received on the main thread via ``QueuedConnection`` so the
      slot can mutate widgets safely.

    The worker NEVER touches Qt widgets. It only operates on the
    pure-Python ``Spec`` / ``Core`` / ``Wire`` / ``Material`` data
    classes (immutable Pydantic models) and calls ``design()``.
    """

    # ``object`` rather than the concrete types because PySide6
    # signal marshaling for Pydantic models works out of the box
    # via ``object`` but is finicky when you hand it the actual
    # class (it tries to register a meta-type).
    finished = Signal(object, object, object, object, object)
    """``(DesignResult, Spec, Core, Wire, Material)`` — calc succeeded."""

    failed = Signal(str)
    """User-facing error message — surfaced via ``QMessageBox``."""

    @Slot(object, object, object, object)
    def compute(self, spec: object, core: object, wire: object, material: object) -> None:
        """Run ``design()`` and emit the result.

        Errors are split into two buckets:

        - ``DesignError`` — expected validation failure (spec out of
          range, infeasible geometry, etc.). Routed to ``failed``
          with the user-friendly message so the GUI shows a
          ``QMessageBox`` mirroring the pre-thread behaviour.
        - Anything else — unexpected. Still routed to ``failed`` so
          the worker thread doesn't die silently, but with a generic
          "Unexpected calculation error" prefix so the user can tell
          this is a bug to file.
        """
        try:
            result = design(spec, core, wire, material)  # type: ignore[arg-type]
        except DesignError as e:
            self.failed.emit(e.user_message())
            return
        except Exception as e:  # pragma: no cover — defensive
            self.failed.emit(f"Unexpected calculation error: {e}")
            return
        self.finished.emit(result, spec, core, wire, material)


class MainWindow(QMainWindow):
    """The application's main window.

    Emits :attr:`design_completed` after every successful recompute so
    the workspace pages (and any future subscribers) can update from a
    single signal."""

    from PySide6.QtCore import Signal as _Signal

    design_completed = _Signal(object, object, object, object, object)
    """``Signal(DesignResult, Spec, Core, Wire, Material)``."""

    _calc_requested = _Signal(object, object, object, object)
    """Internal: emitted to enqueue a calc on the design worker thread.

    Connected to ``_DesignWorker.compute`` via ``QueuedConnection`` in
    ``_start_design_worker``. Using a signal (instead of
    ``QMetaObject.invokeMethod``) avoids the ``QMetaType`` registration
    requirement that fails for arbitrary Python objects like Pydantic
    models.
    """

    # ── Process-exit safety net ───────────────────────────────────
    # Mirrors the ``CascadePage`` pattern: ``aboutToQuit`` only fires
    # after ``QApplication.exec()`` returns, which never happens in
    # pytest (the test fixtures construct ``QApplication`` but never
    # run the event loop). Leaked MainWindow instances would then
    # have their design-worker thread destroyed by Qt mid-run at
    # process exit, triggering ``"QThread: Destroyed while thread is
    # still running"``. The atexit hook below catches that path
    # before Python GC starts tearing down Qt widgets.
    _live_instances: ClassVar[set[weakref.ReferenceType["MainWindow"]]] = set()
    _atexit_registered: ClassVar[bool] = False

    @classmethod
    def _shutdown_all_at_exit(cls) -> None:
        """atexit fallback — quit every live window's design thread."""
        for ref in list(cls._live_instances):
            win = ref()
            if win is None:
                continue
            try:
                win._shutdown_design_thread()
            except Exception:  # noqa: BLE001 — shutdown best-effort
                pass

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

    def __init__(self, *, defer_initial_calc: bool = True):
        """Construct the main shell window.

        ``defer_initial_calc`` controls whether the first
        ``_on_calculate()`` (and the FEA setup probe) run inside
        ``__init__`` or are deferred onto the Qt event queue via
        ``QTimer.singleShot(0, …)``. Production uses the default
        (``True``) so the window paints before ``design()`` burns
        500–3000 ms — without this, the splash sits visible for an
        extra second or three after the window is logically ready.

        Tests that construct ``MainWindow`` outside a running
        ``QApplication.exec()`` loop (i.e. without pumping events)
        can pass ``defer_initial_calc=False`` to keep the historical
        synchronous behaviour they assert against.
        """
        super().__init__()
        self.setWindowTitle("MagnaDesign — Inductor Design Suite")
        # Window geometry — sourced from ``theme.WindowGeometry`` so
        # density / responsive experiments don't need code edits
        # here. Defaults: 1500×900 open, 1100×640 minimum.
        wg = get_theme().window
        # Cap the default size to the available screen so the window
        # never opens larger than the desktop on small laptops (e.g.
        # 1366×768) — that was hiding the bottom Scoreboard on first
        # launch. We leave a 32 px margin for the OS taskbar / dock.
        try:
            from PySide6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                w = min(wg.default_w, max(960, avail.width() - 64))
                h = min(wg.default_h, max(wg.min_h, avail.height() - 64))
                self.resize(w, h)
            else:
                self.resize(wg.default_w, wg.default_h)
        except Exception:
            # Headless / offscreen: fall back to the canonical size.
            self.resize(wg.default_w, wg.default_h)

        # Cap the absolute minimum so child widgets' minimumSizeHints
        # don't cumulatively grow the window past the screen edge.
        # Without this, the ResumoStrip (6 metric tiles) + workspace
        # header (3 CTAs) summed to ~1540 px of mandatory width and
        # the right edge fell off any 1366- or 1440-wide laptop.
        # The token-defaulted floor (1100×640) keeps all child layouts
        # shrinkable via QScrollArea wrappers when the user *does* go
        # narrower than the floor.
        self.setMinimumSize(wg.min_w, wg.min_h)

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
            self._materials,
            self._cores,
            self._wires,
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
            self._materials,
            self._cores,
            self._wires,
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
        # accumulated slots survive). The annotation references
        # ``CompareDialog`` via ``TYPE_CHECKING`` so static checkers
        # see the concrete type while the runtime import stays lazy
        # inside ``_open_compare``.
        self._compare_dialog: Optional[CompareDialog] = None

        # Cached snapshot of the most recent successful design —
        # populated by ``_apply_design_result``. Reused by
        # ``current_compare_slot()`` so opening the compare dialog
        # doesn't re-run ``design()`` synchronously on the GUI
        # thread (the old behaviour froze the UI for 0.5–3 s every
        # time the user clicked Compare).
        self._last_design_snapshot: Optional[tuple[object, Spec, Core, Wire, Material]] = None

        # Design-worker thread state. The worker only spins up in
        # the deferred / async mode used by production; tests with
        # ``defer_initial_calc=False`` keep the synchronous path so
        # they don't need to pump the event queue between operations.
        self._async_recalc_enabled = defer_initial_calc
        self._design_thread: Optional[QThread] = None
        self._design_worker: Optional[_DesignWorker] = None
        # Coalescing: at most one in-flight + one queued. If the
        # user changes the spec while a calc is running, the queued
        # request is replaced (not appended) so we always converge
        # on the freshest inputs rather than racing through stale
        # intermediate values.
        self._calc_in_flight = False
        self._calc_pending_inputs: Optional[tuple[Spec, Core, Wire, Material]] = None

        if self._async_recalc_enabled:
            self._start_design_worker()
            # Connect to ``QApplication.aboutToQuit`` so the worker
            # thread is shut down BEFORE Qt destroys widget children.
            # See ``_shutdown_design_thread`` docstring for the
            # rationale (Cmd+Q on macOS bypasses ``closeEvent``).
            _app = QApplication.instance()
            if _app is not None:
                _app.aboutToQuit.connect(self._shutdown_design_thread)

            # Process-exit safety net — see ``_live_instances``
            # comment above for why ``aboutToQuit`` isn't enough
            # under pytest. Tracks this instance via weakref and
            # installs the global atexit hook once.
            MainWindow._live_instances.add(weakref.ref(self))
            if not MainWindow._atexit_registered:
                atexit.register(MainWindow._shutdown_all_at_exit)
                MainWindow._atexit_registered = True

        # Initial calculation + FEA setup probe. In production we
        # defer both onto the next event-loop tick so ``__init__``
        # returns immediately and Qt can paint the main window
        # BEFORE we burn 500–3000 ms on ``design()`` + FEMMT import
        # probing. Without this defer the user sees the splash for
        # an extra second or three after the window is logically
        # ready, because Qt waits for the first paint event before
        # swapping splash → window, and the first paint can't
        # happen until ``__init__`` returns. The deferred sequence
        # is: ``__init__`` returns → window paints → event loop
        # ticks → first calc runs → KPIs populate.
        #
        # ``QTimer.singleShot(0, …)`` queues the call on the main
        # thread's event queue, NOT a worker thread, so it's safe
        # to touch widgets directly from inside the deferred
        # callbacks (which is what ``_on_calculate`` does — it
        # mutates the spec drawer, KPI strip, nucleo combos, etc.).
        if defer_initial_calc:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, self._on_calculate)
            QTimer.singleShot(0, self._maybe_offer_fea_setup)
        else:
            # Tests that construct ``MainWindow`` outside a running
            # event loop opt out via ``defer_initial_calc=False``
            # so they don't have to pump ``app.processEvents()``
            # between construction and their first assertion.
            self._on_calculate()
            self._maybe_offer_fea_setup()

    # ==================================================================
    # Lifecycle — clean worker thread shutdown on close
    # ==================================================================
    def _shutdown_design_thread(self) -> None:
        """Quit + wait on the design worker thread. Idempotent.

        Wired to both ``closeEvent`` (user clicks X / calls
        ``win.close()``) and ``QApplication.aboutToQuit`` (Cmd+Q on
        macOS, session-end on Linux). The latter is the path that
        actually catches process-shutdown — Qt destroys widgets as
        children of ``QApplication`` without invoking ``closeEvent``
        first, so without an ``aboutToQuit`` hook we'd hit
        ``QThread::~QThread()`` while the thread is still running
        and Qt would ``abort()`` the whole process (the v0.4.x
        Cmd+Q crash with the "method implementation was set
        dynamically" objc trap fingerprint in the report).
        """
        if self._design_thread is not None and self._design_thread.isRunning():
            self._design_thread.quit()
            self._design_thread.wait(2000)
        # Restore the cursor unconditionally in case a calc was in
        # flight at close time — the override stack is application-
        # wide and would otherwise leak into the next dialog.
        QApplication.restoreOverrideCursor()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """Tear down the design worker thread before closing."""
        self._shutdown_design_thread()
        super().closeEvent(event)

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
        self._cmd_palette.register_many(
            [
                # Project lifecycle
                Command(
                    "project.new",
                    "New project",
                    "Ctrl+N",
                    self._on_project_new,
                    hint="Clears the current session after confirmation.",
                ),
                Command(
                    "project.open",
                    "Open project…",
                    "Ctrl+O",
                    self._on_project_open,
                    hint="Reads a .pfc file from disk.",
                ),
                Command("project.save", "Save project", "Ctrl+S", self._on_project_save),
                Command(
                    "project.save_as", "Save project as…", "Ctrl+Shift+S", self._on_project_save_as
                ),
                # Inner-loop actions
                Command(
                    "calc",
                    "Recalculate",
                    "Ctrl+R",
                    self._on_calculate,
                    hint="Runs the engine with the current spec + selection.",
                ),
                Command(
                    "export.report",
                    "Export datasheet (HTML)",
                    "",
                    self._export_report,
                    hint="Generates a 3-page HTML datasheet (base64-embedded).",
                ),
                Command(
                    "export.report_pdf",
                    "Export datasheet (PDF)",
                    "",
                    self._export_report_pdf,
                    hint="Native PDF (vector text, embedded font, deterministic page breaks).",
                ),
                Command(
                    "export.project_pdf",
                    "Export project report (PDF)",
                    "",
                    self._export_project_report,
                    hint="Engineering report — theory, equations, "
                    "and worked calculations per topology.",
                ),
                Command(
                    "export.compare",
                    "Export comparison",
                    "",
                    self._export_compare,
                    hint="Saves the comparison table as HTML or CSV.",
                ),
                Command(
                    "compare.open",
                    "Open comparison",
                    "",
                    self._open_compare,
                    hint="Stack up to 4 designs side by side.",
                ),
                # Validation / dialogs
                Command(
                    "validate.fea",
                    "Run FEM validation",
                    "",
                    self._open_fea,
                    hint="FEMM / FEMMT on the operating point — takes minutes.",
                ),
                Command("similar", "Find similar components", "", self._open_similar_parts),
                Command("litz", "Optimize Litz", "", self._open_litz),
                # Shell
                Command("theme.toggle", "Toggle theme (light / dark)", "", self._toggle_theme),
                Command("about", "About the application", "", self._open_about),
                # Navigation — quick jumps so users don't reach for the
                # mouse mid-flow.
                Command("nav.projeto", "Go to Project", "", lambda: self._goto_area("dashboard")),
                Command(
                    "nav.otimizador", "Go to Optimizer", "", lambda: self._goto_area("otimizador")
                ),
                Command(
                    "nav.cascade", "Go to Full optimizer", "", lambda: self._goto_area("cascade")
                ),
                Command("nav.catalogo", "Go to Catalog", "", lambda: self._goto_area("catalogo")),
                Command(
                    "nav.config", "Go to Settings", "", lambda: self._goto_area("configuracoes")
                ),
            ]
        )
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
            (
                "dashboard",
                "Project",
                "Ctrl+1",
                "Main workspace — spec, core, analysis, validation, export.",
            ),
            (
                "otimizador",
                "Optimizer",
                "Ctrl+2",
                "Fast Pareto sweep (≈30 s) — losses × volume × cost.",
            ),
            (
                "cascade",
                "Full optimizer",
                "Ctrl+3",
                "Multi-tier cascade with RK4 + FEM (≈5–15 min).",
            ),
            ("catalogo", "Catalog", "Ctrl+4", "Edit materials, cores and wires. MAS import."),
            ("configuracoes", "Settings", "Ctrl+5", "Theme, FEA, Litz, project information."),
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

        # Renamed from "Configure FEA..." — users searching the menu
        # for "install" / "download" weren't finding it. The new
        # label spells out exactly what the dialog does (download
        # ONELAB if missing, write the FEMMT config). Keeping it
        # in the Tools menu means even after the user dismisses
        # the auto-popup at startup, they can still trigger the
        # install flow manually here.
        act_setup = QAction("Install / configure FEA backend...", self)
        act_setup.setStatusTip(
            "Download ONELAB (gmsh + getdp) and wire FEMMT against it. "
            "Run this if the FEA dialog reports a missing solver."
        )
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

        help_menu.addSeparator()

        # Auto-update — opt-in. Manual "Check for updates…" runs
        # ``updater.check_for_updates`` on demand; the toggle
        # below persists a preference in QSettings that the
        # MainWindow's startup hook reads on next launch.
        self._act_check_updates = QAction("Check for updates…", self)
        self._act_check_updates.triggered.connect(
            self._on_check_for_updates,
        )
        help_menu.addAction(self._act_check_updates)

        self._act_auto_check = QAction(
            "Automatically check at startup",
            self,
        )
        self._act_auto_check.setCheckable(True)
        self._act_auto_check.setChecked(self._auto_check_enabled())
        self._act_auto_check.toggled.connect(self._set_auto_check)
        help_menu.addAction(self._act_auto_check)

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
            # ``rel.as_posix()`` forces forward slashes on every OS;
            # without it the recents menu on Windows shows the
            # cosmetically ugly ``~/sub\path\file.pfc`` mix because
            # ``str(rel)`` uses ``os.sep`` which is ``\`` there.
            return f"~/{rel.as_posix()}"
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

    def _on_history_restore(self, snapshot) -> None:
        """Restore a snapshot from the history timeline.

        Builds an in-memory :class:`ProjectFile` from the snapshot's
        recorded spec + selection IDs, then routes it through the
        existing ``_apply_project`` machinery — same code path that
        loads a ``.pfc`` file from disk. The recalc runs once,
        appending a *new* snapshot to the timeline (so the user
        can branch off the restored point and still walk back if
        needed). The history feature stays append-only — restoring
        never destroys earlier rows.
        """
        try:
            from pfc_inductor.models import Spec
            from pfc_inductor.project import ProjectFile, ProjectSelection

            # ``snapshot.spec`` is a JSON-derived dict; rehydrate
            # it through Pydantic so any partial / forward-compat
            # field gets clamped to a valid Spec instance. Same
            # safety net ``load_project`` provides for .pfc files.
            spec = Spec(**snapshot.spec)
            sel = snapshot.selection or {}
            state = ProjectFile(
                version="1.0",
                name=snapshot.project or "Restored snapshot",
                spec=spec,
                selection=ProjectSelection(
                    material_id=sel.get("material_id", ""),
                    core_id=sel.get("core_id", ""),
                    wire_id=sel.get("wire_id", ""),
                ),
            )
            self._apply_project(state)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "Restore failed",
                f"Could not restore snapshot {snapshot.id}: {type(e).__name__}: {e}",
            )

    def _on_project_new(self) -> None:
        if not self._confirm_discard("New project"):
            return
        self._apply_project(empty_state())
        self._project_path = None

    def _on_project_open(self) -> None:
        if not self._confirm_discard("Open project"):
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open project",
            "",
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
                self,
                "Failed to open project",
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
            self,
            "Save project as",
            suggested,
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
                self,
                "Failed to save",
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
            self,
            title,
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
            self._RECENTS_KEY,
            json.dumps(recents),
        )

    def _clear_recents(self) -> None:
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(
            self._RECENTS_KEY,
            "[]",
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
        self.stack.addWidget(self.projeto_page)  # 0 dashboard
        self.stack.addWidget(self.otimizador_page)  # 1 otimizador
        self.stack.addWidget(self.cascade_page)  # 2 cascade
        self.stack.addWidget(self.catalogo_page)  # 3 catalogo
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
        self.projeto_page.export_pdf_requested.connect(
            self._export_report_pdf,
        )
        self.projeto_page.export_project_pdf_requested.connect(
            self._export_project_report,
        )
        self.projeto_page.export_compare_requested.connect(
            self._export_compare,
        )
        self.projeto_page.history_restore_requested.connect(
            self._on_history_restore,
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
        # Multi-row Compare → open the global CompareDialog with the
        # picked sweep results pre-populated as slots. The optimizer
        # produces ``SweepResult`` objects which carry spec + core +
        # wire + material + DesignResult — exactly the payload a
        # ``CompareSlot`` needs.
        self.otimizador_page.compare_requested.connect(
            self._open_compare_with_sweep_results,
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
            "about": self._open_about,
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
            unsaved=s.unsaved,
            last_saved_at=s.last_saved_at,
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
        from pfc_inductor.ui.dialogs import TopologyPickerDialog

        sp = self.projeto_page.spec_panel
        try:
            current = sp.topology()
            n_phases = sp.n_phases()
        except (ValueError, TypeError, AttributeError):
            current = "boost_ccm"
            n_phases = 1
        # SpecPanel may not expose ``n_interleave`` yet on older
        # spec-panel revisions; fall back to 2 (default phase count
        # for interleaved boost) when the accessor is missing.
        try:
            n_interleave = sp.n_interleave()
        except (ValueError, TypeError, AttributeError):
            n_interleave = 2
        dlg = TopologyPickerDialog(
            current=current,
            n_phases=int(n_phases),
            n_interleave=int(n_interleave),
            parent=self,
        )
        if dlg.exec() != TopologyPickerDialog.DialogCode.Accepted:
            return
        new_key = dlg.selected_key()
        new_phases = dlg.selected_n_phases()
        new_interleave = dlg.selected_n_interleave()
        # ``set_topology`` is the single SpecPanel-side setter — it
        # toggles the line-reactor / interleaved block visibility and
        # emits ``changed`` / ``topology_changed`` (the drawer button
        # label listens to the latter).
        sp.set_topology(
            new_key,
            n_phases=new_phases,
            n_interleave=new_interleave,
        )
        self._on_calculate()

    def _open_optimizer(self) -> None:
        from pfc_inductor.ui.optimize_dialog import OptimizerDialog

        try:
            spec, _core, _wire, _material = self._collect_inputs()
        except DesignError as e:
            QMessageBox.warning(self, "Invalid spec", e.user_message())
            return
        # Same per-topology filter the inline pages use — the modal
        # optimizer should not surface line-frequency reactor candidates
        # built on switching-frequency powder cores (or vice-versa).
        eligible_materials = materials_for_topology(
            self._materials,
            spec.topology,
        )
        dlg = OptimizerDialog(
            spec,
            eligible_materials,
            self._cores,
            self._wires,
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
            (f"datasheet_{core.part_number}_{material.name}.html")
            .replace(" ", "_")
            .replace("/", "-")
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save datasheet",
            default_name,
            "HTML files (*.html)",
        )
        if not path:
            return
        from pfc_inductor.report import generate_datasheet

        try:
            out = generate_datasheet(spec, core, material, wire, result, path)
        except (OSError, ValueError, KeyError) as e:
            err = ReportGenerationError(
                f"Failed to generate the datasheet: {e}",
                hint=f"Check write permission for\n{path}",
            )
            QMessageBox.critical(
                self,
                "Datasheet generation failed",
                err.user_message(),
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

    def _export_report_pdf(self) -> None:
        """Native PDF datasheet (ReportLab + matplotlib).

        Mirrors ``_export_report`` (HTML) — same gather/design/save/toast
        flow, different output format. PDF is the print/customer
        artefact (vector text, embedded Inter font, deterministic page
        breaks); HTML is the screen-grade preview.
        """
        from PySide6.QtWidgets import QFileDialog

        try:
            spec, core, wire, material = self._collect_inputs()
            result = design(spec, core, wire, material)
        except DesignError as e:
            QMessageBox.warning(self, "Error", e.user_message())
            return
        default_name = (
            (f"datasheet_{core.part_number}_{material.name}.pdf")
            .replace(" ", "_")
            .replace("/", "-")
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save datasheet (PDF)",
            default_name,
            "PDF files (*.pdf)",
        )
        if not path:
            return
        from pfc_inductor.report import generate_pdf_datasheet

        try:
            out = generate_pdf_datasheet(
                spec,
                core,
                material,
                wire,
                result,
                path,
            )
        except (OSError, ValueError, KeyError) as e:
            err = ReportGenerationError(
                f"Failed to generate the PDF datasheet: {e}",
                hint=f"Check write permission for\n{path}",
            )
            QMessageBox.critical(
                self,
                "PDF datasheet generation failed",
                err.user_message(),
            )
            return
        # Same post-export side effects as HTML — mark workspace clean,
        # advance the Next Steps card, transient toast with "Open"
        # action that hands the file off to the OS default PDF viewer.
        self._workflow_state.mark_saved()
        self.projeto_page.mark_action_done("report")
        from pfc_inductor.ui.widgets.toast import Toast

        Toast.show_message(
            self,
            f"PDF datasheet saved to {out}",
            action_label="Open",
            action=lambda p=str(out): self._open_path_externally(p),
        )

    def _export_project_report(self) -> None:
        """Engineering project report (PDF).

        Different artefact from the datasheet: walks the design
        derivation step-by-step (theory paragraphs, symbolic
        equations, substituted values, computed result) per
        topology. Engineers file this in their internal project-
        tracking systems.
        """
        from PySide6.QtWidgets import QFileDialog

        try:
            spec, core, wire, material = self._collect_inputs()
            result = design(spec, core, wire, material)
        except DesignError as e:
            QMessageBox.warning(self, "Error", e.user_message())
            return
        # File name leads with "project_" so the dataheet and
        # project report don't collide in the same folder.
        default_name = (
            (f"project_{core.part_number}_{material.name}.pdf").replace(" ", "_").replace("/", "-")
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save project report (PDF)",
            default_name,
            "PDF files (*.pdf)",
        )
        if not path:
            return
        from pfc_inductor.report import generate_project_report

        try:
            # The optional ``project_id`` falls back to the same
            # spec/core/material hash the datasheet uses for its
            # P/N — so the two artefacts cross-reference.
            out = generate_project_report(
                spec,
                core,
                material,
                wire,
                result,
                path,
                designer=self._workflow_state.project_name or "—",
            )
        except (OSError, ValueError, KeyError) as e:
            err = ReportGenerationError(
                f"Failed to generate the project report: {e}",
                hint=f"Check write permission for\n{path}",
            )
            QMessageBox.critical(
                self,
                "Project report generation failed",
                err.user_message(),
            )
            return
        self._workflow_state.mark_saved()
        self.projeto_page.mark_action_done("report")
        from pfc_inductor.ui.widgets.toast import Toast

        Toast.show_message(
            self,
            f"Project report saved to {out}",
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
                self,
                "Comparison empty",
                "Add at least 2 designs to the comparison before "
                "exporting. I'll open the window now — use \"Add "
                'current" to populate it.',
            )
            self._open_compare()
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export comparison",
            "comparison.pdf",
            "PDF (*.pdf);;HTML (*.html);;CSV (*.csv)",
        )
        if not path:
            return
        try:
            # Format chosen from the file extension. PDF is the
            # default (most users want the print-grade artefact);
            # CSV stays as the data-export option for spreadsheets;
            # HTML is the screen preview.
            lower = path.lower()
            if lower.endswith(".csv"):
                out = dlg.export_csv_to(path)
            elif lower.endswith(".html") or lower.endswith(".htm"):
                out = dlg.export_html_to(path)
            else:
                out = dlg.export_pdf_to(path)
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        QMessageBox.information(
            self,
            "Exported",
            f"Comparison saved to:\n{out}",
        )

    def _open_db_editor(self) -> None:
        from pfc_inductor.ui.db_editor import DbEditorDialog

        dlg = DbEditorDialog(parent=self)
        dlg.saved.connect(self._reload_databases)
        dlg.exec()

    def _open_catalog_update(self) -> None:
        from pfc_inductor.ui.catalog_dialog import CatalogUpdateDialog

        dlg = CatalogUpdateDialog(parent=self)
        dlg.completed.connect(self._reload_databases)
        dlg.exec()

    def _open_setup_deps(self) -> None:
        from pfc_inductor.ui.setup_dialog import SetupDepsDialog

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

    # QSettings key for "user explicitly dismissed the FEA setup
    # prompt — don't auto-show it again". Cleared automatically once
    # ``check_fea_setup`` reports ``fea_ready`` (the install
    # eventually succeeded), so the flag re-enables itself if the
    # user breaks their ONELAB install later. Manual access via the
    # menu (Configurações → Setup FEA) always works regardless.
    _FEA_SETUP_DISMISSED_KEY = "fea/setup_dismissed"

    def _offer_fea_setup_now(self) -> None:
        # ``check_fea_setup`` lives in ``pfc_inductor.setup_deps`` which
        # imports requests / tarfile / hashlib + the platform detection
        # helpers — none of that needs to load until we actually want to
        # check. Lazy import keeps cold-start fast.
        from pfc_inductor.setup_deps import check_fea_setup
        from pfc_inductor.ui.setup_dialog import SetupDepsDialog

        try:
            v = check_fea_setup()
        except (OSError, RuntimeError):
            return
        # FEA already wired up — clear any stale "dismissed" flag so
        # the prompt re-arms if a future install breaks.
        if v.fea_ready:
            settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
            if settings.value(self._FEA_SETUP_DISMISSED_KEY, False, type=bool):
                settings.setValue(self._FEA_SETUP_DISMISSED_KEY, False)
            return
        # User dismissed the prompt at some prior launch — don't
        # nag again. They can still trigger it manually from the
        # Configurações menu.
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        if settings.value(self._FEA_SETUP_DISMISSED_KEY, False, type=bool):
            return
        dlg = SetupDepsDialog(parent=self)
        result = dlg.exec()
        # Persist the dismissal when:
        #   - the user closed the dialog without completing setup
        #     (``QDialog.Rejected`` from Cancel/Esc/window-close), OR
        #   - the dialog ran but FEA still isn't ready (the install
        #     errored — re-prompting on every launch isn't useful,
        #     the user already knows).
        try:
            v_after = check_fea_setup()
        except (OSError, RuntimeError):
            v_after = None
        from PySide6.QtWidgets import QDialog

        rejected = result == QDialog.DialogCode.Rejected
        still_not_ready = v_after is None or not v_after.fea_ready
        if rejected or still_not_ready:
            settings.setValue(self._FEA_SETUP_DISMISSED_KEY, True)

    def _open_about(self) -> None:
        from pfc_inductor.ui.about_dialog import AboutDialog

        dlg = AboutDialog(parent=self)
        dlg.exec()

    # ───── Auto-update (opt-in, see ``pfc_inductor.updater``) ─────

    _AUTO_CHECK_KEY = "updates/auto_check_at_startup"

    def _auto_check_enabled(self) -> bool:
        """Read the persisted "auto-check at startup" preference.

        Default is ``False`` — explicit opt-in only. Mirrors
        the same privacy stance the crash reporter takes.
        """
        try:
            from PySide6.QtCore import QSettings

            settings = QSettings("MagnaDesign", "MagnaDesign")
            raw = settings.value(self._AUTO_CHECK_KEY, False)
        except Exception:
            return False
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in {"true", "1", "yes", "on"}
        return bool(raw)

    def _set_auto_check(self, enabled: bool) -> None:
        from PySide6.QtCore import QSettings

        settings = QSettings("MagnaDesign", "MagnaDesign")
        settings.setValue(self._AUTO_CHECK_KEY, bool(enabled))
        settings.sync()

    def _on_check_for_updates(self) -> None:
        """Manual "Check for updates…" trigger.

        Runs the network probe on a worker thread so the GUI
        stays responsive (the appcast fetch has a 10 s timeout
        and DNS / TLS / 4xx all degrade to "no update available"
        — see ``updater.client.check_for_updates``). Result lands
        on the GUI thread via a Qt signal.
        """
        from PySide6.QtCore import QObject, QThread, Signal
        from PySide6.QtWidgets import QMessageBox

        from pfc_inductor.updater import UpdateInfo, check_for_updates

        # Inline a minimal worker so the import cost stays in the
        # menu-handler path (the updater module has no Qt dep).
        class _Worker(QObject):
            done = Signal(object)  # UpdateInfo | None

            def run(self) -> None:
                info = check_for_updates()
                self.done.emit(info)

        thread = QThread(self)
        worker = _Worker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def _on_done(info) -> None:
            # Non-blocking thread quit — ``thread.wait()`` here would
            # freeze the GUI for up to 1 s on a busy system. We just
            # ask the thread to quit; ``thread.finished`` (wired to
            # ``deleteLater`` below) handles the cleanup async.
            thread.quit()
            if info is None:
                QMessageBox.information(
                    self,
                    "MagnaDesign — Check for updates",
                    "You're running the latest version.",
                )
                return
            assert isinstance(info, UpdateInfo)
            url = info.latest.download_url or "(no download URL)"
            notes = info.latest.description_html or ""
            # Truncate long release notes so the dialog stays
            # readable; the user can click through to the URL
            # for the full text.
            if len(notes) > 800:
                notes = notes[:800].rstrip() + "…"
            text = (
                f"Version {info.latest.version} is available.\n"
                f"You are running {info.current_version}.\n\n"
                f"{notes}\n\n"
                f"Download: {url}"
            )
            QMessageBox.information(
                self,
                "MagnaDesign — Update available",
                text,
            )

        worker.done.connect(_on_done)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def current_compare_slot(self) -> CompareSlot:
        """Return the latest design as a ``CompareSlot``.

        Reuses ``_last_design_snapshot`` when available so the
        compare-dialog open is instant. Falls back to a synchronous
        ``design()`` only on the first call (before ``_on_calculate``
        has had a chance to run, e.g. if the user clicks Compare
        before the deferred initial calc completes); in practice
        that path is exercised only by tests.
        """
        if self._last_design_snapshot is not None:
            result, spec, core, wire, material = self._last_design_snapshot
            return CompareSlot(
                spec=spec,
                core=core,
                wire=wire,
                material=material,
                result=result,  # pyright: ignore[reportArgumentType]
            )

        # Cold-cache fallback. Synchronous because the caller (the
        # compare dialog) expects the slot to exist immediately.
        spec, core, wire, material = self._collect_inputs()
        result = design(spec, core, wire, material)
        # Populate the cache so subsequent calls hit the fast path.
        self._last_design_snapshot = (result, spec, core, wire, material)
        return CompareSlot(
            spec=spec,
            core=core,
            wire=wire,
            material=material,
            result=result,
        )

    def _open_compare(self) -> None:
        if self._compare_dialog is None:
            from pfc_inductor.ui.compare_dialog import CompareDialog

            self._compare_dialog = CompareDialog(parent=self)
            self._compare_dialog.selection_applied.connect(
                self._apply_compare_choice,
            )
        self._compare_dialog.show()
        self._compare_dialog.raise_()

    def _open_compare_with_sweep_results(self, picked: list) -> None:
        """Pre-populate the CompareDialog with rows the user picked
        in the optimizer table.

        ``picked`` is a ``list[SweepResult]`` — same shape the
        optimizer's table model holds. Each one converts trivially to
        a ``CompareSlot``: spec is the active project spec, the rest
        comes straight off the sweep result.
        """
        self._open_compare()
        if self._compare_dialog is None:
            return
        # The current spec is whatever the user has typed in the spec
        # drawer at the moment they hit Compare. The sweep results
        # were computed against that same spec, so it's the right
        # reference for the slots.
        try:
            spec, _core, _wire, _material = self._collect_inputs()
        except Exception:
            return
        for sr in picked:
            try:
                slot = CompareSlot(
                    spec=spec,
                    core=sr.core,
                    wire=sr.wire,
                    material=sr.material,
                    result=sr.result,
                )
                self._compare_dialog.add_slot(slot)
            except Exception:
                # Skip a malformed sweep row rather than abort the
                # whole batch — partial Compare is better than none.
                continue

    def _apply_compare_choice(self, material_id: str, core_id: str, wire_id: str) -> None:
        self._apply_optimizer_choice(material_id, core_id, wire_id)

    def _open_litz(self) -> None:
        from pfc_inductor.ui.litz_dialog import LitzOptimizerDialog

        try:
            spec, core, _wire, material = self._collect_inputs()
        except DesignError as e:
            QMessageBox.warning(self, "Invalid selection", e.user_message())
            return
        dlg = LitzOptimizerDialog(spec, core, material, self._wires, parent=self)
        dlg.wire_saved.connect(lambda _wid: self._reload_databases())
        dlg.exec()

    def _open_fea(self) -> None:
        # FEA dialog pulls the heaviest dependency tree on the
        # whole app (FEMMT 0.5 + ONELAB shim + the FEA-validation
        # chart widget that imports matplotlib's QtAgg backend).
        # Loading it lazily keeps the main window's first paint
        # snappy — the user only pays the cost when they click
        # "Validate (FEA)".
        #
        # Re-run the ONELAB path injection here so the case where
        # the user installed ONELAB *during this session* (via the
        # auto-popping setup dialog earlier) doesn't leave FEMMT
        # crashing with ``ModuleNotFoundError: No module named
        # 'onelab'`` when the FEA dialog opens. ``ensure_onelab_on_path``
        # is idempotent — adding the path twice is a no-op.
        try:
            from pfc_inductor.setup_deps import ensure_onelab_on_path

            ensure_onelab_on_path()
        except Exception:
            pass

        from pfc_inductor.ui.fea_dialog import FEAValidationDialog

        try:
            slot = self.current_compare_slot()
        except DesignError as e:
            QMessageBox.warning(self, "Invalid selection", e.user_message())
            return
        dlg = FEAValidationDialog(
            slot.spec,
            slot.core,
            slot.wire,
            slot.material,
            slot.result,
            parent=self,
        )
        dlg.exec()

    def _open_similar_parts(self) -> None:
        from pfc_inductor.ui.similar_parts_dialog import SimilarPartsDialog

        try:
            target_core = self._calc.find_core(self._current_core_id)
            target_material = self._calc.find_material(self._current_material_id)
        except DesignError as e:
            QMessageBox.warning(self, "Invalid selection", e.user_message())
            return
        dlg = SimilarPartsDialog(
            target_core,
            target_material,
            self._cores,
            self._materials,
            parent=self,
        )
        dlg.selection_applied.connect(self._apply_similar_selection)
        dlg.exec()

    def _apply_similar_selection(self, material_id: str, core_id: str) -> None:
        self._current_material_id = material_id
        self._current_core_id = core_id
        self._on_calculate()

    def _reload_databases(self) -> None:
        self._materials = load_materials()
        self._cores = load_cores()
        self._wires = load_wires()
        self._calc.replace_catalogs(
            self._materials,
            self._cores,
            self._wires,
        )
        # TODO: re-validate that the current selection is still valid,
        # or pick a new default. For now, just trigger a recalc.
        self._on_calculate()

    def _apply_optimizer_choice(self, material_id: str, core_id: str, wire_id: str) -> None:
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

    # ------------------------------------------------------------------
    # Design-worker plumbing — keeps the heavy ``design()`` call off
    # the GUI thread so the spec drawer stays responsive on rapid
    # parameter sweeps and large topologies (~3 s on cascade-eligible
    # cores).
    # ------------------------------------------------------------------
    def _start_design_worker(self) -> None:
        """Construct + start the long-lived design worker thread.

        Called once from ``__init__`` in production. Tests using
        ``defer_initial_calc=False`` skip this and run ``design()``
        synchronously inside ``_on_calculate`` — that path needs no
        worker thread, no signal marshaling, and no event-queue
        pumping, which matches the historical test contract.
        """
        self._design_thread = QThread(self)
        self._design_thread.setObjectName("pfc-design-worker")
        self._design_worker = _DesignWorker()
        self._design_worker.moveToThread(self._design_thread)
        # Both signals must be ``QueuedConnection`` so the slot
        # runs on the GUI thread (where it can mutate widgets).
        # ``AutoConnection`` would also work here (Qt picks Queued
        # because sender and receiver are in different threads),
        # but explicit is safer — it documents intent and survives
        # future refactors that might move the worker to a different
        # thread.
        self._design_worker.finished.connect(
            self._on_design_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._design_worker.failed.connect(
            self._on_design_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        # Main thread → worker: emitting ``_calc_requested`` from the
        # main thread enqueues a ``compute`` call on the worker's event
        # loop. ``QueuedConnection`` is explicit because the slot lives
        # in a different thread; ``AutoConnection`` would also pick
        # Queued here, but explicit beats implicit when threading is
        # involved.
        self._calc_requested.connect(
            self._design_worker.compute,
            Qt.ConnectionType.QueuedConnection,
        )
        self._design_thread.start()

    def _dispatch_calc(self, spec: Spec, core: Core, wire: Wire, material: Material) -> None:
        """Send a calc request to the worker thread.

        Emits ``_calc_requested`` rather than calling
        ``self._design_worker.compute(...)`` directly so the call
        crosses thread boundaries safely via Qt's ``QueuedConnection``.
        See the ``_DesignWorker`` docstring for why we route through a
        signal instead of ``QMetaObject.invokeMethod``.
        """
        assert self._design_worker is not None, "worker not started"
        self._calc_requested.emit(spec, core, wire, material)

    @Slot(object, object, object, object, object)
    def _on_design_finished(
        self,
        result: object,
        spec: object,
        core: object,
        wire: object,
        material: object,
    ) -> None:
        """Worker emitted ``finished`` — apply on the GUI thread."""
        # The Slot decorator types these as ``object`` to match the
        # Signal signature; the runtime types are guaranteed by the
        # worker's contract.
        self._apply_design_result(
            result,
            spec,  # pyright: ignore[reportArgumentType]
            core,  # pyright: ignore[reportArgumentType]
            wire,  # pyright: ignore[reportArgumentType]
            material,  # pyright: ignore[reportArgumentType]
        )
        self._calc_in_flight = False
        self._set_recalc_busy(False)
        # If the user changed the spec while we were running, fire
        # the queued recalc against the freshest inputs. Older
        # queued requests were already dropped at enqueue time.
        if self._calc_pending_inputs is not None:
            pending = self._calc_pending_inputs
            self._calc_pending_inputs = None
            self._calc_in_flight = True
            self._set_recalc_busy(True)
            self._dispatch_calc(*pending)

    @Slot(str)
    def _on_design_failed(self, message: str) -> None:
        """Worker emitted ``failed`` — surface the error on the GUI."""
        self._calc_in_flight = False
        self._set_recalc_busy(False)
        QMessageBox.warning(self, "Calculation error", message)
        # Drop any pending request so we don't immediately re-fail
        # against (likely) the same inputs. The user can retry by
        # touching the spec again.
        self._calc_pending_inputs = None

    def _set_recalc_busy(self, busy: bool) -> None:
        """Visual feedback for an in-flight worker recalc.

        Uses a Qt override cursor for now — the spec drawer keeps
        the previous design's KPIs visible (rather than blanking)
        so the user has a clear ``before / after`` reference. If
        the busy-cursor proves too subtle in user testing we can
        wire a dedicated indicator into the scoreboard later
        without touching the worker plumbing.
        """
        if busy:
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        else:
            QApplication.restoreOverrideCursor()

    def _apply_design_result(
        self,
        result,  # type: ignore[no-untyped-def]
        spec: Spec,
        core: Core,
        wire: Wire,
        material: Material,
    ) -> None:
        """Mutate the GUI from a successful ``design()`` result.

        Always runs on the main thread (either directly from the
        synchronous code path or via a ``QueuedConnection`` slot).
        """
        # Filter the material catalogue by the current topology so
        # downstream pages (core selection, optimizer, cascade)
        # don't waste time evaluating materials that make no
        # engineering sense for the chosen converter — e.g. a line
        # reactor at 60 Hz has no business iterating over 241 powder
        # cores designed for 20–200 kHz switching.
        eligible_materials = materials_for_topology(
            self._materials,
            spec.topology,
        )

        # Update the project workspace with the new result.
        self.projeto_page.update_from_design(
            result,
            spec,
            core,
            wire,
            material,
        )
        self.projeto_page.populate_nucleo(
            spec,
            eligible_materials,
            self._cores,
            self._wires,
            material,
            core,
            wire,
        )
        self.projeto_page.set_current_selection(material, core, wire)
        self.otimizador_page.set_inputs(
            spec,
            eligible_materials,
            self._cores,
            self._wires,
            material.id,
        )
        # Cascade page mirrors the same DB + spec; running a deep
        # sweep doesn't depend on the engineer's current core /
        # wire / material selection — the cascade explores the
        # whole catalogue.
        self.cascade_page.set_inputs(
            spec,
            eligible_materials,
            self._cores,
            self._wires,
        )

        # Cache the snapshot so ``current_compare_slot()`` and any
        # other downstream consumer can read the fresh design state
        # without paying for another ``design()`` call.
        self._last_design_snapshot = (result, spec, core, wire, material)

        # Emit for subscribers (tests, future plug-ins).
        self.design_completed.emit(result, spec, core, wire, material)

    def _on_calculate(self) -> None:
        """Recompute the design from the current spec / core / wire / material.

        Production (``_async_recalc_enabled``): dispatches ``design()``
        to the worker thread; result lands via ``_on_design_finished``.
        Rapid re-triggers (e.g. user dragging a slider) coalesce —
        the current calc completes uninterrupted, and exactly one
        queued recalc fires after it against the latest inputs.

        Test path (``_async_recalc_enabled=False``): runs synchronously
        inline so tests that don't ``app.exec()`` see the state mutate
        before returning. Matches the historical contract of
        construction-time ``_on_calculate``.
        """
        if not self._async_recalc_enabled:
            try:
                spec, core, wire, material = self._collect_inputs()
                result = design(spec, core, wire, material)
            except DesignError as e:
                QMessageBox.warning(self, "Calculation error", e.user_message())
                return
            self._apply_design_result(result, spec, core, wire, material)
            return

        # Async path. Input collection is cheap (<1 ms) and stays
        # on the main thread; only ``design()`` itself is heavy.
        try:
            spec, core, wire, material = self._collect_inputs()
        except DesignError as e:
            QMessageBox.warning(self, "Calculation error", e.user_message())
            return

        if self._calc_in_flight:
            # A calc is already running. Save these inputs as the
            # latest pending; the previous pending (if any) is
            # discarded — we always converge on the freshest values
            # rather than racing through stale intermediates.
            self._calc_pending_inputs = (spec, core, wire, material)
            return

        self._calc_in_flight = True
        self._set_recalc_busy(True)
        self._dispatch_calc(spec, core, wire, material)
