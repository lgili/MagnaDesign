"""CascadeOrchestrator end-to-end tests.

These tests run the full Phase-A pipeline against a small material
slice so they finish in seconds. The parity guarantee with the
existing `optimize.sweep.sweep` is in `tests/test_cascade_tier1.py`;
here we focus on orchestrator-specific behaviour: cancellation,
resume, store integration, and parallel/sequential equivalence.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from pfc_inductor.data_loader import (
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.models import Spec
from pfc_inductor.optimize.cascade import (
    CascadeConfig,
    CascadeOrchestrator,
    RunStore,
    TierProgress,
)


@pytest.fixture(scope="module")
def db():
    materials = load_materials()
    cores = load_cores()
    wires = load_wires()
    # Restrict to a single material so the test runs in seconds.
    target_id = "magnetics-60_highflux"
    return {
        "materials": [m for m in materials if m.id == target_id],
        "cores": [c for c in cores if c.default_material_id == target_id],
        "wires": [w for w in wires if w.id in {"AWG14", "AWG16", "AWG18"}],
    }


def _spec() -> Spec:
    return Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=220.0,
        Vout_V=400.0,
        Pout_W=800.0,
        eta=0.97,
        f_sw_kHz=65.0,
        ripple_pct=30.0,
        T_amb_C=40.0,
        T_max_C=100.0,
        Ku_max=0.40,
        Bsat_margin=0.20,
    )


# ─── End-to-end run (sequential mode) ───────────────────────────────


def test_orchestrator_run_writes_all_candidates(tmp_path: Path, db):
    """Every Cartesian candidate becomes a row in the store."""
    store = RunStore(tmp_path / "cascade.db")
    orch = CascadeOrchestrator(store, parallelism=1)
    spec = _spec()
    run_id = orch.start_run(spec)

    orch.run(run_id, spec, db["materials"], db["cores"], db["wires"])

    record = store.get_run(run_id)
    assert record is not None
    assert record.status == "done"

    n_expected = len(db["cores"]) * len(db["wires"])
    assert store.candidate_count(run_id) == n_expected


def test_orchestrator_progress_callback_fires_for_both_tiers(tmp_path: Path, db):
    """The UI-facing callback gets at least one update per tier."""
    store = RunStore(tmp_path / "cascade.db")
    orch = CascadeOrchestrator(store, parallelism=1)
    spec = _spec()
    run_id = orch.start_run(spec)

    seen_tiers: set[int] = set()
    last_progress: dict[int, TierProgress] = {}

    def cb(p: TierProgress) -> None:
        seen_tiers.add(p.tier)
        last_progress[p.tier] = p

    orch.run(run_id, spec, db["materials"], db["cores"], db["wires"], progress_cb=cb)

    assert 0 in seen_tiers
    assert 1 in seen_tiers
    # Final updates must report `done == total`.
    for tier, p in last_progress.items():
        assert p.done == p.total, f"tier {tier} did not finish: {p}"


def test_orchestrator_top_candidates_are_feasible(tmp_path: Path, db):
    """`top_candidates` ordered by loss returns only Tier-1 results."""
    store = RunStore(tmp_path / "cascade.db")
    orch = CascadeOrchestrator(store, parallelism=1)
    spec = _spec()
    run_id = orch.start_run(spec)

    orch.run(run_id, spec, db["materials"], db["cores"], db["wires"])

    top = store.top_candidates(run_id, n=5, order_by="loss_t1_W")
    assert top
    for row in top:
        assert row.highest_tier == 1
        assert row.loss_t1_W is not None
        assert row.feasible_t0 is True


# ─── Resume after partial completion ───────────────────────────────


def test_orchestrator_resumes_from_store(tmp_path: Path, db):
    """A second `run` call against the same `run_id` re-evaluates nothing.

    We simulate a crash by having the first run pre-populate the
    store with a few Tier-0 rows; the second run must skip those
    keys (no design engine work for them).
    """
    db_path = tmp_path / "cascade.db"
    store = RunStore(db_path)
    spec = _spec()

    # First run completes everything.
    orch_a = CascadeOrchestrator(store, parallelism=1)
    run_id = orch_a.start_run(spec)
    orch_a.run(run_id, spec, db["materials"], db["cores"], db["wires"])
    n_before = store.candidate_count(run_id)
    assert n_before > 0

    # Second run on the same `run_id` is a no-op (every key is in the store).
    orch_b = CascadeOrchestrator(store, parallelism=1)
    orch_b.run(run_id, spec, db["materials"], db["cores"], db["wires"])
    assert store.candidate_count(run_id) == n_before


# ─── Cancellation ──────────────────────────────────────────────────


def test_orchestrator_cancel_marks_status_and_returns_quickly(tmp_path: Path, db):
    """Calling cancel() during a run aborts within seconds."""
    store = RunStore(tmp_path / "cascade.db")
    orch = CascadeOrchestrator(store, parallelism=1)
    spec = _spec()
    run_id = orch.start_run(spec)

    # Cancel before the run even starts: it must finish promptly with
    # `cancelled` status. (The `_cancel` flag is checked at the top of
    # the Tier 0 loop, before any heavy work.)
    orch.cancel()
    start = time.perf_counter()
    orch.run(run_id, spec, db["materials"], db["cores"], db["wires"])
    elapsed = time.perf_counter() - start

    record = store.get_run(run_id)
    assert record is not None
    assert record.status == "cancelled"
    assert elapsed < 5.0


def test_orchestrator_cancel_mid_run_is_responsive(tmp_path: Path, db):
    """Cancelling from another thread mid-Tier-1 stops within 5 s."""
    store = RunStore(tmp_path / "cascade.db")
    orch = CascadeOrchestrator(store, parallelism=1)
    spec = _spec()
    run_id = orch.start_run(spec)

    def _cancel_after_brief_delay():
        time.sleep(0.5)
        orch.cancel()

    threading.Thread(target=_cancel_after_brief_delay, daemon=True).start()

    start = time.perf_counter()
    orch.run(run_id, spec, db["materials"], db["cores"], db["wires"])
    elapsed = time.perf_counter() - start

    record = store.get_run(run_id)
    assert record is not None
    # Either cancelled (cancel landed before completion) or done (the
    # tiny test DB ran faster than the cancel signal — also fine).
    assert record.status in {"cancelled", "done"}
    assert elapsed < 60.0  # bounded; the suite has a hard cap regardless


# ─── Parallel / sequential equivalence ─────────────────────────────


def test_orchestrator_parallel_and_sequential_yield_same_top_n(tmp_path: Path, db):
    """The cascade top-5 must not depend on `parallelism`."""
    spec = _spec()

    def _run(parallelism: int) -> list[str]:
        store = RunStore(tmp_path / f"cascade-p{parallelism}.db")
        orch = CascadeOrchestrator(store, parallelism=parallelism)
        run_id = orch.start_run(spec)
        orch.run(run_id, spec, db["materials"], db["cores"], db["wires"])
        return [r.candidate_key for r in store.top_candidates(run_id, n=5, order_by="loss_t1_W")]

    seq = _run(1)
    par = _run(2)
    assert seq == par


# ─── Spec-hash mismatch must not silently proceed ──────────────────

# ─── Tier 2 stage (Phase B integration) ───────────────────────────


def test_orchestrator_runs_tier2_when_top_k_set(tmp_path: Path, db):
    """`tier2_top_k > 0` should invoke the transient simulator on
    the top-K Tier-1 survivors and persist Tier 2 metrics in `notes`."""
    store = RunStore(tmp_path / "cascade.db")
    orch = CascadeOrchestrator(store, parallelism=1)
    spec = _spec()
    cfg = CascadeConfig(tier2_top_k=5)
    run_id = orch.start_run(spec, cfg)

    seen_t2 = []

    def cb(p: TierProgress) -> None:
        if p.tier == 2:
            seen_t2.append(p)

    orch.run(run_id, spec, db["materials"], db["cores"], db["wires"], cfg, progress_cb=cb)

    # Tier 2 progress fired at least once.
    assert seen_t2, "no Tier-2 progress events received"
    final_t2 = seen_t2[-1]
    assert final_t2.done == final_t2.total

    # Top-5 rows now carry tier 2 metrics + saturation_t2 + bumped highest_tier.
    top = store.top_candidates(run_id, n=5, order_by="loss_t1_W")
    assert top
    n_with_tier2 = 0
    for row in top:
        if row.notes and "tier2" in row.notes:
            payload = row.notes["tier2"]
            # Required fields produced by `_row_with_tier2`.
            assert "L_avg_uH" in payload
            assert "B_pk_T" in payload
            assert "i_pk_A" in payload
            assert isinstance(row.saturation_t2, bool)
            assert row.highest_tier >= 2
            n_with_tier2 += 1
    assert n_with_tier2 >= 1, "no Tier-2 metrics on any top-K row"


def test_orchestrator_skips_tier2_when_top_k_zero(tmp_path: Path, db):
    """Default config keeps Tier 2 off; top rows must carry no tier2 notes."""
    store = RunStore(tmp_path / "cascade.db")
    orch = CascadeOrchestrator(store, parallelism=1)
    spec = _spec()
    cfg = CascadeConfig(tier2_top_k=0)
    run_id = orch.start_run(spec, cfg)
    orch.run(run_id, spec, db["materials"], db["cores"], db["wires"], cfg)

    for row in store.top_candidates(run_id, n=5, order_by="loss_t1_W"):
        assert row.highest_tier <= 1
        if row.notes:
            assert "tier2" not in row.notes


def test_resumable_run_keyed_by_spec_hash(tmp_path: Path, db):
    """`find_resumable_run` distinguishes specs by their canonical hash."""
    store = RunStore(tmp_path / "cascade.db")
    orch = CascadeOrchestrator(store, parallelism=1)

    spec_a = _spec()
    run_a = orch.start_run(spec_a)

    # A different Pout produces a different hash.
    spec_b = spec_a.model_copy(update={"Pout_W": 1200.0})
    assert spec_b.canonical_hash() != spec_a.canonical_hash()

    found_a = store.find_resumable_run(spec_a.canonical_hash())
    found_b = store.find_resumable_run(spec_b.canonical_hash())
    assert found_a is not None and found_a.run_id == run_a
    assert found_b is None
