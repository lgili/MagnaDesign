"""Tier 4 evaluator + orchestrator integration regressions.

Tier 4 calls FEMMT/FEMM at N bias points per candidate (default 5),
which is way too slow for the regular suite. Every test here patches
`pfc_inductor.fea.runner.validate_design` with a synthetic
`FEAValidation` so wall stays under a second.
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
from pfc_inductor.optimize.cascade.tier3 import evaluate_candidate as eval_tier3
from pfc_inductor.optimize.cascade.tier4 import (
    evaluate_candidate,
    evaluate_candidate_safe,
)
from pfc_inductor.topology.boost_ccm_model import BoostCCMModel


@pytest.fixture(scope="module")
def db():
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


def _ref(db):
    material = find_material(db["materials"], "magnetics-60_highflux")
    core = next(
        c
        for c in db["cores"]
        if c.default_material_id == material.id and 40_000 < c.Ve_mm3 < 100_000
    )
    wire = next(w for w in db["wires"] if w.id == "AWG14")
    cand = Candidate(core_id=core.id, material_id=material.id, wire_id=wire.id)
    return cand, core, material, wire


def _fake_fea_factory(L_FEA_uH: float = 380.0, B_pk_FEA_T: float = 0.330):
    """Returns a function that makes a synthetic `FEAValidation` —
    the FEA solver mock for Tier 4 tests."""

    def _make(*args, **kwargs) -> FEAValidation:
        # Simple variation across the sweep: scale L and B by the
        # current that the patched `validate_design` was called with.
        # We can't see the current here without unpacking args, so
        # just return a constant — Tier 4 tests check the aggregate.
        return FEAValidation(
            L_FEA_uH=L_FEA_uH,
            L_analytic_uH=382.7,
            L_pct_error=0.0,
            B_pk_FEA_T=B_pk_FEA_T,
            B_pk_analytic_T=0.324,
            B_pct_error=0.0,
            flux_linkage_FEA_Wb=0.005,
            test_current_A=14.0,
            solve_time_s=0.01,
            femm_binary="femmt",
            fem_path="/tmp/fake.fem",
            log_excerpt="",
            notes="synthetic",
        )

    return _make


# ─── evaluate_candidate happy path ─────────────────────────────────


def test_tier4_evaluate_candidate_runs_n_points_sweep(db):
    """Default Tier 4 hits the FEA solver 5 times; each sample's
    L / B / I lands in the result's parallel arrays."""
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)
    with patch(
        "pfc_inductor.fea.runner.validate_design",
        side_effect=_fake_fea_factory(),
    ) as m:
        r = evaluate_candidate(model, cand, core, material, wire)
    assert r is not None
    # Default sweep schedule has 5 fractions.
    assert m.call_count == 5
    assert r.n_points_simulated == 5
    assert len(r.sample_currents_A) == 5
    assert len(r.sample_L_uH) == 5
    assert len(r.sample_B_T) == 5


def test_tier4_aggregates_min_max_avg_correctly(db):
    """The Tier 4 result's L_min / L_max / L_avg must come from
    the per-sample arrays — synthesise sample-dependent FEA
    values and verify the aggregates."""
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)

    captured: list[float] = []  # captured I_pk on each call

    def _by_current(spec, core, wire, material, design_result, **_kw):
        I = float(design_result.I_pk_max_A)
        captured.append(I)
        # Make L drop slightly with current so L_min appears at the
        # final (highest-bias) sample, mirroring real rolloff.
        L = 400.0 - 5.0 * I
        B = 0.30 + 0.005 * I
        return FEAValidation(
            L_FEA_uH=L,
            L_analytic_uH=L,
            L_pct_error=0.0,
            B_pk_FEA_T=B,
            B_pk_analytic_T=B,
            B_pct_error=0.0,
            flux_linkage_FEA_Wb=0.005,
            test_current_A=I,
            solve_time_s=0.01,
            femm_binary="femmt",
            fem_path="/tmp/x",
        )

    with patch("pfc_inductor.fea.runner.validate_design", side_effect=_by_current):
        r = evaluate_candidate(model, cand, core, material, wire)

    assert r is not None
    # Currents are monotone increasing across the sweep.
    assert captured == sorted(captured)
    # L is monotone decreasing (we constructed it so).
    assert r.L_min_FEA_uH == r.sample_L_uH[-1]
    assert r.L_max_FEA_uH == r.sample_L_uH[0]
    expected_avg = sum(r.sample_L_uH) / len(r.sample_L_uH)
    assert r.L_avg_FEA_uH == pytest.approx(expected_avg)


def test_tier4_saturation_flag_fires_when_any_sample_exceeds_margin(db):
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)
    # Force the highest-bias sample over `Bsat * (1 - margin)`.
    # Bsat_25 ≈ 1.02 T, margin 0.20 → limit ≈ 0.816 T. Our fake
    # peaks at 1.5 T to guarantee saturation.
    with patch(
        "pfc_inductor.fea.runner.validate_design",
        side_effect=_fake_fea_factory(B_pk_FEA_T=1.5),
    ):
        r = evaluate_candidate(model, cand, core, material, wire)
    assert r is not None
    assert r.saturation_t4 is True


def test_tier4_relative_to_tier3_populated_when_tier3_provided(db):
    """When the caller passes a Tier-3 result, Tier 4 reports the
    delta between its cycle-averaged L and Tier 3's single-point L."""
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)
    fake = _fake_fea_factory()
    with patch("pfc_inductor.fea.runner.validate_design", side_effect=fake):
        # Run Tier 3 then Tier 4 on the same fake, to mimic the
        # orchestrator's flow.
        t3 = eval_tier3(model, cand, core, material, wire)
        assert t3 is not None
        t4 = evaluate_candidate(
            model,
            cand,
            core,
            material,
            wire,
            tier3=t3,
        )
    assert t4 is not None
    assert t4.L_avg_relative_to_tier3_pct is not None


# ─── evaluate_candidate_safe ──────────────────────────────────────


def test_tier4_safe_returns_none_when_FEA_unavailable(db):
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)
    with patch(
        "pfc_inductor.fea.runner.validate_design",
        side_effect=FEMMNotAvailable("no backend"),
    ):
        r, err = evaluate_candidate_safe(model, cand, core, material, wire)
    assert r is None
    assert err is not None
    assert err.startswith("tier4_unavailable")


def test_tier4_safe_swallows_arbitrary_exceptions(db):
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)
    with patch(
        "pfc_inductor.fea.runner.validate_design",
        side_effect=RuntimeError("synthetic"),
    ):
        r, err = evaluate_candidate_safe(model, cand, core, material, wire)
    assert r is None
    assert err is not None
    assert "RuntimeError" in err


# ─── Orchestrator integration ─────────────────────────────────────


def test_orchestrator_runs_tier4_when_top_k_set(tmp_path, db):
    store = RunStore(tmp_path / "cascade.db")
    orch = CascadeOrchestrator(store, parallelism=1)
    spec = _spec()
    cfg = CascadeConfig(tier3_top_k=3, tier4_top_k=2, tier4_n_points=3)
    run_id = orch.start_run(spec, cfg)

    seen_t4: list[TierProgress] = []

    def cb(p: TierProgress) -> None:
        if p.tier == 4:
            seen_t4.append(p)

    fake = _fake_fea_factory(L_FEA_uH=400.0, B_pk_FEA_T=0.4)
    with (
        patch(
            "pfc_inductor.optimize.cascade.orchestrator.supports_tier3",
            return_value=True,
        ),
        patch(
            "pfc_inductor.optimize.cascade.orchestrator.supports_tier4",
            return_value=True,
        ),
        patch(
            "pfc_inductor.fea.runner.validate_design",
            side_effect=fake,
        ),
    ):
        orch.run(run_id, spec, db["materials"], db["cores"], db["wires"], cfg, progress_cb=cb)

    assert seen_t4
    final = seen_t4[-1]
    assert final.done == final.total == 2

    # Top rows now carry tier-4 columns + notes.
    rows = store.top_candidates(run_id, n=2, order_by="loss_t1_W")
    n_with_t4 = 0
    for row in rows:
        if row.notes and "tier4" in row.notes:
            payload = row.notes["tier4"]
            assert "L_min_FEA_uH" in payload
            assert "L_max_FEA_uH" in payload
            assert payload["n_points_simulated"] == 3
            assert row.L_t4_uH == pytest.approx(400.0)
            assert row.highest_tier >= 4
            n_with_t4 += 1
    assert n_with_t4 >= 1


def test_orchestrator_marks_tier4_unavailable_when_no_backend(tmp_path, db):
    store = RunStore(tmp_path / "cascade.db")
    orch = CascadeOrchestrator(store, parallelism=1)
    spec = _spec()
    cfg = CascadeConfig(tier4_top_k=2)
    run_id = orch.start_run(spec, cfg)
    with patch(
        "pfc_inductor.optimize.cascade.orchestrator.supports_tier4",
        return_value=False,
    ):
        orch.run(run_id, spec, db["materials"], db["cores"], db["wires"], cfg)
    rows = store.top_candidates(run_id, n=2, order_by="loss_t1_W")
    for row in rows:
        assert row.notes is not None
        assert "tier4_error" in row.notes
        assert "tier4_unavailable" in row.notes["tier4_error"]


def test_orchestrator_skips_tier4_when_top_k_zero(tmp_path, db):
    store = RunStore(tmp_path / "cascade.db")
    orch = CascadeOrchestrator(store, parallelism=1)
    spec = _spec()
    cfg = CascadeConfig(tier4_top_k=0)
    run_id = orch.start_run(spec, cfg)
    orch.run(run_id, spec, db["materials"], db["cores"], db["wires"], cfg)
    for row in store.top_candidates(run_id, n=5, order_by="loss_t1_W"):
        assert row.L_t4_uH is None
        if row.notes:
            assert "tier4" not in row.notes
            assert "tier4_error" not in row.notes


def test_tier4_reuses_provided_tier1(db):
    """Passing `tier1=` saves an engine call in Tier 4 just like Tier 3."""
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)
    fake = _fake_fea_factory()
    t1 = eval_tier1(model, cand, core, material, wire)
    assert t1 is not None
    with patch("pfc_inductor.fea.runner.validate_design", side_effect=fake) as m:
        evaluate_candidate(model, cand, core, material, wire, tier1=t1)
    assert m.call_count == 5


# ─── _RunConfigCard tier4 spinbox ────────────────────────────────


def test_run_config_card_includes_tier4_spinbox():
    """The redesigned config card must expose Tier 4 alongside
    Tier 2 / Tier 3 / Workers."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    from pfc_inductor.ui.workspace.cascade_page import _RunConfigCard

    cfg = _RunConfigCard()
    assert cfg.tier4_spin.value() == 0  # default: off
    cfg.tier4_spin.setValue(5)
    assert cfg.to_cascade_config().tier4_top_k == 5
