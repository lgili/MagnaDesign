"""Tier 1 wrapper tests + parity with the existing sweep."""

from __future__ import annotations

import pytest

from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.models import Candidate, Spec
from pfc_inductor.optimize.cascade.generators import cartesian
from pfc_inductor.optimize.cascade.tier1 import (
    cost_USD,
    evaluate_candidate,
    evaluate_candidate_safe,
)
from pfc_inductor.optimize.sweep import sweep
from pfc_inductor.topology.boost_ccm_model import BoostCCMModel


@pytest.fixture(scope="module")
def db():
    return {
        "materials": load_materials(),
        "cores": load_cores(),
        "wires": load_wires(),
    }


def _boost_spec() -> Spec:
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


def _ref_combo(db):
    material = find_material(db["materials"], "magnetics-60_highflux")
    core = next(
        c
        for c in db["cores"]
        if c.default_material_id == material.id and 40_000 < c.Ve_mm3 < 100_000
    )
    wire = next(w for w in db["wires"] if w.id == "AWG14")
    return material, core, wire


# ─── evaluate_candidate ────────────────────────────────────────────


def test_tier1_evaluate_candidate_returns_design_result(db):
    spec = _boost_spec()
    model = BoostCCMModel(spec)
    material, core, wire = _ref_combo(db)
    cand = Candidate(core_id=core.id, material_id=material.id, wire_id=wire.id)

    result = evaluate_candidate(model, cand, core, material, wire)
    assert result is not None
    assert result.candidate is cand
    assert result.design.L_actual_uH > 0
    assert result.feasible is True
    assert result.total_loss_W >= 0


def test_tier1_drops_design_at_N_max(db):
    """Engine returning N_max means 'unsolved' — Tier 1 must yield None."""
    # Force unsolvable: a tiny core for a 3 kW spec — the engine
    # will hit N_max trying to reach L_required.
    spec = Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=220.0,
        Vout_V=400.0,
        Pout_W=3000.0,
        eta=0.97,
        f_sw_kHz=65.0,
        ripple_pct=30.0,
        T_amb_C=40.0,
        T_max_C=100.0,
        Ku_max=0.40,
        Bsat_margin=0.20,
    )
    model = BoostCCMModel(spec)
    material = find_material(db["materials"], "magnetics-60_highflux")
    smallest = min(
        (c for c in db["cores"] if c.default_material_id == material.id),
        key=lambda c: c.Ve_mm3,
    )
    wire = next(w for w in db["wires"] if w.id == "AWG14")
    cand = Candidate(core_id=smallest.id, material_id=material.id, wire_id=wire.id)

    result = evaluate_candidate(model, cand, smallest, material, wire)
    assert result is None


# ─── evaluate_candidate_safe ───────────────────────────────────────


def test_tier1_safe_returns_result_when_engine_ok(db):
    spec = _boost_spec()
    model = BoostCCMModel(spec)
    material, core, wire = _ref_combo(db)
    cand = Candidate(core_id=core.id, material_id=material.id, wire_id=wire.id)

    result, error = evaluate_candidate_safe(model, cand, core, material, wire)
    assert error is None
    assert result is not None
    assert result.feasible is True


def test_tier1_safe_swallows_exceptions(db):
    """An arbitrary engine exception must be turned into an error string,
    not propagated. This is the contract the orchestrator relies on.
    """

    class _ExplodingModel(BoostCCMModel):
        """A model whose `steady_state` always raises — simulates an engine bug."""

        def steady_state(self, core, material, wire):  # type: ignore[override]
            raise RuntimeError("synthetic failure for test")

    spec = _boost_spec()
    model = _ExplodingModel(spec)
    material, core, wire = _ref_combo(db)
    cand = Candidate(core_id=core.id, material_id=material.id, wire_id=wire.id)

    result, error = evaluate_candidate_safe(model, cand, core, material, wire)
    assert result is None
    assert error is not None
    assert "RuntimeError" in error
    assert "synthetic failure" in error


# ─── cost_USD helper ───────────────────────────────────────────────


def test_cost_USD_returns_finite_when_priced(db):
    spec = _boost_spec()
    model = BoostCCMModel(spec)
    material, core, wire = _ref_combo(db)
    design = model.steady_state(core, material, wire)

    cost = cost_USD(design, core, material, wire)
    # Curated DB ships demo cost data, so this should not be None.
    assert cost is not None
    assert cost > 0


# ─── Parity with the existing sweep ────────────────────────────────


def test_tier1_top10_matches_existing_sweep_top10(db):
    """Cascade Tier 1 must reproduce `optimize.sweep.sweep` top-10 ranking.

    The cascade orchestrator wraps the same `design()` call the
    legacy sweep uses; running them on the same inputs must yield
    the same per-candidate metrics — this guards against drift.
    """
    spec = _boost_spec()
    model = BoostCCMModel(spec)
    materials = db["materials"]
    cores = db["cores"]
    wires = db["wires"]

    # Restrict to a single material so the test runs in seconds, not minutes.
    target_material_id = "magnetics-60_highflux"

    # Sweep (legacy path).
    legacy = sweep(
        spec,
        cores,
        wires,
        materials,
        material_id=target_material_id,
    )
    legacy_top10 = sorted(legacy, key=lambda r: r.P_total_W)[:10]
    legacy_keys = [f"{r.core.id}|{r.material.id}|{r.wire.id}|_|_" for r in legacy_top10]

    # Cascade Tier 1 path.
    materials_by_id = {m.id: m for m in materials}
    cores_by_id = {c.id: c for c in cores}
    wires_by_id = {w.id: w for w in wires}
    candidates = [
        cand
        for cand in cartesian(
            [m for m in materials if m.id == target_material_id],
            cores,
            wires,
        )
    ]
    cascade_results = []
    for cand in candidates:
        m = materials_by_id[cand.material_id]
        c = cores_by_id[cand.core_id]
        w = wires_by_id[cand.wire_id]
        r = evaluate_candidate(model, cand, c, m, w)
        if r is not None:
            cascade_results.append(r)
    cascade_top10 = sorted(cascade_results, key=lambda r: r.total_loss_W)[:10]
    cascade_keys = [r.candidate.key() for r in cascade_top10]

    assert cascade_keys == legacy_keys
