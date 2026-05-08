"""Pure-physics tests for the synchronous buck-CCM topology.

Reference benchmarks come from Erickson §5.2 worked examples and TI
Application Report SLVA477 (TPS54360 datasheet sample design).
"""

from __future__ import annotations

import pytest

from pfc_inductor.models import Spec
from pfc_inductor.topology import buck_ccm

# ---------------------------------------------------------------------------
# Spec fixture — Erickson §5.2 textbook example
# Vin = 12 V, Vout = 3.3 V, Iout = 5 A, fsw = 500 kHz, target ΔI/Iout = 0.30
# ---------------------------------------------------------------------------


def _erickson_spec() -> Spec:
    """Erickson §5.2 worked buck design."""
    return Spec(
        topology="buck_ccm",
        Vin_dc_V=12.0,
        Vin_dc_min_V=10.8,  # 90 % of nom
        Vin_dc_max_V=13.2,  # 110 % of nom
        Vout_V=3.3,
        Pout_W=3.3 * 5.0,  # 16.5 W → Iout = 5 A
        eta=0.95,
        f_sw_kHz=500.0,
        ripple_ratio=0.30,
        T_amb_C=40.0,
        T_max_C=125.0,
        Ku_max=0.4,
        Bsat_margin=0.20,
    )


# ---------------------------------------------------------------------------
# Output current
# ---------------------------------------------------------------------------


def test_output_current_matches_pout_over_vout():
    spec = _erickson_spec()
    assert buck_ccm.output_current_A(spec) == pytest.approx(5.0, rel=1e-6)


def test_output_current_zero_on_zero_vout():
    spec = _erickson_spec()
    spec_zero = spec.model_copy(update={"Vout_V": 0.0})
    # Pydantic may reject Vout_V=0 outright; the helper still has
    # to be defensive.
    assert buck_ccm.output_current_A(spec_zero) == 0.0


# ---------------------------------------------------------------------------
# Duty cycle
# ---------------------------------------------------------------------------


def test_duty_cycle_ideal_volt_seconds_balance():
    spec = _erickson_spec()
    # At Vin = 12 V, Vout = 3.3 V, η = 0.95:
    # D = 3.3 / (12 · 0.95) ≈ 0.289
    assert buck_ccm.duty_cycle(spec, 12.0) == pytest.approx(0.2895, abs=1e-3)


def test_duty_cycle_capped_below_unity():
    spec = _erickson_spec()
    # If Vin == Vout the formula gives D ≈ 1/η > 1; cap at 0.99.
    assert buck_ccm.duty_cycle(spec, 3.3) == pytest.approx(0.99, abs=1e-2)


# ---------------------------------------------------------------------------
# Required inductance — the headline number
# ---------------------------------------------------------------------------


def test_required_inductance_matches_textbook():
    """Worst-case L sizing at Vin_max for the Erickson §5.2 example
    (Vin = 12 V ±10 %, Vout = 3.3 V, Iout = 5 A, fsw = 500 kHz,
    r = 0.30, η = 0.95):

        D_min  = Vout / (Vin_max · η) = 3.3 / (13.2 · 0.95) ≈ 0.263
        ΔI_pp  = r · Iout = 0.30 · 5 = 1.5 A
        L_min  = Vout · (1 − D_min) / (ΔI_pp · f_sw)
               = 3.3 · 0.737 / (1.5 · 500 kHz)
               ≈ 3.24 µH

    Erickson's textbook prints ~3.2 µH at the same operating point
    using η = 1 (analytical D = 0.275). Our number tracks within
    ±2 %.
    """
    spec = _erickson_spec()
    L_uH = buck_ccm.required_inductance_uH(spec)
    assert 3.1 <= L_uH <= 3.4, f"Got L={L_uH:.2f} µH"


def test_required_inductance_scales_inversely_with_fsw():
    """Doubling f_sw should halve the required inductance."""
    spec_500k = _erickson_spec()
    spec_1M = spec_500k.model_copy(update={"f_sw_kHz": 1000.0})
    L_500k = buck_ccm.required_inductance_uH(spec_500k)
    L_1M = buck_ccm.required_inductance_uH(spec_1M)
    assert L_1M == pytest.approx(L_500k / 2.0, rel=1e-3)


def test_required_inductance_scales_inversely_with_ripple_ratio():
    """Halving the target ripple should double the required L."""
    spec_30 = _erickson_spec()
    spec_15 = spec_30.model_copy(update={"ripple_ratio": 0.15})
    L_30 = buck_ccm.required_inductance_uH(spec_30)
    L_15 = buck_ccm.required_inductance_uH(spec_15)
    assert L_15 == pytest.approx(L_30 * 2.0, rel=1e-3)


# ---------------------------------------------------------------------------
# Peak / RMS / boundary current
# ---------------------------------------------------------------------------


def test_peak_current_is_iout_plus_half_ripple():
    spec = _erickson_spec()
    L_uH = buck_ccm.required_inductance_uH(spec)
    Iout = buck_ccm.output_current_A(spec)
    delta = buck_ccm.worst_case_ripple_pp_A(spec, L_uH)
    expected_peak = Iout + 0.5 * delta
    assert buck_ccm.peak_inductor_current_A(spec, L_uH) == pytest.approx(
        expected_peak,
        rel=1e-6,
    )


def test_peak_current_at_design_point_is_30pct_above_iout():
    """At the textbook ripple ratio of 0.30, peak should sit at
    ``Iout · (1 + r/2) = Iout · 1.15``."""
    spec = _erickson_spec()
    L_uH = buck_ccm.required_inductance_uH(spec)
    Iout = buck_ccm.output_current_A(spec)
    Ipk = buck_ccm.peak_inductor_current_A(spec, L_uH)
    # 15 % above Iout for r=0.30 (with the η correction the actual
    # ripple is slightly less than 30 % so the peak sits ~13–15 %).
    assert 1.10 < Ipk / Iout < 1.20


def test_rms_current_triangle_on_dc():
    """``I_rms² = Iout² + (ΔI/√12)²``. At r=0.30 the AC component
    bumps RMS by ~0.4 % — small, as expected for buck."""
    spec = _erickson_spec()
    L_uH = buck_ccm.required_inductance_uH(spec)
    Iout = buck_ccm.output_current_A(spec)
    Irms = buck_ccm.rms_inductor_current_A(spec, L_uH)
    # Triangle on DC: < 1 % RMS uplift at r=0.30.
    assert 1.0 < Irms / Iout < 1.01


def test_rms_falls_back_to_iout_when_l_unknown():
    """``L_uH=None`` is the pre-design state — RMS = Iout (the
    feasibility heuristic uses this before sizing)."""
    spec = _erickson_spec()
    assert buck_ccm.rms_inductor_current_A(spec, None) == buck_ccm.output_current_A(spec)


def test_ccm_dcm_boundary_is_half_ripple():
    spec = _erickson_spec()
    L_uH = buck_ccm.required_inductance_uH(spec)
    delta = buck_ccm.worst_case_ripple_pp_A(spec, L_uH)
    assert buck_ccm.ccm_dcm_boundary_A(spec, L_uH) == pytest.approx(
        0.5 * delta,
        rel=1e-9,
    )


# ---------------------------------------------------------------------------
# Waveforms
# ---------------------------------------------------------------------------


def test_waveform_keys_match_boost_module():
    """Engine code reads the waveform dict by key; the buck module
    must expose the same set so the topology branch is the only
    difference."""
    spec = _erickson_spec()
    L_uH = buck_ccm.required_inductance_uH(spec)
    wf = buck_ccm.waveforms(spec, L_uH)
    expected = {"t_s", "iL_avg_A", "delta_iL_pp_A", "iL_pk_A", "iL_min_A", "vin_inst_V", "duty"}
    assert expected.issubset(set(wf.keys()))


def test_waveform_iL_oscillates_around_iout():
    spec = _erickson_spec()
    L_uH = buck_ccm.required_inductance_uH(spec)
    wf = buck_ccm.waveforms(spec, L_uH)
    Iout = buck_ccm.output_current_A(spec)
    iL = wf["iL_pk_A"]
    # Average over the sample should be ~Iout.
    assert abs(float(iL.mean()) - Iout) / Iout < 0.05
    # Peak-to-peak swing should be ~ΔI_pp at the nominal Vin.
    delta = buck_ccm.ripple_pp_at_Vin(spec, L_uH, 12.0)
    swing = float(iL.max() - iL.min())
    assert abs(swing - delta) / delta < 0.10


def test_waveform_helpers_round_trip():
    """The boost-style helper functions
    (``rms_inductor_current_from_waveform``, ``ripple_max_pp_A``,
    etc.) operate on the same dict and return the expected
    summaries."""
    spec = _erickson_spec()
    L_uH = buck_ccm.required_inductance_uH(spec)
    wf = buck_ccm.waveforms(spec, L_uH)
    Iout = buck_ccm.output_current_A(spec)
    # ``ripple_max`` ≈ ``ripple_avg`` for buck (no envelope).
    assert buck_ccm.ripple_max_pp_A(wf) == pytest.approx(
        buck_ccm.ripple_avg_pp_A(wf),
        rel=1e-9,
    )
    # Peak from waveform ≈ Iout + half ripple at Vin_nom.
    Ipk_from_wf = buck_ccm.peak_inductor_current_from_waveform(wf)
    delta = buck_ccm.ripple_pp_at_Vin(spec, L_uH, 12.0)
    assert Ipk_from_wf == pytest.approx(Iout + 0.5 * delta, rel=0.05)


# ---------------------------------------------------------------------------
# THD
# ---------------------------------------------------------------------------


def test_estimate_thd_returns_zero_for_dc_output():
    """Buck has DC output — line-side THD is undefined (depends on
    the input EMI filter, not the inductor design)."""
    assert buck_ccm.estimate_thd_pct(_erickson_spec()) == 0.0


# ---------------------------------------------------------------------------
# Spec validator
# ---------------------------------------------------------------------------


def test_spec_rejects_buck_with_vout_geq_vin():
    """Buck must step DOWN — the validator should reject Vout ≥ Vin."""
    with pytest.raises(ValueError, match="step-down"):
        Spec(
            topology="buck_ccm",
            Vin_dc_V=5.0,
            Vout_V=12.0,  # ← upside-down
            Pout_W=10.0,
        )


def test_spec_accepts_buck_with_legacy_vin_min_vrms():
    """Specs migrated from boost-CCM tests didn't carry ``Vin_dc_V``;
    the engine falls back to ``Vin_min_Vrms`` so old fixtures keep
    loading."""
    spec = Spec(
        topology="buck_ccm",
        Vin_min_Vrms=12.0,  # legacy AC field reused as DC
        Vout_V=3.3,
        Pout_W=16.5,
        f_sw_kHz=500.0,
    )
    assert spec.topology == "buck_ccm"
    # The buck helpers should still return sane numbers.
    assert buck_ccm.output_current_A(spec) == pytest.approx(5.0, rel=1e-6)
