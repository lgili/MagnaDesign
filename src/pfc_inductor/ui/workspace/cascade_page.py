"""Cascade workspace page — UI host for the deep multi-tier optimizer.

The page wraps `CascadeOrchestrator` in a Qt-friendly worker thread,
exposes Run / Cancel controls, renders per-tier progress bars, and
streams a top-N table from the SQLite `RunStore` every second.

Phase A scope:
- Tier 0 + Tier 1 progress + ranking only.
- Sidebar / MainWindow integration is intentionally **not** wired
  here so the UI surface stays stable for shipping users; embedding
  CascadePage in MainWindow is a deliberate follow-up that ships
  behind a flag once Phase A has been benchmarked.

The host is expected to call :meth:`set_inputs` before :meth:`run`
to provide the spec and the live database.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from platformdirs import user_data_dir
from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, Material, Spec, Wire
from pfc_inductor.optimize.cascade import (
    CascadeConfig,
    CascadeOrchestrator,
    RunStore,
    TierProgress,
)
from pfc_inductor.ui.widgets import Card

# ─── Worker thread ────────────────────────────────────────────────

class _CascadeWorker(QObject):
    """Runs `CascadeOrchestrator.run` on a worker `QThread`.

    Emits `progress(tier, done, total)` for each tier update and
    `finished(status)` once the run completes (status is
    `'done'`, `'cancelled'`, or `'error: <msg>'`).
    """

    progress = Signal(int, int, int)
    finished = Signal(str)

    def __init__(
        self,
        orchestrator: CascadeOrchestrator,
        run_id: str,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        config: CascadeConfig,
    ) -> None:
        super().__init__()
        self._orch = orchestrator
        self._run_id = run_id
        self._spec = spec
        self._materials = materials
        self._cores = cores
        self._wires = wires
        self._config = config

    def run(self) -> None:
        def _cb(p: TierProgress) -> None:
            self.progress.emit(p.tier, p.done, p.total)

        try:
            self._orch.run(
                self._run_id, self._spec,
                self._materials, self._cores, self._wires,
                self._config, progress_cb=_cb,
            )
            record = self._orch.store.get_run(self._run_id)
            status = record.status if record is not None else "error: no record"
        except Exception as exc:
            status = f"error: {type(exc).__name__}: {exc}"
        self.finished.emit(status)


# ─── Page ─────────────────────────────────────────────────────────

class CascadePage(QWidget):
    """Workspace page hosting the cascade optimizer."""

    # Emits the candidate-key when the user double-clicks a row, so
    # the host can hydrate it into the standard design view.
    open_in_design_requested = Signal(str)

    POLL_INTERVAL_MS = 1000
    TOP_N = 20

    def __init__(
        self,
        store_path: Optional[Path] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Defaults to <user_data>/cascade.db so multiple runs accumulate
        # in a single inspectable file.
        if store_path is None:
            store_path = Path(user_data_dir("PFCInductorDesigner", "indutor")) / "cascade.db"
        self._store = RunStore(store_path)
        self._orch = CascadeOrchestrator(self._store)

        # Mutable state for the active run.
        self._spec: Optional[Spec] = None
        self._materials: list[Material] = []
        self._cores: list[Core] = []
        self._wires: list[Wire] = []
        self._config = CascadeConfig()
        self._run_id: Optional[str] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[_CascadeWorker] = None

        self._build_ui()

        # Polls the store while a run is active so the top-N table
        # reflects newly written rows.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._refresh_top_n)

    # ─── UI construction ─────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        title = QLabel("Otimizador profundo")
        title.setProperty("role", "title")
        outer.addWidget(title)

        intro = QLabel(
            "Sweep multi-tier sobre todas as combinações viáveis: "
            "filtro de viabilidade (Tier 0) seguido de avaliação "
            "analítica completa (Tier 1) com persistência. "
            "Tiers 2/3/4 (transitório + FEA) entram em fases seguintes."
        )
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        # ── Action bar ─────────────────────────────────────────
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._btn_run = QPushButton("Run")
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setEnabled(False)
        self._btn_run.clicked.connect(self.run)
        self._btn_cancel.clicked.connect(self.cancel)
        actions.addWidget(self._btn_run)
        actions.addWidget(self._btn_cancel)
        actions.addStretch(1)

        actions_holder = QWidget()
        actions_holder.setLayout(actions)
        outer.addWidget(Card("Controles", actions_holder))

        # ── Per-tier progress ──────────────────────────────────
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(6)
        self._tier_bars: dict[int, QProgressBar] = {}
        self._tier_labels: dict[int, QLabel] = {}
        for tier_id, tier_label in [
            (0, "Tier 0  Feasibility"),
            (1, "Tier 1  Analítico"),
        ]:
            row = QHBoxLayout()
            label = QLabel(tier_label)
            label.setMinimumWidth(180)
            bar = QProgressBar()
            bar.setRange(0, 1)
            bar.setValue(0)
            bar.setFormat("%v / %m")
            status = QLabel("idle")
            status.setProperty("role", "muted")
            row.addWidget(label)
            row.addWidget(bar, 1)
            row.addWidget(status)
            self._tier_bars[tier_id] = bar
            self._tier_labels[tier_id] = status
            holder = QWidget()
            holder.setLayout(row)
            progress_layout.addWidget(holder)

        progress_holder = QWidget()
        progress_holder.setLayout(progress_layout)
        outer.addWidget(Card("Progresso por tier", progress_holder))

        # ── Top-N table ────────────────────────────────────────
        self._table = QTableWidget(0, 6, self)
        self._table.setHorizontalHeaderLabels(
            ["#", "Core", "Material", "Wire", "Loss [W]", "ΔT [°C]"],
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self._table.itemDoubleClicked.connect(self._on_row_activated)

        outer.addWidget(Card(f"Top {self.TOP_N} por loss (Tier 1)", self._table), 1)

    # ─── Public API ──────────────────────────────────────────────

    def set_inputs(
        self,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        config: Optional[CascadeConfig] = None,
    ) -> None:
        """Configure the page's spec and database before `run`.

        Calling this while a run is in flight is a no-op — wait for
        `finished` first or call `cancel` and then re-setup.
        """
        if self._thread is not None and self._thread.isRunning():
            return
        self._spec = spec
        self._materials = list(materials)
        self._cores = list(cores)
        self._wires = list(wires)
        self._config = config or CascadeConfig()

    def run(self) -> None:
        """Start a cascade run on the configured inputs."""
        if self._spec is None:
            return
        if self._thread is not None and self._thread.isRunning():
            return

        self._orch.reset_cancel()
        run_id = self._orch.start_run(self._spec, self._config)
        self._run_id = run_id

        # Reset progress UI.
        for bar, label in zip(self._tier_bars.values(), self._tier_labels.values(), strict=False):
            bar.setRange(0, 1)
            bar.setValue(0)
            label.setText("pending")
        self._table.setRowCount(0)

        # Spin up worker thread.
        self._thread = QThread(self)
        self._worker = _CascadeWorker(
            self._orch, run_id, self._spec,
            self._materials, self._cores, self._wires, self._config,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._btn_run.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._poll_timer.start()
        self._thread.start()

    def cancel(self) -> None:
        """Signal cancellation. The worker drains its in-flight call."""
        self._orch.cancel()
        self._btn_cancel.setEnabled(False)

    # ─── Slots ───────────────────────────────────────────────────

    def _on_progress(self, tier: int, done: int, total: int) -> None:
        bar = self._tier_bars.get(tier)
        label = self._tier_labels.get(tier)
        if bar is None or label is None:
            return
        bar.setRange(0, max(total, 1))
        bar.setValue(done)
        label.setText("running" if done < total else "done")

    def _on_finished(self, status: str) -> None:
        self._poll_timer.stop()
        self._refresh_top_n()  # final pass to capture last-second writes
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._thread = None
        self._worker = None

    def _refresh_top_n(self) -> None:
        if self._run_id is None:
            return
        rows = self._store.top_candidates(
            self._run_id, n=self.TOP_N, order_by="loss_t1_W",
        )
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            cells = [
                str(i + 1),
                r.core_id,
                r.material_id,
                r.wire_id,
                f"{r.loss_t1_W:.2f}" if r.loss_t1_W is not None else "—",
                f"{r.temp_t1_C:.0f}" if r.temp_t1_C is not None else "—",
            ]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                # Keep the candidate key on the row's first cell so we
                # can read it back on double-click.
                if col == 0:
                    item.setData(0x0100, r.candidate_key)  # Qt.UserRole = 0x0100
                self._table.setItem(i, col, item)

    def _on_row_activated(self, item: QTableWidgetItem) -> None:
        if item is None:
            return
        first = self._table.item(item.row(), 0)
        if first is None:
            return
        key = first.data(0x0100)
        if isinstance(key, str):
            self.open_in_design_requested.emit(key)
