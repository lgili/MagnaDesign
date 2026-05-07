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

import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from multiprocessing.synchronize import Event as MPEvent
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
from pfc_inductor.topology.registry import model_for

# ─── Public configuration & progress types ────────────────────────

@dataclass(frozen=True)
class CascadeConfig:
    """Tier thresholds and search-space filters for one run.

    Phase A only uses `K_1` (Tier 1 top-K survivors) and the
    candidate-generator filters. Future phases extend this struct
    with `K_2`, `K_3`, etc.
    """

    K_1: int = 1000
    only_compatible_cores: bool = True
    only_round_wires: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "K_1": self.K_1,
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
        s["model"], candidate, core, mat, wire,
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
    safe to call from any thread; cancellation propagates via an
    `mp.Event` observed by the orchestrator between batches.
    """

    store: RunStore
    parallelism: int = field(default_factory=lambda: os.cpu_count() or 1)
    _cancel: MPEvent = field(
        default_factory=mp.Event, init=False, repr=False,
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
            spec, current_db_versions(), cfg.to_dict(),
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

        all_candidates = [
            c for c in cartesian(
                materials, cores, wires,
                only_compatible_cores=cfg.only_compatible_cores,
                only_round_wires=cfg.only_round_wires,
            )
            if c.key() not in seen
        ]
        total_t0 = len(all_candidates)

        survivors: list[Candidate] = []
        for i, t0 in enumerate(filter_candidates(
            model, all_candidates,
            materials_by_id, cores_by_id, wires_by_id,
        )):
            if self._cancel.is_set():
                self.store.update_status(run_id, "cancelled")
                return
            self.store.write_candidate(run_id, _row_from_tier0(t0))
            if t0.envelope.feasible:
                survivors.append(t0.candidate)
            if progress_cb is not None and (i + 1) % 50 == 0:
                progress_cb(TierProgress(tier=0, done=i + 1, total=total_t0))
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
                run_id, spec, materials, cores, wires, survivors, progress_cb,
            )
        else:
            self._run_tier1_sequential(
                run_id, spec, materials, cores, wires, survivors, progress_cb,
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
                batch = survivors[start:start + batch_size]
                # `map` preserves order across the batch — we need that to
                # zip results back to candidates.
                for cand, (t1, err, cost) in zip(
                    batch, ex.map(_tier1_worker, batch), strict=False,
                ):
                    self.store.write_candidate(
                        run_id, _row_from_tier1(cand, t1, err, cost),
                    )
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
        for i, cand in enumerate(survivors):
            if self._cancel.is_set():
                return
            t1, err, cost = _tier1_worker(cand)
            self.store.write_candidate(
                run_id, _row_from_tier1(cand, t1, err, cost),
            )
            if progress_cb is not None and (i + 1) % 25 == 0:
                progress_cb(TierProgress(tier=1, done=i + 1, total=total))
        if progress_cb is not None:
            progress_cb(TierProgress(tier=1, done=total, total=total))
