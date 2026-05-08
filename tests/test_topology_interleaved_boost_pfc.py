"""Domain-level tests for the interleaved boost-PFC topology.

Validates the per-phase delegation, the Hwu-Yau ripple-cancellation
factor at the natural nulls / worst-case duties, the worst-case-duty
helper, and the THD scaling. Engine integration is covered in
``tests/test_design_engine.py``.
"""

from __future__ import annotations

import math

import pytest

from pfc_inductor.models import Spec
from pfc_inductor.topology import boost_ccm
from pfc_inductor.topology import interleaved_boost_pfc as ipfc


def _spec(n: int = 2, P: float = 3000.0) -> Spec:
    """Spec helper — 3 kW universal-input PFC, 2- or 3-phase."""
    return Spec(
        topology="interleaved_boost_pfc",
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=220.0,
        Vout_V=400.0,
        Pout_W=P,
        eta=0.97,
        f_sw_kHz=65.0,
        ripple_pct=30.0,
        n_interleave=n,
    )


# ---------------------------------------------------------------------------
# Per-phase delegation.
# ---------------------------------------------------------------------------
def test_per_phase_spec_scales_pout_and_changes_topology():
    spec = _spec(n=2, P=3000.0)
    pp = ipfc.per_phase_spec(spec)
    assert pp.topology == "boost_ccm"
    assert pp.Pout_W == pytest.approx(1500.0)
    # Everything else should be unchanged.
    assert pp.Vin_min_Vrms == spec.Vin_min_Vrms
    assert pp.Vout_V == spec.Vout_V
    assert pp.f_sw_kHz == spec.f_sw_kHz
    assert pp.ripple_pct == spec.ripple_pct


def test_per_phase_three_phase_splits_by_three():
    spec = _spec(n=3, P=3000.0)
    assert ipfc.per_phase_spec(spec).Pout_W == pytest.approx(1000.0)


def test_per_phase_currents_match_boost_at_per_phase_pout():
    """Per-phase RMS / peak should equal what the single-phase
    boost engine reports at Pout/N — same code path."""
    spec = _spec(n=2, P=3000.0)
    Vin = 85.0  # worst-case
    pp_spec = ipfc.per_phase_spec(spec)
    assert ipfc.line_rms_current_A(spec, Vin) == pytest.approx(
        boost_ccm.line_rms_current_A(pp_spec, Vin),
    )
    assert ipfc.line_peak_current_A(spec, Vin) == pytest.approx(
        boost_ccm.line_peak_current_A(pp_spec, Vin),
    )


def test_required_inductance_matches_boost_per_phase():
    spec = _spec(n=3, P=3000.0)
    Vin = 85.0
    L_per_phase = ipfc.required_inductance_uH(spec, Vin)
    L_boost = boost_ccm.required_inductance_uH(
        ipfc.per_phase_spec(spec),
        Vin,
    )
    assert L_per_phase == pytest.approx(L_boost)


def test_aggregate_input_is_n_times_per_phase():
    """The source still has to deliver Pout total — interleaving
    only redistributes the per-phase currents."""
    spec = _spec(n=2, P=3000.0)
    Vin = 220.0
    per_phase = ipfc.line_rms_current_A(spec, Vin)
    aggregate = ipfc.aggregate_input_rms_current_A(spec, Vin)
    assert aggregate == pytest.approx(2.0 * per_phase, rel=1e-9)


# ---------------------------------------------------------------------------
# Hwu-Yau cancellation factor.
# ---------------------------------------------------------------------------
def test_cancellation_at_natural_nulls_two_phase():
    """For N=2 the cancellation is exact at D = 0.5 (the only
    interior null)."""
    assert ipfc.ripple_cancellation_factor(0.5, 2) == pytest.approx(0.0, abs=1e-9)


def test_cancellation_at_natural_nulls_three_phase():
    """For N=3 the interior nulls sit at D = 1/3 and D = 2/3."""
    assert ipfc.ripple_cancellation_factor(1.0 / 3.0, 3) == pytest.approx(0.0, abs=1e-9)
    assert ipfc.ripple_cancellation_factor(2.0 / 3.0, 3) == pytest.approx(0.0, abs=1e-9)


def test_cancellation_factor_in_unit_interval():
    """``α(D, N)`` must always sit in [0, 1] for the symmetric
    N-phase case."""
    for D in (0.05, 0.15, 0.25, 0.4, 0.45, 0.55, 0.6, 0.75, 0.85, 0.95):
        for N in (2, 3):
            f = ipfc.ripple_cancellation_factor(D, N)
            assert 0.0 <= f <= 1.0, f"α({D}, {N}) = {f} outside [0, 1]"


def test_cancellation_factor_degenerates_for_n1():
    """N=1 means no interleaving — α should be 1 (no cancellation)."""
    for D in (0.1, 0.5, 0.9):
        assert ipfc.ripple_cancellation_factor(D, 1) == pytest.approx(1.0)


def test_cancellation_factor_at_zero_and_one():
    """Edge cases: ``α(0, N) = α(1, N) = 0`` (no current → no
    ripple to cancel; full duty → no off-time → no triangular ripple)."""
    for N in (2, 3):
        assert ipfc.ripple_cancellation_factor(0.0, N) == 0.0
        assert ipfc.ripple_cancellation_factor(1.0, N) == 0.0


def test_aggregate_pp_is_per_phase_pp_times_factor():
    per_phase_pp = 5.0  # arbitrary [A]
    D = 0.4
    expected = per_phase_pp * ipfc.ripple_cancellation_factor(D, 2)
    assert ipfc.aggregate_input_ripple_pp(per_phase_pp, D, 2) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Effective ripple frequency.
# ---------------------------------------------------------------------------
def test_effective_ripple_frequency_is_n_times_fsw():
    """The aggregate ripple's lowest harmonic sits at ``N · f_sw``."""
    assert ipfc.effective_input_ripple_frequency_Hz(65.0, 2) == pytest.approx(130_000.0)
    assert ipfc.effective_input_ripple_frequency_Hz(65.0, 3) == pytest.approx(195_000.0)


# ---------------------------------------------------------------------------
# Worst-case duty.
# ---------------------------------------------------------------------------
def test_worst_case_duty_two_phase():
    """For N=2 the cancellation cells are (0, 0.5) and (0.5, 1);
    the helper returns 0.25 (centre of the lower cell)."""
    assert ipfc.worst_case_duty_for_ripple(2) == pytest.approx(0.25)


def test_worst_case_duty_three_phase():
    """For N=3 the centre of the middle cell is 0.5."""
    assert ipfc.worst_case_duty_for_ripple(3) == pytest.approx(0.5)


def test_worst_case_duty_falls_back_to_05_for_n1():
    assert ipfc.worst_case_duty_for_ripple(1) == 0.5


# ---------------------------------------------------------------------------
# THD scaling.
# ---------------------------------------------------------------------------
def test_thd_scales_inversely_with_sqrt_n():
    """Interleaved THD = single-phase THD / √N."""
    spec_2 = _spec(n=2, P=3000.0)
    spec_3 = _spec(n=3, P=3000.0)
    base = boost_ccm.estimate_thd_pct(spec_2)
    assert ipfc.estimate_thd_pct(spec_2) == pytest.approx(base / math.sqrt(2))
    assert ipfc.estimate_thd_pct(spec_3) == pytest.approx(base / math.sqrt(3))


# ---------------------------------------------------------------------------
# Spec validator.
# ---------------------------------------------------------------------------
def test_spec_rejects_invalid_n_interleave():
    """Pydantic should reject n_interleave outside {2, 3}."""
    with pytest.raises(Exception):  # ValidationError
        Spec(
            topology="interleaved_boost_pfc",
            Vin_min_Vrms=85.0,
            Vin_max_Vrms=265.0,
            Vin_nom_Vrms=220.0,
            Vout_V=400.0,
            Pout_W=3000.0,
            eta=0.97,
            f_sw_kHz=65.0,
            ripple_pct=30.0,
            n_interleave=5,
        )


def test_spec_accepts_two_phase_default():
    spec = Spec(
        topology="interleaved_boost_pfc",
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=220.0,
        Vout_V=400.0,
        Pout_W=3000.0,
        eta=0.97,
        f_sw_kHz=65.0,
        ripple_pct=30.0,
    )
    assert spec.n_interleave == 2  # field default
