"""Cascade DTO Pydantic round-trip tests."""
from __future__ import annotations

import pytest

from pfc_inductor.models.cascade import (
    Candidate,
    FeasibilityEnvelope,
    Tier0Result,
    Tier1Result,
)
from pfc_inductor.models.result import DesignResult, LossBreakdown


def test_candidate_default_optional_fields():
    c = Candidate(core_id="C1", material_id="M1", wire_id="W1")
    assert c.N is None
    assert c.gap_mm is None


def test_candidate_key_is_stable_for_identical_inputs():
    c1 = Candidate(core_id="C1", material_id="M1", wire_id="W1", N=42, gap_mm=0.5)
    c2 = Candidate(core_id="C1", material_id="M1", wire_id="W1", N=42, gap_mm=0.5)
    assert c1.key() == c2.key()


def test_candidate_key_differs_when_any_field_changes():
    base = Candidate(core_id="C1", material_id="M1", wire_id="W1", N=42, gap_mm=0.5)
    assert base.key() != base.model_copy(update={"core_id": "C2"}).key()
    assert base.key() != base.model_copy(update={"material_id": "M2"}).key()
    assert base.key() != base.model_copy(update={"wire_id": "W2"}).key()
    assert base.key() != base.model_copy(update={"N": 43}).key()
    assert base.key() != base.model_copy(update={"gap_mm": 0.6}).key()


def test_candidate_key_handles_none_fields():
    c_none = Candidate(core_id="C1", material_id="M1", wire_id="W1")
    c_set = Candidate(core_id="C1", material_id="M1", wire_id="W1", N=10, gap_mm=0.0)
    assert c_none.key() != c_set.key()
    # The None-encoding should not collide with any plausible numeric value.
    assert "_" in c_none.key()


def test_feasibility_envelope_feasible_default_no_reasons():
    env = FeasibilityEnvelope(feasible=True)
    assert env.reasons == []


def test_feasibility_envelope_carries_rejection_reasons():
    env = FeasibilityEnvelope(
        feasible=False,
        reasons=["window_overflow", "saturates"],
    )
    assert env.reasons == ["window_overflow", "saturates"]


def test_tier0_result_round_trip():
    r = Tier0Result(
        candidate=Candidate(core_id="C1", material_id="M1", wire_id="W1"),
        envelope=FeasibilityEnvelope(feasible=True),
    )
    dumped = r.model_dump()
    restored = Tier0Result.model_validate(dumped)
    assert restored == r


def _make_design_result(*, P_total: float = 5.0, T: float = 80.0,
                       feasible: bool = True) -> DesignResult:
    """Hand-rolled DesignResult for tests — avoids spinning the engine."""
    return DesignResult(
        L_required_uH=400.0,
        L_actual_uH=410.0,
        N_turns=42,
        I_line_pk_A=14.0,
        I_line_rms_A=10.0,
        I_ripple_pk_pk_A=4.0,
        I_pk_max_A=16.0,
        I_rms_total_A=10.5,
        H_dc_peak_Oe=120.0,
        mu_pct_at_peak=0.55,
        B_pk_T=0.30 if feasible else 0.95,
        B_sat_limit_T=0.40,
        sat_margin_pct=0.20,
        R_dc_ohm=0.05,
        R_ac_ohm=0.07,
        losses=LossBreakdown(
            P_cu_dc_W=P_total * 0.4,
            P_cu_ac_W=P_total * 0.1,
            P_core_line_W=P_total * 0.4,
            P_core_ripple_W=P_total * 0.1,
        ),
        T_rise_C=T - 40.0,
        T_winding_C=T,
        Ku_actual=0.35,
        Ku_max=0.40,
        converged=True,
        warnings=[] if feasible else ["B_pk above limit"],
    )


def test_tier1_result_exposes_design_metrics():
    r = Tier1Result(
        candidate=Candidate(core_id="C1", material_id="M1", wire_id="W1"),
        design=_make_design_result(P_total=8.0, T=72.0, feasible=True),
    )
    assert r.feasible is True
    assert r.total_loss_W == pytest.approx(8.0)
    assert r.temp_C == pytest.approx(72.0)
    assert r.n_warnings == 0


def test_tier1_result_marks_infeasible_when_design_is():
    r = Tier1Result(
        candidate=Candidate(core_id="C1", material_id="M1", wire_id="W1"),
        design=_make_design_result(feasible=False),
    )
    assert r.feasible is False
    assert r.n_warnings >= 1
