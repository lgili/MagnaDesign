"""Core-loss model tests including iGSE Jensen factor."""

import numpy as np

from pfc_inductor.data_loader import find_material, load_materials
from pfc_inductor.physics.core_loss import (
    core_loss_W_pfc,
    core_loss_W_pfc_ripple_iGSE,
    core_loss_W_sinusoidal,
    steinmetz_volumetric_mWcm3,
)


def test_steinmetz_anchored_at_reference_point():
    """At (f_ref, B_ref), Pv must equal Pv_ref exactly (modulo float epsilon)."""
    mats = load_materials()
    for m in mats[:10]:
        s = m.steinmetz
        Pv = steinmetz_volumetric_mWcm3(m, s.f_ref_kHz, s.B_ref_mT)
        assert abs(Pv - s.Pv_ref_mWcm3) < 0.01 * s.Pv_ref_mWcm3


def test_steinmetz_zero_below_f_min():
    mats = load_materials()
    m = mats[0]
    Pv = steinmetz_volumetric_mWcm3(m, m.steinmetz.f_min_kHz / 2, 100.0)
    assert Pv == 0.0


def test_iGSE_matches_naive_for_constant_dB():
    """If ΔB is constant over the line cycle, iGSE must equal Steinmetz at that ΔB/2."""
    mats = load_materials()
    mat = find_material(mats, "magnetics-60_highflux")
    delta_B_const = np.full(200, 0.04)  # 40 mT pp constant
    P_iGSE = core_loss_W_pfc_ripple_iGSE(mat, 65.0, delta_B_const, Ve_mm3=50000)
    P_naive = core_loss_W_sinusoidal(mat, 65.0, 0.02, Ve_mm3=50000)
    assert abs(P_iGSE - P_naive) / P_naive < 1e-3


def test_iGSE_higher_than_naive_for_varying_dB_jensen():
    """For β > 1 and varying ΔB(t), <ΔB^β> > <ΔB>^β (Jensen). iGSE >= naive."""
    mats = load_materials()
    mat = find_material(mats, "magnetics-60_highflux")
    t = np.linspace(0, 1, 200)
    delta_B = 0.06 * np.sin(np.pi * t) ** 1.0  # half-sine envelope
    P_iGSE = core_loss_W_pfc_ripple_iGSE(mat, 65.0, delta_B, Ve_mm3=50000)
    P_naive = core_loss_W_sinusoidal(mat, 65.0, float(delta_B.mean()) / 2, Ve_mm3=50000)
    assert P_iGSE > P_naive  # Jensen
    assert P_iGSE / P_naive >= 1.0
    assert P_iGSE / P_naive < 3.0  # sanity ceiling


def test_core_loss_pfc_dispatches_iGSE():
    """When delta_B_pp_T_array is given, the function uses iGSE path."""
    mats = load_materials()
    mat = find_material(mats, "magnetics-60_highflux")
    arr = np.full(100, 0.05)
    _, P_with = core_loss_W_pfc(mat, 50, 65.0, 0.3, 0.05, 50000, delta_B_pp_T_array=arr)
    _, P_without = core_loss_W_pfc(mat, 50, 65.0, 0.3, 0.05, 50000)
    # With constant array, both paths must match
    assert abs(P_with - P_without) / P_without < 1e-3
