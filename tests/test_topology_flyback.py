"""Domain tests for ``pfc_inductor.topology.flyback``.

Benchmark fixture: TI UCC28780 EVM, 12 V → 5 V, 10 W, 100 kHz.
Erickson Ch. 6 worked example for the DCM design path.
"""

from __future__ import annotations

import math

import pytest

from pfc_inductor.models import Spec
from pfc_inductor.topology import flyback


def _erickson_spec(mode: str = "dcm") -> Spec:
    """Erickson §6.3 fixture: 12 V → 5 V, 10 W, 100 kHz, DCM."""
    return Spec(
        topology="flyback",
        Vin_dc_V=12.0,
        Vin_dc_min_V=10.8,
        Vin_dc_max_V=13.2,
        Vout_V=5.0,
        Pout_W=10.0,
        eta=0.85,  # typical small flyback at 10 W
        f_sw_kHz=100.0,
        T_amb_C=40.0,
        T_max_C=125.0,
        Ku_max=0.4,
        Bsat_margin=0.20,
        flyback_mode=mode,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Mode selection + spec accessors
# ---------------------------------------------------------------------------


def test_flyback_mode_default_is_dcm() -> None:
    """When the spec doesn't set ``flyback_mode``, the helper
    defaults to DCM — the textbook starting point."""
    spec = Spec(
        topology="flyback",
        Vin_dc_V=12.0,
        Vout_V=5.0,
        Pout_W=10.0,
        f_sw_kHz=100.0,
    )
    assert flyback._flyback_mode(spec) == "dcm"


def test_flyback_mode_ccm_round_trip() -> None:
    spec = _erickson_spec("ccm")
    assert flyback._flyback_mode(spec) == "ccm"


def test_vin_helpers_prefer_dc_fields() -> None:
    spec = _erickson_spec()
    assert flyback._vin_min(spec) == pytest.approx(10.8)
    assert flyback._vin_max(spec) == pytest.approx(13.2)
    assert flyback._vin_nom(spec) == pytest.approx(12.0)


# ---------------------------------------------------------------------------
# Output / input current
# ---------------------------------------------------------------------------


def test_output_current_matches_pout_div_vout() -> None:
    spec = _erickson_spec()
    assert flyback.output_current_A(spec) == pytest.approx(10.0 / 5.0, rel=1e-9)


def test_average_input_current_low_line_full_load() -> None:
    """``I_in_avg = Pout / (Vin_min · η)`` at the worst-case low-line
    operating point. For Erickson's 10 W / 10.8 V_min / η=0.85:
    I_in_avg = 10 / (10.8 · 0.85) ≈ 1.089 A."""
    spec = _erickson_spec()
    expected = 10.0 / (10.8 * 0.85)
    assert flyback.average_input_current_A(spec) == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# DCM duty cycle + required Lp
# ---------------------------------------------------------------------------


def test_required_lp_dcm_textbook() -> None:
    """Erickson DCM formula gives Lp_max for the worst-case
    low-line operating point. With D_max = 0.45:
    Lp_max = 0.85 · 10.8² · 0.45² / (2 · 10 · 100e3)
           = 0.85 · 116.64 · 0.2025 / (2e6)
           ≈ 10.04 µH
    """
    spec = _erickson_spec()
    Lp = flyback.required_primary_inductance_uH(spec, D_max=0.45)
    assert 9.0 <= Lp <= 11.0, f"Lp_max={Lp} µH outside textbook band"


def test_required_lp_scales_inversely_with_fsw() -> None:
    """Doubling f_sw halves the required Lp (flyback core formula)."""
    spec_100 = _erickson_spec()
    spec_200 = _erickson_spec()
    spec_200.f_sw_kHz = 200.0
    Lp_100 = flyback.required_primary_inductance_uH(spec_100, D_max=0.45)
    Lp_200 = flyback.required_primary_inductance_uH(spec_200, D_max=0.45)
    assert Lp_100 / Lp_200 == pytest.approx(2.0, rel=0.05)


def test_dcm_duty_falls_below_dmax_at_low_lp() -> None:
    """A smaller Lp than ``Lp_max`` keeps the design in DCM with
    a smaller duty cycle. Sanity check: at Lp = 0.5·Lp_max,
    D ≈ √0.5 · D_max ≈ 0.318."""
    spec = _erickson_spec()
    Lp_max = flyback.required_primary_inductance_uH(spec, D_max=0.45)
    Lp_half = 0.5 * Lp_max
    D = flyback.dcm_duty_cycle(spec, Lp_half)
    expected = math.sqrt(0.5) * 0.45
    assert D == pytest.approx(expected, rel=0.05)


# ---------------------------------------------------------------------------
# CCM duty cycle (volt-seconds balance)
# ---------------------------------------------------------------------------


def test_ccm_duty_volt_seconds_balance() -> None:
    """``D = n·Vout / (Vin + n·Vout)``. At Vin=12, Vout=5, n=2:
    D = 10 / (12 + 10) = 0.4545.
    """
    spec = _erickson_spec("ccm")
    D = flyback.ccm_duty_cycle(spec, n=2.0, Vin=12.0)
    assert D == pytest.approx(10.0 / 22.0, rel=1e-3)


def test_ccm_duty_at_low_line_is_largest() -> None:
    """D is largest at the smallest Vin — that's why we size for
    low-line worst-case."""
    spec = _erickson_spec("ccm")
    D_low = flyback.ccm_duty_cycle(spec, n=2.0, Vin=10.8)
    D_high = flyback.ccm_duty_cycle(spec, n=2.0, Vin=13.2)
    assert D_low > D_high


# ---------------------------------------------------------------------------
# Turns ratio
# ---------------------------------------------------------------------------


def test_optimal_turns_ratio_universal_input() -> None:
    """For Vin_max=13.2 V and Vout=5 V with a 600 V FET target,
    the headroom is ``600 - 13.2 = 586.8 V``, dividing by Vout
    gives n ≈ 117 — capped to 15 by the helper."""
    spec = _erickson_spec()
    n = flyback.optimal_turns_ratio(spec)
    assert n == pytest.approx(15.0, abs=0.01)


def test_optimal_turns_ratio_universal_input_pfc_bus() -> None:
    """A more realistic case: post-PFC bus 375 V → 5 V, 600 V FET.
    Headroom 600 - 375 = 225, /5 = 45 → still capped at 15."""
    spec = _erickson_spec()
    spec.Vin_dc_max_V = 400.0
    n = flyback.optimal_turns_ratio(spec)
    assert n == pytest.approx(15.0, abs=0.01)


def test_user_overrides_optimal_turns_ratio() -> None:
    spec = _erickson_spec()
    spec.turns_ratio_n = 3.5
    assert flyback.optimal_turns_ratio(spec) == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# Currents (DCM peak / RMS)
# ---------------------------------------------------------------------------


def test_primary_peak_current_dcm() -> None:
    """``Ip_pk = Vin·D·Tsw/Lp``. With Vin=10.8, D=0.45, Tsw=10us,
    Lp ≈ 10 µH: Ip_pk = 10.8 · 0.45 · 10e-6 / 10e-6 = 4.86 A.
    """
    spec = _erickson_spec()
    Lp = flyback.required_primary_inductance_uH(spec, D_max=0.45)
    Ip_pk = flyback.primary_peak_current(spec, Lp)
    # The duty cycle the helper uses is D = √(2·Lp·Pout·fsw / (η·Vin²))
    # which at Lp=Lp_max recovers the design point. Allow ±5 %.
    assert 4.5 <= Ip_pk <= 5.2


def test_primary_rms_current_dcm_triangular_pulse() -> None:
    """``Ip_rms = Ip_pk · √(D / 3)`` for a triangular pulse over
    D·Tsw with zero outside. At D=0.45: Ip_rms = Ip_pk · √0.15
    ≈ Ip_pk · 0.387."""
    spec = _erickson_spec()
    Lp = flyback.required_primary_inductance_uH(spec, D_max=0.45)
    Ip_pk = flyback.primary_peak_current(spec, Lp)
    Ip_rms = flyback.primary_rms_current(spec, Lp, Ip_pk)
    expected = Ip_pk * math.sqrt(0.45 / 3.0)
    # Within ±10 % since the helper uses its own dcm_duty_cycle
    # which may pick a slightly different D from the formula's
    # algebraic D_max=0.45 boundary.
    assert Ip_rms == pytest.approx(expected, rel=0.10)


def test_secondary_peak_is_n_times_primary() -> None:
    """Coupled-inductor energy balance: same flux, secondary
    sees ``n × Ip_pk``."""
    spec = _erickson_spec()
    n = 3.0
    Ip_pk = 5.0
    Is_pk = flyback.secondary_peak_current(spec, Ip_pk, n)
    assert Is_pk == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Reflected voltages — FET drain + diode reverse stress
# ---------------------------------------------------------------------------


def test_reflected_voltages_v_drain_includes_clamp() -> None:
    """``V_drain = Vin_max + n·Vout + V_clamp``. With Vin_max=13.2,
    n=2, Vout=5, V_clamp=1.5·n·Vout=15:
    V_drain = 13.2 + 10 + 15 = 38.2 V.
    """
    spec = _erickson_spec()
    V_drain, _V_diode = flyback.reflected_voltages(spec, n=2.0)
    assert V_drain == pytest.approx(38.2, abs=0.2)


def test_reflected_voltages_diode_reverse() -> None:
    """``V_diode = Vout + Vin_max/n``. With n=2, Vin_max=13.2,
    Vout=5: V_diode = 5 + 6.6 = 11.6 V."""
    spec = _erickson_spec()
    _, V_diode = flyback.reflected_voltages(spec, n=2.0)
    assert V_diode == pytest.approx(11.6, abs=0.05)


# ---------------------------------------------------------------------------
# Snubber
# ---------------------------------------------------------------------------


def test_snubber_dissipation_grows_with_leakage() -> None:
    """Ten-fold L_leak ⇒ ten-fold P_snubber (linear in L_leak)."""
    P_low = flyback.snubber_dissipation_W(
        L_leak_uH=0.5,
        Ip_pk=5.0,
        f_sw_kHz=100.0,
        n=2.0,
        Vout=5.0,
    )
    P_high = flyback.snubber_dissipation_W(
        L_leak_uH=5.0,
        Ip_pk=5.0,
        f_sw_kHz=100.0,
        n=2.0,
        Vout=5.0,
    )
    assert P_high / P_low == pytest.approx(10.0, rel=0.02)


def test_snubber_dissipation_grows_with_ip_squared() -> None:
    """``P_snubber ∝ Ip²`` — flyback's hard rule."""
    P_5 = flyback.snubber_dissipation_W(
        L_leak_uH=1.0,
        Ip_pk=5.0,
        f_sw_kHz=100.0,
        n=2.0,
        Vout=5.0,
    )
    P_10 = flyback.snubber_dissipation_W(
        L_leak_uH=1.0,
        Ip_pk=10.0,
        f_sw_kHz=100.0,
        n=2.0,
        Vout=5.0,
    )
    assert P_10 / P_5 == pytest.approx(4.0, rel=0.02)


# ---------------------------------------------------------------------------
# Waveforms
# ---------------------------------------------------------------------------


def test_waveform_keys_match_engine_contract() -> None:
    """The engine's loss code reads waveforms via fixed keys
    (``iL_pk_A``, ``delta_iL_pp_A``, etc). Check the flyback
    helper emits the same keys plus ``is_pk_A`` for the
    secondary stack on the Análise card."""
    spec = _erickson_spec()
    Lp = flyback.required_primary_inductance_uH(spec, D_max=0.45)
    wf = flyback.waveforms(spec, Lp, n=2.0)
    for key in (
        "t_s",
        "iL_pk_A",
        "iL_min_A",
        "delta_iL_pp_A",
        "is_pk_A",
        "duty",
        "demag_duty",
    ):
        assert key in wf, f"missing waveform key: {key}"


def test_waveform_primary_oscillates_zero_to_ip_pk_dcm() -> None:
    """DCM primary current is zero outside D·Tsw and ramps up to
    Ip_pk by end-of-ON. Min should be 0, max should be ≈Ip_pk."""
    spec = _erickson_spec()
    Lp = flyback.required_primary_inductance_uH(spec, D_max=0.45)
    Ip_pk = flyback.primary_peak_current(spec, Lp)
    wf = flyback.waveforms(spec, Lp, n=2.0)
    ip_max = float(wf["iL_pk_A"].max())
    ip_min = float(wf["iL_pk_A"].min())
    assert ip_min == pytest.approx(0.0, abs=0.01)
    assert ip_max == pytest.approx(Ip_pk, rel=0.05)


def test_waveform_secondary_zero_outside_demag() -> None:
    """DCM secondary current is non-zero only during D₂. It must
    have a non-zero peak and reach zero somewhere in the cycle."""
    spec = _erickson_spec()
    Lp = flyback.required_primary_inductance_uH(spec, D_max=0.45)
    wf = flyback.waveforms(spec, Lp, n=2.0)
    is_arr = wf["is_pk_A"]
    assert float(is_arr.max()) > 0.5
    assert float(is_arr.min()) == pytest.approx(0.0, abs=0.01)


def test_estimate_thd_returns_zero() -> None:
    """Flyback runs from a DC bus — no AC line current, no THD."""
    spec = _erickson_spec()
    assert flyback.estimate_thd_pct(spec) == 0.0


# ---------------------------------------------------------------------------
# Spec validator
# ---------------------------------------------------------------------------


def test_spec_rejects_flyback_with_zero_vin() -> None:
    """A flyback spec needs *some* Vin source — either the new
    ``Vin_dc_V`` field or the legacy ``Vin_min_Vrms`` fallback.
    With every Vin source explicitly zero, the validator must
    trip."""
    # ``Vin_min_Vrms`` has a Field-level default of 85.0; pydantic
    # ge=0 isn't enforced here so we can pass 0 explicitly.
    with pytest.raises(ValueError, match="Vin_dc_V"):
        Spec(
            topology="flyback",
            Vin_min_Vrms=0.0,
            Vin_max_Vrms=0.0,
            Vin_dc_V=0.0,
            Vin_dc_min_V=0.0,
            Vin_dc_max_V=0.0,
            Vout_V=5.0,
            Pout_W=10.0,
            f_sw_kHz=100.0,
        )


def test_spec_rejects_invalid_flyback_mode() -> None:
    with pytest.raises(ValueError):
        Spec(
            topology="flyback",
            Vin_dc_V=12.0,
            Vout_V=5.0,
            Pout_W=10.0,
            f_sw_kHz=100.0,
            flyback_mode="qrf",  # type: ignore[arg-type]
        )


def test_spec_accepts_flyback_with_legacy_vin_min_vrms() -> None:
    """Pre-Vin_dc_V specs that set the AC field are still valid
    flyback inputs (the validator falls back to Vin_min_Vrms)."""
    spec = Spec(
        topology="flyback",
        Vin_min_Vrms=85.0,
        Vout_V=5.0,
        Pout_W=10.0,
        f_sw_kHz=100.0,
    )
    assert flyback._vin_min(spec) == pytest.approx(85.0)
