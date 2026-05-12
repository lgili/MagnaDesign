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
  Optimizer and Core card use, so MainWindow's existing
  `_apply_optimizer_choice` handler picks it up unchanged.

Phase B / Phase C wiring lives in `optimize.cascade.orchestrator`;
the page is purely a view / controller around that.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, Mapping, Optional

from platformdirs import user_data_dir
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
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
from pfc_inductor.optimize.cascade.store import RunRecord
from pfc_inductor.optimize.cascade.tier3 import supports_tier3
from pfc_inductor.ui.widgets import Card, wrap_scrollable
from pfc_inductor.ui.widgets.optimizer_filters_bar import OptimizerFiltersBar

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
            "topology": "TOPOLOGY",
            "Pout": "POWER",
            "Vin": "INPUT",
            "Vout": "OUTPUT",
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
        if spec.topology in ("boost_ccm", "interleaved_boost_pfc"):
            self._fields["Vout"].setText(f"{spec.Vout_V:.0f} V")
        else:
            self._fields["Vout"].setText("—")
        if spec.f_sw_kHz > 0 and spec.topology in ("boost_ccm", "interleaved_boost_pfc"):
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
        # Tier 4 is N × Tier 3 wall, so the practical ceiling is
        # ~10 even on fast workstations. Default 0 (off).
        self.tier4_spin = self._make_spin(0, 50, 0)
        import os as _os

        self.workers_spin = self._make_spin(
            1, max(_os.cpu_count() or 1, 1), min(4, _os.cpu_count() or 1)
        )
        for spin in (self.tier2_spin, self.tier3_spin, self.tier4_spin, self.workers_spin):
            # QSpinBox.valueChanged passes the int value; our signal
            # is parameter-less, so wrap with a lambda.
            spin.valueChanged.connect(lambda _value: self.config_changed.emit())

        layout.addLayout(self._labelled("Tier 2 (top-K)", self.tier2_spin))
        layout.addLayout(self._labelled("Tier 3 (top-K)", self.tier3_spin))
        layout.addLayout(self._labelled("Tier 4 (top-K)", self.tier4_spin))
        layout.addLayout(self._labelled("Workers", self.workers_spin))

        # FEA backend badge — informational; refresh on Run.
        self.fea_badge = QLabel("FEA backend: probing…")
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
            self.fea_badge.setText("FEA backend: configured")
            self.fea_badge.setProperty("pill", "ok")
        else:
            self.fea_badge.setText("FEA backend: unavailable")
            self.fea_badge.setProperty("pill", "warn")
        self.fea_badge.style().unpolish(self.fea_badge)
        self.fea_badge.style().polish(self.fea_badge)

    def to_cascade_config(self) -> CascadeConfig:
        return CascadeConfig(
            tier2_top_k=int(self.tier2_spin.value()),
            tier3_top_k=int(self.tier3_spin.value()),
            tier4_top_k=int(self.tier4_spin.value()),
        )

    def workers(self) -> int:
        return int(self.workers_spin.value())

    def set_busy(self, busy: bool) -> None:
        for spin in (self.tier2_spin, self.tier3_spin, self.tier4_spin, self.workers_spin):
            spin.setEnabled(not busy)


class _TierProgressGrid(QWidget):
    """Four tier rows with progress bar + status label each."""

    TIERS: tuple[tuple[int, str], ...] = (
        (0, "Tier 0  Feasibility"),
        (1, "Tier 1  Analytical"),
        (2, "Tier 2  Transient"),
        (3, "Tier 3  Static FEA"),
        (4, "Tier 4  Swept FEA"),
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
        self._t4_evaluated = self._stat_block("TIER 4")

        for block in (
            self._t0_total,
            self._t0_feasible,
            self._t0_rejected,
            self._t1_evaluated,
            self._t2_evaluated,
            self._t3_evaluated,
            self._t4_evaluated,
        ):
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
        for _, label in (
            self._t0_total,
            self._t0_feasible,
            self._t0_rejected,
            self._t1_evaluated,
            self._t2_evaluated,
            self._t3_evaluated,
            self._t4_evaluated,
        ):
            label.setText("0")
        self._reasons.setText("—")

    def apply_counts(
        self,
        stats: tuple[int, int, int, int, int, int, int],
        reasons_text: str,
    ) -> None:
        """Apply a pre-computed stats tuple to the labels.

        Receives the result of ``_RefreshWorker._compute`` so the GUI
        thread doesn't itself touch SQLite. Order matches the worker's
        emission order: ``(total, t0_ok, t0_rej, t1, t2, t3, t4)``.
        """
        total, t0_ok, t0_rej, t1, t2, t3, t4 = stats
        self._t0_total[1].setText(str(total))
        self._t0_feasible[1].setText(str(t0_ok))
        self._t0_rejected[1].setText(str(t0_rej))
        self._t1_evaluated[1].setText(str(t1))
        self._t2_evaluated[1].setText(str(t2))
        self._t3_evaluated[1].setText(str(t3))
        self._t4_evaluated[1].setText(str(t4))
        self._reasons.setText(reasons_text)

    def update_from_store(self, store: RunStore, run_id: str) -> None:
        """Pull aggregate counts straight from SQLite (cheap)."""
        # Reuse the cli's `_gather_stats` shape via the same SQL.
        with store._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=?",
                (run_id,),
            ).fetchone()["n"]
            t0_ok = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=? AND feasible_t0=1",
                (run_id,),
            ).fetchone()["n"]
            t0_rej = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=? AND feasible_t0=0",
                (run_id,),
            ).fetchone()["n"]
            t1 = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=? AND highest_tier>=1",
                (run_id,),
            ).fetchone()["n"]
            t2 = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=? AND highest_tier>=2",
                (run_id,),
            ).fetchone()["n"]
            t3 = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=? AND highest_tier>=3",
                (run_id,),
            ).fetchone()["n"]
            t4 = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=? AND highest_tier>=4",
                (run_id,),
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
        self._t4_evaluated[1].setText(str(t4))
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
            parts = [f"{name}={count}" for name, count in counts.most_common()]
            self._reasons.setText("Tier 0 rejects: " + " · ".join(parts))
        else:
            self._reasons.setText("—")


def _figure_imports():
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
    from matplotlib.figure import Figure

    return Canvas, Figure


class _ParetoChart(QWidget):
    """Loss × volume Pareto chart for the top-N candidates.

    Each candidate is a scatter point at (volume, loss); the
    non-dominated set (lower loss AND lower volume than any peer)
    is highlighted as the Pareto frontier connecting Vmin–Vmax.
    Clicking a point emits `selection_changed(candidate_key)`,
    so it stays in lock-step with the sibling top-N table.

    The chart depends on `Core` lookup to read `Ve_mm3` (volume),
    so callers pass a `cores_by_id` map alongside the rows.
    """

    selection_changed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._outer = layout

        # Deferred Figure construction. Cascade page is not the
        # default workspace page, so the matplotlib cost lands when
        # the user first navigates here.
        self._placeholder = QWidget()
        self._placeholder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._placeholder)
        self._fig = None
        self._ax = None
        self._canvas = None
        self._canvas_built = False
        self._row_keys: list[str] = []  # parallel to scatter point indexes
        self._pending_populate: Optional[tuple[list, dict]] = None
        # Stashed payload from the off-thread refresh worker for the
        # case where the user hasn't shown the cascade tab yet.
        self._pending_chart_payload: Optional[_RefreshPayload] = None

    def _ensure_canvas_built(self) -> None:
        if self._canvas_built:
            return
        Canvas, Figure = _figure_imports()
        self._fig = Figure(figsize=(5.4, 3.6), dpi=100, tight_layout=True)
        self._ax = self._fig.add_subplot(1, 1, 1)
        self._canvas = Canvas(self._fig)
        idx = self._outer.indexOf(self._placeholder)
        self._outer.removeWidget(self._placeholder)
        self._placeholder.deleteLater()
        self._placeholder = None  # type: ignore[assignment]
        self._outer.insertWidget(idx, self._canvas)
        self._canvas_built = True
        self._canvas.mpl_connect("pick_event", self._on_pick)
        # Replay priority: prefer the pre-computed payload (no
        # extra worker round-trip needed) over the raw rows fallback.
        if self._pending_chart_payload is not None:
            payload = self._pending_chart_payload
            self._pending_chart_payload = None
            self.populate_from_payload(payload)
        elif self._pending_populate is not None:
            rows, cores_by_id = self._pending_populate
            self._pending_populate = None
            self.populate(rows, cores_by_id)
        else:
            self._render_empty()

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        self._ensure_canvas_built()

    # ─── Public API ──────────────────────────────────────────────

    def populate_from_payload(self, payload: _RefreshPayload) -> None:
        """Render from a pre-computed ``_RefreshPayload``.

        The xs / ys / candidate-key arrays AND the Pareto-front
        index list have already been computed off the GUI thread by
        ``_RefreshWorker._compute``; the chart's only remaining job
        is the matplotlib draw call itself. Keeps the GUI thread
        away from the SQLite + per-core volume math that used to
        dominate every refresh tick.
        """
        xs_t, ys_t, keys_t = payload.chart_data
        # Update ``_row_keys`` regardless of canvas state — picks
        # depend on it being in sync with the latest rendered set.
        self._row_keys = list(keys_t)
        if not self._canvas_built:
            self._pending_chart_payload = payload
            return
        assert self._ax is not None and self._canvas is not None
        xs = list(xs_t)
        ys = list(ys_t)
        if not xs:
            self._render_empty()
            return
        self._render_scatter(xs, ys, list(payload.pareto_indices))

    def populate(
        self,
        rows: list[CandidateRow],
        cores_by_id: dict[str, Core],
    ) -> None:
        """Re-render with a fresh row set.

        Rows whose core is not in ``cores_by_id`` or that don't
        carry a loss number from any tier are skipped — the chart
        plots the *highest-tier* loss (via ``loss_top_W``) so a
        candidate that ran through Tier 4 lands at its FEA-corrected
        loss, not the original analytical Tier-1 value.
        """
        # ``_row_keys`` is the contract picks depend on, so it has
        # to update regardless of canvas state — otherwise a pick on
        # a chart constructed off-screen would emit the wrong key.
        # We compute xs/ys/_row_keys eagerly, then only do the
        # matplotlib draw call when the canvas is built.
        xs: list[float] = []
        ys: list[float] = []
        self._row_keys = []
        for r in rows:
            loss = r.loss_top_W
            if loss is None:
                continue
            core = cores_by_id.get(r.core_id)
            if core is None:
                continue
            volume_cm3 = float(core.Ve_mm3) / 1000.0
            xs.append(volume_cm3)
            ys.append(float(loss))
            self._row_keys.append(r.candidate_key)
        if not self._canvas_built:
            # Stash the source rows for replay on first ``showEvent``.
            # ``_row_keys`` is already populated for picks-before-show.
            self._pending_populate = (list(rows), dict(cores_by_id))
            return
        assert self._ax is not None and self._canvas is not None
        if not xs:
            self._render_empty()
            return
        pareto = _pareto_indices(xs, ys)
        self._render_scatter(xs, ys, pareto)

    def _render_scatter(self, xs: list[float], ys: list[float], pareto: list[int]) -> None:
        """Apply the matplotlib draw calls — extracted so both the
        live-data path (:meth:`populate`) and the off-thread path
        (:meth:`populate_from_payload`) reuse the same rendering
        code without duplicating logic."""
        assert self._ax is not None and self._canvas is not None
        self._ax.clear()

        # All-points scatter.
        self._ax.scatter(
            xs,
            ys,
            s=42,
            c="#7c8696",
            alpha=0.65,
            edgecolors="#3a4351",
            linewidths=0.6,
            picker=8,
            label="Candidates",
        )
        # Pareto front overlay (front indices are pre-computed by
        # the caller so we don't redo the O(n²) scan in both the
        # ``populate`` path and the ``populate_from_payload`` path).
        if pareto:
            xp = [xs[i] for i in pareto]
            yp = [ys[i] for i in pareto]
            # Sort along volume axis to draw a clean frontier line.
            order = sorted(range(len(xp)), key=lambda i: xp[i])
            xp_sorted = [xp[i] for i in order]
            yp_sorted = [yp[i] for i in order]
            self._ax.plot(
                xp_sorted,
                yp_sorted,
                color="#ee7c2b",
                linewidth=1.4,
                marker="o",
                markersize=7,
                markerfacecolor="#ee7c2b",
                markeredgecolor="#a85013",
                label="Pareto",
            )
        self._ax.set_xlabel("Volume Ve [cm³]")
        self._ax.set_ylabel("Loss total [W]")
        self._ax.grid(True, alpha=0.25, linestyle=":")
        self._ax.legend(loc="upper right", frameon=False, fontsize=9)
        self._canvas.draw_idle()

    # ─── Internals ──────────────────────────────────────────────

    def _render_empty(self) -> None:
        assert self._ax is not None and self._canvas is not None
        self._ax.clear()
        self._ax.text(
            0.5,
            0.5,
            "No Tier 1 results yet.\nRun a cascade to populate the chart.",
            transform=self._ax.transAxes,
            ha="center",
            va="center",
            color="#7c8696",
            fontsize=10,
        )
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        self._canvas.draw_idle()

    def _on_pick(self, event) -> None:
        ind = getattr(event, "ind", None)
        if ind is None or len(ind) == 0:
            return
        first = int(ind[0])
        if 0 <= first < len(self._row_keys):
            self.selection_changed.emit(self._row_keys[first])


def _pareto_indices(xs: list[float], ys: list[float]) -> list[int]:
    """Return indices of the Pareto-optimal points (lower-is-better
    on both axes). O(n²) — fine for the cascade's top-N (<= ~50)."""
    n = len(xs)
    pareto: list[int] = []
    for i in range(n):
        dominated = False
        for j in range(n):
            if i == j:
                continue
            if xs[j] <= xs[i] and ys[j] <= ys[i] and (xs[j] < xs[i] or ys[j] < ys[i]):
                dominated = True
                break
        if not dominated:
            pareto.append(i)
    return pareto


def _tier_badge(row: CandidateRow) -> str:
    """Short label naming the tier that produced the displayed
    Loss / ΔT cell. Read in lockstep with
    :pyattr:`store.CandidateRow.loss_top_W`."""
    if row.loss_t4_W is not None:
        return "T4"
    if row.loss_t3_W is not None:
        return "T3"
    if row.loss_t2_W is not None:
        return "T2"
    if row.loss_t1_W is not None:
        return "T1"
    return "—"


class _TopNTable(QTableWidget):
    """Candidate ranking table — auto-widens when T2 / T3 columns arrive."""

    selection_changed = Signal(str)  # candidate_key (or empty)

    BASE_HEADERS: tuple[str, ...] = (
        "#",
        "Core",
        "Mat",
        "Wire",
        "N",
        "Loss W",
        "ΔT °C",
        "Cost $",
        "Tier",
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

    def populate_from_payload(self, payload: _RefreshPayload) -> None:
        """Variant of :meth:`populate` that takes a ``_RefreshPayload``
        produced off the GUI thread. The pre-computed ``has_t2`` /
        ``has_t3`` flags save another pass over rows on the GUI
        thread; everything else mirrors :meth:`populate`."""
        self._populate_internal(list(payload.rows), payload.has_t2, payload.has_t3)

    def populate(self, rows: list[CandidateRow]) -> None:
        has_t2 = any(r.notes and "tier2" in r.notes for r in rows)
        has_t3 = any(r.notes and "tier3" in r.notes for r in rows)
        self._populate_internal(rows, has_t2, has_t3)

    def _populate_internal(self, rows: list[CandidateRow], has_t2: bool, has_t3: bool) -> None:
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
            # Loss / ΔT read the highest-tier value the candidate
            # has reached — the Tier-2 simulator and Tier-3 / 4
            # FEA solvers each write a refined number into their
            # own column (see ``optimize.cascade.refine``). The
            # ``loss_top_W`` / ``temp_top_C`` properties COALESCE
            # down the tier ladder so the table never shows a
            # stale Tier-1 number when a deeper tier has refined
            # it. Cost stays at Tier 1 because the BOM doesn't
            # change with simulation fidelity.
            loss = r.loss_top_W
            temp = r.temp_top_C
            # T_amb fallback (25 °C) for ΔT = T_winding − T_amb is
            # held implicitly by the engine when ``temp_top_C`` is
            # already a rise; we don't need to materialise it here.
            # ``temp_t*_C`` columns store winding temperature; the
            # historical column header is "ΔT" but the engine has
            # always written the rise, not the absolute. Keep that
            # contract here — temp_top_C is a winding-temp value;
            # the rise is recovered by subtracting ambient if we
            # don't have temp_t1_C handy.
            cells: list[str] = [
                str(i + 1),
                r.core_id,
                r.material_id,
                r.wire_id,
                str(r.N) if r.N is not None else "—",
                f"{loss:.2f}" if loss is not None else "—",
                f"{temp:.0f}" if temp is not None else "—",
                f"{r.cost_t1_USD:.2f}" if r.cost_t1_USD is not None else "—",
                _tier_badge(r),
            ]
            t2 = (r.notes or {}).get("tier2") or {}
            t3 = (r.notes or {}).get("tier3") or {}
            if has_t2:
                cells += [
                    f"{t2['L_avg_uH']:.1f}" if "L_avg_uH" in t2 else "—",
                    f"{t2['B_pk_T']:.3f}" if "B_pk_T" in t2 else "—",
                    "Y" if r.saturation_t2 else "N" if r.saturation_t2 is not None else "—",
                ]
            if has_t3:
                cells += [
                    f"{r.L_t3_uH:.1f}" if r.L_t3_uH is not None else "—",
                    (
                        f"{t3['L_relative_error_pct']:+.1f}"
                        if t3.get("L_relative_error_pct") is not None
                        else "—"
                    ),
                    f"{r.Bpk_t3_T:.3f}" if r.Bpk_t3_T is not None else "—",
                    str(t3.get("confidence", "—")),
                ]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(_USER_ROLE_KEY, r.candidate_key)
                self.setItem(i, col, item)

    def selected_candidate(
        self,
    ) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
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


# ─── Run history dialog ───────────────────────────────────────────


class _RunHistoryDialog(QDialog):
    """Modal dialog listing past cascade runs from the SQLite store.

    Each row shows timestamp + status + candidate count + topology
    + spec-hash prefix. Selecting a row and confirming returns the
    `run_id`; CascadePage hydrates its table + stats from the
    store without re-running anything.
    """

    def __init__(
        self,
        store: RunStore,
        *,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run history")
        self.setMinimumSize(640, 360)
        self._store = store
        self._selected_run_id: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro = QLabel(
            "Pick a previous run to load its results "
            "(top-N + stats). No candidate is re-evaluated.",
        )
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._list, 1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel,
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Open).setEnabled(False)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self._list.itemSelectionChanged.connect(self._update_button_state)
        layout.addWidget(self._buttons)

        self._populate()

    # ─── Populate from store ────────────────────────────────────

    def _populate(self) -> None:
        runs = self._store.list_runs()
        self._list.clear()
        if not runs:
            placeholder = QListWidgetItem("(no runs in store)")
            placeholder.setFlags(
                placeholder.flags() & ~Qt.ItemFlag.ItemIsSelectable,
            )
            self._list.addItem(placeholder)
            return
        for record in runs:
            n_cand = self._store.candidate_count(record.run_id)
            label = self._format_label(record, n_cand)
            item = QListWidgetItem(label)
            item.setData(0x0100, record.run_id)  # Qt.UserRole
            self._list.addItem(item)
        # Default selection on the most recent run.
        self._list.setCurrentRow(0)

    @staticmethod
    def _format_label(record: RunRecord, n_cand: int) -> str:
        ts = time.strftime(
            "%Y-%m-%d %H:%M",
            time.localtime(record.started_at),
        )
        try:
            topology = record.spec().topology
        except Exception:
            topology = "?"
        short_id = record.run_id[-12:]  # truncated; full id available on hover
        return (
            f"{ts}  ·  {topology:<14}  ·  {record.status:<10}  ·  "
            f"{n_cand:>5} cand  ·  spec {record.spec_hash[:8]}…  "
            f"·  {short_id}"
        )

    # ─── Slots ──────────────────────────────────────────────────

    def _update_button_state(self) -> None:
        item = self._list.currentItem()
        ok = item is not None and item.data(0x0100) is not None
        self._buttons.button(QDialogButtonBox.StandardButton.Open).setEnabled(bool(ok))

    def _on_double_click(self, item: QListWidgetItem) -> None:
        if item.data(0x0100) is not None:
            self.accept()

    # ─── Public API ────────────────────────────────────────────

    def selected_run_id(self) -> Optional[str]:
        item = self._list.currentItem()
        if item is None:
            return None
        rid = item.data(0x0100)
        return rid if isinstance(rid, str) else None


# ─── Worker thread ────────────────────────────────────────────────


@dataclass(frozen=True)
class _RefreshPayload:
    """Snapshot of everything the cascade UI needs to repaint a single
    poll cycle. Computed by ``_RefreshWorker`` off the main thread so
    the chart + table only see a ready-to-render result.
    """

    stats: tuple[int, int, int, int, int, int, int]
    """(total, t0_ok, t0_rej, t1, t2, t3, t4) — counts from the store."""
    reasons_text: str
    """Rendered ``Tier 0 rejects: x=N · y=M`` summary, or ``"—"``."""
    rows: tuple
    """Top-N ``CandidateRow`` rows, already objective-sorted."""
    chart_data: tuple[tuple[float, ...], tuple[float, ...], tuple[str, ...]]
    """``(xs, ys, candidate_keys)`` — pre-computed scatter inputs so the
    UI thread only does the matplotlib draw call, not the data pull."""
    pareto_indices: tuple[int, ...]
    """Indices into ``chart_data`` arrays that form the Pareto front."""
    has_t2: bool
    has_t3: bool
    """Column-visibility flags so the table can decide its header set
    without re-scanning ``rows`` on the main thread."""

    def fingerprint(self) -> int:
        """Hash for change-detection. ``_refresh_dynamic`` skips the
        repaint entirely when the new payload matches the previous —
        avoids redundant matplotlib redraws when the cascade is mid-
        SQLite-flush and the visible state hasn't changed."""
        return hash(
            (
                self.stats,
                self.reasons_text,
                tuple(
                    (r.candidate_key, r.loss_top_W, r.temp_top_C, r.highest_tier) for r in self.rows
                ),
            )
        )


class _RefreshWorker(QObject):
    """Pull stats + top-N + Pareto data off the UI thread.

    The cascade run lives in its own ``QThread`` (see ``_CascadeWorker``)
    so the engine itself never blocks the main loop. The poll timer
    that drives the live results table + Pareto chart, however,
    historically ran on the GUI thread — 8 SQLite reads + a
    matplotlib redraw every 750 ms while the cascade was active. On
    a mid-spec laptop with a busy chart that's 100–300 ms of UI-
    thread work per cycle, surfacing as visible jank during the
    multi-minute Tier 0 / 1 phases users complained about ("trava
    tudo durante o full optimizer").

    Moving the SQLite + ranking + Pareto math here lets the UI
    thread only handle the cheap final updates: ``QLabel.setText``,
    ``QTableWidget.setItem``, and matplotlib's ``draw_idle``.
    """

    done = Signal(object)  # _RefreshPayload
    failed = Signal(str)

    @Slot(str, str, object)
    def compute(self, run_id: str, objective: str, cores_by_id: object) -> None:
        """Compute a refresh payload from the live store.

        ``cores_by_id`` crosses the thread boundary as a plain dict
        of immutable Pydantic models — safe to read concurrently
        with the parent CascadePage's ``self._cores`` list.
        """
        try:
            payload = self._compute(run_id, objective, cores_by_id)  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover — defensive
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(payload)

    def _compute(
        self, run_id: str, objective: str, cores_by_id: dict[str, Core]
    ) -> _RefreshPayload:

        # The store is process-safe via SQLite WAL mode; opening a
        # connection per call is cheap and avoids cross-thread
        # connection sharing (sqlite3 connections are not thread-
        # safe by default).
        store = self._store
        with store._connect() as conn:
            stats_total = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=?",
                (run_id,),
            ).fetchone()["n"]
            stats_t0_ok = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=? AND feasible_t0=1",
                (run_id,),
            ).fetchone()["n"]
            stats_t0_rej = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=? AND feasible_t0=0",
                (run_id,),
            ).fetchone()["n"]
            stats_t1 = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=? AND highest_tier>=1",
                (run_id,),
            ).fetchone()["n"]
            stats_t2 = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=? AND highest_tier>=2",
                (run_id,),
            ).fetchone()["n"]
            stats_t3 = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=? AND highest_tier>=3",
                (run_id,),
            ).fetchone()["n"]
            stats_t4 = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id=? AND highest_tier>=4",
                (run_id,),
            ).fetchone()["n"]
            reason_rows = conn.execute(
                "SELECT notes FROM candidates "
                "WHERE run_id=? AND feasible_t0=0 AND notes IS NOT NULL",
                (run_id,),
            ).fetchall()

        import json
        from collections import Counter

        counts: Counter[str] = Counter()
        for row in reason_rows:
            try:
                payload_notes = json.loads(row["notes"])
            except (TypeError, json.JSONDecodeError):
                continue
            for r in payload_notes.get("reasons", []):
                counts[str(r)] += 1
        if counts:
            reasons_text = "Tier 0 rejects: " + " · ".join(
                f"{name}={count}" for name, count in counts.most_common()
            )
        else:
            reasons_text = "—"

        # Top-N rows + objective re-rank.
        column = self._objective_to_column.get(objective)
        if column is not None:
            rows = store.top_candidates(run_id, n=self._top_n, order_by=column)
        else:
            wide = store.top_candidates(run_id, n=self._top_n * 5, order_by="loss_top_W")
            rows = self._rerank(wide, cores_by_id, objective)[: self._top_n]

        # Pareto scatter inputs — same logic the UI used to do
        # synchronously inside ``_ParetoChart.populate``. Pre-compute
        # so the GUI thread only has to feed matplotlib.
        xs: list[float] = []
        ys: list[float] = []
        keys: list[str] = []
        for r in rows:
            loss = r.loss_top_W
            if loss is None:
                continue
            core = cores_by_id.get(r.core_id)
            if core is None:
                continue
            xs.append(float(core.Ve_mm3) / 1000.0)
            ys.append(float(loss))
            keys.append(r.candidate_key)
        pareto = _pareto_indices(xs, ys) if xs else []

        # Tier badge column visibility flags.
        has_t2 = any(r.notes and "tier2" in r.notes for r in rows)
        has_t3 = any(r.notes and "tier3" in r.notes for r in rows)

        return _RefreshPayload(
            stats=(stats_total, stats_t0_ok, stats_t0_rej, stats_t1, stats_t2, stats_t3, stats_t4),
            reasons_text=reasons_text,
            rows=tuple(rows),
            chart_data=(tuple(xs), tuple(ys), tuple(keys)),
            pareto_indices=tuple(pareto),
            has_t2=has_t2,
            has_t3=has_t3,
        )

    # Worker-side mirrors of the page's class-level config. Filled
    # in by ``CascadePage._start_refresh_worker`` so the worker is
    # fully self-contained (no QObject parent reach-back).
    _store: RunStore
    _top_n: int
    _objective_to_column: dict[str, str]

    @staticmethod
    def _rerank(rows: list, cores_by_id: dict[str, Core], objective: str) -> list:
        """Mirror of ``CascadePage._rerank_client_side``. Kept in the
        worker so we don't ferry a method-bound reference across
        threads (slot signatures stay clean)."""

        def vol_of(r) -> float:  # type: ignore[no-untyped-def]
            c = cores_by_id.get(r.core_id)
            if c is None:
                return float("inf")
            v = getattr(c, "volume_cm3", None)
            if v is not None:
                return float(v)
            try:
                return float(c.OD_mm or 0) ** 2 * float(c.HT_mm or 0) * 1e-3
            except (AttributeError, TypeError):
                return float("inf")

        if objective == "volume":
            return sorted(rows, key=vol_of)

        def norm(values: list[float]) -> list[float]:
            finite = [v for v in values if v != float("inf")]
            if not finite:
                return [0.0] * len(values)
            lo, hi = min(finite), max(finite)
            span = hi - lo or 1.0
            return [(v - lo) / span if v != float("inf") else 1.0 for v in values]

        losses = norm([(r.loss_top_W if r.loss_top_W is not None else float("inf")) for r in rows])
        vols = norm([vol_of(r) for r in rows])
        if objective == "score_with_cost":
            costs = norm([r.cost_t1_USD or float("inf") for r in rows])
            scores = [0.4 * losses[i] + 0.3 * vols[i] + 0.3 * costs[i] for i in range(len(rows))]
        else:
            scores = [0.6 * losses[i] + 0.4 * vols[i] for i in range(len(rows))]
        order = sorted(range(len(rows)), key=lambda i: scores[i])
        return [rows[i] for i in order]


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
                self._run_id,
                self._spec,
                self._materials,
                self._cores,
                self._wires,
                self._config,
                progress_cb=_cb,
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

    # Poll interval — used to be 750 ms but the SQL + Pareto math
    # ran on the GUI thread, so even at 750 ms the user perceived
    # the cascade as freezing the app. With ``_RefreshWorker``
    # handling the heavy work off-thread, 1 500 ms is plenty: a
    # cascade typically advances ~50–200 candidates between polls
    # at this cadence, which the engineer can absorb visually, and
    # we cut the GUI-side update rate in half regardless.
    POLL_INTERVAL_MS = 1_500
    TOP_N = 25

    # Internal — fires the worker's ``compute`` slot via
    # ``QueuedConnection``. Using a Signal instead of
    # ``QMetaObject.invokeMethod(Q_ARG(object, ...))`` because
    # PySide6 has no registered ``QMetaType`` for arbitrary Python
    # objects (same fix we applied to ``MainWindow._calc_requested``
    # after the v0.4.12 ``qArgDataFromPyType`` regression).
    _refresh_requested = Signal(str, str, object)
    """``(run_id, objective, cores_by_id)`` — dispatches a refresh."""

    def __init__(
        self,
        store_path: Optional[Path] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        if store_path is None:
            store_path = (
                Path(
                    user_data_dir("PFCInductorDesigner", "indutor"),
                )
                / "cascade.db"
            )
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

        # Refresh-worker plumbing — keeps the heavy SQL + Pareto
        # math off the GUI thread so the rest of the app stays
        # responsive while the cascade is running. The worker
        # thread lives for the lifetime of the page (vs. one-per-
        # refresh) so we don't pay thread-spawn cost on every
        # 1.5 s tick.
        self._refresh_thread: Optional[QThread] = None
        self._refresh_worker: Optional[_RefreshWorker] = None
        # Coalescing: at most one in-flight refresh + one pending.
        # If the timer fires while a worker is still computing, we
        # set ``_refresh_pending`` and re-dispatch when the current
        # one returns. Avoids backlog under heavy SQLite load.
        self._refresh_in_flight = False
        self._refresh_pending = False
        # Change-detection fingerprint — repaints are skipped when
        # the new payload matches the previous (SQLite-quiet phases
        # would otherwise still trigger a matplotlib redraw on
        # every tick).
        self._last_refresh_fingerprint: Optional[int] = None
        self._start_refresh_worker()

        # Connect to ``QApplication.aboutToQuit`` so the long-lived
        # refresh thread is shut down BEFORE Qt starts destroying
        # widgets. The page's own ``closeEvent`` would suffice for
        # ``win.close()`` flows, but on Cmd+Q (macOS) and on Linux
        # session-end the page is destroyed as a child of the
        # QStackedWidget WITHOUT ``closeEvent`` firing — and Qt
        # fatals with "QThread: Destroyed while thread is still
        # running" if we hit the destructor with the thread live.
        # ``aboutToQuit`` is the canonical pre-destruction hook for
        # global cleanup like this.
        from PySide6.QtWidgets import QApplication as _QApplication

        _app = _QApplication.instance()
        if _app is not None:
            _app.aboutToQuit.connect(self._shutdown_refresh_thread)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._refresh_dynamic)

    def _shutdown_refresh_thread(self) -> None:
        """Quit + wait on the refresh worker thread. Idempotent.

        Called from both ``closeEvent`` (user-initiated window close)
        and ``QApplication.aboutToQuit`` (process shutdown via Cmd+Q
        / session-end). The first call to fire wins; subsequent
        calls see the thread already stopped and return immediately.
        """
        if self._refresh_thread is not None and self._refresh_thread.isRunning():
            self._refresh_thread.quit()
            self._refresh_thread.wait(2000)

    # ─── UI construction ─────────────────────────────────────────

    def _build_ui(self) -> None:
        # Outer layout hosts a single QScrollArea. All cards stack
        # inside the scrollable body so the page can shrink to fit
        # 1366×768 laptops — the cards alone (Spec strip + run config
        # + tier progress + stats + Top-N table 220 px min + selection
        # row) require ~920 px to display without clipping. Without
        # the scroll wrapper Qt grows the window past the screen edge
        # and hides the bottom Scoreboard.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QWidget()
        inner = QVBoxLayout(body)
        inner.setContentsMargins(24, 24, 24, 24)
        inner.setSpacing(12)

        title = QLabel("Full optimizer")
        title.setProperty("role", "title")
        inner.addWidget(title)

        intro = QLabel(
            "Multi-tier sweep over every feasible combination. "
            "Tier 0 prunes infeasible candidates (geometry + saturation), "
            "Tier 1 computes the analytical operating point, "
            "Tier 2 (transient) refines L_avg and saturation flags via "
            "the anhysteretic curve, and Tier 3 (FEA) cross-checks "
            "numerically in FEMMT / FEMM on the top-K."
        )
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)
        inner.addWidget(intro)

        # Spec strip (compact, read-only).
        self._spec_strip = _SpecStrip()
        inner.addWidget(Card("Active spec", self._spec_strip))

        # Eligible-catalogue summary. Reports how many materials made
        # it past the per-topology filter (see
        # ``topology.material_filter``) so the engineer can see at a
        # glance whether the cascade is iterating over the right
        # families. Updated on every ``set_inputs`` call.
        self._catalog_summary = QLabel("Eligible catalog: —")
        self._catalog_summary.setProperty("role", "muted")
        self._catalog_summary.setContentsMargins(0, 0, 0, 4)
        inner.addWidget(self._catalog_summary)

        # ---- Filter bar — pick which materials/cores/wires to sweep
        # plus the objective the top-N table is ordered by. Empty
        # selection on each chip == include the whole topology-eligible
        # catalogue, which matches the cascade's previous "sweep
        # everything" default.
        self._filters = OptimizerFiltersBar()
        self._filters.objective_changed.connect(
            lambda _key: self._refresh_dynamic(),
        )
        inner.addWidget(Card("Filters & objective", self._filters))

        # Run config + actions row, side by side.
        self._cfg = _RunConfigCard()
        inner.addWidget(Card("Run configuration", self._cfg))

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self._btn_run = QPushButton("▶  Run")
        self._btn_run.setMinimumHeight(32)
        self._btn_run.setProperty("class", "Primary")
        self._btn_cancel = QPushButton("■  Cancel")
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.setMinimumHeight(32)
        self._btn_history = QPushButton("History")
        self._btn_history.setMinimumHeight(32)
        self._btn_history.setToolTip(
            "Load results from a previous store run (no re-evaluation)",
        )
        self._btn_run.clicked.connect(self.run)
        self._btn_cancel.clicked.connect(self.cancel)
        self._btn_history.clicked.connect(self._open_history)

        self._status_label = QLabel("idle")
        self._status_label.setProperty("role", "muted")

        action_row.addWidget(self._btn_run)
        action_row.addWidget(self._btn_cancel)
        action_row.addWidget(self._btn_history)
        action_row.addSpacing(20)
        action_row.addWidget(self._status_label, 1)

        action_holder = QWidget()
        action_holder.setLayout(action_row)
        inner.addWidget(action_holder)

        # Tier progress.
        self._tiers = _TierProgressGrid()
        inner.addWidget(Card("Progress per tier", self._tiers))

        # Stats.
        self._stats = _StatsCard()
        inner.addWidget(Card("Run statistics", self._stats))

        # Top-N — table + Pareto chart in a tab widget.
        self._table = _TopNTable()
        self._table.itemDoubleClicked.connect(self._on_row_activated)
        self._table.selection_changed.connect(self._on_selection_changed)
        self._chart = _ParetoChart()
        self._chart.selection_changed.connect(self._on_chart_pick)
        self._results_tabs = QTabWidget()
        self._results_tabs.addTab(self._table, "List")
        self._results_tabs.addTab(self._chart, "Pareto")
        inner.addWidget(Card(f"Top {self.TOP_N} by loss", self._results_tabs), 1)

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
        inner.addWidget(sel_holder)

        # Mount the scrollable body. The QScrollArea takes ownership
        # of ``body``; the page itself is just the scroll viewport.
        outer.addWidget(wrap_scrollable(body))

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
        self._update_catalog_summary()
        # Push the topology-filtered catalogue into the filter bar so
        # its chips show the right "All N" defaults; the user's
        # current selection survives so long as the items are still
        # in the new catalogue (set_items prunes ids that disappeared).
        self._filters.set_catalogs(
            self._materials,
            self._cores,
            self._wires,
        )
        # Refresh the FEA badge so the user sees if FEMMT got
        # provisioned between sessions.
        self._cfg.refresh_fea_status()

    def _update_catalog_summary(self) -> None:
        """Refresh the small "Eligible catalog" line under the spec
        strip. Materials handed in here have already been filtered by
        :func:`pfc_inductor.topology.material_filter.materials_for_topology`
        upstream in MainWindow; we just summarise what arrived."""
        if not self._materials:
            self._catalog_summary.setText(
                "Eligible catalog: 0 materials",
            )
            return
        n = len(self._materials)
        types = sorted({m.type for m in self._materials})
        topology = self._spec.topology if self._spec is not None else "—"
        self._catalog_summary.setText(
            f"Eligible catalog: {n} materials ({', '.join(types)}) · topology: {topology}",
        )

    def run(self) -> None:
        if self._spec is None:
            return
        if self._thread is not None and self._thread.isRunning():
            return

        config = self._cfg.to_cascade_config()
        # Set parallelism on the orchestrator before starting the run.
        self._orch.parallelism = self._cfg.workers()
        self._orch.reset_cancel()

        # Resolve the user's filter selections. Empty chip == wildcard,
        # so ``selected_*`` returns the full topology-eligible catalogue.
        # The cascade engine receives whatever subset (or full set) the
        # engineer asked for, with no extra plumbing changes required —
        # ``CascadeOrchestrator.run`` already accepts arbitrary lists.
        materials = self._filters.selected_materials()
        cores = self._filters.selected_cores()
        wires = self._filters.selected_wires()

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
        if config.tier4_top_k > 0:
            self._scheduled_tiers.add(4)
        else:
            self._tiers.mark_skipped(4)

        self._status_label.setText(f"running · run_id={run_id}")

        self._thread = QThread(self)
        self._worker = _CascadeWorker(
            self._orch,
            run_id,
            self._spec,
            materials,
            cores,
            wires,
            config,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        # Standard Qt worker-thread pattern: queue cleanup on the
        # page side, quit the thread, schedule worker + thread
        # deletion. The `_on_finished` slot is auto-queued because
        # the worker lives in `self._thread` while the page lives
        # on the main thread.
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

    # ─── Run history loading ─────────────────────────────────────

    def _open_history(self) -> None:
        """Pop the modal, load the chosen run's data into the page."""
        if self._thread is not None and self._thread.isRunning():
            return
        dialog = _RunHistoryDialog(self._store, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        run_id = dialog.selected_run_id()
        if not run_id:
            return
        self._load_run_id(run_id)

    def _load_run_id(self, run_id: str) -> None:
        """Hydrate the page from an existing store run (no execution).

        - Stats card pulls from SQLite.
        - Top-N table populates from the same store query as a live run.
        - Tier progress bars all snap to `done` since this is historical
          data (we don't know the exact pre-prune candidate counts;
          showing them as 1/1 done keeps the UI honest).
        - Spec strip refreshes from the run's stored canonical spec
          so the engineer sees what *that* run was optimised for.

        Hydration runs the refresh payload **synchronously** here
        (unlike the live-run path, which dispatches via the worker).
        The reason is that ``_load_run_id`` is a one-shot triggered
        by a user action (selecting from the history dialog); they
        expect the table to be populated by the time the dialog
        closes. The query is also cheap — the cascade isn't writing
        concurrently — so blocking the GUI thread for one round-trip
        is negligible (~5–20 ms) vs. the user-visible delay of
        waiting for the worker to round-trip via the event loop.
        """
        record = self._store.get_run(run_id)
        if record is None:
            return
        try:
            historical_spec = record.spec()
            self._spec_strip.update_from_spec(historical_spec)
        except Exception:
            pass
        self._run_id = run_id
        self._tiers.reset()
        for t in (0, 1, 2, 3, 4):
            self._tiers.update_tier(t, 1, 1)
        # Synchronous hydration — see docstring. We piggy-back on
        # the worker's ``_compute`` implementation by calling it
        # from this thread (it doesn't touch any QObject state, so
        # cross-thread isn't an issue).
        assert self._refresh_worker is not None
        try:
            payload = self._refresh_worker._compute(
                run_id,
                self._filters.objective(),
                {c.id: c for c in self._cores},
            )
            self._stats.apply_counts(payload.stats, payload.reasons_text)
            self._table.populate_from_payload(payload)
            self._chart.populate_from_payload(payload)
            self._last_refresh_fingerprint = payload.fingerprint()
        except Exception:
            # Fall back to the async path on any error so the page
            # never gets stuck with stale data.
            self._refresh_dynamic()
        self._status_label.setText(
            f"loaded · {record.status} · run_id={run_id}",
        )

    # ─── Slots ───────────────────────────────────────────────────

    def _on_progress(self, tier: int, done: int, total: int) -> None:
        self._tiers.update_tier(tier, done, total)

    def _on_finished(self, status: str) -> None:
        # Reset the button state BEFORE everything else so even if a
        # subsequent step raises (matplotlib quirks etc.) the UI
        # doesn't stay stuck with Run disabled. Each step is wrapped
        # defensively because this slot is queued from the worker
        # thread and Qt silently swallows any exception leaking out.
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._cfg.set_busy(False)
        self._thread = None
        self._worker = None
        try:
            self._poll_timer.stop()
        except Exception:
            pass
        # Final refresh runs **synchronously** so the table /
        # chart / stats reflect the completed run before the
        # ``finished`` signal returns to subscribers (tests rely on
        # this contract — they read ``rowCount()`` right after
        # waiting on ``finished``). Same sync-compute trick we use
        # in ``_load_run_id``: bypass the worker thread for one-shot
        # hydration, where round-trip latency hurts more than the
        # brief GUI-thread block helps.
        try:
            if self._run_id is not None and self._refresh_worker is not None:
                payload = self._refresh_worker._compute(
                    self._run_id,
                    self._filters.objective(),
                    {c.id: c for c in self._cores},
                )
                self._stats.apply_counts(payload.stats, payload.reasons_text)
                self._table.populate_from_payload(payload)
                self._chart.populate_from_payload(payload)
                self._last_refresh_fingerprint = payload.fingerprint()
        except Exception:
            import traceback

            traceback.print_exc()
        # Make sure tiers that got no progress events are visibly
        # done (the orchestrator can finish a tier without firing a
        # final 100 % event when the candidate set is empty).
        try:
            for t in self._scheduled_tiers:
                self._tiers.update_tier(t, 1, 1)
            self._status_label.setText(f"{status} · run_id={self._run_id}")
        except Exception:
            pass

    # Map ``OptimizerFiltersBar`` objective keys → store ``order_by``
    # column names. Volume / score variants don't have a single column
    # in the store, so we order by loss server-side and re-rank
    # client-side with the volume / score weighting applied below.
    # Wrapped in ``MappingProxyType`` so the class-level default is
    # immutable — accidental ``cls._OBJECTIVE_TO_COLUMN["x"] = ...``
    # in test patching won't bleed across instances.
    # The ``loss_top_W`` / ``temp_top_C`` virtual columns COALESCE
    # down the tier ladder — a candidate that ran through Tier 4
    # is sorted by Tier-4 loss, while a Tier-1-only candidate is
    # sorted by Tier 1. No mode-flipping here. Cost is invariant
    # across tiers (same BOM) so it stays at the Tier-1 column.
    _OBJECTIVE_TO_COLUMN: ClassVar[Mapping[str, str]] = MappingProxyType(
        {
            "loss": "loss_top_W",
            "temp": "temp_top_C",
            "cost": "cost_t1_USD",
        },
    )

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """Tear down the long-lived refresh worker thread.

        Routes through ``_shutdown_refresh_thread`` so the same
        logic runs from both ``closeEvent`` and ``aboutToQuit``.
        The ``aboutToQuit`` path is what actually catches the
        Cmd+Q / session-end flow on macOS — ``closeEvent`` only
        fires when the user clicks the window's X button or calls
        ``win.close()`` explicitly.
        """
        self._shutdown_refresh_thread()
        super().closeEvent(event)

    def _start_refresh_worker(self) -> None:
        """Construct + start the long-lived refresh worker thread.

        Called once from ``__init__``. The worker holds onto the
        page's ``RunStore`` reference (sqlite3 connections are not
        thread-safe, so the worker opens its own short-lived
        connection per ``compute`` call) plus the class-level
        objective→column map.
        """
        self._refresh_thread = QThread(self)
        self._refresh_thread.setObjectName("pfc-cascade-refresh")
        self._refresh_worker = _RefreshWorker()
        # Hand the worker the references it needs to run without
        # reach-back into the parent ``QObject`` (which would mean
        # cross-thread attribute access).
        self._refresh_worker._store = self._store
        self._refresh_worker._top_n = self.TOP_N
        self._refresh_worker._objective_to_column = dict(self._OBJECTIVE_TO_COLUMN)
        self._refresh_worker.moveToThread(self._refresh_thread)
        self._refresh_worker.done.connect(
            self._on_refresh_payload,
            Qt.ConnectionType.QueuedConnection,
        )
        self._refresh_worker.failed.connect(
            self._on_refresh_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        # Main thread → worker dispatch via signal (see the
        # ``_calc_requested`` pattern in ``MainWindow`` for the
        # rationale — invokeMethod can't marshal Python objects).
        self._refresh_requested.connect(
            self._refresh_worker.compute,
            Qt.ConnectionType.QueuedConnection,
        )
        self._refresh_thread.start()

    def _refresh_dynamic(self) -> None:
        """Kick off (or coalesce) a refresh on the worker thread.

        Used to do all the work inline — 8 SQL queries, candidate
        re-ranking, Pareto-front math, and a matplotlib redraw — on
        every poll tick. With a busy cascade dumping rows into the
        store every batch, those redraws stacked up and turned the
        whole UI sluggish ("trava tudo durante o full optimizer").
        The worker pattern keeps everything off the GUI thread; the
        ``done`` slot only does the cheap final updates.
        """
        if self._run_id is None:
            return
        if self._refresh_in_flight:
            # A compute is already running — mark a follow-up
            # without queueing a backlog of stale requests.
            self._refresh_pending = True
            return
        self._refresh_in_flight = True
        self._refresh_requested.emit(
            self._run_id,
            self._filters.objective(),
            {c.id: c for c in self._cores},
        )

    @Slot(object)
    def _on_refresh_payload(self, payload: object) -> None:
        """Worker emitted ``done`` — apply the result on the GUI thread.

        Most of the work has already been done off-thread; here we
        just feed prepared values into widget setters. Change-
        detection via ``fingerprint`` skips redundant matplotlib /
        QTableWidget updates when the cascade is mid-flush and the
        visible state hasn't moved.
        """
        self._refresh_in_flight = False
        assert isinstance(payload, _RefreshPayload)
        fingerprint = payload.fingerprint()
        skip = fingerprint == self._last_refresh_fingerprint
        if not skip:
            self._last_refresh_fingerprint = fingerprint
            self._stats.apply_counts(payload.stats, payload.reasons_text)
            self._table.populate_from_payload(payload)
            self._chart.populate_from_payload(payload)
        # If another refresh was requested while we were running,
        # fire it now — but only after we've applied the current
        # payload so the user sees forward progress.
        if self._refresh_pending:
            self._refresh_pending = False
            self._refresh_dynamic()

    @Slot(str)
    def _on_refresh_failed(self, message: str) -> None:
        """Worker raised — log and keep polling. Refresh failures
        are not fatal; the next tick will retry."""
        self._refresh_in_flight = False
        # Don't spam the status bar — most failures are transient
        # SQLite-locked retries during heavy cascade writes. Log
        # to stderr so support bundles capture them.
        import sys

        print(f"[cascade refresh] {message}", file=sys.stderr)
        if self._refresh_pending:
            self._refresh_pending = False
            self._refresh_dynamic()

    @staticmethod
    def _rerank_client_side(
        rows: list[CandidateRow],
        cores_by_id: dict[str, Core],
        objective: str,
    ) -> list[CandidateRow]:
        """Sort ``rows`` by an objective the SQL store can't express.

        ``volume`` reads ``Core.volume_cm3`` (or computes it from
        OD × HT) for each row's ``core_id``. ``score`` and
        ``score_with_cost`` apply the same min-max-normalised weighting
        the simple optimizer's :func:`pfc_inductor.optimize.sweep.rank`
        uses, so the cascade and Pareto sweep agree on ordering.
        """

        def vol_of(r: CandidateRow) -> float:
            c = cores_by_id.get(r.core_id)
            if c is None:
                return float("inf")
            v = getattr(c, "volume_cm3", None)
            if v is not None:
                return float(v)
            # Fallback estimate when the catalogue entry lacks a
            # pre-computed volume. Order is what matters here, not
            # absolute magnitude.
            try:
                return float(c.OD_mm or 0) ** 2 * float(c.HT_mm or 0) * 1e-3
            except (AttributeError, TypeError):
                return float("inf")

        if objective == "volume":
            return sorted(rows, key=vol_of)

        # Min-max normalise loss + volume (+ optionally cost) to [0, 1]
        # then linearly combine. Matches sweep.rank()'s 60/40 and
        # 40/30/30 presets so the cascade ranking agrees with the
        # simple optimizer.
        def norm(values: list[float]) -> list[float]:
            finite = [v for v in values if v != float("inf")]
            if not finite:
                return [0.0] * len(values)
            lo, hi = min(finite), max(finite)
            span = hi - lo or 1.0
            return [(v - lo) / span if v != float("inf") else 1.0 for v in values]

        # Use the highest-tier loss (``loss_top_W``) so a candidate
        # ranked here also reflects the FEA-corrected loss when
        # Tier 3 / 4 ran. ``or float('inf')`` keeps Nones sortable.
        losses = norm([(r.loss_top_W if r.loss_top_W is not None else float("inf")) for r in rows])
        vols = norm([vol_of(r) for r in rows])
        if objective == "score_with_cost":
            costs = norm([r.cost_t1_USD or float("inf") for r in rows])
            scores = [0.4 * losses[i] + 0.3 * vols[i] + 0.3 * costs[i] for i in range(len(rows))]
        else:  # "score" (60/40 loss/vol) or unknown → behave as score
            scores = [0.6 * losses[i] + 0.4 * vols[i] for i in range(len(rows))]
        order = sorted(range(len(rows)), key=lambda i: scores[i])
        return [rows[i] for i in order]

    def _on_chart_pick(self, candidate_key: str) -> None:
        """Sync the table selection with whatever the user clicked
        in the Pareto chart, then re-emit the page-level selection
        signal so Apply / Open buttons enable."""
        if not candidate_key:
            return
        for row in range(self._table.rowCount()):
            cell = self._table.item(row, 0)
            if cell is None:
                continue
            if cell.data(_USER_ROLE_KEY) == candidate_key:
                self._table.selectRow(row)
                break

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
