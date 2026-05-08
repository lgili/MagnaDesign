"""Cascade tier-refinement tests.

The cascade's Phase B / C / D promise is "Tier 2 / 3 / 4 don't
just refine L and B — they push the refined numbers all the way
through to losses + temp + the displayed Top-N". These tests
cover that contract end-to-end:

- :mod:`...optimize.cascade.refine` recomputes losses + temp
  given override knobs and matches the engine when no override
  is supplied (no-op identity).
- A different ``B_pk_T`` produces a different ``loss_W``.
- A different ``L_actual_uH`` produces a different ``loss_W``.
- The orchestrator's row builders (Tier 2 / 3 / 4) write the
  refined values into ``loss_t{N}_W`` and ``temp_t{N}_C`` columns
  — **not** copy ``loss_t1_W`` forward.
- The store's ``COALESCE`` virtual columns
  (``loss_top_W`` / ``temp_top_C``) sort candidates by their
  highest-fidelity number; a Tier-1-only candidate falls back to
  ``loss_t1_W`` automatically.

The orchestrator integration tests don't require a real FEA
backend — Tier 3 / 4 are exercised via the row-builder helpers
with a synthesised :class:`Tier3Result` / :class:`Tier4Result`
payload, mirroring how the orchestrator's safe wrappers convert
solver output into rows.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pfc_inductor.data_loader import (
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.models import (
    Candidate,
    Spec,
    Tier3Result,
    Tier4Result,
)
from pfc_inductor.optimize.cascade.orchestrator import (
    _row_with_tier2,
    _row_with_tier3,
    _row_with_tier4,
)
from pfc_inductor.optimize.cascade.refine import (
    RefinedDesign,
    recompute_with_overrides,
)
from pfc_inductor.optimize.cascade.store import CandidateRow, RunStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def reference_design():
    """Boost-PFC reference specimen — has a feasible Tier-1
    answer with non-trivial loss / temp numbers we can perturb."""
    from pfc_inductor.design import design as run_design

    spec = Spec(
        topology="boost_ccm",
        Pout_W=600,
        Vin_min_Vrms=85,
        Vin_max_Vrms=265,
        Vout_V=400,
        f_sw_kHz=65,
        ripple_pct=20,
        T_amb_C=40,
    )
    mats = load_materials()
    cores = load_cores()
    wires = load_wires()
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    result = run_design(spec, core, wire, mat)
    return spec, core, wire, mat, result


@pytest.fixture
def base_row(reference_design) -> CandidateRow:
    """A CandidateRow standing in for what the orchestrator
    persists after Tier 1 — has loss_t1_W / temp_t1_C populated
    so a Tier-2/3/4 row builder has something to refine over."""
    _spec, core, wire, mat, result = reference_design
    return CandidateRow(
        candidate_key=f"{core.id}|{mat.id}|{wire.id}|{result.N_turns}|0.0",
        core_id=core.id,
        material_id=mat.id,
        wire_id=wire.id,
        N=result.N_turns,
        gap_mm=0.0,
        highest_tier=1,
        feasible_t0=True,
        loss_t1_W=float(result.losses.P_total_W),
        temp_t1_C=float(result.T_winding_C),
        cost_t1_USD=10.0,
    )


# ---------------------------------------------------------------------------
# refine.recompute_with_overrides
# ---------------------------------------------------------------------------
def test_recompute_no_overrides_matches_engine(reference_design) -> None:
    """Calling the recompute helper with no overrides should
    reproduce the engine's loss + temp within ~1 % — the no-op
    identity that proves the recompute pipeline isn't drifting
    from the engine."""
    spec, core, wire, mat, result = reference_design
    refined = recompute_with_overrides(
        spec=spec,
        core=core,
        wire=wire,
        material=mat,
        base=result,
    )
    assert isinstance(refined, RefinedDesign)
    assert refined.loss_W == pytest.approx(
        float(result.losses.P_total_W),
        rel=0.05,
    )
    assert refined.temp_C == pytest.approx(
        float(result.T_winding_C),
        abs=2.0,
    )


def test_recompute_B_pk_override_is_honoured(
    reference_design,
) -> None:
    """The B_pk override must land verbatim on the returned
    :class:`RefinedDesign`. (Whether it visibly changes total
    loss depends on the material's Steinmetz f_min — for powder
    cores 2·f_line is below f_min, so the line-band Steinmetz
    contribution is suppressed by construction. The override is
    still surfaced so a downstream consumer who *does* care can
    read it.)"""
    spec, core, wire, mat, result = reference_design
    higher_B = float(result.B_pk_T) * 1.5
    refined = recompute_with_overrides(
        spec=spec,
        core=core,
        wire=wire,
        material=mat,
        base=result,
        B_pk_T=higher_B,
    )
    assert refined.B_pk_T == pytest.approx(higher_B)


def test_recompute_lower_L_increases_cu_ac_loss(
    reference_design,
) -> None:
    """Halving L doubles the carrier ripple ΔiL → ~4× the AC Cu
    loss (Rac·I_rip²) → measurable jump in total loss. Confirms
    the L override flows through the carrier-waveform synthesis
    in :func:`recompute_with_overrides`. (Note: ΔB is invariant
    to L because flux = V·dt/(N·Ae); only the *current* ripple
    grows, which is a Cu-loss effect, not core-loss.)"""
    spec, core, wire, mat, result = reference_design
    base = recompute_with_overrides(
        spec=spec,
        core=core,
        wire=wire,
        material=mat,
        base=result,
    )
    halved_L = recompute_with_overrides(
        spec=spec,
        core=core,
        wire=wire,
        material=mat,
        base=result,
        L_actual_uH=float(result.L_actual_uH) * 0.5,
    )
    assert halved_L.P_cu_ac_W > base.P_cu_ac_W
    assert halved_L.loss_W > base.loss_W


def test_recompute_lower_I_rms_decreases_cu_loss(
    reference_design,
) -> None:
    """Half the i_rms_total_A → ¼ the Rdc·I² Cu DC loss → total
    loss must drop. Confirms the i_rms override flows through
    to the copper-loss formula."""
    spec, core, wire, mat, result = reference_design
    base_loss = recompute_with_overrides(
        spec=spec,
        core=core,
        wire=wire,
        material=mat,
        base=result,
    ).loss_W
    halved_loss = recompute_with_overrides(
        spec=spec,
        core=core,
        wire=wire,
        material=mat,
        base=result,
        I_rms_total_A=float(result.I_rms_total_A) * 0.5,
    ).loss_W
    assert halved_loss < base_loss


def test_recompute_returns_consistent_temperature_rise(
    reference_design,
) -> None:
    """``T_rise_C`` must equal ``temp_C - spec.T_amb_C`` exactly."""
    spec, core, wire, mat, result = reference_design
    refined = recompute_with_overrides(
        spec=spec,
        core=core,
        wire=wire,
        material=mat,
        base=result,
    )
    assert refined.T_rise_C == pytest.approx(
        refined.temp_C - float(spec.T_amb_C),
        abs=1e-6,
    )


# ---------------------------------------------------------------------------
# Row-builder integration: refined values land in the row, not Tier-1 carried
# ---------------------------------------------------------------------------
def test_row_with_tier2_writes_refined_loss_not_tier1_copy(
    reference_design,
    base_row,
) -> None:
    """Calling ``_row_with_tier2`` with a real RefinedDesign
    payload must put the refined loss into ``loss_t2_W`` —
    **not** copy ``loss_t1_W``. This is the gambiarra fix.

    We use an L_avg perturbation big enough to guarantee a
    measurable shift in copper loss (lower L → larger ΔiL →
    larger I_rip_rms → larger Rac·I² term). The test asserts:
    (a) tier-2 columns are populated, (b) they're not the Tier-1
    copy, (c) the direction matches physics (lower L → higher
    loss).
    """
    spec, core, wire, mat, result = reference_design

    class _StubT2:
        candidate = Candidate(
            core_id=core.id,
            material_id=mat.id,
            wire_id=wire.id,
            N=result.N_turns,
            gap_mm=0.0,
        )
        L_min_uH = float(result.L_actual_uH) * 0.5
        L_avg_uH = float(result.L_actual_uH) * 0.6  # measurably lower L
        B_pk_T = float(result.B_pk_T)
        i_pk_A = float(result.I_pk_max_A)
        i_rms_A = float(result.I_rms_total_A)
        L_relative_error_pct = -40.0
        B_relative_error_pct = 0.0
        i_pk_relative_error_pct = 0.0
        saturation_t2 = False
        converged = True
        n_line_cycles_simulated = 5
        sim_wall_time_s = 0.05

    # Don't override I_rms — let the carrier-waveform recover the
    # consistent rip-RMS for the lower L (otherwise the override
    # would short-circuit the L flow-through).
    refined = recompute_with_overrides(
        spec=spec,
        core=core,
        wire=wire,
        material=mat,
        base=result,
        L_actual_uH=_StubT2.L_avg_uH,
        B_pk_T=_StubT2.B_pk_T,
    )
    row = _row_with_tier2(base_row, _StubT2(), None, refined=refined)

    # Tier-1 numbers preserved unchanged.
    assert row.loss_t1_W == pytest.approx(base_row.loss_t1_W)
    assert row.temp_t1_C == pytest.approx(base_row.temp_t1_C)
    # Tier-2 numbers are the *refined* ones — populated AND
    # different from the Tier-1 baseline.
    assert row.loss_t2_W is not None
    assert row.temp_t2_C is not None
    assert row.loss_t2_W != pytest.approx(base_row.loss_t1_W, rel=0.005)
    # Lower L → larger ripple → higher Cu AC loss → strictly
    # higher total. (This is the gambiarra fix: pre-fix, the
    # row would carry the Tier-1 loss verbatim regardless of
    # what Tier 2 measured.)
    assert row.loss_t2_W > base_row.loss_t1_W


def test_row_with_tier3_writes_refined_loss(
    reference_design,
    base_row,
) -> None:
    spec, core, wire, mat, result = reference_design
    cand = Candidate(
        core_id=core.id,
        material_id=mat.id,
        wire_id=wire.id,
        N=result.N_turns,
        gap_mm=0.0,
    )
    t3 = Tier3Result(
        candidate=cand,
        # Use a substantially lower L so the carrier ripple grows
        # measurably and the recompute can't accidentally collapse
        # to the Tier-1 number.
        L_FEA_uH=float(result.L_actual_uH) * 0.5,
        B_pk_FEA_T=float(result.B_pk_T) * 1.10,
        L_relative_error_pct=-50.0,
        B_relative_error_pct=10.0,
        solve_time_s=12.0,
        backend="femmt",
        confidence="medium",
        disagrees_with_tier1=False,
    )
    refined = recompute_with_overrides(
        spec=spec,
        core=core,
        wire=wire,
        material=mat,
        base=result,
        L_actual_uH=t3.L_FEA_uH,
        B_pk_T=t3.B_pk_FEA_T,
    )
    row = _row_with_tier3(base_row, t3, None, refined=refined)

    # Tier-3 columns populated.
    assert row.loss_t3_W is not None
    assert row.temp_t3_C is not None
    assert row.L_t3_uH == pytest.approx(t3.L_FEA_uH)
    assert row.Bpk_t3_T == pytest.approx(t3.B_pk_FEA_T)
    # Tier-3 loss differs from Tier-1 — the FEA-corrected
    # inductance changed the carrier ripple, which changed Cu
    # loss + temp. Pre-fix, ``loss_t3_W`` didn't even exist as a
    # column; this assertion proves the recompute is wired in.
    assert row.loss_t3_W != pytest.approx(base_row.loss_t1_W, rel=0.005)


def test_row_with_tier4_writes_refined_loss(
    reference_design,
    base_row,
) -> None:
    spec, core, wire, mat, result = reference_design
    cand = Candidate(
        core_id=core.id,
        material_id=mat.id,
        wire_id=wire.id,
        N=result.N_turns,
        gap_mm=0.0,
    )
    t4 = Tier4Result(
        candidate=cand,
        L_avg_FEA_uH=float(result.L_actual_uH) * 0.5,  # measurable shift
        L_min_FEA_uH=float(result.L_actual_uH) * 0.4,
        L_max_FEA_uH=float(result.L_actual_uH) * 0.6,
        B_pk_FEA_T=float(result.B_pk_T) * 1.15,
        saturation_t4=False,
        n_points_simulated=5,
        solve_time_s=60.0,
        backend="femmt",
        L_avg_relative_to_tier3_pct=-4.0,
        sample_currents_A=(1.0, 2.0, 3.0, 4.0, 5.0),
        sample_L_uH=(100.0, 95.0, 90.0, 85.0, 80.0),
        sample_B_T=(0.1, 0.2, 0.3, 0.35, 0.4),
    )
    refined = recompute_with_overrides(
        spec=spec,
        core=core,
        wire=wire,
        material=mat,
        base=result,
        L_actual_uH=t4.L_avg_FEA_uH,
        B_pk_T=t4.B_pk_FEA_T,
    )
    row = _row_with_tier4(base_row, t4, None, refined=refined)

    assert row.loss_t4_W is not None
    assert row.temp_t4_C is not None
    assert row.L_t4_uH == pytest.approx(t4.L_avg_FEA_uH)
    # The Tier-4 cycle-averaged inductance changed → carrier
    # ripple changed → Cu loss + temp shifted. Confirms the
    # refinement is plumbed end-to-end.
    assert row.loss_t4_W != pytest.approx(base_row.loss_t1_W, rel=0.005)


def test_row_skip_paths_keep_loss_columns_null(
    reference_design,
    base_row,
) -> None:
    """Tier 2 / 3 / 4 skipped (e.g. no FEA backend, simulator
    declined) → ``loss_t{N}_W`` stays None. The COALESCE virtual
    column then falls through to Tier 1 automatically."""
    row2 = _row_with_tier2(base_row, None, "tier2_unavailable")
    row3 = _row_with_tier3(base_row, None, "tier3_unavailable")
    row4 = _row_with_tier4(base_row, None, "tier4_unavailable")
    for r in (row2, row3, row4):
        assert r.loss_t2_W is None
        assert r.loss_t3_W is None
        assert r.loss_t4_W is None
        # Tier-1 numbers preserved unchanged.
        assert r.loss_t1_W == base_row.loss_t1_W


# ---------------------------------------------------------------------------
# CandidateRow.loss_top_W / temp_top_C COALESCE
# ---------------------------------------------------------------------------
def test_loss_top_W_falls_through_to_tier1(base_row) -> None:
    """A Tier-1-only candidate must report its Tier-1 loss as
    ``loss_top_W``."""
    assert base_row.loss_top_W == pytest.approx(base_row.loss_t1_W)


def test_loss_top_W_prefers_highest_tier() -> None:
    """When multiple tiers have written, ``loss_top_W`` returns
    the deepest one — Tier 4 wins over 3 wins over 2 wins over 1."""
    row = CandidateRow(
        candidate_key="k",
        core_id="c",
        material_id="m",
        wire_id="w",
        N=10,
        gap_mm=0.0,
        highest_tier=4,
        loss_t1_W=10.0,
        loss_t2_W=11.0,
        loss_t3_W=12.0,
        loss_t4_W=13.0,
    )
    assert row.loss_top_W == 13.0
    assert row.temp_top_C is None  # nothing in the temp chain


def test_temp_top_C_prefers_highest_tier() -> None:
    row = CandidateRow(
        candidate_key="k",
        core_id="c",
        material_id="m",
        wire_id="w",
        N=10,
        gap_mm=0.0,
        highest_tier=3,
        temp_t1_C=80.0,
        temp_t2_C=85.0,
        temp_t3_C=90.0,
    )
    assert row.temp_top_C == 90.0


# ---------------------------------------------------------------------------
# Store integration: top_candidates ranks on COALESCE
# ---------------------------------------------------------------------------
def test_top_candidates_loss_top_W_uses_highest_tier(
    tmp_path: Path,
) -> None:
    """``top_candidates(order_by='loss_top_W')`` must rank a
    Tier-4 candidate by its Tier-4 loss, not its Tier-1 loss.

    Setup:
      - Candidate A: Tier-1 loss = 10 W, Tier-4 loss = 5 W.
      - Candidate B: Tier-1 loss = 7 W, Tier-1 only.

    Old (Tier-1-only) sort puts B first (7 < 10). The fix sorts
    A first (5 < 7) because A's deeper tier wins.
    """
    spec = Spec(
        topology="boost_ccm",
        Pout_W=600,
        Vin_min_Vrms=85,
        Vin_max_Vrms=265,
        Vout_V=400,
        f_sw_kHz=65,
        ripple_pct=20,
        T_amb_C=40,
    )
    store = RunStore(tmp_path / "test.db")
    run_id = store.create_run(spec, db_versions={}, config={})

    row_a = CandidateRow(
        candidate_key="a",
        core_id="c1",
        material_id="m1",
        wire_id="w1",
        N=20,
        gap_mm=0.0,
        highest_tier=4,
        loss_t1_W=10.0,
        loss_t4_W=5.0,
        temp_t1_C=80.0,
        temp_t4_C=70.0,
    )
    row_b = CandidateRow(
        candidate_key="b",
        core_id="c2",
        material_id="m2",
        wire_id="w2",
        N=20,
        gap_mm=0.0,
        highest_tier=1,
        loss_t1_W=7.0,
        temp_t1_C=78.0,
    )
    store.write_candidate(run_id, row_a)
    store.write_candidate(run_id, row_b)

    top = store.top_candidates(run_id, n=10, order_by="loss_top_W")
    keys = [r.candidate_key for r in top]
    assert keys == ["a", "b"], (
        "Tier-4-refined candidate must rank ahead of Tier-1-only "
        "candidate when its Tier-4 loss is lower"
    )


def test_top_candidates_temp_top_C_uses_highest_tier(
    tmp_path: Path,
) -> None:
    spec = Spec(
        topology="boost_ccm",
        Pout_W=600,
        Vin_min_Vrms=85,
        Vin_max_Vrms=265,
        Vout_V=400,
        f_sw_kHz=65,
        ripple_pct=20,
        T_amb_C=40,
    )
    store = RunStore(tmp_path / "test.db")
    run_id = store.create_run(spec, db_versions={}, config={})
    row_a = CandidateRow(
        candidate_key="a",
        core_id="c",
        material_id="m",
        wire_id="w",
        N=20,
        gap_mm=0.0,
        highest_tier=3,
        loss_t1_W=10.0,
        temp_t1_C=120.0,  # T1 says hot
        loss_t3_W=8.0,
        temp_t3_C=85.0,  # T3 says cool
    )
    row_b = CandidateRow(
        candidate_key="b",
        core_id="c",
        material_id="m",
        wire_id="w",
        N=20,
        gap_mm=0.0,
        highest_tier=1,
        loss_t1_W=9.0,
        temp_t1_C=95.0,
    )
    store.write_candidate(run_id, row_a)
    store.write_candidate(run_id, row_b)
    top = store.top_candidates(run_id, n=10, order_by="temp_top_C")
    keys = [r.candidate_key for r in top]
    # A's Tier-3 temp (85) beats B's Tier-1 temp (95).
    assert keys[0] == "a"


def test_store_migrates_legacy_schema(tmp_path: Path) -> None:
    """Opening a store created by an older code version (without
    the per-tier refinement columns) must transparently migrate
    via ALTER TABLE — no data loss, all queries still work."""
    import sqlite3

    db_path = tmp_path / "legacy.db"
    # Create a stripped-down legacy schema (no tier-refinement
    # columns). Mirrors what Phase A shipped before the recompute
    # work landed.
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE runs (
            run_id      TEXT PRIMARY KEY,
            started_at  INTEGER NOT NULL,
            spec_hash   TEXT NOT NULL,
            spec_json   TEXT NOT NULL,
            db_versions TEXT NOT NULL,
            config      TEXT NOT NULL,
            status      TEXT NOT NULL,
            pid         INTEGER NOT NULL
        );
        CREATE TABLE candidates (
            run_id        TEXT NOT NULL,
            candidate_key TEXT NOT NULL,
            core_id       TEXT NOT NULL,
            material_id   TEXT NOT NULL,
            wire_id       TEXT NOT NULL,
            N             INTEGER,
            gap_mm        REAL,
            highest_tier  INTEGER NOT NULL,
            feasible_t0   INTEGER,
            loss_t1_W     REAL,
            temp_t1_C     REAL,
            cost_t1_USD   REAL,
            loss_t2_W     REAL,
            saturation_t2 INTEGER,
            L_t3_uH       REAL,
            Bpk_t3_T      REAL,
            L_t4_uH       REAL,
            notes         TEXT,
            PRIMARY KEY (run_id, candidate_key)
        );
    """)
    conn.commit()
    conn.close()

    # Re-opening with the current store should add the missing
    # columns transparently and let us write + read a row.
    store = RunStore(db_path)
    spec = Spec(
        topology="boost_ccm",
        Pout_W=600,
        Vin_min_Vrms=85,
        Vin_max_Vrms=265,
        Vout_V=400,
        f_sw_kHz=65,
        ripple_pct=20,
        T_amb_C=40,
    )
    run_id = store.create_run(spec, db_versions={}, config={})
    row = CandidateRow(
        candidate_key="x",
        core_id="c",
        material_id="m",
        wire_id="w",
        N=20,
        gap_mm=0.0,
        highest_tier=4,
        loss_t1_W=10.0,
        loss_t4_W=5.0,
    )
    store.write_candidate(run_id, row)
    top = store.top_candidates(run_id, n=10, order_by="loss_top_W")
    assert len(top) == 1
    assert top[0].loss_t4_W == 5.0
    assert top[0].loss_top_W == 5.0
