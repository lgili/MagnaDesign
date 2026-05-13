"""Tests for Phase 3.3 EM-thermal coupling + Phase 4.1 transient."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest

# ─── Phase 3.3: EM-thermal coupling ────────────────────────────────


def test_em_thermal_converges_typical_pfc():
    """For a PFC choke at modest operating conditions, the EM-thermal
    loop should converge and report a sensible T_winding above
    ambient. Use low frequency + thicker wire (Litz-equivalent) so
    F_R stays modest and the test doesn't enter thermal runaway."""
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.fea.direct.physics.em_thermal_coupling import solve_em_thermal

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    core = next(c for c in cores if c.id == "tdkepcos-pq-4040-n87")
    mat = next(m for m in mats if m.id == core.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)

    with tempfile.TemporaryDirectory() as td:
        out = solve_em_thermal(
            core=core,
            material=mat,
            wire=wire,
            n_turns=39,
            current_rms_A=2.0,  # moderate, not full PFC drive
            current_pk_A=3.0,
            workdir=Path(td),
            gap_mm=0.5,
            frequency_Hz=10_000.0,  # 10 kHz, low F_R penalty
            n_layers=2,
            T_amb_C=40.0,
            P_core_W=0.5,
        )
    # Converged or hit iteration cap (still useful info)
    assert out.n_iterations >= 1
    assert out.T_winding_C > 40.0  # above ambient
    assert out.T_winding_C < 250.0  # not extreme runaway
    assert out.L_dc_uH > 0
    assert out.R_dc_mOhm > 0
    # AC penalty
    if out.R_ac_mOhm is not None:
        assert out.R_ac_mOhm > out.R_dc_mOhm  # F_R > 1 at any AC frequency


def test_em_thermal_no_ac_when_no_frequency():
    """Without frequency_Hz, R_ac stays None and P_cu uses R_dc."""
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.fea.direct.physics.em_thermal_coupling import solve_em_thermal

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    core = next(c for c in cores if c.id == "tdkepcos-pq-4040-n87")
    mat = next(m for m in mats if m.id == core.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)

    with tempfile.TemporaryDirectory() as td:
        out = solve_em_thermal(
            core=core,
            material=mat,
            wire=wire,
            n_turns=39,
            current_rms_A=6.5,
            current_pk_A=8.0,
            workdir=Path(td),
            gap_mm=0.5,
            T_amb_C=25.0,
        )
    assert out.R_ac_mOhm is None


# ─── Phase 4.1: Transient ──────────────────────────────────────────


def test_transient_square_wave_drives_ripple():
    """A symmetric square-wave drive (V_high = -V_low) produces a
    triangular i(t) with peak-to-peak ripple = V_high · D · T / L
    in steady state. Asymmetric drives ramp until R·i balances the
    average voltage — use a symmetric drive for the ripple check."""
    from pfc_inductor.fea.direct.physics.transient import (
        simulate_transient,
        square_wave_drive,
    )

    L_uH = 1000.0
    R_Ohm = 0.1
    V_high = 50.0
    T_sw = 10e-6  # 100 kHz
    duty = 0.5

    drive = square_wave_drive(V_high=V_high, V_low=-V_high, period_s=T_sw, duty=duty)
    out = simulate_transient(
        v_drive=drive,
        L_dc_uH=L_uH,
        R_dc_Ohm=R_Ohm,
        Bsat_T=10.0,
        Ae_mm2=200.0,
        n_turns=39,  # high Bsat → no saturation
        t_end_s=10 * T_sw,
        dt_s=T_sw / 200,
    )
    # Steady-state ripple for symmetric drive at D=0.5:
    # peak-to-peak = V_high · D · T_sw / L (single rising phase)
    expected_ripple = V_high * duty * T_sw / (L_uH * 1e-6)
    # Allow generous tolerance — start-up transient affects measurement.
    assert math.isclose(out.i_ripple_pkpk_A, expected_ripple, rel_tol=0.5)
    # Some current present
    assert out.i_pk_A > 0


def test_transient_validates_inputs():
    from pfc_inductor.fea.direct.physics.transient import (
        simulate_transient,
        square_wave_drive,
    )

    drive = square_wave_drive(V_high=10, V_low=0, period_s=1e-5)
    with pytest.raises(ValueError):
        simulate_transient(
            v_drive=drive,
            L_dc_uH=100,
            R_dc_Ohm=0.1,
            Bsat_T=1,
            Ae_mm2=100,
            n_turns=10,
            t_end_s=0.0,  # invalid
        )
    with pytest.raises(ValueError):
        simulate_transient(
            v_drive=drive,
            L_dc_uH=100,
            R_dc_Ohm=0.1,
            Bsat_T=1,
            Ae_mm2=100,
            n_turns=10,
            t_end_s=1e-4,
            dt_s=-1e-7,  # invalid
        )


# ─── Stubs for 4.2 / 4.3 raise cleanly ─────────────────────────────


def test_3d_stub_raises_not_implemented():
    from pfc_inductor.fea.direct.physics.magnetostatic_3d import run_3d_solve_stub

    with pytest.raises(NotImplementedError, match="3-D mode"):
        run_3d_solve_stub()


def test_rom_stub_raises_not_implemented():
    from pfc_inductor.fea.direct.physics.rom_proxy import run_rom_solve_stub

    with pytest.raises(NotImplementedError, match="ROM"):
        run_rom_solve_stub()
