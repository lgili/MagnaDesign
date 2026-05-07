"""NonlinearInductor — unit + property tests.

Validates that the Tier-2 inductor wrapper agrees with the
analytical engine's `physics.rolloff` at every operating point.
Drift between Tier 1 and Tier 2 due to a duplicated rolloff
implementation is the most likely failure mode of Phase B; these
tests close that door.
"""
from __future__ import annotations

import numpy as np
import pytest

from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
)
from pfc_inductor.physics import rolloff as rf
from pfc_inductor.simulate import NonlinearInductor


@pytest.fixture(scope="module")
def db():
    return {
        "materials": load_materials(),
        "cores": load_cores(),
    }


def _ref_inductor(db, *, N: int = 45) -> NonlinearInductor:
    material = find_material(db["materials"], "magnetics-60_highflux")
    core = next(
        c for c in db["cores"]
        if c.default_material_id == material.id and 40_000 < c.Ve_mm3 < 100_000
    )
    return NonlinearInductor(core=core, material=material, N=N)


# ─── L at zero current matches nominal AL inductance ────────────

def test_L_at_zero_current_matches_N_squared_AL(db):
    ind = _ref_inductor(db, N=45)
    L_uH = ind.L_uH(0.0)
    expected = rf.inductance_uH(45, ind.core.AL_nH, mu_fraction=1.0)
    assert L_uH == pytest.approx(expected, rel=1e-12)


# ─── L decreases (or stays constant) with bias ─────────────────

def test_L_is_monotonically_non_increasing_with_bias(db):
    ind = _ref_inductor(db, N=45)
    currents = np.linspace(0.0, 30.0, 31)
    L_arr = ind.L_H_array(currents)
    diffs = np.diff(L_arr)
    # Allow a sliver of float noise; monotonic non-increasing.
    assert (diffs <= 1e-12).all(), f"L not monotone: {diffs[diffs > 0]}"


# ─── L_H scalar and L_H_array agree ─────────────────────────────

def test_scalar_and_vector_L_agree(db):
    ind = _ref_inductor(db, N=45)
    currents = np.array([0.0, 1.0, 5.0, 10.0, 14.0, 20.0])
    L_scalar = np.array([ind.L_H(float(i)) for i in currents])
    L_vector = ind.L_H_array(currents)
    np.testing.assert_allclose(L_scalar, L_vector, rtol=1e-12)


# ─── B = L · i / (N · Ae) sanity ───────────────────────────────

def test_B_matches_L_times_I_over_N_Ae(db):
    ind = _ref_inductor(db, N=45)
    i_A = 14.0
    L_H = ind.L_H(i_A)
    Ae_m2 = ind.core.Ae_mm2 * 1e-6
    expected = L_H * i_A / (ind.N * Ae_m2)
    assert ind.B_T(i_A) == pytest.approx(expected, rel=1e-12)


# ─── Phase-1 / Phase-2 alignment: same μ at the same H ─────────

def test_mu_pct_matches_physics_rolloff(db):
    """The Tier-2 wrapper must call into `physics.rolloff` directly
    so Tier 1 and Tier 2 cannot drift on calibrated curves."""
    ind = _ref_inductor(db, N=45)
    for i_A in (1.0, 5.0, 14.0, 20.0):
        H_Oe = ind.H_Oe(i_A)
        mu_t2 = ind.mu_pct(i_A)
        mu_t1 = rf.mu_pct(ind.material, H_Oe)
        assert mu_t2 == pytest.approx(mu_t1, rel=1e-12)


# ─── Rolloff actually fires for a strong-rolloff material ──────

def test_strong_rolloff_material_drops_L_at_high_bias(db):
    """High Flux 125µ has aggressive rolloff above ~50 Oe — confirm
    the curve fires when the bias is pushed."""
    materials = db["materials"]
    cores = db["cores"]
    # `magnetics-125_highflux` ships the highest-mu Magnetics High
    # Flux variant; its rolloff coefficient `b` is ~2.4× that of
    # the 60-µ variant, so deep rolloff is guaranteed by H ≈ 100 Oe.
    high_125 = find_material(materials, "magnetics-125_highflux")
    core = next(
        c for c in cores
        if c.default_material_id == high_125.id and 40_000 < c.Ve_mm3 < 100_000
    )
    ind = NonlinearInductor(core=core, material=high_125, N=80)

    L_low = ind.L_H(0.5)         # near zero bias
    L_high = ind.L_H(20.0)       # well into the rolloff knee
    drop = (L_low - L_high) / L_low
    assert drop > 0.10, (
        f"expected meaningful rolloff at high bias, got drop={drop:.1%}"
    )


# ─── Saturation envelope helpers ───────────────────────────────

def test_is_saturated_uses_temperature_corrected_Bsat(db):
    ind = _ref_inductor(db, N=45)
    # At 25 °C, Bsat is the higher anchor; engineering margin reduces it.
    Bsat_25 = ind.material.Bsat_25C_T
    margin = 0.20
    assert ind.is_saturated(Bsat_25 * (1.0 - margin) - 0.001, margin=margin) is False
    assert ind.is_saturated(Bsat_25 * (1.0 - margin) + 0.001, margin=margin) is True


def test_Bsat_T_clamps_outside_anchor_range(db):
    ind = _ref_inductor(db, N=45)
    ind.T_C = 200.0  # well above the 100 °C anchor
    # Must not extrapolate dangerously; clamps to the 100 °C anchor.
    assert ind.Bsat_T() == pytest.approx(ind.material.Bsat_100C_T, rel=1e-12)
    ind.T_C = -40.0
    # Below 25 °C clamps to the 25 °C anchor.
    assert ind.Bsat_T() == pytest.approx(ind.material.Bsat_25C_T, rel=1e-12)


# ─── from_design_point construction sugar ──────────────────────

def test_from_design_point_uses_winding_temperature(db):
    material = find_material(db["materials"], "magnetics-60_highflux")
    core = next(
        c for c in db["cores"]
        if c.default_material_id == material.id and 40_000 < c.Ve_mm3 < 100_000
    )
    ind = NonlinearInductor.from_design_point(core, material, N=45, T_C=80.0)
    assert ind.T_C == 80.0
    assert ind.N == 45
