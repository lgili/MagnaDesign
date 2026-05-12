"""Optimizer: sweep cores × wires for the selected material, show Pareto.

Two surfaces:

- :class:`OptimizerEmbed` — a ``QWidget`` containing the entire
  optimizer body (controls, table, plot, "Apply" button). Mountable
  in any page; used by the v3 :class:`OtimizadorPage
  <pfc_inductor.ui.workspace.otimizador_page.OtimizadorPage>`.

- :class:`OptimizerDialog` — modal wrapper that composes
  ``OptimizerEmbed`` plus a ``Close`` button. Kept for back-compat
  with the legacy overflow-menu launch path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# matplotlib costs ~150–300 ms on cold import. ``OptimizerEmbed`` is
# the entry-point for the Otimizador workspace tab, which is NOT the
# default page on launch — most cold starts paint the dashboard
# without ever instantiating the optimizer chart. Deferring matplotlib
# to ``_figure_imports`` keeps the cost off the boot path; the first
# OptimizerEmbed construction pays the import (only one chart per
# session, cached by Python's import system thereafter).
if TYPE_CHECKING:  # pragma: no cover — typing only
    from matplotlib.backends.backend_qtagg import (  # noqa: F401
        FigureCanvasQTAgg,
    )
    from matplotlib.figure import Figure  # noqa: F401


def _figure_imports():
    """Lazy matplotlib import — see the module-level docstring above."""
    import matplotlib

    matplotlib.use("QtAgg")
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    return Figure, FigureCanvasQTAgg


from pfc_inductor.models import Core, Material, Spec, Wire
from pfc_inductor.optimize import SweepResult, pareto_front, sweep
from pfc_inductor.optimize.sweep import rank
from pfc_inductor.ui.theme import get_theme
from pfc_inductor.ui.widgets.optimizer_filters_bar import OptimizerFiltersBar


class _ErrorBanner(QWidget):
    """Inline status banner — error / info messages without modal QMessageBox.

    QMessageBox.critical pulled focus and blocked the optimizer
    workflow every time the user hit a benign error (CSV path not
    writable, sweep produced 0 designs). The banner lives at the
    top of the optimizer page and auto-hides when the next sweep
    runs or after the user clicks the ✕. Modeled after GitHub's
    inline error banners — calm, scannable, dismissable.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setVisible(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(8)
        self._icon = QLabel("")
        self._icon.setFixedWidth(20)
        self._label = QLabel("")
        self._label.setWordWrap(True)
        from PySide6.QtWidgets import QToolButton

        self._close_btn = QToolButton()
        self._close_btn.setText("✕")
        self._close_btn.setAutoRaise(True)
        self._close_btn.setToolTip("Dismiss")
        self._close_btn.clicked.connect(self.hide)
        layout.addWidget(self._icon)
        layout.addWidget(self._label, 1)
        layout.addWidget(self._close_btn)

    def show_error(self, message: str) -> None:
        self._icon.setText("⚠")
        self._apply_palette("#FEF2F2", "#B91C1C", "#FECACA")
        self._label.setText(message)
        self.setVisible(True)

    def show_info(self, message: str) -> None:
        self._icon.setText("✓")
        self._apply_palette("#F0FDF4", "#15803D", "#BBF7D0")
        self._label.setText(message)
        self.setVisible(True)

    def _apply_palette(self, bg: str, fg: str, border: str) -> None:
        # Inline stylesheet so this widget is theme-independent
        # (it's used from a path that may run before the QSS theme
        # has been applied — e.g. very early in a CSV export error
        # during the first sweep).
        self.setStyleSheet(
            f"_ErrorBanner {{ background: {bg}; border: 1px solid {border};"
            f" border-radius: 6px; }}"
            f"_ErrorBanner QLabel {{ color: {fg}; }}"
            f"_ErrorBanner QToolButton {{ color: {fg}; border: 0; padding: 2px 6px; }}"
            f"_ErrorBanner QToolButton:hover {{ background: rgba(0,0,0,0.05); }}"
        )


class _SweepWorker(QObject):
    progress = Signal(int, int)
    done = Signal(list, list)
    """``(results, pareto)`` — pareto pre-computed off the GUI thread."""
    failed = Signal(str)

    def __init__(self, spec, cores, wires, materials, only_compat):
        super().__init__()
        self.spec = spec
        self.cores = cores
        self.wires = wires
        self.materials = materials
        self.only_compat = only_compat

    def run(self):
        try:
            # ``materials`` is now the *already-filtered* list from
            # the OptimizerFiltersBar — no separate ``material_id``
            # path. The single-id parameter on ``sweep()`` is kept
            # for back-compat callers but we leave it unset; the
            # engine iterates the full list we hand in.
            results = sweep(
                self.spec,
                self.cores,
                self.wires,
                self.materials,
                only_compatible_cores=self.only_compat,
                progress_cb=lambda d, t: self.progress.emit(d, t),
            )
            # Pareto front is O(n²) over feasible candidates — for a
            # thousand-design sweep that's a million comparisons. Doing
            # it here (in the worker thread) keeps it off the GUI
            # thread, which was a measurable contributor to the
            # post-sweep cursor-freeze the user reported on v0.4.12.
            pareto = pareto_front(results)
            self.done.emit(results, pareto)
        except Exception as e:
            self.failed.emit(str(e))


class OptimizerEmbed(QWidget):
    """Optimizer body — controls + ranked table + Pareto plot + Apply.

    Designed to be embedded inline in a workspace page or wrapped in a
    modal :class:`OptimizerDialog`. The constructor accepts an
    optional spec; if ``None`` the run button is disabled until
    :meth:`set_inputs` is called with a valid spec + catalogs.
    """

    selection_applied = Signal(str, str, str)  # material_id, core_id, wire_id
    compare_requested = Signal(list)  # list[SweepResult] — picked rows for Compare

    # QSettings keys used to persist user toggle preferences across
    # sessions. Engineering users keep "Curated only" on once they've
    # discovered it; novices keep it off. Persisting both groups'
    # preference is the right default.
    _SETTINGS_KEY_COMPAT = "optimizer/restrict_to_compatible_cores"
    _SETTINGS_KEY_FEASIBLE = "optimizer/hide_infeasible"
    _SETTINGS_KEY_CURATED = "optimizer/curated_only"
    _SETTINGS_KEY_OBJECTIVE = "optimizer/objective_key"

    def __init__(
        self,
        spec: Optional[Spec] = None,
        materials: Optional[list[Material]] = None,
        cores: Optional[list[Core]] = None,
        wires: Optional[list[Wire]] = None,
        current_material_id: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._spec = spec
        self._materials = list(materials) if materials else []
        self._cores = list(cores) if cores else []
        self._wires = list(wires) if wires else []
        self._results: list[SweepResult] = []
        self._pareto: list[SweepResult] = []
        self._row_to_result: list[SweepResult] = []
        self._thread: Optional[QThread] = None
        # ETA tracking — populated when ``_run_sweep`` starts so
        # ``_on_progress`` can format "X.YYY / Y.YYY combinations ·
        # ~12 s remaining" instead of just a numeric percentage.
        self._sweep_started_at: Optional[float] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # Inline error banner — shows above the controls when the
        # sweep fails or CSV export hits a filesystem error. Replaces
        # the modal QMessageBox.critical for non-fatal errors, which
        # was disruptive to the workflow.
        self._error_banner = _ErrorBanner()
        outer.addWidget(self._error_banner)

        outer.addWidget(self._build_controls(current_material_id))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_plot())
        splitter.setSizes([700, 500])
        outer.addWidget(splitter, 1)

        outer.addLayout(self._build_buttons())

        # Restore persisted toggle state. Done AFTER the widgets are
        # built so we can set their checked state directly.
        self._restore_toggles()

        # Disable run if no spec yet.
        if self._spec is None:
            self.btn_run.setEnabled(False)
            self.lbl_count.setText(
                "Waiting for a spec — calculate a design first.",
            )

    def _restore_toggles(self) -> None:
        from PySide6.QtCore import QSettings

        from pfc_inductor.settings import SETTINGS_APP, SETTINGS_ORG

        s = QSettings(SETTINGS_ORG, SETTINGS_APP)
        # ``QSettings.value`` returns the literal stored value, which
        # for booleans round-trips as the string "true"/"false" on
        # some platforms. Normalize via ``bool()`` after the explicit
        # type cast — safer than relying on ``type=bool`` which the
        # legacy PySide stubs don't always typecheck.
        compat = s.value(self._SETTINGS_KEY_COMPAT)
        feasible = s.value(self._SETTINGS_KEY_FEASIBLE)
        curated = s.value(self._SETTINGS_KEY_CURATED)
        objective = s.value(self._SETTINGS_KEY_OBJECTIVE)

        def _as_bool(v, default: bool) -> bool:
            if v is None:
                return default
            if isinstance(v, bool):
                return v
            return str(v).lower() in ("true", "1", "yes")

        self.chk_compat.setChecked(_as_bool(compat, True))
        self.chk_feasible.setChecked(_as_bool(feasible, True))
        self.chk_curated_only.setChecked(_as_bool(curated, False))
        if isinstance(objective, str) and objective:
            self.filters_bar.set_objective(objective)

        # Persist on subsequent changes — wire this AFTER the
        # initial setChecked() above so the restore itself doesn't
        # trigger a write.
        self.chk_compat.stateChanged.connect(
            lambda st: self._persist_toggle(self._SETTINGS_KEY_COMPAT, bool(st))
        )
        self.chk_feasible.stateChanged.connect(
            lambda st: self._persist_toggle(self._SETTINGS_KEY_FEASIBLE, bool(st))
        )
        self.chk_curated_only.stateChanged.connect(
            lambda st: self._persist_toggle(self._SETTINGS_KEY_CURATED, bool(st))
        )
        self.filters_bar.objective_changed.connect(
            lambda key: self._persist_toggle(self._SETTINGS_KEY_OBJECTIVE, key)
        )

    @staticmethod
    def _persist_toggle(key: str, value) -> None:
        from PySide6.QtCore import QSettings

        from pfc_inductor.settings import SETTINGS_APP, SETTINGS_ORG

        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(key, value)

    def _show_error(self, message: str) -> None:
        """Surface a non-fatal error in the inline banner.

        For genuinely fatal cases (engine raised, no way forward)
        we still want a modal — but most errors here are recoverable
        (CSV path not writable, sweep produced 0 feasible designs).
        """
        self._error_banner.show_error(message)

    def _show_info(self, message: str) -> None:
        self._error_banner.show_info(message)

    # ------------------------------------------------------------------
    def set_inputs(
        self,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        current_material_id: str = "",
    ) -> None:
        """(Re)bind the optimizer inputs without rebuilding the UI.

        Called by the host whenever the user edits the spec / reloads
        the catalogs in another part of the app — the optimizer page
        always reflects the latest state."""
        self._spec = spec
        self._materials = list(materials)
        self._cores = list(cores)
        self._wires = list(wires)
        # Hand the topology-filtered catalogue to the filter bar.
        self.filters_bar.set_catalogs(
            self._materials,
            self._cores,
            self._wires,
        )
        # Pre-select the project's current material so the default
        # sweep is narrow (~1 material × its compatible cores × all
        # wires). Without this seed the chip would default to the
        # wildcard "All N materials" and hitting Run would launch a
        # full N×M×K combinatorial sweep — with the current 470
        # material / 10 k core / 1 k wire catalogue that's billions
        # of evaluations and locks the worker thread for hours. Users
        # who genuinely want a wide search can clear the chip and add
        # whatever subset they like.
        if current_material_id:
            self.filters_bar.chip_materials.set_selected(
                [current_material_id],
            )
        # Only re-enable Run when a sweep is NOT in flight. Otherwise
        # ``set_inputs`` (which the host calls on every recalc, even
        # while the worker thread is busy) would re-enable the button
        # mid-sweep — a second click during that window would then
        # take the early-return path because ``self._thread`` is
        # still alive. The result was the "fica sempre 100 por 100"
        # bug: progress bar pinned at 100, no new sweep starts.
        # ``_on_thread_finished`` is the authoritative re-enabler.
        if self._thread is None or not self._thread.isRunning():
            self.btn_run.setEnabled(True)
        self._refresh_estimate()
        if not self._results:
            self.lbl_count.setText(
                "Ready — pick filters and an objective, then click "
                "<b>Run sweep</b> to generate the Pareto front.",
            )

    def _build_controls(self, current_material_id: str) -> QGroupBox:
        box = QGroupBox("Sweep configuration")
        v = QVBoxLayout(box)
        v.setSpacing(8)

        # ---- Multi-select filters + objective (shared widget) -----
        self.filters_bar = OptimizerFiltersBar()
        self.filters_bar.set_catalogs(
            self._materials,
            self._cores,
            self._wires,
        )
        # Re-rank the visible table on objective change without a
        # full re-sweep — the underlying ``self._results`` cache is
        # already enough to ``rank()`` again client-side.
        self.filters_bar.objective_changed.connect(
            lambda _key: self._refresh_table(),
        )
        # Weight-slider drags re-rank the table in real time without
        # touching the engine — the score function reads ``weights``
        # from the filter bar on every refresh. Lets engineers tune
        # the loss / volume / cost trade-off interactively.
        self.filters_bar.weights_changed.connect(self._refresh_table)
        # The estimate label tracks chip selection too — refresh on
        # any filter change so the user always sees what they're
        # about to run before they click.
        self.filters_bar.filters_changed.connect(self._refresh_estimate)
        v.addWidget(self.filters_bar)

        # ---- Secondary toggles + run button -----------------------
        h = QHBoxLayout()
        h.setSpacing(12)

        self.chk_compat = QCheckBox(
            "Restrict to cores compatible with the material",
        )
        self.chk_compat.setChecked(True)
        self.chk_feasible = QCheckBox("Hide infeasible designs")
        # Default ON: show only candidates that satisfy Ku/Bsat/T limits.
        # Most users want a list of "what can I actually build", not a
        # catalogue of failures. Toggle off to inspect borderline cases.
        self.chk_feasible.setChecked(True)
        self.chk_curated_only = QCheckBox("Curated only")
        self.chk_curated_only.setToolTip(
            "Limits the sweep to curated materials and wires, ignoring "
            "the OpenMagnetics catalog — avoids rankings dominated by "
            "entries without Steinmetz/rolloff calibration.",
        )
        self.chk_compat.stateChanged.connect(self._refresh_estimate)
        h.addWidget(self.chk_compat)
        h.addWidget(self.chk_feasible)
        h.addWidget(self.chk_curated_only)
        h.addStretch(1)

        # Cardinality estimate — surfaces the "this run will evaluate
        # ~N combinations" reality before the user clicks Run, so
        # they don't kick off a 6-billion-combo sweep by accident.
        # Refreshed on any filter / compat-toggle change.
        self.lbl_estimate = QLabel("")
        self.lbl_estimate.setProperty("role", "muted")
        self.lbl_estimate.setToolTip(
            "Approximate number of (material × core × wire) "
            "combinations the sweep will evaluate. Sweeping the full "
            "catalogue can take many minutes and tens of GB of RAM —\n"
            "narrow the chips above to keep runtime sane.",
        )
        h.addWidget(self.lbl_estimate)

        self.btn_run = QPushButton("Run sweep")
        # Mark as the primary action so the theme QSS can paint it
        # bold + brand-violet. Falling back to an inline style would
        # ignore dark-mode + lose the focus ring; the ``Primary`` class
        # is the same one used by ``btn_apply`` below.
        self.btn_run.setProperty("class", "Primary")
        self.btn_run.clicked.connect(self._run_sweep)
        h.addWidget(self.btn_run)
        # Progress bar shows percentage + an ETA string while a sweep
        # is in flight. Hidden when idle so the action row reads
        # cleaner; the cardinality estimate label above does the
        # "what's about to happen" duty pre-Run.
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumWidth(220)
        self.progress.setMaximumWidth(280)
        self.progress.setFormat("%p% · idle")
        self.progress.setVisible(False)
        h.addWidget(self.progress)
        v.addLayout(h)

        self.chk_feasible.stateChanged.connect(self._refresh_table)
        return box

    def _build_table(self) -> QGroupBox:
        box = QGroupBox("Results")
        v = QVBoxLayout(box)

        # Status row + action toolbar above the table.
        status_row = QHBoxLayout()
        status_row.setSpacing(12)
        self.lbl_count = QLabel("No sweep yet.")
        status_row.addWidget(self.lbl_count, 1)
        self.lbl_selection = QLabel("")
        self.lbl_selection.setProperty("role", "muted")
        status_row.addWidget(self.lbl_selection)
        # Pareto-front quick select — highlights every non-dominated
        # candidate in one click. Common workflow: run sweep, click
        # this, then Compare to see the trade-off curve in detail.
        self.btn_select_pareto = QPushButton("Select Pareto front")
        self.btn_select_pareto.setToolTip(
            "Select every non-dominated candidate (the corner-of-the-front "
            "designs) so you can compare them side-by-side."
        )
        self.btn_select_pareto.setEnabled(False)
        self.btn_select_pareto.clicked.connect(self._select_pareto_rows)
        status_row.addWidget(self.btn_select_pareto)
        # Compare N selected — opens the standard CompareDialog with
        # every selected row pre-populated as a slot.
        self.btn_compare = QPushButton("Compare selected")
        self.btn_compare.setToolTip(
            "Open the Compare view with every selected row pre-populated. "
            "Cmd/Ctrl-click rows to add to the selection."
        )
        self.btn_compare.setEnabled(False)
        self.btn_compare.clicked.connect(self._compare_selected)
        status_row.addWidget(self.btn_compare)
        # CSV export.
        self.btn_export = QPushButton("Export CSV…")
        self.btn_export.setToolTip(
            "Save the visible table as a CSV file (one row per design, "
            "honouring the active filters and ranking)."
        )
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export_csv)
        status_row.addWidget(self.btn_export)
        v.addLayout(status_row)

        self.table = QTableWidget(0, 10)
        # Column headers — terse engineer-friendly tags. Tooltips on
        # each header carry the full definition (what "P", "T",
        # "Status" actually mean) so we don't bloat the visible cells.
        headers = [
            ("Core", "Catalog part number of the magnetic core."),
            ("Wire", "Wire gauge / Litz spec (e.g. AWG14, 200×38 Litz)."),
            ("Material", "Magnetic material name (powder / ferrite / silicon-steel)."),
            ("Vol [cm³]", "Effective magnetic volume Ve. Smaller is better."),
            (
                "L [µH]",
                "Actual inductance at the operating point, including saturation rolloff. "
                "Lower than the cold-bias AL·N² figure on powder cores.",
            ),
            ("N", "Turn count."),
            (
                "P [W]",
                "Total losses = copper (DC + AC + proximity / skin) + core "
                "(Steinmetz hysteresis + eddy). Lower is better.",
            ),
            (
                "T [°C]",
                "Steady-state winding temperature in still air at the "
                "spec's ambient. Below the core's class limit is feasible.",
            ),
            (
                "Cost",
                "Estimated BOM cost from the catalog price points. "
                '"—" means the catalog entry has no price data.',
            ),
            (
                "Status",
                "✓ feasible · ✓ Pareto = on the non-dominated front · "
                "⚠ N = infeasible with N warning(s). Hover the row for details.",
            ),
        ]
        self.table.setHorizontalHeaderLabels([h[0] for h in headers])
        hdr = self.table.horizontalHeader()
        for i, (_label, tip) in enumerate(headers):
            self.table.horizontalHeaderItem(i).setToolTip(tip)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # ``ExtendedSelection`` enables Cmd/Ctrl-click multi-select +
        # Shift-click range-select. The optimizer historically only
        # supported single-row selection; multi-select unlocks the
        # "compare 3-5 candidates from the Pareto front" workflow
        # that's the whole point of a sweep.
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # Material column (col 2) can hold long names ("Magnetics 60 µ
        # High Flux / Sendust"). Mid-elide keeps the row height stable
        # without truncating the vendor prefix that disambiguates
        # similar parts.
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        f = QFont()
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setFamily("Menlo")
        self.table.setFont(f)
        v.addWidget(self.table, 1)
        return box

    def _build_plot(self) -> QGroupBox:
        """Return the plot-section container with a placeholder body.

        The matplotlib ``Figure`` itself isn't constructed here — that
        triggers a ~150–300 ms cold import on the first widget that
        creates one. Instead we lay out an empty container and an
        ``_ensure_plot_built`` hook that fills in the real chart on
        first ``showEvent``. The optimizer tab is not the default page,
        so deferring the chart construction keeps matplotlib off the
        main-window boot path entirely (a cold start that never opens
        the optimizer never pays the matplotlib cost).
        """
        box = QGroupBox("Volume × Total loss (Pareto highlighted)")
        self._plot_box = box
        v = QVBoxLayout(box)
        self._plot_layout = v
        self.fig = None  # populated by ``_ensure_plot_built``
        self.canvas = None
        self.ax = None
        self._plot_built = False
        return box

    def _ensure_plot_built(self) -> None:
        """Construct the matplotlib Figure on first call. Idempotent."""
        if self._plot_built:
            return
        Figure, FigureCanvasQTAgg = _figure_imports()
        self._FigureCanvasQTAgg = FigureCanvasQTAgg
        self.fig = Figure(figsize=(5, 5), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Volume [cm³]")
        self.ax.set_ylabel("P_total [W]")
        # Empty-state painting: a 0..1 axis with the default ticks
        # reads as "broken plot" before the first sweep. Hide the
        # spines/ticks and centre an instructional caption — the
        # canvas now communicates "no data yet, here's how to get
        # data" instead of "this chart is empty".
        self._paint_empty_plot()
        self._plot_layout.addWidget(self.canvas)
        self._plot_built = True

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        # First time the optimizer tab becomes visible, build the plot.
        # Subsequent shows are no-ops via the ``_plot_built`` guard.
        # Synchronous build (vs. ``QTimer.singleShot(0, …)``) avoids a
        # one-frame empty-plot flash when the user opens this tab.
        self._ensure_plot_built()

    def _paint_empty_plot(self) -> None:
        """Draw an instructional empty state on the matplotlib canvas.

        Called once at construction and again whenever ``set_inputs``
        runs without yet having results. Replaced with the real
        Pareto scatter as soon as a sweep produces data.

        v3 was a 2-line text block on a blank axes — visually a huge
        white slab that didn't tell the user what the chart will
        look like. v4 ships a **silhouette preview**: ~30 ghost
        candidates + a highlighted Pareto front + axis labels, so
        the user sees the shape they'll get before clicking
        "Run sweep". Greys are below WCAG AA against the surface so
        nobody mistakes them for real data — they're decorative
        scaffolding for the empty state.
        """
        # The Figure is built lazily on first ``showEvent`` so the
        # matplotlib import doesn't fire during MainWindow boot.
        # Calls before then (e.g. ``set_inputs`` arriving while the
        # user is on the dashboard) become no-ops; the next
        # showEvent will run ``_ensure_plot_built`` which calls
        # this method again to paint the empty state for real.
        if self.ax is None or self.canvas is None:
            return
        import numpy as np

        self.ax.clear()
        # Ghost scatter — 30 random points along a downward-trending
        # cloud (lower volume → higher loss for the worst designs;
        # the Pareto front bends down-left). Seed pinned so the
        # silhouette doesn't shift between paints.
        rng = np.random.default_rng(seed=42)
        n = 30
        vol = rng.uniform(8, 70, n)
        loss = 4.0 + 90.0 / vol + rng.uniform(-1.5, 1.5, n)
        # Pareto front — sweep + sort by volume + carry running
        # minimum loss to the right.
        order = np.argsort(vol)
        vol_s = vol[order]
        loss_s = loss[order]
        front_mask = np.minimum.accumulate(loss_s[::-1])[::-1] == loss_s

        ghost = "#D4D4D8"  # zinc-300 — clearly decorative
        front = "#A1A1AA"  # zinc-400 — slightly stronger
        self.ax.scatter(vol, loss, s=26, color=ghost, alpha=0.7, edgecolors="none", zorder=2)
        self.ax.plot(
            vol_s[front_mask],
            loss_s[front_mask],
            color=front,
            linewidth=1.4,
            alpha=0.65,
            zorder=3,
        )

        # Axis chrome — labels but no tick numbers (no data → no
        # units to commit to). Spines stay visible so the user
        # parses this as "a chart, but pending".
        self.ax.set_xlabel("Volume → smaller", fontsize=9, color="#71717A")
        self.ax.set_ylabel("Loss → lower", fontsize=9, color="#71717A")
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        for spine in ("top", "right"):
            self.ax.spines[spine].set_visible(False)
        for spine in ("bottom", "left"):
            self.ax.spines[spine].set_color("#E4E4E7")

        # Inline call-to-action sits in the empty corner where the
        # winning Pareto designs will land — the user's eye goes
        # there first when results arrive. Tight box, semibold
        # verdict + 1-line hint underneath.
        self.ax.text(
            0.04,
            0.10,
            "Click Run sweep to populate",
            ha="left",
            va="bottom",
            fontsize=10,
            fontweight="bold",
            transform=self.ax.transAxes,
            color="#52525B",
        )
        self.ax.text(
            0.04,
            0.04,
            "Pareto front highlights designs that aren't beaten on both axes.",
            ha="left",
            va="bottom",
            fontsize=8,
            transform=self.ax.transAxes,
            color="#71717A",
        )
        self.canvas.draw_idle()

    def _build_buttons(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addStretch(1)
        self.btn_apply = QPushButton("Apply selection")
        self.btn_apply.setProperty("class", "Primary")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply_selection)
        h.addWidget(self.btn_apply)
        return h

    # Above this many evaluations the sweep stops being interactive
    # (minutes of CPU + GBs of RAM). We confirm with the user before
    # launching so they don't lock up the app by accident. The
    # baseline single-material run is ~65 k combinations
    # (1 material × ~45 compatible cores × ~1.4 k wires) so we set
    # the threshold above that — multi-material sweeps cross the
    # bar and trigger the dialog.
    _SWEEP_CONFIRM_THRESHOLD = 250_000

    def _estimate_combinations(self) -> int:
        """Best-effort estimate of (material × core × wire) cardinality.

        Used by both the inline label and the run-time confirmation
        dialog. Honours the ``Restrict to compatible cores`` toggle:
        when on we count only the cores whose ``default_material_id``
        matches at least one selected material, which is the same
        rule ``sweep()`` applies internally.
        """
        try:
            mats = self.filters_bar.selected_materials()
            cores = self.filters_bar.selected_cores()
            wires = self.filters_bar.selected_wires()
        except AttributeError:
            return 0

        n_wires = len(wires)
        if not mats or not cores or not n_wires:
            return 0

        if self.chk_compat.isChecked():
            mat_ids = {m.id for m in mats}
            compat_cores = sum(
                1 for c in cores if getattr(c, "default_material_id", None) in mat_ids
            )
            return compat_cores * n_wires
        return len(mats) * len(cores) * n_wires

    def _refresh_estimate(self) -> None:
        n = self._estimate_combinations()
        if n == 0:
            self.lbl_estimate.setText("Filters reject every candidate.")
            return
        if n >= self._SWEEP_CONFIRM_THRESHOLD:
            self.lbl_estimate.setText(
                f"≈ {n:,} combinations · <b>large run</b>",
            )
        else:
            self.lbl_estimate.setText(f"≈ {n:,} combinations")

    def _run_sweep(self):
        if self._thread is not None and self._thread.isRunning():
            return

        # Clear any stale banner from a previous run.
        self._error_banner.setVisible(False)

        # Confirm before launching anything that will take minutes /
        # GBs. The threshold is conservative (≈50 k combos = a few
        # seconds on a modern CPU); above it the worker thread blocks
        # interactivity and the process pool can leak semaphores if
        # the user hits Cancel.
        n_estimate = self._estimate_combinations()
        if n_estimate >= self._SWEEP_CONFIRM_THRESHOLD:
            from PySide6.QtWidgets import QMessageBox

            reply = QMessageBox.question(
                self,
                "Large sweep",
                f"This will evaluate roughly <b>{n_estimate:,}</b> "
                f"combinations.\n\n"
                f"That can take several minutes and noticeable RAM. "
                f"Narrow the Materials / Cores / Wires chips above "
                f"to keep things interactive.\n\n"
                f"Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.btn_run.setEnabled(False)
        # Show the progress bar only while running. Idle state shows
        # the cardinality estimate label instead — less visual clutter.
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.progress.setFormat("%p% · starting…")
        import time as _time

        self._sweep_started_at = _time.perf_counter()
        only_compat = self.chk_compat.isChecked()

        # ``selected_*`` returns the full topology-filtered catalogue
        # when the user hasn't picked anything (empty chip → wildcard).
        mats = self.filters_bar.selected_materials()
        cores = self.filters_bar.selected_cores()
        wires = self.filters_bar.selected_wires()

        # ``Curated only`` then narrows materials + wires further.
        # We intersect with whatever the user already selected so the
        # two filters compose predictably (curated *and* hand-picked).
        if self.chk_curated_only.isChecked():
            from pfc_inductor.data_loader import load_curated_ids

            cur_mats = load_curated_ids("materials")
            cur_wires = load_curated_ids("wires")
            filtered_mats = [m for m in mats if m.id in cur_mats]
            filtered_wires = [w for w in wires if w.id in cur_wires]
            # If the curated intersection is empty, fall back to the
            # user's selection — better to honour their explicit pick
            # than to silently sweep an empty set.
            mats = filtered_mats or mats
            wires = filtered_wires or wires

        self._worker = _SweepWorker(
            self._spec,
            cores,
            wires,
            mats,
            only_compat,
        )
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        # ``_on_done`` / ``_on_failed`` handle thread cleanup directly
        # via ``_teardown_thread`` (which calls ``quit() + wait()``
        # synchronously). We don't connect ``done`` / ``failed`` to
        # ``_thread.quit`` separately because ``_teardown_thread``
        # already does the quit, and double-quitting is a no-op
        # but produces noisy "thread already finished" warnings on
        # some Qt builds.
        self._thread.start()

    def _on_progress(self, done: int, total: int):
        if total <= 0:
            return
        self.progress.setValue(int(100 * done / total))
        # ETA — extrapolates from elapsed time per evaluated
        # candidate. The first few callbacks are noisy (sweep startup
        # / process-pool spin-up costs are amortized at the start) so
        # we wait until at least 1 % done OR 50 candidates evaluated
        # before showing the time estimate.
        import time as _time

        if self._sweep_started_at is None or done < 50 or done < total // 100 or done >= total:
            self.progress.setFormat(f"%p% · {done:,} / {total:,}")
            return
        elapsed = _time.perf_counter() - self._sweep_started_at
        remaining = elapsed * (total - done) / done
        self.progress.setFormat(
            f"%p% · {done:,} / {total:,} · ~{self._format_duration(remaining)} remaining"
        )

    @staticmethod
    def _heatmap_minmax(rows: list[SweepResult], extractor) -> Optional[tuple[float, float, float]]:
        """Return ``(min, max, span)`` for the ``extractor`` over feasible
        rows, or ``None`` when all values are missing / equal.

        ``span = max - min``; precomputed once per refresh so the
        heatmap colouring inside the loop is just an arithmetic step
        per cell instead of a min/max scan per row.
        """
        vals = [extractor(r) for r in rows]
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        mn, mx = min(vals), max(vals)
        span = mx - mn
        if span <= 0:
            return None
        return mn, mx, span

    @staticmethod
    def _heatmap_color(value: float, mn: float, mx: float):
        """Map ``value ∈ [mn, mx]`` to a green→amber→red background.

        Lower-is-better convention — green for min, red for max.
        Returns a ``QBrush`` (or None when ``value`` is out of range).
        Hue scale is intentionally pastel so the foreground text
        stays readable without per-cell colour-contrast adjustment.
        """
        from PySide6.QtGui import QBrush, QColor

        if mx <= mn:
            return None
        # Normalise to [0, 1]; clip in case ``value`` is slightly
        # outside (floating-point edge).
        t = max(0.0, min(1.0, (value - mn) / (mx - mn)))
        # Three-stop gradient: green (#DCFCE7) → amber (#FEF3C7) → red (#FEE2E2).
        # All pastel so monospace text stays legible.
        if t < 0.5:
            # green → amber
            u = t / 0.5
            r = int(220 + (254 - 220) * u)
            g = int(252 + (243 - 252) * u)
            b = int(231 + (199 - 231) * u)
        else:
            # amber → red
            u = (t - 0.5) / 0.5
            r = int(254 + (254 - 254) * u)
            g = int(243 + (226 - 243) * u)
            b = int(199 + (226 - 199) * u)
        return QBrush(QColor(r, g, b))

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds < 1:
            return "<1 s"
        if seconds < 60:
            return f"{int(seconds)} s"
        m, s = divmod(int(seconds), 60)
        if m < 60:
            return f"{m} min {s} s" if s else f"{m} min"
        h, m = divmod(m, 60)
        return f"{h} h {m} min"

    def _on_done(self, results: list[SweepResult], pareto: list[SweepResult]):
        self._results = results
        # Pareto was computed off-thread by the worker — no recompute
        # on the GUI thread.
        self._pareto = pareto
        self.progress.setValue(100)
        # Hide the bar shortly after — the count label below the
        # action row already says "{n_feasible} feasible out of {n}".
        from PySide6.QtCore import QTimer

        QTimer.singleShot(1500, lambda: self.progress.setVisible(False))
        # Now that there are results, enable the post-sweep actions.
        self.btn_select_pareto.setEnabled(bool(self._pareto))
        self.btn_export.setEnabled(bool(results))
        # Heavy-but-cheap-each repaints (table populate + chart
        # redraw) run on the GUI thread, but we sandwich them with
        # ``processEvents()`` so the OS cursor / window-server keep
        # ticking — the user no longer sees a "everything frozen"
        # spinning beachball moment. ``_refresh_table`` itself uses
        # ``setUpdatesEnabled(False)`` to suppress per-cell paints
        # so the cost there is mostly QTableWidgetItem allocation,
        # which is well under the 16 ms frame budget on modern
        # hardware even for the 200-row cap.
        from PySide6.QtWidgets import QApplication as _QApp

        self._refresh_table()
        _QApp.processEvents()
        self._refresh_plot()

        # Async cleanup — see ``_teardown_thread`` for why we don't
        # block here.
        self._teardown_thread()

    def _on_failed(self, msg: str):
        # Inline banner instead of a modal QMessageBox.critical —
        # the latter pulled focus and stalled the workflow even for
        # benign errors. ``_show_error`` is dismissable.
        self._show_error(f"Sweep failed: {msg}")
        self.progress.setVisible(False)
        self._teardown_thread()

    def _teardown_thread(self) -> None:
        """Tear down the worker thread WITHOUT blocking the GUI.

        Earlier rev did ``thread.wait(1000)`` here to guarantee the
        thread had exited before re-enabling Run; that turned out to
        be a visible cursor-freeze on slower machines (the wait
        completed in microseconds on dev hardware, but on a busy
        system it could land anywhere up to the 1 s cap). The fix is
        to wire the cleanup to the thread's ``finished`` signal,
        which fires from the GUI thread's event loop AFTER the
        thread's event loop has truly exited — same correctness
        guarantee, zero GUI-thread block.

        Idempotent: safe to call from both the success (``_on_done``)
        and failure (``_on_failed``) paths.
        """
        thread = self._thread
        worker = self._worker
        # NOTE: we deliberately keep ``self._thread`` and
        # ``self._worker`` populated until ``_on_thread_finished``
        # fires — that way, if the user hits Run during the brief
        # quit→exit window, the ``isRunning()`` guard at the top of
        # ``_run_sweep`` still catches them and prevents starting a
        # second sweep on top of a not-quite-dead thread.
        if thread is not None:
            # Wire a one-shot cleanup before asking the thread to exit.
            # ``finished`` is emitted by the thread itself once exec()
            # returns; the slot fires queued on the GUI thread.
            thread.finished.connect(lambda t=thread, w=worker: self._on_thread_finished(t, w))
            thread.quit()

    def _on_thread_finished(self, thread: QThread, worker: Optional[QObject]) -> None:
        """Async cleanup hook — runs on the GUI thread once the
        sweep worker thread has truly exited.

        Clears ``self._thread`` / ``self._worker`` and re-enables Run.
        Schedules ``deleteLater`` on the thread + worker so we don't
        leak QObjects across sweeps.
        """
        # If a new sweep was started before this slot fired (rare,
        # but possible if the user is fast), don't clobber the new
        # thread reference.
        if self._thread is thread:
            self._thread = None
        if self._worker is worker:
            self._worker = None
        thread.deleteLater()
        if worker is not None:
            worker.deleteLater()
        self.btn_run.setEnabled(True)

    def _refresh_table(self):
        rank_key = self.filters_bar.objective()
        feasible_only = self.chk_feasible.isChecked()
        n_total = len(self._results)
        n_feasible = sum(1 for x in self._results if x.feasible)
        rows = [r for r in self._results if (not feasible_only or r.feasible)]
        # Pass user-tunable weights for the ``score`` family. ``rank``
        # falls back to its built-in defaults (60/40 / 40/30/30) when
        # weights is None or the objective doesn't use them.
        weights = self.filters_bar.weights() if rank_key.startswith("score") else None
        rows = rank(rows, by=rank_key, feasible_first=True, weights=weights)
        rows = rows[:200]  # cap at 200 for UI responsiveness

        # ---- Compute per-column min/max for the heatmap ----
        # Heatmap shading is computed over the *feasible* subset of
        # ``rows`` only. Including infeasible designs would skew the
        # range (an infeasible row at 800 °C would compress the
        # feasible 60-110 °C range into a single colour band).
        feas_rows = [r for r in rows if r.feasible]
        heat_vol = self._heatmap_minmax(feas_rows, lambda r: r.volume_cm3)
        heat_loss = self._heatmap_minmax(feas_rows, lambda r: r.result.losses.P_total_W)
        heat_temp = self._heatmap_minmax(feas_rows, lambda r: r.result.T_winding_C)
        heat_cost = self._heatmap_minmax(
            feas_rows,
            lambda r: r.cost.total_cost if r.cost is not None else None,
        )

        # Suspend per-cell repaints during the bulk populate. Without
        # this Qt issues a layout / paint event for EACH ``setItem``
        # call, which for 200 rows × 10 columns = 2 000 paint
        # invalidations totalling 100–300 ms of GUI-thread work on
        # slower machines (visible cursor stutter). Wrapping in
        # ``setUpdatesEnabled(False)`` collapses it to a single paint
        # at the end; ``blockSignals(True)`` similarly suppresses
        # ``selectionChanged`` floods while the model is empty.
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(rows))
            pareto_set = {id(r) for r in self._pareto}
            for i, r in enumerate(rows):
                r0 = r.result
                in_pareto = id(r) in pareto_set
                cost_cell = (
                    f"{r.cost.currency} {r.cost.total_cost:.2f}" if r.cost is not None else "—"
                )
                # Status badge — Pareto designs get a more prominent
                # tag so the user can scan the table column for the
                # not-dominated set. "✓ feasible" plain stays subtle.
                status_text = (
                    ("★ Pareto" if in_pareto else "✓ feasible")
                    if r.feasible
                    else f"⚠ {r.n_warnings} warn"
                )
                cells = [
                    r.core.part_number,
                    r.wire.id,
                    r.material.name,
                    f"{r.volume_cm3:.1f}",
                    f"{r0.L_actual_uH:.0f}",
                    f"{r0.N_turns}",
                    f"{r0.losses.P_total_W:.2f}",
                    f"{r0.T_winding_C:.0f}",
                    cost_cell,
                    status_text,
                ]
                # Per-column heatmap shading. Lower-is-better metrics
                # (volume, loss, temp, cost) → green at minimum, red
                # at maximum. The heatmap only applies to feasible
                # rows; infeasible cells use a flat tint instead so
                # the engineer can scan past them quickly.
                heat_cells: list[Optional[tuple[float, float, float]]] = [None] * 10
                if r.feasible:
                    heat_cells[3] = heat_vol
                    heat_cells[6] = heat_loss
                    heat_cells[7] = heat_temp
                    if r.cost is not None:
                        heat_cells[8] = heat_cost
                for c_idx, txt in enumerate(cells):
                    item = QTableWidgetItem(txt)
                    if not r.feasible:
                        item.setForeground(Qt.GlobalColor.red)
                    elif in_pareto:
                        item.setForeground(Qt.GlobalColor.darkGreen)
                    # Apply column-specific heatmap.
                    if r.feasible and heat_cells[c_idx] is not None:
                        val: Optional[float]
                        if c_idx == 3:
                            val = r.volume_cm3
                        elif c_idx == 6:
                            val = r0.losses.P_total_W
                        elif c_idx == 7:
                            val = r0.T_winding_C
                        elif c_idx == 8:
                            val = r.cost.total_cost if r.cost is not None else None
                        else:
                            val = None
                        if val is not None:
                            mn, mx, _span = heat_cells[c_idx]  # type: ignore[misc]
                            bg = self._heatmap_color(val, mn, mx)
                            if bg is not None:
                                item.setBackground(bg)
                    # Tooltip for the Material cell — full vendor + name
                    # so the user can identify entries when the column
                    # is narrow (ElideMiddle is set on the table).
                    if c_idx == 2:
                        item.setToolTip(r.material.name)
                    self.table.setItem(i, c_idx, item)
            self._row_to_result = list(rows)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

        # Header: clearly say "X viable / Y total". When 0 viable, give
        # the user a concrete remediation path instead of just an empty
        # table.
        if n_total == 0:
            self.lbl_count.setText("No designs evaluated yet. Click <b>Run sweep</b>.")
        elif n_feasible == 0:
            self.lbl_count.setText(
                f"<b>0 feasible designs</b> out of {n_total} evaluated. "
                "Try: increasing <i>Ku max</i> or <i>Bsat margin</i>; "
                "reducing Pout; selecting (sweep all) materials; "
                "unchecking <i>Curated only</i>."
            )
        else:
            pct = 100.0 * n_feasible / n_total
            extra = "" if feasible_only else f" — {n_total - n_feasible} infeasible hidden below"
            self.lbl_count.setText(
                f"<b>{n_feasible} feasible</b> out of {n_total} evaluated ({pct:.1f}%). "
                f"Showing top {len(rows)}{extra}."
            )

    # ``objective key → (x_axis, x_label, y_axis, y_label)`` for the
    # Pareto chart. The chart now reflects whatever the user picked
    # as the ranking objective: volume / cost / temp swap the y axis
    # so the trade-off curve aligned with the user's goal becomes
    # visually obvious. Defaults to Volume × Loss for ``loss`` and
    # ``score`` objectives — the canonical "EE textbook" view.
    _AXIS_PAIRS: ClassVar[dict[str, tuple[str, str, str, str]]] = {
        "loss": ("volume_cm3", "Volume [cm³]", "P_total_W", "P_total [W]"),
        "volume": ("P_total_W", "P_total [W]", "volume_cm3", "Volume [cm³]"),
        "temp": ("volume_cm3", "Volume [cm³]", "T_winding_C", "T_winding [°C]"),
        "cost": ("P_total_W", "P_total [W]", "cost_value", "Cost"),
        "score": ("volume_cm3", "Volume [cm³]", "P_total_W", "P_total [W]"),
        "score_with_cost": ("cost_value", "Cost", "P_total_W", "P_total [W]"),
    }

    @staticmethod
    def _axis_value(r: SweepResult, key: str) -> Optional[float]:
        """Resolve an axis-spec key to a numeric attribute of ``r``."""
        if key == "volume_cm3":
            return r.volume_cm3
        if key == "P_total_W":
            return r.P_total_W
        if key == "T_winding_C":
            return r.result.T_winding_C
        if key == "cost_value":
            return r.cost.total_cost if r.cost is not None else None
        return None

    def _refresh_plot(self):
        # ``_refresh_plot`` is invoked from the sweep callback. By the
        # time the user has clicked Run, they're on the optimizer tab,
        # so ``showEvent`` has already built the figure. But guard
        # anyway: a future code path could land results without the
        # tab ever being shown (e.g. headless test invocation).
        self._ensure_plot_built()
        assert self.ax is not None and self.canvas is not None  # type narrowing
        self.ax.clear()
        p = get_theme().palette

        objective = self.filters_bar.objective()
        x_key, x_label, y_key, y_label = self._AXIS_PAIRS.get(objective, self._AXIS_PAIRS["loss"])
        # Update the plot group-box title so the user always knows
        # which two axes they're looking at — this used to be a static
        # "Volume × Total loss" string that lied as soon as the user
        # picked Cost or Temp as the ranking objective.
        if hasattr(self, "_plot_box") and self._plot_box is not None:
            self._plot_box.setTitle(
                f"{x_label.split(' ')[0]} × {y_label.split(' ')[0]} (Pareto highlighted)"
            )

        def _xy(r: SweepResult) -> Optional[tuple[float, float]]:
            x = self._axis_value(r, x_key)
            y = self._axis_value(r, y_key)
            if x is None or y is None:
                return None
            return x, y

        all_results = self._results
        feas: list[tuple[float, float]] = []
        infeas: list[tuple[float, float]] = []
        for r in all_results:
            xy = _xy(r)
            if xy is None:
                continue
            if r.feasible:
                feas.append(xy)
            else:
                # Clamp y to a sane window so a runaway 1000 °C
                # infeasible row doesn't blow out the y-scale.
                infeas.append(
                    (xy[0], min(xy[1], (max(y for _x, y in feas) if feas else xy[1]) * 1.5))
                )
        if infeas:
            xi, yi = zip(*infeas, strict=False)
            self.ax.scatter(xi, yi, c=p.plot_pareto_infeasible, s=8, alpha=0.4, label="infeasible")
        if feas:
            xf, yf = zip(*feas, strict=False)
            self.ax.scatter(xf, yf, c=p.plot_pareto_feasible, s=10, alpha=0.7, label="feasible")
        if self._pareto:
            pareto_xy = [_xy(r) for r in self._pareto]
            pareto_xy = [xy for xy in pareto_xy if xy is not None]
            if pareto_xy:
                pareto_xy.sort()  # sort by x for a clean polyline
                xp, yp = zip(*pareto_xy, strict=False)
                self.ax.plot(
                    xp,
                    yp,
                    "-o",
                    c=p.plot_pareto_frontier,
                    label="Pareto",
                    linewidth=2,
                    markersize=8,
                )
        self.ax.set_xlabel(x_label)
        self.ax.set_ylabel(y_label)
        # Log-x stays for axes whose physical range is wide
        # (volume, cost). For temperature / loss (mostly linear)
        # a linear scale reads better.
        if x_key in ("volume_cm3", "cost_value"):
            self.ax.set_xscale("log")
        else:
            self.ax.set_xscale("linear")
        self.ax.legend(loc="upper right")
        self.ax.grid(True, alpha=0.4, which="both")
        self.canvas.draw()

    def _on_row_selected(self):
        rows = self.table.selectionModel().selectedRows()
        n = len(rows)
        # Apply only the first selected row (single-row semantic preserved).
        self.btn_apply.setEnabled(n > 0)
        # Compare needs at least 2 rows to be meaningful — comparing
        # a single design against itself is the default workspace
        # view, not what the user wants here.
        self.btn_compare.setEnabled(n >= 2)
        if n == 0:
            self.lbl_selection.setText("")
        elif n == 1:
            self.lbl_selection.setText("1 row selected")
        else:
            self.lbl_selection.setText(f"{n} rows selected")

    def _apply_selection(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        idx = rows[0].row()
        if idx >= len(self._row_to_result):
            return
        sr = self._row_to_result[idx]
        self.selection_applied.emit(sr.material.id, sr.core.id, sr.wire.id)

    def _select_pareto_rows(self) -> None:
        """Multi-select every row that belongs to the Pareto front.

        Pareto = non-dominated on (volume, loss). Common follow-up:
        click Compare to inspect the trade-off curve in detail. The
        front is typically 3-7 candidates out of a 200-row table —
        without this button the user would have to scroll the table
        and Cmd-click them one by one.
        """
        if not self._pareto or not self._row_to_result:
            return
        pareto_ids = {id(r) for r in self._pareto}
        sel_model = self.table.selectionModel()
        sel_model.clearSelection()
        from PySide6.QtCore import QItemSelection, QItemSelectionModel

        sel = QItemSelection()
        n_cols = self.table.columnCount()
        for row_idx, sr in enumerate(self._row_to_result):
            if id(sr) in pareto_ids:
                top_left = self.table.model().index(row_idx, 0)
                bot_right = self.table.model().index(row_idx, n_cols - 1)
                sel.select(top_left, bot_right)
        sel_model.select(
            sel,
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
        # Scroll so the first Pareto row is visible — without this
        # users at the bottom of a 200-row table don't realise the
        # selection happened.
        first = next(
            (i for i, sr in enumerate(self._row_to_result) if id(sr) in pareto_ids),
            None,
        )
        if first is not None:
            self.table.scrollToItem(
                self.table.item(first, 0),
                self.table.ScrollHint.PositionAtTop,
            )

    def _compare_selected(self) -> None:
        """Open the global Compare view with the selected rows
        pre-populated as slots.

        Defers the actual dialog construction to the host (the
        ``compare_requested`` signal). The optimizer doesn't own
        the compare workflow — MainWindow does — so we just hand
        over the picked ``SweepResult`` objects via a side channel.
        """
        rows = self.table.selectionModel().selectedRows()
        if len(rows) < 2:
            return
        # Sort by row index so the compare slots land in table order.
        picked: list[SweepResult] = []
        for qmi in sorted(rows, key=lambda r: r.row()):
            idx = qmi.row()
            if idx < len(self._row_to_result):
                picked.append(self._row_to_result[idx])
        if not picked:
            return
        self.compare_requested.emit(picked)

    def _export_csv(self) -> None:
        """Save the visible table to a CSV.

        Honours the active feasible-only / objective filters — the
        CSV is what the user is *seeing* in the table right now,
        not the raw ``self._results`` cache. Lets engineers paste
        into Excel / Google Sheets for cross-team review.
        """
        if not self._row_to_result:
            self._show_error("No results to export. Run a sweep first.")
            return
        from PySide6.QtWidgets import QFileDialog

        path, _filt = QFileDialog.getSaveFileName(
            self,
            "Export sweep results",
            "sweep-results.csv",
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return
        try:
            self._write_csv(path, self._row_to_result)
        except OSError as e:
            self._show_error(f"Could not write {path}: {e}")
            return
        self._show_info(f"Exported {len(self._row_to_result)} rows → {path}")

    def _write_csv(self, path: str, rows: list[SweepResult]) -> None:
        import csv

        pareto_set = {id(r) for r in self._pareto}
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(
                [
                    "core",
                    "wire",
                    "material",
                    "volume_cm3",
                    "L_uH",
                    "N",
                    "P_total_W",
                    "T_winding_C",
                    "cost_currency",
                    "cost_value",
                    "feasible",
                    "pareto",
                    "warnings",
                ]
            )
            for r in rows:
                r0 = r.result
                w.writerow(
                    [
                        r.core.part_number,
                        r.wire.id,
                        r.material.name,
                        f"{r.volume_cm3:.3f}",
                        f"{r0.L_actual_uH:.3f}",
                        r0.N_turns,
                        f"{r0.losses.P_total_W:.4f}",
                        f"{r0.T_winding_C:.2f}",
                        r.cost.currency if r.cost else "",
                        f"{r.cost.total_cost:.2f}" if r.cost else "",
                        "yes" if r.feasible else "no",
                        "yes" if id(r) in pareto_set else "no",
                        r.n_warnings,
                    ]
                )


class OptimizerDialog(QDialog):
    """Modal wrapper around :class:`OptimizerEmbed`.

    Kept for back-compat with callers that prefer a dialog. New code
    should embed :class:`OptimizerEmbed` directly inside a page.
    """

    selection_applied = Signal(str, str, str)

    def __init__(
        self,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        current_material_id: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Optimizer — sweep cores × wires")
        self.resize(1200, 700)
        layout = QVBoxLayout(self)

        self._embed = OptimizerEmbed(
            spec,
            materials,
            cores,
            wires,
            current_material_id,
            parent=self,
        )
        # Forward the inner signal AND auto-accept so callers that wait
        # for ``dlg.exec() == Accepted`` keep working unchanged.
        self._embed.selection_applied.connect(self._on_inner_applied)
        layout.addWidget(self._embed, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        bottom.addWidget(btn_close)
        layout.addLayout(bottom)

    def _on_inner_applied(self, material_id: str, core_id: str, wire_id: str) -> None:
        self.selection_applied.emit(material_id, core_id, wire_id)
        self.accept()
