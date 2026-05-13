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


def test_runner_populates_R_ac_when_frequency_given():
    """``run_direct_fea(frequency_Hz=130_000, n_layers=3)`` returns a
    ``DirectFeaResult`` with ``R_ac_mOhm`` populated and a sensible
    value (much bigger than R_dc due to skin + proximity)."""
    import tempfile
    from pathlib import Path

    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.fea.direct.runner import run_direct_fea

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    core = next(c for c in cores if c.id == "tdkepcos-pq-4040-n87")
    mat = next(m for m in mats if m.id == core.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)

    with tempfile.TemporaryDirectory() as td:
        out = run_direct_fea(
            core=core,
            material=mat,
            wire=wire,
            n_turns=39,
            current_A=8.0,
            workdir=Path(td),
            gap_mm=0.5,
            frequency_Hz=130_000.0,
            n_layers=3,
        )
    assert out.R_ac_mOhm is not None
    # 3-layer AWG18 at 130 kHz: F_R ≈ 20-25 → R_ac ≈ 1.5-2 Ω
    assert 1000 < out.R_ac_mOhm < 3000
    # L_ac is set to ≈ L_dc for this analytical path
    assert out.L_ac_uH is not None
    assert math.isclose(out.L_ac_uH, out.L_dc_uH, rel_tol=1e-6)


def test_runner_skips_R_ac_when_no_frequency():
    """No ``frequency_Hz`` → ``R_ac_mOhm`` stays ``None``."""
    import tempfile
    from pathlib import Path

    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.fea.direct.runner import run_direct_fea

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    core = next(c for c in cores if c.id == "tdkepcos-pq-4040-n87")
    mat = next(m for m in mats if m.id == core.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)

    with tempfile.TemporaryDirectory() as td:
        out = run_direct_fea(
            core=core,
            material=mat,
            wire=wire,
            n_turns=39,
            current_A=8.0,
            workdir=Path(td),
            gap_mm=0.5,
        )
    assert out.R_ac_mOhm is None
    assert out.L_ac_uH is None


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
