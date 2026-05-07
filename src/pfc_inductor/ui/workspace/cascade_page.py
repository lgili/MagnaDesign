"""Cascade workspace page — multi-tier optimizer UI.

Layout, top to bottom:

- **Header**: title + intro paragraph.
- **Spec strip**: read-only summary of the spec being optimised
  (topology, Pout, Vin/Vout, fsw). Tells the user what they're
  about to sweep.
- **Run config card**: spinboxes for Tier 2 K, Tier 3 K, parallel
  workers; a small badge that probes the FEA backend live so the
  user knows whether `--tier3` will actually do anything.
- **Action row**: Run / Cancel + run-id + elapsed seconds.
- **Tier progress card**: four labelled progress bars (one per
  tier) with a status label that reads ``idle | running | done |
  skipped`` per tier.
- **Top-N table**: candidate ranking. Columns auto-widen when
  Tier 2 / Tier 3 metrics arrive in the row's `notes` payload —
  same reveal pattern the CLI's `_print_top` uses.
- **Tier 0 reject reasons**: a compact stats strip beneath the
  table showing what got cut and why (window_overflow,
  too_small_L, saturates).
- **Selection actions**: Apply / Open in design view, both
  enabled only when a row is selected. Apply emits the same
  `selection_applied(material_id, core_id, wire_id)` signal the
  Otimizador and Núcleo card use, so MainWindow's existing
  `_apply_optimizer_choice` handler picks it up unchanged.

Phase B / Phase C wiring lives in `optimize.cascade.orchestrator`;
the page is purely a view / controller around that.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from platformdirs import user_data_dir
from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, Material, Spec, Wire
from pfc_inductor.optimize.cascade import (
    CandidateRow,
    CascadeConfig,
    CascadeOrchestrator,
    RunStore,
    TierProgress,
)
from pfc_inductor.optimize.cascade.tier3 import supports_tier3
from pfc_inductor.ui.widgets import Card

# Qt UserRole carries the candidate_key on the first cell of each row.
_USER_ROLE_KEY = 0x0100


# ─── Sub-widgets ──────────────────────────────────────────────────


class _SpecStrip(QFrame):
    """Read-only horizontal strip showing key spec fields."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("CascadeSpecStrip")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(18)

        self._fields: dict[str, QLabel] = {}
        for key in ("topology", "Pout", "Vin", "Vout", "fsw", "ripple"):
            container = QFrame()
            container.setObjectName("CascadeSpecField")
            v = QVBoxLayout(container)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            cap = QLabel(self._caption(key))
            cap.setProperty("role", "muted")
            val = QLabel("—")
            val.setProperty("role", "metric")
            v.addWidget(cap)
            v.addWidget(val)
            h.addWidget(container)
            self._fields[key] = val
        h.addStretch(1)

    @staticmethod
    def _caption(key: str) -> str:
        return {
            "topology": "TOPOLOGIA",
            "Pout": "POTÊNCIA",
            "Vin": "ENTRADA",
            "Vout": "SAÍDA",
            "fsw": "F_SW",
            "ripple": "RIPPLE",
        }[key]

    def update_from_spec(self, spec: Optional[Spec]) -> None:
        if spec is None:
            for label in self._fields.values():
                label.setText("—")
            return
        self._fields["topology"].setText(spec.topology)
        self._fields["Pout"].setText(f"{spec.Pout_W:.0f} W")
        self._fields["Vin"].setText(
            f"{spec.Vin_min_Vrms:.0f}–{spec.Vin_max_Vrms:.0f} V",
        )
        if spec.topology == "boost_ccm":
            self._fields["Vout"].setText(f"{spec.Vout_V:.0f} V")
        else:
            self._fields["Vout"].setText("—")
        if spec.f_sw_kHz > 0 and spec.topology == "boost_ccm":
            self._fields["fsw"].setText(f"{spec.f_sw_kHz:.0f} kHz")
        else:
            self._fields["fsw"].setText(f"{spec.f_line_Hz:.0f} Hz")
        self._fields["ripple"].setText(f"{spec.ripple_pct:.0f} %")


class _RunConfigCard(QWidget):
    """Spinboxes for Tier-K values + workers + FEA badge."""

    config_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("CascadeRunConfig")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        self.tier2_spin = self._make_spin(0, 1000, 50)
        self.tier3_spin = self._make_spin(0, 200, 0)
        import os as _os
        self.workers_spin = self._make_spin(1, max(_os.cpu_count() or 1, 1),
                                            min(4, _os.cpu_count() or 1))
        for spin in (self.tier2_spin, self.tier3_spin, self.workers_spin):
            # QSpinBox.valueChanged passes the int value; our signal
            # is parameter-less, so wrap with a lambda.
            spin.valueChanged.connect(lambda _value: self.config_changed.emit())

        layout.addLayout(self._labelled("Tier 2 (top-K)", self.tier2_spin))
        layout.addLayout(self._labelled("Tier 3 (top-K)", self.tier3_spin))
        layout.addLayout(self._labelled("Workers", self.workers_spin))

        # FEA backend badge — informational; refresh on Run.
        self.fea_badge = QLabel("Backend FEA: probing…")
        self.fea_badge.setProperty("class", "Pill")
        self.fea_badge.setProperty("pill", "neutral")
        layout.addStretch(1)
        layout.addWidget(self.fea_badge)

        self.refresh_fea_status()

    def _labelled(self, label: str, widget: QWidget) -> QVBoxLayout:
        v = QVBoxLayout()
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        cap = QLabel(label.upper())
        cap.setProperty("role", "muted")
        v.addWidget(cap)
        v.addWidget(widget)
        return v

    @staticmethod
    def _make_spin(lo: int, hi: int, default: int) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(default)
        s.setMinimumWidth(80)
        return s

    def refresh_fea_status(self) -> None:
        """Probe FEMMT/FEMM at runtime and update the badge."""
        ok = supports_tier3()
        if ok:
            self.fea_badge.setText("Backend FEA: configurado")
            self.fea_badge.setProperty("pill", "ok")
        else:
            self.fea_badge.setText("Backend FEA: indisponível")
            self.fea_badge.setProperty("pill", "warn")
        self.fea_badge.style().unpolish(self.fea_badge)
        self.fea_badge.style().polish(self.fea_badge)

    def to_cascade_config(self) -> CascadeConfig:
        return CascadeConfig(
            tier2_top_k=int(self.tier2_spin.value()),
            tier3_top_k=int(self.tier3_spin.value()),
        )

    def workers(self) -> int:
        return int(self.workers_spin.value())

    def set_busy(self, busy: bool) -> None:
        for spin in (self.tier2_spin, self.tier3_spin, self.workers_spin):
            spin.setEnabled(not busy)


class _TierProgressGrid(QWidget):
    """Four tier rows with progress bar + status label each."""

    TIERS: tuple[tuple[int, str], ...] = (
        (0, "Tier 0  Feasibility"),
        (1, "Tier 1  Analítico"),
        (2, "Tier 2  Transitório"),
        (3, "Tier 3  FEA"),
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._bars: dict[int, QProgressBar] = {}
        self._statuses: dict[int, QLabel] = {}
        for tier_id, label in self.TIERS:
            row = QHBoxLayout()
            row.setSpacing(10)
            lbl = QLabel(label)
            lbl.setMinimumWidth(170)
            bar = QProgressBar()
            bar.setRange(0, 1)
            bar.setValue(0)
            bar.setFormat("%v / %m")
            bar.setMinimumHeight(20)
            status = QLabel("idle")
            status.setProperty("role", "muted")
            status.setMinimumWidth(70)
            row.addWidget(lbl)
            row.addWidget(bar, 1)
            row.addWidget(status)
            holder = QWidget()
            holder.setLayout(row)
            layout.addWidget(holder)
            self._bars[tier_id] = bar
            self._statuses[tier_id] = status

    def reset(self) -> None:
        for bar, status in zip(self._bars.values(), self._statuses.values(), strict=False):
            bar.setRange(0, 1)
            bar.setValue(0)
            status.setText("idle")

    def mark_skipped(self, tier_id: int) -> None:
        if tier_id in self._statuses:
            self._statuses[tier_id].setText("skipped")
            bar = self._bars[tier_id]
            bar.setRange(0, 1)
            bar.setValue(0)

    def update_tier(self, tier: int, done: int, total: int) -> None:
        bar = self._bars.get(tier)
        status = self._statuses.get(tier)
        if bar is None or status is None:
            return
        bar.setRange(0, max(total, 1))
        bar.setValue(done)
        if done >= total and total > 0:
            status.setText("done")
        else:
            status.setText("running")


class _StatsCard(QWidget):
    """Tier 0 reject breakdown + per-tier counts."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        self._t0_total = self._stat_block("TOTAL")
        self._t0_feasible = self._stat_block("TIER 0 OK")
        self._t0_rejected = self._stat_block("TIER 0 REJECT")
        self._reasons = QLabel("—")
        self._reasons.setProperty("role", "muted")
        self._reasons.setWordWrap(True)
        self._t1_evaluated = self._stat_block("TIER 1")
        self._t2_evaluated = self._stat_block("TIER 2")
        self._t3_evaluated = self._stat_block("TIER 3")

        for block in (self._t0_total, self._t0_feasible, self._t0_rejected,
                      self._t1_evaluated, self._t2_evaluated, self._t3_evaluated):
            layout.addLayout(block[0])
        layout.addWidget(self._reasons, 1)

    def _stat_block(self, caption: str) -> tuple[QVBoxLayout, QLabel]:
        v = QVBoxLayout()
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        cap = QLabel(caption)
        cap.setProperty("role", "muted")
        val = QLabel("0")
        val.setProperty("role", "metric")
        v.addWidget(cap)
        v.addWidget(val)
        return v, val

    def reset(self) -> None:
        for _, label in (self._t0_total, self._t0_feasible, self._t0_rejected,
                         self._t1_evaluated, self._t2_evaluated,
                         self._t3_evaluated):
            label.setText("0")
        self._reasons.setText("—")

    def update_from_store(self, store: RunStore, run_id: str) -> None:
        """Pull aggregate counts straight from SQLite (cheap)."""
        # Reuse the cli's `_gather_stats` shape via the same SQL.
        with store._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=?",
                (run_id,),
            ).fetchone()["n"]
            t0_ok = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates "
                "WHERE run_id=? AND feasible_t0=1", (run_id,),
            ).fetchone()["n"]
            t0_rej = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates "
                "WHERE run_id=? AND feasible_t0=0", (run_id,),
            ).fetchone()["n"]
            t1 = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates "
                "WHERE run_id=? AND highest_tier>=1", (run_id,),
            ).fetchone()["n"]
            t2 = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates "
                "WHERE run_id=? AND highest_tier>=2", (run_id,),
            ).fetchone()["n"]
            t3 = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates "
                "WHERE run_id=? AND highest_tier>=3", (run_id,),
            ).fetchone()["n"]
            reason_rows = conn.execute(
                "SELECT notes FROM candidates "
                "WHERE run_id=? AND feasible_t0=0 AND notes IS NOT NULL",
                (run_id,),
            ).fetchall()
        # Update labels.
        self._t0_total[1].setText(str(total))
        self._t0_feasible[1].setText(str(t0_ok))
        self._t0_rejected[1].setText(str(t0_rej))
        self._t1_evaluated[1].setText(str(t1))
        self._t2_evaluated[1].setText(str(t2))
        self._t3_evaluated[1].setText(str(t3))
        # Reasons.
        import json
        from collections import Counter
        counts: Counter[str] = Counter()
        for row in reason_rows:
            try:
                payload = json.loads(row["notes"])
            except (TypeError, json.JSONDecodeError):
                continue
            for r in payload.get("reasons", []):
                counts[str(r)] += 1
        if counts:
            parts = [
                f"{name}={count}"
                for name, count in counts.most_common()
            ]
            self._reasons.setText("Tier 0 rejects: " + " · ".join(parts))
        else:
            self._reasons.setText("—")


class _TopNTable(QTableWidget):
    """Candidate ranking table — auto-widens when T2 / T3 columns arrive."""

    selection_changed = Signal(str)  # candidate_key (or empty)

    BASE_HEADERS: tuple[str, ...] = (
        "#", "Core", "Mat", "Wire", "N",
        "Loss W", "ΔT °C", "Cost $",
    )
    T2_HEADERS: tuple[str, ...] = ("L_avg µH", "B_pk T", "sat")
    T3_HEADERS: tuple[str, ...] = ("L_FEA µH", "ΔL₃ %", "B_FEA T", "conf")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(0, len(self.BASE_HEADERS), parent)
        self.setHorizontalHeaderLabels(list(self.BASE_HEADERS))
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        h = self.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        h.setStretchLastSection(True)
        self.setMinimumHeight(220)
        self.itemSelectionChanged.connect(self._on_selection_changed)

    def populate(self, rows: list[CandidateRow]) -> None:
        has_t2 = any(r.notes and "tier2" in r.notes for r in rows)
        has_t3 = any(r.notes and "tier3" in r.notes for r in rows)
        headers = list(self.BASE_HEADERS)
        if has_t2:
            headers += list(self.T2_HEADERS)
        if has_t3:
            headers += list(self.T3_HEADERS)
        if self.columnCount() != len(headers):
            self.setColumnCount(len(headers))
            self.setHorizontalHeaderLabels(headers)

        self.setRowCount(len(rows))
        for i, r in enumerate(rows):
            cells: list[str] = [
                str(i + 1),
                r.core_id,
                r.material_id,
                r.wire_id,
                str(r.N) if r.N is not None else "—",
                f"{r.loss_t1_W:.2f}" if r.loss_t1_W is not None else "—",
                f"{r.temp_t1_C:.0f}" if r.temp_t1_C is not None else "—",
                f"{r.cost_t1_USD:.2f}" if r.cost_t1_USD is not None else "—",
            ]
            t2 = (r.notes or {}).get("tier2") or {}
            t3 = (r.notes or {}).get("tier3") or {}
            if has_t2:
                cells += [
                    f"{t2['L_avg_uH']:.1f}" if "L_avg_uH" in t2 else "—",
                    f"{t2['B_pk_T']:.3f}" if "B_pk_T" in t2 else "—",
                    "Y" if r.saturation_t2 else
                    "N" if r.saturation_t2 is not None else "—",
                ]
            if has_t3:
                cells += [
                    f"{r.L_t3_uH:.1f}" if r.L_t3_uH is not None else "—",
                    (
                        f"{t3['L_relative_error_pct']:+.1f}"
                        if t3.get("L_relative_error_pct") is not None else "—"
                    ),
                    f"{r.Bpk_t3_T:.3f}" if r.Bpk_t3_T is not None else "—",
                    str(t3.get("confidence", "—")),
                ]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(_USER_ROLE_KEY, r.candidate_key)
                self.setItem(i, col, item)

    def selected_candidate(self) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Return (candidate_key, core_id, material_id, wire_id) for the
        currently selected row, or all-None if none."""
        rows = self.selectionModel().selectedRows()
        if not rows:
            return None, None, None, None
        idx = rows[0].row()
        first = self.item(idx, 0)
        if first is None:
            return None, None, None, None
        key = first.data(_USER_ROLE_KEY)
        core_item = self.item(idx, 1)
        mat_item = self.item(idx, 2)
        wire_item = self.item(idx, 3)
        return (
            key,
            core_item.text() if core_item is not None else None,
            mat_item.text() if mat_item is not None else None,
            wire_item.text() if wire_item is not None else None,
        )

    def _on_selection_changed(self) -> None:
        key, *_ = self.selected_candidate()
        self.selection_changed.emit(key or "")


# ─── Worker thread ────────────────────────────────────────────────


class _CascadeWorker(QObject):
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
    """Workspace page hosting the multi-tier cascade optimizer."""

    open_in_design_requested = Signal(str)
    selection_applied = Signal(str, str, str)

    POLL_INTERVAL_MS = 750
    TOP_N = 25

    def __init__(
        self,
        store_path: Optional[Path] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        if store_path is None:
            store_path = Path(
                user_data_dir("PFCInductorDesigner", "indutor"),
            ) / "cascade.db"
        self._store = RunStore(store_path)
        self._orch = CascadeOrchestrator(self._store)

        self._spec: Optional[Spec] = None
        self._materials: list[Material] = []
        self._cores: list[Core] = []
        self._wires: list[Wire] = []
        self._run_id: Optional[str] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[_CascadeWorker] = None
        # Tracks which tiers were configured this run so we can
        # mark them `skipped` immediately when K=0.
        self._scheduled_tiers: set[int] = {0, 1}

        self._build_ui()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._refresh_dynamic)

    # ─── UI construction ─────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        title = QLabel("Otimizador profundo")
        title.setProperty("role", "title")
        outer.addWidget(title)

        intro = QLabel(
            "Sweep multi-tier sobre todas as combinações viáveis. "
            "Tier 0 elimina inviáveis (geometria + saturação), "
            "Tier 1 calcula o operating-point analítico, "
            "Tier 2 (transitório) refina L_avg e flags de saturação "
            "via curva anhisterética, e Tier 3 (FEA) cross-check "
            "numérico em FEMMT / FEMM nos top-K."
        )
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        # Spec strip (compact, read-only).
        self._spec_strip = _SpecStrip()
        outer.addWidget(Card("Spec ativo", self._spec_strip))

        # Run config + actions row, side by side.
        self._cfg = _RunConfigCard()
        outer.addWidget(Card("Configuração do run", self._cfg))

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self._btn_run = QPushButton("▶  Run")
        self._btn_run.setMinimumHeight(32)
        self._btn_run.setProperty("class", "Primary")
        self._btn_cancel = QPushButton("■  Cancel")
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.setMinimumHeight(32)
        self._btn_run.clicked.connect(self.run)
        self._btn_cancel.clicked.connect(self.cancel)

        self._status_label = QLabel("idle")
        self._status_label.setProperty("role", "muted")

        action_row.addWidget(self._btn_run)
        action_row.addWidget(self._btn_cancel)
        action_row.addSpacing(20)
        action_row.addWidget(self._status_label, 1)

        action_holder = QWidget()
        action_holder.setLayout(action_row)
        outer.addWidget(action_holder)

        # Tier progress.
        self._tiers = _TierProgressGrid()
        outer.addWidget(Card("Progresso por tier", self._tiers))

        # Stats.
        self._stats = _StatsCard()
        outer.addWidget(Card("Estatísticas do run", self._stats))

        # Top-N table.
        self._table = _TopNTable()
        self._table.itemDoubleClicked.connect(self._on_row_activated)
        self._table.selection_changed.connect(self._on_selection_changed)
        outer.addWidget(Card(f"Top {self.TOP_N} por loss", self._table), 1)

        # Selection actions.
        sel_row = QHBoxLayout()
        sel_row.setSpacing(8)
        self._btn_apply = QPushButton("Aplicar selecionado no projeto")
        self._btn_apply.setEnabled(False)
        self._btn_apply.clicked.connect(self._on_apply_clicked)
        self._btn_open = QPushButton("Abrir no Projeto")
        self._btn_open.setEnabled(False)
        self._btn_open.clicked.connect(self._on_open_clicked)
        sel_row.addWidget(self._btn_apply)
        sel_row.addWidget(self._btn_open)
        sel_row.addStretch(1)
        sel_holder = QWidget()
        sel_holder.setLayout(sel_row)
        outer.addWidget(sel_holder)

    # ─── Public API ──────────────────────────────────────────────

    def set_inputs(
        self,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        config: Optional[CascadeConfig] = None,  # legacy compat
    ) -> None:
        """Configure the page's spec and database before `run`."""
        if self._thread is not None and self._thread.isRunning():
            return
        self._spec = spec
        self._materials = list(materials)
        self._cores = list(cores)
        self._wires = list(wires)
        self._spec_strip.update_from_spec(spec)
        # Refresh the FEA badge so the user sees if FEMMT got
        # provisioned between sessions.
        self._cfg.refresh_fea_status()

    def run(self) -> None:
        if self._spec is None:
            return
        if self._thread is not None and self._thread.isRunning():
            return

        config = self._cfg.to_cascade_config()
        # Set parallelism on the orchestrator before starting the run.
        self._orch.parallelism = self._cfg.workers()
        self._orch.reset_cancel()

        run_id = self._orch.start_run(self._spec, config)
        self._run_id = run_id

        # Reset UI surfaces to a clean "running" state.
        self._tiers.reset()
        self._stats.reset()
        self._table.setRowCount(0)
        self._scheduled_tiers = {0, 1}
        if config.tier2_top_k > 0:
            self._scheduled_tiers.add(2)
        else:
            self._tiers.mark_skipped(2)
        if config.tier3_top_k > 0:
            self._scheduled_tiers.add(3)
        else:
            self._tiers.mark_skipped(3)

        self._status_label.setText(f"running · run_id={run_id}")

        self._thread = QThread(self)
        self._worker = _CascadeWorker(
            self._orch, run_id, self._spec,
            self._materials, self._cores, self._wires, config,
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
        self._cfg.set_busy(True)
        self._poll_timer.start()
        self._thread.start()

    def cancel(self) -> None:
        self._orch.cancel()
        self._btn_cancel.setEnabled(False)
        self._status_label.setText("cancelando…")

    # ─── Slots ───────────────────────────────────────────────────

    def _on_progress(self, tier: int, done: int, total: int) -> None:
        self._tiers.update_tier(tier, done, total)

    def _on_finished(self, status: str) -> None:
        self._poll_timer.stop()
        self._refresh_dynamic()
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._cfg.set_busy(False)
        self._thread = None
        self._worker = None
        # Make sure tiers that got no progress events are visibly
        # done (the orchestrator can finish a tier without firing a
        # final 100 % event when the candidate set is empty).
        for t in self._scheduled_tiers:
            self._tiers.update_tier(t, 1, 1)
        self._status_label.setText(f"{status} · run_id={self._run_id}")

    def _refresh_dynamic(self) -> None:
        """Refresh the parts of the UI that read from the store."""
        if self._run_id is None:
            return
        self._stats.update_from_store(self._store, self._run_id)
        rows = self._store.top_candidates(
            self._run_id, n=self.TOP_N, order_by="loss_t1_W",
        )
        self._table.populate(rows)

    def _on_selection_changed(self, candidate_key: str) -> None:
        self._btn_apply.setEnabled(bool(candidate_key))
        self._btn_open.setEnabled(bool(candidate_key))

    def _on_apply_clicked(self) -> None:
        _key, core_id, mat_id, wire_id = self._table.selected_candidate()
        if not (core_id and mat_id and wire_id):
            return
        self.selection_applied.emit(mat_id, core_id, wire_id)

    def _on_open_clicked(self) -> None:
        key, *_ = self._table.selected_candidate()
        if key:
            self.open_in_design_requested.emit(key)

    def _on_row_activated(self, item: QTableWidgetItem) -> None:
        if item is None:
            return
        first = self._table.item(item.row(), 0)
        if first is None:
            return
        key = first.data(_USER_ROLE_KEY)
        if isinstance(key, str):
            self.open_in_design_requested.emit(key)
