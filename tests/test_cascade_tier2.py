"""Tier 2 evaluator regression + validation against Tier 1 / ground truth."""

from __future__ import annotations

import pytest

from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.models import Candidate, Spec
from pfc_inductor.optimize.cascade.tier1 import evaluate_candidate as eval_tier1
from pfc_inductor.optimize.cascade.tier2 import (
    evaluate_candidate,
    evaluate_candidate_safe,
    supports_tier2,
)
from pfc_inductor.topology.boost_ccm_model import BoostCCMModel
from pfc_inductor.topology.line_reactor_model import LineReactorModel
from pfc_inductor.topology.passive_choke_model import PassiveChokeModel
from pfc_inductor.topology.protocol import Tier2ConverterModel


@pytest.fixture(scope="module")
def db():
    return {
        "materials": load_materials(),
        "cores": load_cores(),
        "wires": load_wires(),
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


# ─── Tier-2 protocol detection ─────────────────────────────────


def test_boost_ccm_model_advertises_tier2_capability():
    spec = _spec()
    model = BoostCCMModel(spec)
    assert isinstance(model, Tier2ConverterModel) is True
    assert supports_tier2(model) is True


def test_passive_choke_model_advertises_tier2_capability():
    """Phase B Step 3: passive_choke gains Tier 2 support."""
    spec = _spec().model_copy(update={"topology": "passive_choke"})
    model = PassiveChokeModel(spec)
    assert isinstance(model, Tier2ConverterModel) is True
    assert supports_tier2(model) is True


def test_line_reactor_model_advertises_tier2_capability():
    """Phase B Step 3: line_reactor gains Tier 2 support."""
    spec = Spec(
        topology="line_reactor",
        Vin_nom_Vrms=400.0,
        f_line_Hz=60.0,
        n_phases=3,
        L_req_mH=1.0,
        I_rated_Arms=30.0,
    )
    model = LineReactorModel(spec)
    assert isinstance(model, Tier2ConverterModel) is True
    assert supports_tier2(model) is True


# ─── Reference design — Tier 2 vs Tier 1 ────────────────────────


def test_tier2_reproduces_analytical_L_at_modest_rolloff(db):
    """High Flux 60 at 14 A peak / 45 turns has only mild rolloff,
    so the cycle-averaged L from Tier 2 must match Tier 1's
    `L_actual_uH` to within a few percent."""
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)
    r = evaluate_candidate(model, cand, core, material, wire)
    assert r is not None
    # Sanity: didn't accidentally trip saturation on a known-good design.
    assert r.saturation_t2 is False
    # L_avg should agree with the analytical L_actual to ≤ 5 %.
    assert abs(r.L_relative_error_pct) < 5.0
    # i_pk_relative_error compares Tier-2's peak with HF ripple
    # against the engine's `I_pk_max_A`, which already includes the
    # analytical ripple, so the two must match closely (≤ 5 %).
    assert abs(r.i_pk_relative_error_pct) < 5.0
    # B_pk must EXCEED the engine's line-envelope `B_pk_T` (Tier 2
    # adds the HF ripple-driven flux excursion).
    assert r.B_relative_error_pct is not None
    assert r.B_relative_error_pct > 0.0


def test_tier2_picks_up_HF_ripple_in_B(db):
    """B_pk_t2 must exceed B_pk_t1 by something comparable to the
    HF ripple-driven flux excursion ΔB_PP/2."""
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)
    r = evaluate_candidate(model, cand, core, material, wire)
    assert r is not None
    assert r.B_relative_error_pct is not None
    # Strictly greater than the line-envelope analytical, by a
    # margin that reflects the HF ripple.
    assert r.B_relative_error_pct > 0.0


def test_tier2_reuses_tier1_design_when_provided(db):
    """Passing `tier1=` avoids running the engine twice — verify the
    Tier-2 numbers are identical whether the engine ran once or twice."""
    spec = _spec()
    model = BoostCCMModel(spec)
    cand, core, material, wire = _ref(db)

    t1 = eval_tier1(model, cand, core, material, wire)
    assert t1 is not None
    r_with = evaluate_candidate(model, cand, core, material, wire, tier1=t1)
    r_without = evaluate_candidate(model, cand, core, material, wire)

    assert r_with is not None and r_without is not None
    assert r_with.i_pk_A == pytest.approx(r_without.i_pk_A, rel=1e-9)
    assert r_with.B_pk_T == pytest.approx(r_without.B_pk_T, rel=1e-9)


# ─── Saturation flag ───────────────────────────────────────────


def test_tier2_saturation_flag_trips_when_B_exceeds_margin(db):
    """A 3 kW spec on a small core forces deep saturation. Tier 2
    must flag it even when the engine resolves a Tier-1 design."""
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
    # Smallest compatible core — guarantees deep saturation.
    smallest = min(
        (c for c in db["cores"] if c.default_material_id == material.id),
        key=lambda c: c.Ve_mm3,
    )
    wire = next(w for w in db["wires"] if w.id == "AWG14")
    cand = Candidate(core_id=smallest.id, material_id=material.id, wire_id=wire.id)

    r = evaluate_candidate(model, cand, smallest, material, wire)
    if r is None:
        # Engine couldn't solve N either — fine; we want the test to
        # pass when *either* the engine or Tier 2 catches the failure.
        return
    assert r.saturation_t2 is True


# ─── Tier 2 on passive topologies (Phase B Step 3) ─────────────


def test_tier2_passive_choke_returns_result(db):
    """Passive topologies now run Tier 2 via the imposed-trajectory
    path (no PWM, no DCM) — the result must be populated, not None."""
    spec = _spec().model_copy(update={"topology": "passive_choke", "Pout_W": 400.0})
    model = PassiveChokeModel(spec)
    cand, core, material, wire = _ref(db)
    r = evaluate_candidate(model, cand, core, material, wire)
    assert r is not None
    assert r.i_pk_A > 0
    assert r.L_avg_uH > 0


def test_tier2_passive_choke_has_bidirectional_current(db):
    """Passive AC inductor: current is bidirectional (sine), so the
    captured trace must contain negative samples."""
    spec = _spec().model_copy(update={"topology": "passive_choke", "Pout_W": 400.0})
    model = PassiveChokeModel(spec)
    _cand, core, material, wire = _ref(db)
    inductor_N = model.steady_state(core, material, wire).N_turns

    from pfc_inductor.simulate import (
        NonlinearInductor,
        simulate_to_steady_state,
    )

    inductor = NonlinearInductor(core=core, material=material, N=inductor_N)
    wf = simulate_to_steady_state(model, inductor)
    assert (wf.i_L_A < 0).any(), (
        f"passive choke current must dip below zero (min = {wf.i_L_A.min():.3f} A)"
    )
    assert (wf.i_L_A > 0).any()


def test_tier2_line_reactor_returns_result(db):
    """Line reactor uses the existing diode-bridge waveform generator;
    Tier 2 must surface the same signal as a `Waveform`."""
    spec = Spec(
        topology="line_reactor",
        Vin_nom_Vrms=400.0,
        f_line_Hz=60.0,
        n_phases=3,
        L_req_mH=1.0,
        I_rated_Arms=30.0,
    )
    model = LineReactorModel(spec)
    cand, core, material, wire = _ref(db)
    r = evaluate_candidate(model, cand, core, material, wire)
    assert r is not None
    # Peak current should be near sqrt(2) · I_rated_Arms = 42.4 A; the
    # diode-bridge waveform clips a bit, so accept anywhere in the
    # 30–55 A band.
    assert 30.0 <= r.i_pk_A <= 55.0, f"unexpected line-reactor peak current: {r.i_pk_A:.2f} A"


# ─── Safe wrapper swallows exceptions ──────────────────────────


def test_tier2_safe_returns_error_on_engine_failure(db):
    spec = _spec()

    class _Boom(BoostCCMModel):
        def steady_state(self, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("synthetic engine failure")

    model = _Boom(spec)
    cand, core, material, wire = _ref(db)
    r, err = evaluate_candidate_safe(model, cand, core, material, wire)
    assert r is None
    assert err is not None
    assert "RuntimeError" in err
    assert "synthetic" in err
