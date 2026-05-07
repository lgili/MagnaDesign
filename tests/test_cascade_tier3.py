"""Tier 3 evaluator + orchestrator integration regressions.

Tier 3 calls FEMMT / FEMM, which spawn ONELAB / Lua and take 5–30 s
per design — too slow for the regular suite. Every test here patches
`pfc_inductor.fea.runner.validate_design` (the single entry point
the Tier 3 evaluator uses) with a synthetic `FEAValidation` so the
suite stays sub-second.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.fea.models import FEAValidation, FEMMNotAvailable
from pfc_inductor.models import Candidate, Spec
from pfc_inductor.optimize.cascade import (
    CascadeConfig,
    CascadeOrchestrator,
    RunStore,
    TierProgress,
)
from pfc_inductor.optimize.cascade.tier1 import evaluate_candidate as eval_tier1
from pfc_inductor.optimize.cascade.tier3 import (
    evaluate_candidate,
    evaluate_candidate_safe,
)
from pfc_inductor.topology.boost_ccm_model import BoostCCMModel


@pytest.fixture(scope="module")
def db():
    """A small slice of the catalogue — single material, ~45 cores, 3 wires.

    Loading the full DB and running Tier 0 over its ~50 k Cartesian
    candidates takes ~20 s per orchestrator test; restricting up
    front keeps the suite under a couple of seconds.
    """
    materials = load_materials()
    cores = load_cores()
    wires = load_wires()
    target_id = "magnetics-60_highflux"
    return {
        "materials": [m for m in materials if m.id == target_id],
        "cores": [c for c in cores if c.default_material_id == target_id],
        "wires": [w for w in wires if w.id in {"AWG14", "AWG16", "AWG18"}],
    }


def _spec() -> Spec:
    return Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
        Vout_V=400.0, Pout_W=800.0, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
        T_amb_C=40.0, T_max_C=100.0, Ku_max=0.40, Bsat_margin=0.20,
    )


def _ref(db):
    material = find_material(db["materials"], "magnetics-60_highflux")
    core = next(
        c for c in db["cores"]
        if c.default_material_id == material.id and 40_000 < c.Ve_mm3 < 100_000
    )
    wire = next(w for w in db["wires"] if w.id == "AWG14")
    cand = Candidate(core_id=core.id, material_id=material.id, wire_id=wire.id)
    return cand, core, material, wire


def _fake_fea(L_FEA_uH: float = 380.0, B_pk_FEA_T: float = 0.330,
              L_pct_error: float = -0.7, B_pct_error: float = 1.9,
              backend: str = "femmt") -> FEAValidation:
    return FEAValidation(
        L_FEA_uH=L_FEA_uH, L_analytic_uH=382.7, L_pct_error=L_pct_error,
        B_pk_FEA_T=B_pk_FEA_T, B_pk_analytic_T=0.324, B_pct_error=B_pct_error,
        flux_linkage_FEA_Wb=0.005, test_current_A=14.0,
        solve_time_s=0.01,
        femm_binary=backend, fem_path="/tmp/fake.fem",
        log_excerpt="", notes="synthetic",
    )


# ─── evaluate_candidate happy path ─────────────────────────────────

def test_tier3_evaluate_candidate_packages_FEAValidation(db):
    """The evaluator must pass spec/core/wire/material/result through
    to `validate_design` and wrap the result in a `Tier3Result`."""
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)
    fake = _fake_fea(L_FEA_uH=384.5, B_pk_FEA_T=0.331,
                     L_pct_error=0.5, B_pct_error=2.2)

    with patch("pfc_inductor.fea.runner.validate_design", return_value=fake):
        r = evaluate_candidate(model, cand, core, material, wire)

    assert r is not None
    assert r.L_FEA_uH == pytest.approx(384.5)
    assert r.B_pk_FEA_T == pytest.approx(0.331)
    assert r.L_relative_error_pct == pytest.approx(0.5)
    assert r.B_relative_error_pct == pytest.approx(2.2)
    assert r.confidence == "alta"          # both errors < 5 %
    assert r.disagrees_with_tier1 is False  # under default 15 % threshold
    assert r.backend == "femmt"


def test_tier3_disagrees_flag_fires_when_pct_exceeds_threshold(db):
    """A 20 % L_pct_error must flip `disagrees_with_tier1` to True
    against the default 15 % threshold."""
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)
    fake = _fake_fea(L_pct_error=20.0, B_pct_error=2.0)

    with patch("pfc_inductor.fea.runner.validate_design", return_value=fake):
        r = evaluate_candidate(model, cand, core, material, wire)

    assert r is not None
    assert r.disagrees_with_tier1 is True
    assert r.confidence == "baixa"  # 20 % is in the > 15 % band


def test_tier3_reuses_provided_tier1_design(db):
    """If the caller already ran Tier 1, Tier 3 must skip the
    redundant `model.steady_state()` call — saves ~5 ms."""
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)
    tier1 = eval_tier1(model, cand, core, material, wire)
    assert tier1 is not None

    fake = _fake_fea()
    with patch("pfc_inductor.fea.runner.validate_design", return_value=fake) as m:
        evaluate_candidate(model, cand, core, material, wire, tier1=tier1)
        passed_design = m.call_args.args[4]  # 5th positional is `result`
        assert passed_design is tier1.design


# ─── Safe wrapper ─────────────────────────────────────────────────

def test_tier3_safe_returns_none_when_FEA_unavailable(db):
    """`FEMMNotAvailable` (no backend installed) is the most common
    real-world Tier 3 failure mode — the safe wrapper must yield a
    clean `(None, "tier3_unavailable: ...")` so the orchestrator
    keeps going."""
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)

    with patch("pfc_inductor.fea.runner.validate_design",
               side_effect=FEMMNotAvailable("no backend")):
        r, err = evaluate_candidate_safe(model, cand, core, material, wire)
    assert r is None
    assert err is not None
    assert err.startswith("tier3_unavailable")
    assert "no backend" in err


def test_tier3_safe_swallows_arbitrary_exceptions(db):
    """Defensive: any random exception is converted to a notes string
    so the cascade loop never crashes mid-batch."""
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)

    with patch("pfc_inductor.fea.runner.validate_design",
               side_effect=RuntimeError("synthetic crash")):
        r, err = evaluate_candidate_safe(model, cand, core, material, wire)
    assert r is None
    assert err is not None
    assert "RuntimeError" in err


# ─── Orchestrator integration ─────────────────────────────────────

def test_orchestrator_runs_tier3_when_top_k_set(tmp_path, db):
    """`tier3_top_k > 0` schedules Tier 3 on the top-K survivors
    (ranked by Tier 2 if available, else Tier 1) and persists FEA
    metrics into the dedicated `L_t3_uH` / `Bpk_t3_T` columns plus
    `notes['tier3']`."""
    store = RunStore(tmp_path / "cascade.db")
    orch = CascadeOrchestrator(store, parallelism=1)
    spec = _spec()
    cfg = CascadeConfig(tier2_top_k=5, tier3_top_k=3)
    run_id = orch.start_run(spec, cfg)

    seen_t3: list[TierProgress] = []

    def cb(p: TierProgress) -> None:
        if p.tier == 3:
            seen_t3.append(p)

    fake = _fake_fea(L_FEA_uH=384.5, B_pk_FEA_T=0.331)
    # supports_tier3() probes for FEMMT — patch it True so the
    # orchestrator schedules Tier 3 unconditionally.
    with patch("pfc_inductor.optimize.cascade.orchestrator.supports_tier3",
               return_value=True), \
         patch("pfc_inductor.fea.runner.validate_design", return_value=fake):
        orch.run(run_id, spec, db["materials"], db["cores"], db["wires"], cfg, progress_cb=cb)

    # Tier 3 progress fired and reached `done == total`.
    assert seen_t3
    assert seen_t3[-1].done == seen_t3[-1].total
    assert seen_t3[-1].total == 3

    # Top rows now carry Tier-3 columns + notes.
    rows = store.top_candidates(run_id, n=3, order_by="loss_t1_W")
    n_with_tier3 = 0
    for row in rows:
        if row.notes and "tier3" in row.notes:
            assert row.L_t3_uH == pytest.approx(384.5)
            assert row.Bpk_t3_T == pytest.approx(0.331)
            assert row.highest_tier >= 3
            assert row.notes["tier3"]["backend"] == "femmt"
            n_with_tier3 += 1
    assert n_with_tier3 >= 1


def test_orchestrator_marks_tier3_unavailable_when_no_backend(tmp_path, db):
    """When no FEA backend is installed the orchestrator must still
    leave a breadcrumb on each top-K row so the user knows Tier 3
    was attempted."""
    store = RunStore(tmp_path / "cascade.db")
    orch = CascadeOrchestrator(store, parallelism=1)
    spec = _spec()
    cfg = CascadeConfig(tier2_top_k=0, tier3_top_k=2)
    run_id = orch.start_run(spec, cfg)

    with patch("pfc_inductor.optimize.cascade.orchestrator.supports_tier3",
               return_value=False):
        orch.run(run_id, spec, db["materials"], db["cores"], db["wires"], cfg)

    top = store.top_candidates(run_id, n=2, order_by="loss_t1_W")
    for row in top:
        assert row.notes is not None
        assert "tier3_error" in row.notes
        assert "tier3_unavailable" in row.notes["tier3_error"]


def test_orchestrator_skips_tier3_when_top_k_zero(tmp_path, db):
    """Default config keeps Tier 3 off; rows must carry no `tier3`
    notes at all (not even `tier3_skipped`)."""
    store = RunStore(tmp_path / "cascade.db")
    orch = CascadeOrchestrator(store, parallelism=1)
    spec = _spec()
    cfg = CascadeConfig(tier2_top_k=0, tier3_top_k=0)
    run_id = orch.start_run(spec, cfg)
    orch.run(run_id, spec, db["materials"], db["cores"], db["wires"], cfg)

    for row in store.top_candidates(run_id, n=5, order_by="loss_t1_W"):
        assert row.L_t3_uH is None
        assert row.Bpk_t3_T is None
        if row.notes:
            assert "tier3" not in row.notes
            assert "tier3_error" not in row.notes
            assert "tier3_skipped" not in row.notes
