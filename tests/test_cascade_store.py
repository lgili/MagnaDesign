"""RunStore (SQLite persistence) regression tests."""
from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from pfc_inductor.data_loader import current_db_versions
from pfc_inductor.models import Spec
from pfc_inductor.optimize.cascade.store import (
    CandidateRow,
    RunStore,
)


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "cascade.db")


def _make_spec(Pout: float = 800.0) -> Spec:
    return Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
        Vout_V=400.0, Pout_W=Pout, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
        T_amb_C=40.0, T_max_C=100.0, Ku_max=0.40, Bsat_margin=0.20,
    )


def _make_candidate(i: int, *, loss: float | None = None) -> CandidateRow:
    return CandidateRow(
        candidate_key=f"core{i}|mat0|wire0|_|_",
        core_id=f"core{i}",
        material_id="mat0",
        wire_id="wire0",
        N=None,
        gap_mm=None,
        highest_tier=1 if loss is not None else 0,
        feasible_t0=True,
        loss_t1_W=loss,
        temp_t1_C=70.0 if loss is not None else None,
    )


# ─── Spec.canonical_hash ────────────────────────────────────────────

def test_spec_canonical_hash_is_deterministic():
    s1 = _make_spec()
    s2 = _make_spec()
    assert s1.canonical_hash() == s2.canonical_hash()
    assert len(s1.canonical_hash()) == 64  # SHA-256 hex


def test_spec_canonical_hash_changes_with_any_field():
    base = _make_spec()
    assert base.canonical_hash() != _make_spec(Pout=801.0).canonical_hash()


# ─── current_db_versions ────────────────────────────────────────────

def test_current_db_versions_returns_three_hashes():
    versions = current_db_versions()
    assert set(versions.keys()) == {"materials", "cores", "wires"}
    for value in versions.values():
        assert isinstance(value, str)
        assert len(value) == 64  # SHA-256 hex


def test_current_db_versions_is_stable_across_calls():
    assert current_db_versions() == current_db_versions()


# ─── RunStore — runs ───────────────────────────────────────────────

def test_create_run_returns_id_and_record(store: RunStore):
    spec = _make_spec()
    run_id = store.create_run(spec, current_db_versions(), {"K_1": 1000})
    record = store.get_run(run_id)
    assert record is not None
    assert record.run_id == run_id
    assert record.spec_hash == spec.canonical_hash()
    assert record.status == "running"
    assert record.config == {"K_1": 1000}
    # Round-trip the embedded spec.
    assert record.spec().Pout_W == spec.Pout_W


def test_update_status_persists(store: RunStore):
    run_id = store.create_run(_make_spec(), current_db_versions())
    store.update_status(run_id, "done")
    record = store.get_run(run_id)
    assert record is not None
    assert record.status == "done"


def test_list_runs_filters_by_status(store: RunStore):
    a = store.create_run(_make_spec(Pout=400.0), current_db_versions())
    b = store.create_run(_make_spec(Pout=800.0), current_db_versions())
    store.update_status(b, "done")
    running = store.list_runs(status="running")
    done = store.list_runs(status="done")
    assert [r.run_id for r in running] == [a]
    assert [r.run_id for r in done] == [b]


def test_find_resumable_run_returns_most_recent_running(store: RunStore):
    spec = _make_spec()
    a = store.create_run(spec, current_db_versions())
    store.update_status(a, "done")
    b = store.create_run(spec, current_db_versions())
    found = store.find_resumable_run(spec.canonical_hash())
    assert found is not None
    assert found.run_id == b


def test_find_resumable_run_ignores_other_specs(store: RunStore):
    store.create_run(_make_spec(Pout=400.0), current_db_versions())
    other_hash = _make_spec(Pout=800.0).canonical_hash()
    assert store.find_resumable_run(other_hash) is None


# ─── RunStore — candidates ─────────────────────────────────────────

def test_write_and_read_candidate(store: RunStore):
    run_id = store.create_run(_make_spec(), current_db_versions())
    row = _make_candidate(0, loss=5.5)
    store.write_candidate(run_id, row)

    keys = store.candidate_keys(run_id)
    assert keys == {row.candidate_key}
    assert store.candidate_count(run_id) == 1


def test_write_candidate_is_idempotent_on_key(store: RunStore):
    """INSERT OR REPLACE means re-writing the same key updates, not duplicates."""
    run_id = store.create_run(_make_spec(), current_db_versions())
    a = _make_candidate(0, loss=5.5)
    store.write_candidate(run_id, a)
    b = _make_candidate(0, loss=4.0)  # same key, new loss
    store.write_candidate(run_id, b)

    assert store.candidate_count(run_id) == 1
    top = store.top_candidates(run_id, n=10)
    assert top[0].loss_t1_W == 4.0


def test_top_candidates_orders_ascending(store: RunStore):
    run_id = store.create_run(_make_spec(), current_db_versions())
    losses = [9.0, 3.0, 7.0, 1.5, 5.0]
    for i, loss in enumerate(losses):
        store.write_candidate(run_id, _make_candidate(i, loss=loss))

    top = store.top_candidates(run_id, n=3)
    assert [r.loss_t1_W for r in top] == sorted(losses)[:3]


def test_top_candidates_skips_null_metric(store: RunStore):
    """Tier-0-only rows (no Tier-1 metric yet) must not poison the ranking."""
    run_id = store.create_run(_make_spec(), current_db_versions())
    store.write_candidate(run_id, _make_candidate(0, loss=None))  # Tier 0 only
    store.write_candidate(run_id, _make_candidate(1, loss=10.0))
    top = store.top_candidates(run_id, n=10)
    assert [r.candidate_key for r in top] == ["core1|mat0|wire0|_|_"]


def test_top_candidates_rejects_unsupported_order_by(store: RunStore):
    run_id = store.create_run(_make_spec(), current_db_versions())
    with pytest.raises(ValueError, match="order_by"):
        store.top_candidates(run_id, order_by="DROP TABLE; --")


# ─── Resumability — kill, restart, no re-evaluation ────────────────

def _writer_subprocess(db_path: str, run_id: str, n: int) -> None:
    """Helper run in a separate process so we can simulate a crash."""
    store = RunStore(Path(db_path))
    for i in range(n):
        store.write_candidate(run_id, _make_candidate(i, loss=float(i)))


def test_resume_finds_already_evaluated_keys(tmp_path: Path):
    """A second process opening the same file sees what the first wrote.

    This is the foundation of resume: after a crash, the orchestrator
    re-attaches to the run, asks the store which candidates already
    have rows, and skips them.
    """
    db_path = tmp_path / "cascade.db"
    store_a = RunStore(db_path)
    run_id = store_a.create_run(_make_spec(), current_db_versions())

    # Simulate a "crashed" first session: a child process writes 1000
    # candidates, then exits abruptly.
    p = multiprocessing.Process(
        target=_writer_subprocess,
        args=(str(db_path), run_id, 1000),
    )
    p.start()
    p.join(timeout=30)
    assert p.exitcode == 0

    # New session: open the store fresh, list keys, and confirm
    # zero re-evaluation is needed.
    store_b = RunStore(db_path)
    keys = store_b.candidate_keys(run_id)
    assert len(keys) == 1000
    # Resuming would skip exactly these:
    assert "core500|mat0|wire0|_|_" in keys


# ─── Batched writes ──────────────────────────────────────────────────────
#
# Tier 0 used to call ``write_candidate`` once per row, each call opening
# a fresh sqlite3 connection — that single design choice was the cause
# of the user-visible "first step never finishes" symptom. Below we lock
# in the batch contract so a regression would surface immediately.

def test_write_candidates_batch_persists_all_rows(store):
    """All rows in the iterable land in the table, in INSERT order."""
    spec = Spec()
    run_id = store.create_run(spec, current_db_versions())
    rows = [
        CandidateRow(
            candidate_key=f"k{i}",
            core_id=f"core{i % 10}", material_id="mat", wire_id="wire",
            N=None, gap_mm=None,
            highest_tier=0, feasible_t0=(i % 2 == 0),
        )
        for i in range(2_500)
    ]
    n = store.write_candidates_batch(run_id, rows)
    assert n == 2_500
    assert store.candidate_count(run_id) == 2_500
    keys = store.candidate_keys(run_id)
    assert keys == {f"k{i}" for i in range(2_500)}


def test_write_candidates_batch_idempotent_on_replay(store):
    """Same key written twice → INSERT OR REPLACE keeps a single row."""
    spec = Spec()
    run_id = store.create_run(spec, current_db_versions())
    row = CandidateRow(
        candidate_key="k0",
        core_id="c", material_id="m", wire_id="w",
        N=None, gap_mm=None,
        highest_tier=0, feasible_t0=True,
    )
    store.write_candidates_batch(run_id, [row])
    store.write_candidates_batch(run_id, [row])  # replay
    assert store.candidate_count(run_id) == 1


def test_write_candidates_batch_handles_empty_iter(store):
    """Empty iterable is a no-op — no transaction, no error."""
    spec = Spec()
    run_id = store.create_run(spec, current_db_versions())
    n = store.write_candidates_batch(run_id, [])
    assert n == 0
    assert store.candidate_count(run_id) == 0


def test_write_candidates_batch_chunks_large_input(store):
    """Inputs larger than the internal chunk size still land cleanly.

    Triggers the ``_BATCH_CHUNK`` flush path — past sloppy fixes have
    forgotten the trailing ``executemany`` for the last partial chunk.
    """
    spec = Spec()
    run_id = store.create_run(spec, current_db_versions())
    # Roughly 1.5 chunks at the 5 000-row default.
    rows = [
        CandidateRow(
            candidate_key=f"k{i}",
            core_id="c", material_id="m", wire_id="w",
            N=None, gap_mm=None,
            highest_tier=0, feasible_t0=True,
        )
        for i in range(7_500)
    ]
    n = store.write_candidates_batch(run_id, rows)
    assert n == 7_500
    assert store.candidate_count(run_id) == 7_500
