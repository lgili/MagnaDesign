"""CascadeOrchestrator — drives the multi-tier sweep end-to-end.

Phase A wires Tier 0 (sequential) and Tier 1 (process-pool) into a
single resumable, cancellable, persistent run. Tier 2/3/4 hooks
land in their respective phases without changing the orchestrator's
public API.

Public API:

```python
orch = CascadeOrchestrator(store, parallelism=8)
run_id = orch.start_run(spec, materials, cores, wires, config)
orch.run(run_id, spec, materials, cores, wires, config, progress_cb=cb)
# ... or, from another thread:
orch.cancel()
```

`run` is idempotent: candidates already written to the store for
this `run_id` are skipped. After a crash, calling `run` again with
the same `run_id` resumes without re-evaluation.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from multiprocessing.synchronize import Event as MPEvent  # noqa: F401
from typing import Any, Callable, Optional

from pfc_inductor.data_loader import current_db_versions
from pfc_inductor.models import (
    Candidate,
    Core,
    Material,
    Spec,
    Tier0Result,
    Tier1Result,
    Wire,
)
from pfc_inductor.optimize.cascade.generators import cartesian
from pfc_inductor.optimize.cascade.store import CandidateRow, RunStore
from pfc_inductor.optimize.cascade.tier0 import filter_candidates
from pfc_inductor.optimize.cascade.tier1 import (
    cost_USD,
    evaluate_candidate_safe,
)
from pfc_inductor.optimize.cascade.tier2 import (
    evaluate_candidate_safe as evaluate_tier2_safe,
)
from pfc_inductor.optimize.cascade.tier2 import (
    supports_tier2,
)
from pfc_inductor.optimize.cascade.tier3 import (
    evaluate_candidate_safe as evaluate_tier3_safe,
)
from pfc_inductor.optimize.cascade.tier3 import (
    supports_tier3,
)
from pfc_inductor.optimize.cascade.tier4 import (
    DEFAULT_SWEEP_FRACTIONS,
    supports_tier4,
)
from pfc_inductor.optimize.cascade.tier4 import (
    evaluate_candidate_safe as evaluate_tier4_safe,
)
from pfc_inductor.optimize.feasibility import viable_wires_for_spec
from pfc_inductor.topology.registry import model_for

# ─── Public configuration & progress types ────────────────────────


@dataclass(frozen=True)
class CascadeConfig:
    """Tier thresholds and search-space filters for one run.

    `K_1` caps the Tier-1 survivors (top-N by ranking objective).
    `tier2_top_k` controls Tier 2: 0 disables it, K > 0 runs the
    transient simulator on the top-K Tier-1 survivors.
    `K_2`, `K_3` etc. enter when their phases land.
    """

    K_1: int = 1000
    tier2_top_k: int = 0
    tier3_top_k: int = 0
    tier3_timeout_s: int = 300
    tier3_disagree_pct: float = 15.0
    tier4_top_k: int = 0
    tier4_timeout_s: int = 600
    tier4_n_points: int = 5
    only_compatible_cores: bool = True
    only_round_wires: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "K_1": self.K_1,
            "tier2_top_k": self.tier2_top_k,
            "tier3_top_k": self.tier3_top_k,
            "tier3_timeout_s": self.tier3_timeout_s,
            "tier3_disagree_pct": self.tier3_disagree_pct,
            "tier4_top_k": self.tier4_top_k,
            "tier4_timeout_s": self.tier4_timeout_s,
            "tier4_n_points": self.tier4_n_points,
            "only_compatible_cores": self.only_compatible_cores,
            "only_round_wires": self.only_round_wires,
        }


@dataclass(frozen=True)
class TierProgress:
    """One progress update from the orchestrator to the UI / CLI.

    `tier` is 0..4. `done` and `total` are counts within that tier;
    when `done == total` the tier is finished.
    """

    tier: int
    done: int
    total: int


ProgressCallback = Callable[[TierProgress], None]


# ─── Worker-pool plumbing ─────────────────────────────────────────
#
# `multiprocessing` requires that the worker function and its
# initializer live at module top-level (so they pickle by name).
# `_WORKER_STATE` is a per-process dict populated once per worker
# by `_init_worker`. Each candidate then resolves its DB lookups
# from that local dict — avoids re-pickling the database for every
# candidate.

_WORKER_STATE: dict[str, Any] = {}


def _init_worker(
    spec_json: str,
    materials: list[Material],
    cores: list[Core],
    wires: list[Wire],
) -> None:
    spec = Spec.model_validate_json(spec_json)
    _WORKER_STATE["model"] = model_for(spec)
    _WORKER_STATE["materials"] = {m.id: m for m in materials}
    _WORKER_STATE["cores"] = {c.id: c for c in cores}
    _WORKER_STATE["wires"] = {w.id: w for w in wires}


def _tier1_worker(
    candidate: Candidate,
) -> tuple[Optional[Tier1Result], Optional[str], Optional[float]]:
    """Tier-1 worker: evaluate one candidate, return (result, error, cost).

    The cost is computed in-worker so the main process never has to
    re-resolve the (core, material, wire) for the cost model.
    """
    s = _WORKER_STATE
    mat = s["materials"][candidate.material_id]
    core = s["cores"][candidate.core_id]
    wire = s["wires"][candidate.wire_id]
    result, error = evaluate_candidate_safe(
        s["model"],
        candidate,
        core,
        mat,
        wire,
    )
    cost: Optional[float] = None
    if result is not None:
        cost = cost_USD(result.design, core, mat, wire)
    return result, error, cost


# ─── Row builders ─────────────────────────────────────────────────


def _row_from_tier0(t0: Tier0Result) -> CandidateRow:
    return CandidateRow(
        candidate_key=t0.candidate.key(),
        core_id=t0.candidate.core_id,
        material_id=t0.candidate.material_id,
        wire_id=t0.candidate.wire_id,
        N=t0.candidate.N,
        gap_mm=t0.candidate.gap_mm,
        highest_tier=0,
        feasible_t0=t0.envelope.feasible,
        notes={"reasons": t0.envelope.reasons} if t0.envelope.reasons else None,
    )


def _row_with_tier4(
    base: CandidateRow,
    tier4,  # Tier4Result | None
    error: Optional[str],
) -> CandidateRow:
    """Return a copy of `base` with Tier 4 columns + notes filled.

    `L_t4_uH` (the existing schema column) holds `L_avg_FEA_uH` from
    the multi-point sweep — Tier 4's headline number. The full sweep
    payload (per-point currents / L / B, saturation flag, backend,
    cost) goes into `notes['tier4']` for the CLI / UI to surface.
    """
    notes_in = dict(base.notes) if base.notes else {}
    if tier4 is None:
        if error is not None:
            notes_in["tier4_error"] = error
        else:
            notes_in["tier4_skipped"] = True
        return CandidateRow(
            candidate_key=base.candidate_key,
            core_id=base.core_id,
            material_id=base.material_id,
            wire_id=base.wire_id,
            N=base.N,
            gap_mm=base.gap_mm,
            highest_tier=base.highest_tier,
            feasible_t0=base.feasible_t0,
            loss_t1_W=base.loss_t1_W,
            temp_t1_C=base.temp_t1_C,
            cost_t1_USD=base.cost_t1_USD,
            loss_t2_W=base.loss_t2_W,
            saturation_t2=base.saturation_t2,
            L_t3_uH=base.L_t3_uH,
            Bpk_t3_T=base.Bpk_t3_T,
            L_t4_uH=base.L_t4_uH,
            notes=notes_in or None,
        )
    notes_in["tier4"] = {
        "backend": tier4.backend,
        "L_min_FEA_uH": tier4.L_min_FEA_uH,
        "L_max_FEA_uH": tier4.L_max_FEA_uH,
        "B_pk_FEA_T": tier4.B_pk_FEA_T,
        "saturation_t4": tier4.saturation_t4,
        "n_points_simulated": tier4.n_points_simulated,
        "solve_time_s": tier4.solve_time_s,
        "L_avg_relative_to_tier3_pct": tier4.L_avg_relative_to_tier3_pct,
        "sample_currents_A": list(tier4.sample_currents_A),
        "sample_L_uH": list(tier4.sample_L_uH),
        "sample_B_T": list(tier4.sample_B_T),
    }
    return CandidateRow(
        candidate_key=base.candidate_key,
        core_id=base.core_id,
        material_id=base.material_id,
        wire_id=base.wire_id,
        N=base.N,
        gap_mm=base.gap_mm,
        highest_tier=max(base.highest_tier, 4),
        feasible_t0=base.feasible_t0,
        loss_t1_W=base.loss_t1_W,
        temp_t1_C=base.temp_t1_C,
        cost_t1_USD=base.cost_t1_USD,
        loss_t2_W=base.loss_t2_W,
        saturation_t2=base.saturation_t2,
        L_t3_uH=base.L_t3_uH,
        Bpk_t3_T=base.Bpk_t3_T,
        L_t4_uH=tier4.L_avg_FEA_uH,
        notes=notes_in or None,
    )


def _row_with_tier3(
    base: CandidateRow,
    tier3,  # Tier3Result | None
    error: Optional[str],
) -> CandidateRow:
    """Return a copy of `base` with Tier 3 columns + notes filled.

    `L_t3_uH` / `Bpk_t3_T` go into their dedicated SQLite columns
    (the schema has reserved space for them since Phase A); the
    extra Tier-3 metadata (backend, confidence, disagreement flag,
    error string) packs into `notes['tier3']` for CLI inspection
    and UI badges.
    """
    notes_in = dict(base.notes) if base.notes else {}
    if tier3 is None:
        if error is not None:
            notes_in["tier3_error"] = error
        else:
            notes_in["tier3_skipped"] = True
        return CandidateRow(
            candidate_key=base.candidate_key,
            core_id=base.core_id,
            material_id=base.material_id,
            wire_id=base.wire_id,
            N=base.N,
            gap_mm=base.gap_mm,
            highest_tier=base.highest_tier,
            feasible_t0=base.feasible_t0,
            loss_t1_W=base.loss_t1_W,
            temp_t1_C=base.temp_t1_C,
            cost_t1_USD=base.cost_t1_USD,
            loss_t2_W=base.loss_t2_W,
            saturation_t2=base.saturation_t2,
            L_t3_uH=base.L_t3_uH,
            Bpk_t3_T=base.Bpk_t3_T,
            L_t4_uH=base.L_t4_uH,
            notes=notes_in or None,
        )
    notes_in["tier3"] = {
        "backend": tier3.backend,
        "confidence": tier3.confidence,
        "L_relative_error_pct": tier3.L_relative_error_pct,
        "B_relative_error_pct": tier3.B_relative_error_pct,
        "disagrees_with_tier1": tier3.disagrees_with_tier1,
        "solve_time_s": tier3.solve_time_s,
    }
    return CandidateRow(
        candidate_key=base.candidate_key,
        core_id=base.core_id,
        material_id=base.material_id,
        wire_id=base.wire_id,
        N=base.N,
        gap_mm=base.gap_mm,
        highest_tier=max(base.highest_tier, 3),
        feasible_t0=base.feasible_t0,
        loss_t1_W=base.loss_t1_W,
        temp_t1_C=base.temp_t1_C,
        cost_t1_USD=base.cost_t1_USD,
        loss_t2_W=base.loss_t2_W,
        saturation_t2=base.saturation_t2,
        L_t3_uH=tier3.L_FEA_uH,
        Bpk_t3_T=tier3.B_pk_FEA_T,
        L_t4_uH=base.L_t4_uH,
        notes=notes_in or None,
    )


def _row_with_tier2(
    base: CandidateRow,
    tier2,  # Tier2Result | None
    error: Optional[str],
) -> CandidateRow:
    """Return a copy of `base` with Tier 2 columns + notes filled.

    `loss_t2_W` is left at the Tier-1 value because Tier 2 doesn't
    recompute losses — it refines L and B. `saturation_t2` always
    reflects the latest verdict (anhysteretic-curve check). The
    full Tier-2 metric pack lands in `notes['tier2']` so the CLI
    can surface them without a schema change.
    """
    notes_in = dict(base.notes) if base.notes else {}
    if tier2 is None:
        if error is not None:
            notes_in["tier2_error"] = error
        else:
            notes_in["tier2_skipped"] = True
        return CandidateRow(
            candidate_key=base.candidate_key,
            core_id=base.core_id,
            material_id=base.material_id,
            wire_id=base.wire_id,
            N=base.N,
            gap_mm=base.gap_mm,
            highest_tier=base.highest_tier,
            feasible_t0=base.feasible_t0,
            loss_t1_W=base.loss_t1_W,
            temp_t1_C=base.temp_t1_C,
            cost_t1_USD=base.cost_t1_USD,
            loss_t2_W=base.loss_t2_W,
            saturation_t2=base.saturation_t2,
            L_t3_uH=base.L_t3_uH,
            Bpk_t3_T=base.Bpk_t3_T,
            L_t4_uH=base.L_t4_uH,
            notes=notes_in or None,
        )
    notes_in["tier2"] = {
        "L_min_uH": tier2.L_min_uH,
        "L_avg_uH": tier2.L_avg_uH,
        "B_pk_T": tier2.B_pk_T,
        "i_pk_A": tier2.i_pk_A,
        "i_rms_A": tier2.i_rms_A,
        "L_relative_error_pct": tier2.L_relative_error_pct,
        "B_relative_error_pct": tier2.B_relative_error_pct,
        "i_pk_relative_error_pct": tier2.i_pk_relative_error_pct,
        "converged": tier2.converged,
        "sim_wall_time_s": tier2.sim_wall_time_s,
    }
    return CandidateRow(
        candidate_key=base.candidate_key,
        core_id=base.core_id,
        material_id=base.material_id,
        wire_id=base.wire_id,
        N=base.N,
        gap_mm=base.gap_mm,
        highest_tier=max(base.highest_tier, 2),
        feasible_t0=base.feasible_t0,
        loss_t1_W=base.loss_t1_W,
        temp_t1_C=base.temp_t1_C,
        cost_t1_USD=base.cost_t1_USD,
        # Carry Tier-1 loss into the t2 column so downstream rankers
        # that order on `loss_t2_W` work transparently. If a future
        # tier recomputes loss, it overwrites this.
        loss_t2_W=base.loss_t1_W,
        saturation_t2=tier2.saturation_t2,
        L_t3_uH=base.L_t3_uH,
        Bpk_t3_T=base.Bpk_t3_T,
        L_t4_uH=base.L_t4_uH,
        notes=notes_in or None,
    )


def _row_from_tier1(
    candidate: Candidate,
    tier1: Optional[Tier1Result],
    error: Optional[str],
    cost: Optional[float],
) -> CandidateRow:
    if tier1 is None:
        notes: dict[str, Any] = {}
        if error is not None:
            notes["error"] = error
        else:
            notes["unsolved"] = True
        return CandidateRow(
            candidate_key=candidate.key(),
            core_id=candidate.core_id,
            material_id=candidate.material_id,
            wire_id=candidate.wire_id,
            N=candidate.N,
            gap_mm=candidate.gap_mm,
            highest_tier=0,
            feasible_t0=True,
            notes=notes or None,
        )
    return CandidateRow(
        candidate_key=candidate.key(),
        core_id=candidate.core_id,
        material_id=candidate.material_id,
        wire_id=candidate.wire_id,
        N=tier1.design.N_turns,
        gap_mm=candidate.gap_mm,
        highest_tier=1,
        feasible_t0=True,
        loss_t1_W=tier1.total_loss_W,
        temp_t1_C=tier1.temp_C,
        cost_t1_USD=cost,
        notes={"warnings": tier1.design.warnings} if tier1.design.warnings else None,
    )


# ─── Orchestrator ─────────────────────────────────────────────────


@dataclass
class CascadeOrchestrator:
    """Drives a cascade run from start to completion (or cancellation).

    Owns the run store and the process pool. All public methods are
    safe to call from any thread; cancellation propagates via a
    `threading.Event` observed by the orchestrator between batches.

    Cancellation is checked **only in the parent process** — the tier
    worker functions (`_tier1_worker`, etc.) don't read it. Pre-fix
    we used ``mp.Event`` for the cancel flag, which on macOS allocates
    five POSIX semaphores via ``multiprocessing.resource_tracker``;
    those leaked at every shutdown ("There appear to be 5 leaked
    semaphore objects to clean up") because nothing explicitly closes
    them. ``threading.Event`` has the same set/clear/is_set API
    without the IPC primitive, so the leak warning goes away and the
    cancellation semantics stay identical.
    """

    store: RunStore
    parallelism: int = field(default_factory=lambda: os.cpu_count() or 1)
    _cancel: threading.Event = field(
        default_factory=threading.Event,
        init=False,
        repr=False,
    )

    # ─── Lifecycle ────────────────────────────────────────────────

    def cancel(self) -> None:
        """Signal cancellation. Workers complete their in-flight call."""
        self._cancel.set()

    def reset_cancel(self) -> None:
        """Clear the cancel flag (e.g. before reusing the orchestrator)."""
        self._cancel.clear()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    # ─── Run creation / resume ───────────────────────────────────

    def start_run(
        self,
        spec: Spec,
        config: Optional[CascadeConfig] = None,
    ) -> str:
        """Insert a new `runs` row and return the generated `run_id`."""
        cfg = config or CascadeConfig()
        return self.store.create_run(
            spec,
            current_db_versions(),
            cfg.to_dict(),
        )

    # ─── Main entry point ────────────────────────────────────────

    def run(
        self,
        run_id: str,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        config: Optional[CascadeConfig] = None,
        *,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> None:
        """Execute Tier 0 → Tier 1 for the given run.

        Idempotent: candidates already in the store are skipped, so
        calling `run` twice with the same `run_id` is a no-op the
        second time (assuming the first finished). After a crash
        mid-run, calling `run` again resumes from the next unwritten
        candidate.
        """
        cfg = config or CascadeConfig()
        seen = self.store.candidate_keys(run_id)

        # ── Tier 0 — single-process; cheap envelope check ──
        materials_by_id = {m.id: m for m in materials}
        cores_by_id = {c.id: c for c in cores}
        wires_by_id = {w.id: w for w in wires}
        model = model_for(spec)

        # Pre-filter wires by current density. Curated catalogs ship
        # 1 400+ round-wire entries spanning 0.0001 mm² grade-1 magnet
        # wire to 107 mm² welding cable; for any given spec only ~10
        # gauges land in the [J_MIN, J_MAX] band. Without this filter
        # the cartesian below produces 1.7 M candidates for a typical
        # 1.5 kW boost-CCM spec — Tier 0's per-row SQLite write-loop
        # then takes ~30 minutes (and looked like a hang to the user).
        # ``cartesian`` keeps its ``only_round_wires`` filter as a
        # backstop in case a Litz wire slipped through.
        viable_wires = viable_wires_for_spec(spec, wires)

        all_candidates = [
            c
            for c in cartesian(
                materials,
                cores,
                viable_wires,
                only_compatible_cores=cfg.only_compatible_cores,
                only_round_wires=cfg.only_round_wires,
            )
            if c.key() not in seen
        ]
        total_t0 = len(all_candidates)

        # Tier 0 throughput is dominated by SQLite writes once the
        # ~5 µs feasibility check is amortised. Buffering rows and
        # flushing via ``write_candidates_batch`` cuts the per-row
        # cost ~100× (one connection + one transaction per chunk
        # instead of per row). 1 000 rows/flush balances progress-
        # callback latency against fsync cost.
        TIER0_FLUSH_EVERY = 1_000

        survivors: list[Candidate] = []
        pending_rows: list[CandidateRow] = []

        def _flush_pending() -> None:
            if pending_rows:
                self.store.write_candidates_batch(run_id, pending_rows)
                pending_rows.clear()

        for i, t0 in enumerate(
            filter_candidates(
                model,
                all_candidates,
                materials_by_id,
                cores_by_id,
                wires_by_id,
            )
        ):
            if self._cancel.is_set():
                _flush_pending()
                self.store.update_status(run_id, "cancelled")
                return
            pending_rows.append(_row_from_tier0(t0))
            if t0.envelope.feasible:
                survivors.append(t0.candidate)
            if len(pending_rows) >= TIER0_FLUSH_EVERY:
                _flush_pending()
                if progress_cb is not None:
                    progress_cb(TierProgress(tier=0, done=i + 1, total=total_t0))
        _flush_pending()
        if progress_cb is not None:
            progress_cb(TierProgress(tier=0, done=total_t0, total=total_t0))

        if self._cancel.is_set():
            self.store.update_status(run_id, "cancelled")
            return

        # ── Tier 1 — parallel pool; analytical evaluation ──
        total_t1 = len(survivors)
        if total_t1 == 0:
            self.store.update_status(run_id, "done")
            return

        if self.parallelism > 1:
            self._run_tier1_parallel(
                run_id,
                spec,
                materials,
                cores,
                wires,
                survivors,
                progress_cb,
            )
        else:
            self._run_tier1_sequential(
                run_id,
                spec,
                materials,
                cores,
                wires,
                survivors,
                progress_cb,
            )

        # ── Tier 2 — sequential transient simulation on top-K survivors ──
        # Tier 2 is much cheaper per candidate than Tier 1 (sub-millisecond
        # for the imposed-trajectory simulator), so a sequential loop
        # is plenty fast for the typical K = 10–100. Skipped silently
        # when `tier2_top_k == 0` or the topology lacks Tier-2 support.
        if cfg.tier2_top_k > 0 and not self._cancel.is_set():
            self._run_tier2_top_k(
                run_id,
                spec,
                materials,
                cores,
                wires,
                cfg,
                progress_cb,
            )

        # ── Tier 3 — magnetostatic FEA on top-K survivors ─────────
        # Tier 3 is expensive per candidate (5–30 s) and FEMMT
        # spawns ONELAB with shared temp dirs, so the loop is
        # strictly sequential. Skipped silently if no FEA backend
        # is installed/configured — the orchestrator records that
        # as a `tier3_skipped` notes entry on each row instead.
        if cfg.tier3_top_k > 0 and not self._cancel.is_set():
            self._run_tier3_top_k(
                run_id,
                spec,
                materials,
                cores,
                wires,
                cfg,
                progress_cb,
            )

        # ── Tier 4 — swept-magnetostatic FEA on top-K survivors ──
        # Tier 4 reruns the same FEA solver Tier 3 uses but at N
        # bias points across the half-cycle, producing a real
        # cycle-averaged L_FEA. Wall is N × Tier 3, so the default
        # `tier4_top_k = 0` keeps it opt-in. Same backend probe;
        # same temp-dir serialisation; same skip-cleanly-on-no-FEA
        # contract Tier 3 has.
        if cfg.tier4_top_k > 0 and not self._cancel.is_set():
            self._run_tier4_top_k(
                run_id,
                spec,
                materials,
                cores,
                wires,
                cfg,
                progress_cb,
            )

        if self._cancel.is_set():
            self.store.update_status(run_id, "cancelled")
        else:
            self.store.update_status(run_id, "done")

    # ─── Tier 1 execution paths ──────────────────────────────────

    def _run_tier1_parallel(
        self,
        run_id: str,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        survivors: list[Candidate],
        progress_cb: Optional[ProgressCallback],
    ) -> None:
        total = len(survivors)
        # Submit in batches so we can observe `_cancel` between batches.
        batch_size = max(self.parallelism * 4, 8)
        with ProcessPoolExecutor(
            max_workers=self.parallelism,
            initializer=_init_worker,
            initargs=(spec.model_dump_json(), materials, cores, wires),
        ) as ex:
            done = 0
            for start in range(0, total, batch_size):
                if self._cancel.is_set():
                    ex.shutdown(wait=False, cancel_futures=True)
                    return
                batch = survivors[start : start + batch_size]
                # `map` preserves order across the batch — we need that to
                # zip results back to candidates.
                rows = [
                    _row_from_tier1(cand, t1, err, cost)
                    for cand, (t1, err, cost) in zip(
                        batch,
                        ex.map(_tier1_worker, batch),
                        strict=False,
                    )
                ]
                # Single batched write per pool batch — Tier 1 surfaces
                # at most ~1 000 survivors so one transaction per chunk
                # is comfortable in memory and saves N − 1 connection
                # opens per batch.
                self.store.write_candidates_batch(run_id, rows)
                done += len(batch)
                if progress_cb is not None:
                    progress_cb(TierProgress(tier=1, done=done, total=total))

    def _run_tier1_sequential(
        self,
        run_id: str,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        survivors: list[Candidate],
        progress_cb: Optional[ProgressCallback],
    ) -> None:
        # Same hot path as the worker, but in-process — used when
        # the caller asks for `parallelism=1` (tests, debugging).
        _init_worker(spec.model_dump_json(), materials, cores, wires)
        total = len(survivors)

        # Mirror the parallel path's batched-write contract — same
        # 100-row flush threshold the parallel pool naturally batches
        # at (4× parallelism). Keeps test and prod write patterns
        # within one order of magnitude of each other.
        TIER1_FLUSH_EVERY = 100
        pending: list[CandidateRow] = []

        def _flush_pending() -> None:
            if pending:
                self.store.write_candidates_batch(run_id, pending)
                pending.clear()

        for i, cand in enumerate(survivors):
            if self._cancel.is_set():
                _flush_pending()
                return
            t1, err, cost = _tier1_worker(cand)
            pending.append(_row_from_tier1(cand, t1, err, cost))
            if len(pending) >= TIER1_FLUSH_EVERY:
                _flush_pending()
            if progress_cb is not None and (i + 1) % 25 == 0:
                progress_cb(TierProgress(tier=1, done=i + 1, total=total))
        _flush_pending()
        if progress_cb is not None:
            progress_cb(TierProgress(tier=1, done=total, total=total))

    # ─── Tier 2 execution path ───────────────────────────────────

    def _run_tier2_top_k(
        self,
        run_id: str,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        cfg: CascadeConfig,
        progress_cb: Optional[ProgressCallback],
    ) -> None:
        """Run Tier 2 (transient simulation) on the top-K Tier-1 survivors.

        - Topologies that don't implement `Tier2ConverterModel` skip
          silently (no rows touched).
        - Each candidate's row is updated in place: Tier-1 columns
          are preserved, Tier-2 metrics land in the JSON `notes`,
          and `highest_tier` advances to 2 (or stays where it was).
        """
        model = model_for(spec)
        if not supports_tier2(model):
            return

        top_rows = self.store.top_candidates(
            run_id,
            n=cfg.tier2_top_k,
            order_by="loss_t1_W",
        )
        if not top_rows:
            return

        materials_by_id = {m.id: m for m in materials}
        cores_by_id = {c.id: c for c in cores}
        wires_by_id = {w.id: w for w in wires}
        total = len(top_rows)

        for i, row in enumerate(top_rows):
            if self._cancel.is_set():
                return
            mat = materials_by_id.get(row.material_id)
            core = cores_by_id.get(row.core_id)
            wire = wires_by_id.get(row.wire_id)
            if mat is None or core is None or wire is None:
                # The store points at an entry the live DB no longer has;
                # leave the row untouched, mark notes for later debugging.
                self.store.write_candidate(
                    run_id,
                    _row_with_tier2(row, None, "missing_db_entry"),
                )
                continue
            cand = Candidate(
                core_id=row.core_id,
                material_id=row.material_id,
                wire_id=row.wire_id,
                N=row.N,
                gap_mm=row.gap_mm,
            )
            t2, err = evaluate_tier2_safe(model, cand, core, mat, wire)
            self.store.write_candidate(
                run_id,
                _row_with_tier2(row, t2, err),
            )
            if progress_cb is not None:
                progress_cb(TierProgress(tier=2, done=i + 1, total=total))
        if progress_cb is not None:
            progress_cb(TierProgress(tier=2, done=total, total=total))

    # ─── Tier 3 execution path ───────────────────────────────────

    def _run_tier3_top_k(
        self,
        run_id: str,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        cfg: CascadeConfig,
        progress_cb: Optional[ProgressCallback],
    ) -> None:
        """Run Tier 3 (magnetostatic FEA) on the top-K survivors.

        Pulls the top-K rows by Tier-2 loss when Tier 2 ran (the
        more accurate ranking), otherwise falls back to Tier-1
        loss. Skips cleanly when no FEA backend is installed —
        the per-row note records `tier3_skipped` so the user can
        spot it.
        """
        if not supports_tier3():
            # Mark each top-K row with a notes entry instead of
            # writing nothing — tells the user "we tried, no FEA".
            top_rows = self.store.top_candidates(
                run_id,
                n=cfg.tier3_top_k,
                order_by=_tier3_order_column(cfg),
            )
            for row in top_rows:
                self.store.write_candidate(
                    run_id,
                    _row_with_tier3(row, None, "tier3_unavailable: no FEA backend"),
                )
            if progress_cb is not None:
                progress_cb(
                    TierProgress(
                        tier=3,
                        done=len(top_rows),
                        total=len(top_rows),
                    )
                )
            return

        model = model_for(spec)
        top_rows = self.store.top_candidates(
            run_id,
            n=cfg.tier3_top_k,
            order_by=_tier3_order_column(cfg),
        )
        if not top_rows:
            return

        materials_by_id = {m.id: m for m in materials}
        cores_by_id = {c.id: c for c in cores}
        wires_by_id = {w.id: w for w in wires}
        total = len(top_rows)

        for i, row in enumerate(top_rows):
            if self._cancel.is_set():
                return
            mat = materials_by_id.get(row.material_id)
            core = cores_by_id.get(row.core_id)
            wire = wires_by_id.get(row.wire_id)
            if mat is None or core is None or wire is None:
                self.store.write_candidate(
                    run_id,
                    _row_with_tier3(row, None, "missing_db_entry"),
                )
                continue
            cand = Candidate(
                core_id=row.core_id,
                material_id=row.material_id,
                wire_id=row.wire_id,
                N=row.N,
                gap_mm=row.gap_mm,
            )
            t3, err = evaluate_tier3_safe(
                model,
                cand,
                core,
                mat,
                wire,
                timeout_s=cfg.tier3_timeout_s,
                disagree_pct=cfg.tier3_disagree_pct,
            )
            self.store.write_candidate(
                run_id,
                _row_with_tier3(row, t3, err),
            )
            if progress_cb is not None:
                progress_cb(TierProgress(tier=3, done=i + 1, total=total))
        if progress_cb is not None:
            progress_cb(TierProgress(tier=3, done=total, total=total))

    # ─── Tier 4 execution path ───────────────────────────────────

    def _run_tier4_top_k(
        self,
        run_id: str,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        cfg: CascadeConfig,
        progress_cb: Optional[ProgressCallback],
    ) -> None:
        """Run Tier 4 (swept magnetostatic) on the top-K survivors.

        Order-by mirrors Tier 3's: prefer the most-refined existing
        ranking. The sweep fractions are clipped to the highest-bias
        portion of the default schedule so saturation is always
        probed even when the user dials `tier4_n_points` down.
        """
        if not supports_tier4():
            top_rows = self.store.top_candidates(
                run_id,
                n=cfg.tier4_top_k,
                order_by=_tier4_order_column(cfg),
            )
            for row in top_rows:
                self.store.write_candidate(
                    run_id,
                    _row_with_tier4(row, None, "tier4_unavailable: no FEA backend"),
                )
            if progress_cb is not None:
                progress_cb(
                    TierProgress(
                        tier=4,
                        done=len(top_rows),
                        total=len(top_rows),
                    )
                )
            return

        model = model_for(spec)
        top_rows = self.store.top_candidates(
            run_id,
            n=cfg.tier4_top_k,
            order_by=_tier4_order_column(cfg),
        )
        if not top_rows:
            return

        materials_by_id = {m.id: m for m in materials}
        cores_by_id = {c.id: c for c in cores}
        wires_by_id = {w.id: w for w in wires}
        total = len(top_rows)
        n_points = max(1, min(cfg.tier4_n_points, len(DEFAULT_SWEEP_FRACTIONS)))
        sweep_fractions = DEFAULT_SWEEP_FRACTIONS[-n_points:]

        for i, row in enumerate(top_rows):
            if self._cancel.is_set():
                return
            mat = materials_by_id.get(row.material_id)
            core = cores_by_id.get(row.core_id)
            wire = wires_by_id.get(row.wire_id)
            if mat is None or core is None or wire is None:
                self.store.write_candidate(
                    run_id,
                    _row_with_tier4(row, None, "missing_db_entry"),
                )
                continue
            cand = Candidate(
                core_id=row.core_id,
                material_id=row.material_id,
                wire_id=row.wire_id,
                N=row.N,
                gap_mm=row.gap_mm,
            )
            t4, err = evaluate_tier4_safe(
                model,
                cand,
                core,
                mat,
                wire,
                sweep_fractions=sweep_fractions,
                timeout_s=cfg.tier4_timeout_s,
            )
            self.store.write_candidate(
                run_id,
                _row_with_tier4(row, t4, err),
            )
            if progress_cb is not None:
                progress_cb(TierProgress(tier=4, done=i + 1, total=total))
        if progress_cb is not None:
            progress_cb(TierProgress(tier=4, done=total, total=total))


def _tier3_order_column(cfg: CascadeConfig) -> str:
    """Pick the Tier-3 ranking source: prefer Tier 2's loss when
    Tier 2 was scheduled (it's the better filter), otherwise the
    analytical Tier 1 loss."""
    return "loss_t2_W" if cfg.tier2_top_k > 0 else "loss_t1_W"


def _tier4_order_column(cfg: CascadeConfig) -> str:
    """Tier-4 ranking source: Tier 3's `L_t3_uH` (FEA-corrected) is
    the most accurate column we have; fall back through Tier 2 and
    Tier 1 when those weren't scheduled."""
    if cfg.tier3_top_k > 0:
        # Order on the Tier-3 inductance is fine — the FEA-corrected
        # designs that landed at the top by analytical loss almost
        # always also have valid `L_t3_uH`. If a row has `L_t3_uH = NULL`
        # it's pushed to the end by `top_candidates`'s NOT NULL filter.
        return "loss_t2_W" if cfg.tier2_top_k > 0 else "loss_t1_W"
    if cfg.tier2_top_k > 0:
        return "loss_t2_W"
    return "loss_t1_W"
