"""Tests for the line-reactor topology (50/60 Hz harmonic mitigation)."""
from __future__ import annotations

import math

import pytest

from pfc_inductor.models import Spec
from pfc_inductor.topology import line_reactor as lr


# ---------------------------------------------------------------------------
# Reference reactor — 3-phase 380 V_LL / 30 A / 5 %Z / 60 Hz
# ---------------------------------------------------------------------------
def _ref_3ph() -> Spec:
    return Spec(
        topology="line_reactor",
        n_phases=3,
        Vin_nom_Vrms=380.0,    # L-L
        I_rated_Arms=30.0,
        pct_impedance=5.0,
        f_line_Hz=60.0,
    )


def test_phase_voltage_3ph_is_VLL_over_sqrt3():
    spec = _ref_3ph()
    assert math.isclose(lr.phase_voltage_Vrms(spec), 380.0 / math.sqrt(3.0), rel_tol=1e-6)


def test_phase_voltage_1ph_is_input_value():
    spec = Spec(topology="line_reactor", n_phases=1, Vin_nom_Vrms=220.0,
                I_rated_Arms=15.0, pct_impedance=8.0, f_line_Hz=60.0)
    assert lr.phase_voltage_Vrms(spec) == 220.0


def test_required_inductance_3ph_380_30A_5pct_60Hz():
    """Reference value 0.97 mH (textbook calculation in the spec docstring)."""
    L_mH = lr.required_inductance_mH(_ref_3ph())
    assert math.isclose(L_mH, 0.97, abs_tol=0.01)


def test_required_inductance_1ph_220_15A_8pct_60Hz():
    """Reference value ≈3.1 mH per spec scenario."""
    spec = Spec(topology="line_reactor", n_phases=1, Vin_nom_Vrms=220.0,
                I_rated_Arms=15.0, pct_impedance=8.0, f_line_Hz=60.0)
    L_mH = lr.required_inductance_mH(spec)
    assert 3.0 <= L_mH <= 3.2


def test_voltage_drop_at_design_L_equals_target_pct():
    spec = _ref_3ph()
    L_mH = lr.required_inductance_mH(spec)
    drop_pct = lr.voltage_drop_pct(L_mH, spec)
    assert math.isclose(drop_pct, spec.pct_impedance, abs_tol=0.05)


@pytest.mark.parametrize("pct,expected_thd", [
    (3, 43),
    (5, 33),
    (8, 26),
    (12, 22),
])
def test_thd_estimate_matches_pomilio_rule_3phase(pct, expected_thd):
    """3-phase: textbook ``75/√%Z`` rule (Pomilio Cap. 11)."""
    thd = lr.estimate_thd_pct(pct, n_phases=3)
    assert abs(thd - expected_thd) < 3, f"%Z={pct} -> THD={thd:.1f} (expected ~{expected_thd})"


def test_thd_estimate_1phase_higher_than_3phase():
    """1-phase cap-DC-link rectifiers have much higher THD than 3-phase
    industrial drives — typically 80-130% for residential equipment."""
    for pct in (1.5, 3, 5, 8):
        thd_1ph = lr.estimate_thd_pct(pct, n_phases=1)
        thd_3ph = lr.estimate_thd_pct(pct, n_phases=3)
        assert thd_1ph > thd_3ph
        assert 40 < thd_1ph < 140, f"%Z={pct}: 1ph THD {thd_1ph} out of range"


def test_line_pk_current_is_sqrt2_times_rms():
    spec = _ref_3ph()
    assert math.isclose(lr.line_pk_current_A(spec), math.sqrt(2.0) * 30.0)


def test_fundamental_B_pk_formula():
    """B_pk = √2·V_L_rms / (ω·N·Ae). Sanity check against textbook units."""
    B = lr.fundamental_B_pk_T(N=30, V_L_rms=11.0, Ae_mm2=1000.0, f_line_Hz=60.0)
    expected = math.sqrt(2.0) * 11.0 / (2.0 * math.pi * 60.0 * 30.0 * 1e-3)
    assert math.isclose(B, expected, rel_tol=1e-6)


def test_required_inductance_uH_matches_mH():
    """The engine reuses required_inductance_uH; it must be 1000× the mH version."""
    spec = _ref_3ph()
    assert math.isclose(
        lr.required_inductance_uH(spec),
        lr.required_inductance_mH(spec) * 1000.0,
    )


# ---------------------------------------------------------------------------
# End-to-end through the design engine
# ---------------------------------------------------------------------------
def test_engine_design_runs_for_line_reactor():
    """A line-reactor spec must run through the engine without raising and
    populate the new line-reactor fields in DesignResult."""
    from pfc_inductor.data_loader import find_material, load_cores, load_materials, load_wires
    from pfc_inductor.design import design

    mats = load_materials()
    cores = load_cores()
    wires = load_wires()

    # Use one of the silicon-steel materials shipped with the topology
    try:
        m = find_material(mats, "akarc-m19_050")
    except KeyError:
        pytest.skip("akarc-m19_050 not in DB (curated set not refreshed)")
    candidate_cores = [c for c in cores if c.default_material_id == "akarc-m19_050"]
    if not candidate_cores:
        pytest.skip("no cores tied to akarc-m19_050")
    core = sorted(candidate_cores, key=lambda c: c.Ve_mm3)[-1]
    wire = next(w for w in wires if w.id == "AWG10")

    spec = Spec(
        topology="line_reactor", n_phases=3,
        Vin_nom_Vrms=380.0, I_rated_Arms=30.0,
        pct_impedance=5.0, f_line_Hz=60.0,
    )
    res = design(spec, core, wire, m)

    assert res.L_required_uH > 0
    assert res.N_turns > 0
    assert res.pct_impedance_actual is not None
    assert res.voltage_drop_pct is not None
    assert res.thd_estimate_pct is not None
    # No HF ripple by construction
    assert res.I_ripple_pk_pk_A == 0.0
    assert res.losses.P_cu_ac_W == 0.0


def test_engine_skips_boost_validation_for_line_reactor():
    """Setting topology=line_reactor must not trigger the boost Vout>Vin
    invariant — Vout is irrelevant here."""
    spec = Spec(
        topology="line_reactor",
        Vin_nom_Vrms=380.0, n_phases=3,
        I_rated_Arms=30.0, pct_impedance=5.0,
        Vout_V=100.0,  # would fail the boost invariant; should be ignored
    )
    assert spec.topology == "line_reactor"


# ---------------------------------------------------------------------------
# Waveform + harmonic spectrum
# ---------------------------------------------------------------------------
def test_harmonic_amplitudes_3ph_match_textbook():
    """3-phase 6-pulse: only orders 6k±1 are non-zero (5, 7, 11, 13, ...).

    With small µ the magnitudes converge to the textbook 100, 20, 14.3,
    9.1, 7.7 (Mohan eq. 5-66).
    """
    spec = Spec(topology="line_reactor", n_phases=3, Vin_nom_Vrms=380,
                I_rated_Arms=30, pct_impedance=0.5, f_line_Hz=60)
    L_mH = lr.required_inductance_mH(spec)
    p = lr.harmonic_amplitudes_pct(spec, L_mH)
    # Triplens must be near-zero (small leakage from FFT alignment)
    for h in (3, 9, 15):
        assert p[h - 1] < 1.0, f"triplen h={h} should be ~0, got {p[h-1]}"
    # Even harmonics zero
    for h in (2, 4, 6, 8, 10, 12, 14):
        assert p[h - 1] < 1.0
    # 5/7/11/13 within ±2 pp of textbook
    assert p[0] == 100.0
    assert abs(p[4] - 20.0) < 2.0
    assert abs(p[6] - 14.3) < 2.0
    assert abs(p[10] - 9.1) < 2.0
    assert abs(p[12] - 7.7) < 2.0


def test_harmonic_amplitudes_1ph_high_third_for_cap_dc_link():
    """1-phase cap-DC-link drives have a strong 3rd harmonic (≥50% of
    fundamental at 5%Z, ≥70% at 1.5%Z) — characteristic of pulse-shaped
    line current. Confirms we model cap-DC-link, not the textbook
    'infinite DC inductor' idealisation that gives 1/n harmonics.
    """
    for pct_z, min_third in [(1.5, 70.0), (3.0, 60.0), (5.0, 50.0)]:
        spec = Spec(topology="line_reactor", n_phases=1, Vin_nom_Vrms=220,
                    I_rated_Arms=1.0, pct_impedance=pct_z, f_line_Hz=50)
        L_mH = lr.required_inductance_mH(spec)
        p = lr.harmonic_amplitudes_pct(spec, L_mH)
        assert p[0] == 100.0
        assert p[2] >= min_third, (
            f"%Z={pct_z}: h=3 = {p[2]:.1f}, expected ≥ {min_third}"
        )


def test_harmonic_higher_z_reduces_low_harmonics_1ph():
    """Bigger reactor → wider conduction window → lower 3rd harmonic."""
    low_z = Spec(topology="line_reactor", n_phases=1, Vin_nom_Vrms=220,
                 I_rated_Arms=1.0, pct_impedance=1.5, f_line_Hz=50)
    high_z = Spec(topology="line_reactor", n_phases=1, Vin_nom_Vrms=220,
                  I_rated_Arms=1.0, pct_impedance=8.0, f_line_Hz=50)
    p_low = lr.harmonic_amplitudes_pct(low_z, lr.required_inductance_mH(low_z))
    p_high = lr.harmonic_amplitudes_pct(high_z, lr.required_inductance_mH(high_z))
    assert p_high[2] < p_low[2]   # h=3 drops
    assert p_high[4] < p_low[4]   # h=5 drops


def test_waveform_rms_equals_rated_current():
    spec = _ref_3ph()
    L_mH = lr.required_inductance_mH(spec)
    t, i = lr.line_current_waveform(spec, L_mH, n_cycles=4, n_points=4000)
    rms = float(np.sqrt(np.mean(i * i)))
    assert math.isclose(rms, spec.I_rated_Arms, rel_tol=1e-3)


def test_waveform_period_matches_line_frequency():
    spec = _ref_3ph()
    L_mH = lr.required_inductance_mH(spec)
    t, i = lr.line_current_waveform(spec, L_mH, n_cycles=2, n_points=2000)
    expected_T = 2.0 / spec.f_line_Hz
    assert math.isclose(t[-1] + (t[1] - t[0]), expected_T, rel_tol=1e-6)


def test_fft_round_trip_recovers_input_harmonics():
    """Building i(t) from harmonics then FFT'ing it should give back the
    same harmonic table within numerical precision."""
    spec = _ref_3ph()
    L_mH = lr.required_inductance_mH(spec)
    t, i = lr.line_current_waveform(spec, L_mH, n_cycles=10, n_points=10000)
    n, pct_fft, _thd = lr.harmonic_spectrum(t, i, f_line_Hz=60)
    pct_an = lr.harmonic_amplitudes_pct(spec, L_mH, n_harmonics=15)
    # Compare 1, 5, 7, 11, 13 — the dominant content
    for h in (1, 5, 7, 11, 13):
        assert abs(pct_fft[h - 1] - pct_an[h - 1]) < 0.5


# Numpy is needed by the tests above
import numpy as np  # noqa: E402
