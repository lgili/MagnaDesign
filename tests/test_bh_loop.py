"""B-H loop / anhysteretic curve tests."""
import numpy as np
import pytest

from pfc_inductor.data_loader import find_material, load_cores, load_materials, load_wires
from pfc_inductor.design import design
from pfc_inductor.models import Spec
from pfc_inductor.physics.rolloff import (
    B_anhysteretic_array_T,
    B_anhysteretic_T,
    mu_pct_array,
)
from pfc_inductor.visual import compute_bh_trajectory


@pytest.fixture(scope="module")
def db():
    return load_materials(), load_cores(), load_wires()


def test_B_at_zero_is_zero(db):
    mats, _, _ = db
    for m in mats[:8]:
        assert abs(B_anhysteretic_T(m, 0.0)) < 1e-9


def test_B_grows_monotonically_with_H(db):
    mats, _, _ = db
    m = find_material(mats, "magnetics-60_highflux")
    H_arr = np.linspace(0, 500, 50)
    B = B_anhysteretic_array_T(m, H_arr)
    assert np.all(np.diff(B) >= -1e-6), "B(H) must be non-decreasing"


def test_B_capped_at_Bsat_for_powder(db):
    """Far past saturation, anhysteretic B saturates near Bsat (within +5% headroom)."""
    mats, _, _ = db
    m = find_material(mats, "magnetics-60_highflux")
    B_huge = B_anhysteretic_T(m, 5000.0)
    Bsat = m.Bsat_100C_T
    assert B_huge <= Bsat * 1.06
    assert B_huge >= Bsat * 0.9, f"B_anhysteretic at huge H should approach Bsat, got {B_huge*1000:.0f} mT"


def test_B_linear_for_ferrite(db):
    """Ferrites have no rolloff in our model, so B = mu_0·mu_r·H below Bsat."""
    mats, _, _ = db
    m = find_material(mats, "tdkepcos-n87")
    # Pick H low enough that linear B < Bsat: H ~ 0.5 Oe
    B_low = B_anhysteretic_T(m, 0.5)
    expected = (4 * np.pi * 1e-7) * m.mu_initial * (0.5 / (1.0 / 79.5774715459))
    assert abs(B_low - expected) / expected < 0.02


def test_mu_pct_array_matches_scalar(db):
    """Vectorized mu_pct_array must agree with the scalar mu_pct."""
    from pfc_inductor.physics.rolloff import mu_pct
    mats, _, _ = db
    m = find_material(mats, "magnetics-60_highflux")
    H_arr = [0.1, 10.0, 80.0, 200.0, 500.0]
    arr = mu_pct_array(m, H_arr)
    for h, a in zip(H_arr, arr, strict=False):
        assert abs(a - mu_pct(m, h)) < 1e-9


def test_trajectory_returns_expected_keys(db):
    mats, cores, wires = db
    spec = Spec(Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
                Vout_V=400.0, Pout_W=800.0, eta=0.97,
                f_sw_kHz=65.0, ripple_pct=30.0)
    m = find_material(mats, "magnetics-60_highflux")
    c = next(c for c in cores if c.default_material_id == m.id and 40000 < c.Ve_mm3 < 100000)
    w = next(w for w in wires if w.id == "AWG14")
    r = design(spec, c, w, m)
    tr = compute_bh_trajectory(r, c, m)
    for k in ("H_static_Oe", "B_static_T", "H_envelope_Oe", "B_envelope_T",
              "H_pk_Oe", "B_pk_T", "Bsat_T"):
        assert k in tr, f"Missing key {k} in trajectory result"


def test_trajectory_envelope_matches_design_pk(db):
    """The envelope's peak B should be close to the engine's B_pk_T."""
    mats, cores, wires = db
    spec = Spec(Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
                Vout_V=400.0, Pout_W=800.0, eta=0.97,
                f_sw_kHz=65.0, ripple_pct=30.0)
    m = find_material(mats, "magnetics-60_highflux")
    c = next(c for c in cores if c.default_material_id == m.id and 40000 < c.Ve_mm3 < 100000)
    w = next(w for w in wires if w.id == "AWG14")
    r = design(spec, c, w, m)
    tr = compute_bh_trajectory(r, c, m)
    # Anhysteretic-integral B can deviate from the L·I/(N·Ae) approximation
    # by up to ~30% in the rolloff knee region; just bound it.
    assert 0.5 * r.B_pk_T <= tr["B_pk_T"] <= 1.5 * r.B_pk_T


def test_trajectory_has_ripple_for_boost(db):
    """A boost-CCM design has nonzero HF ripple, so the ripple segment exists."""
    mats, cores, wires = db
    spec = Spec(Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
                Vout_V=400.0, Pout_W=800.0, eta=0.97,
                f_sw_kHz=65.0, ripple_pct=30.0)
    m = find_material(mats, "magnetics-60_highflux")
    c = next(c for c in cores if c.default_material_id == m.id and 40000 < c.Ve_mm3 < 100000)
    w = next(w for w in wires if w.id == "AWG14")
    r = design(spec, c, w, m)
    tr = compute_bh_trajectory(r, c, m)
    assert tr["H_ripple_Oe"] is not None
    assert tr["B_ripple_T"] is not None
    assert tr["H_ripple_Oe"].size > 0
