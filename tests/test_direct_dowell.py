"""Tests for the Dowell AC-resistance helper — Phase 2.8.

Validates against textbook formulas and analytical limits.
"""

from __future__ import annotations

import math

import pytest


def test_skin_depth_textbook_at_130khz():
    """Copper skin depth at 130 kHz, 20°C: ≈ 181 μm."""
    from pfc_inductor.fea.direct.physics.dowell_ac import skin_depth_m

    delta_um = skin_depth_m(frequency_Hz=130_000.0) * 1e6
    assert 175 < delta_um < 190


def test_dowell_fr_single_layer_skin_only():
    """For m=1 the proximity term vanishes and F_R = ξ · Re_1(ξ).
    At very high ξ this approaches ξ asymptotically."""
    from pfc_inductor.fea.direct.physics.dowell_ac import dowell_fr

    # AWG18 (1.024 mm) at 500 kHz, m=1
    F_R, xi = dowell_fr(
        wire_diameter_m=1.024e-3,
        n_layers=1,
        frequency_Hz=500_000.0,
    )
    # ξ ≈ 6.6 at 500 kHz on AWG18 → F_R approaches ξ
    assert 1.0 < F_R
    assert F_R < xi * 1.5  # upper bound from skin term


def test_dowell_fr_low_frequency_limit():
    """At very low frequency, ξ → 0 and F_R → 1.0 (no AC loss).
    At 10 Hz with AWG18, ξ ≈ 0.03 → F_R essentially 1.0 (the
    proximity term scales as ξ⁵ at small ξ)."""
    from pfc_inductor.fea.direct.physics.dowell_ac import dowell_fr

    F_R, xi = dowell_fr(
        wire_diameter_m=1.024e-3,
        n_layers=3,
        frequency_Hz=10.0,  # 10 Hz
    )
    assert xi < 0.1  # well below 1
    # F_R should be very close to 1.0 at this low frequency
    assert math.isclose(F_R, 1.0, abs_tol=0.01)


def test_dowell_fr_layer_dependence():
    """F_R should grow strongly with layer count (proximity effect)."""
    from pfc_inductor.fea.direct.physics.dowell_ac import dowell_fr

    F_R_1, _ = dowell_fr(wire_diameter_m=1.024e-3, n_layers=1, frequency_Hz=130_000.0)
    F_R_3, _ = dowell_fr(wire_diameter_m=1.024e-3, n_layers=3, frequency_Hz=130_000.0)
    F_R_5, _ = dowell_fr(wire_diameter_m=1.024e-3, n_layers=5, frequency_Hz=130_000.0)
    # Layer-3 is significantly higher than layer-1; layer-5 even more
    assert F_R_3 > F_R_1 * 3
    assert F_R_5 > F_R_3 * 1.5


def test_dowell_fr_validates_inputs():
    from pfc_inductor.fea.direct.physics.dowell_ac import dowell_fr

    with pytest.raises(ValueError):
        dowell_fr(wire_diameter_m=0.0, n_layers=1, frequency_Hz=100_000.0)
    with pytest.raises(ValueError):
        dowell_fr(wire_diameter_m=1e-3, n_layers=0, frequency_Hz=100_000.0)
    with pytest.raises(ValueError):
        dowell_fr(wire_diameter_m=1e-3, n_layers=1, frequency_Hz=-100.0)


def test_evaluate_ac_resistance_round_trip():
    """End-to-end: R_dc reasonable, F_R applied, T-correction works."""
    from pfc_inductor.fea.direct.physics.dowell_ac import evaluate_ac_resistance

    out_20 = evaluate_ac_resistance(
        n_turns=39,
        wire_diameter_m=1.024e-3,
        n_layers=3,
        mlt_mm=80.0,
        frequency_Hz=130_000.0,
        T_winding_C=20.0,
    )
    out_100 = evaluate_ac_resistance(
        n_turns=39,
        wire_diameter_m=1.024e-3,
        n_layers=3,
        mlt_mm=80.0,
        frequency_Hz=130_000.0,
        T_winding_C=100.0,
    )
    # R_dc scales with copper resistivity (~1.31× at 100 vs 20)
    assert math.isclose(out_100.R_dc_mOhm / out_20.R_dc_mOhm, 1.3144, rel_tol=5e-3)
    # R_ac > R_dc (F_R ≥ 1)
    assert out_20.R_ac_mOhm > out_20.R_dc_mOhm
    # F_R coherent
    assert math.isclose(out_20.R_ac_mOhm / out_20.R_dc_mOhm, out_20.F_R, rel_tol=1e-6)


def test_evaluate_ac_resistance_textbook_pfc_inductor():
    """Reference design from Texas Instruments app note:
    AWG18, N=40, 130 kHz, 3 layers, MLT=80 mm at 70°C.
    Expected R_dc ≈ 70 mΩ, R_ac ≈ 1.5-2 Ω.
    """
    from pfc_inductor.fea.direct.physics.dowell_ac import evaluate_ac_resistance

    out = evaluate_ac_resistance(
        n_turns=40,
        wire_diameter_m=1.024e-3,
        n_layers=3,
        mlt_mm=80.0,
        frequency_Hz=130_000.0,
        T_winding_C=70.0,
    )
    # R_dc reasonable for ~3.2 m of AWG18 at 70°C
    assert 60 < out.R_dc_mOhm < 100
    # R_ac in the 1.5-2 Ω range
    assert 1500 < out.R_ac_mOhm < 2200
