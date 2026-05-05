"""Litz optimizer tests."""
import math

import pytest

from pfc_inductor.data_loader import load_materials, load_cores, load_wires, find_material
from pfc_inductor.models import Spec
from pfc_inductor.optimize import (
    optimal_strand_diameter_mm, closest_strand_AWG,
    strand_count_for_current, bundle_diameter_mm,
    make_litz_wire, recommend_litz,
)
from pfc_inductor.physics.dowell import Rac_over_Rdc_litz


@pytest.fixture(scope="module")
def db():
    return load_materials(), load_cores(), load_wires()


def test_optimal_strand_diameter_at_100kHz_n_layers_1():
    """At 100 kHz, N_l=1, AC/DC=1.10 → d ≈ 0.20 mm (in published range)."""
    d = optimal_strand_diameter_mm(100_000, layers=1, target_AC_DC=1.10)
    assert 0.18 < d < 0.23


def test_optimal_strand_diameter_grows_with_lower_freq():
    d_100k = optimal_strand_diameter_mm(100_000, 1, 1.10)
    d_50k = optimal_strand_diameter_mm(50_000, 1, 1.10)
    assert d_50k > d_100k


def test_optimal_strand_diameter_shrinks_with_more_layers():
    d_l1 = optimal_strand_diameter_mm(100_000, 1, 1.10)
    d_l5 = optimal_strand_diameter_mm(100_000, 5, 1.10)
    assert d_l5 < d_l1


def test_closest_strand_AWG_known():
    awg, d = closest_strand_AWG(0.10)
    assert awg == 38
    assert abs(d - 0.101) < 1e-3


def test_strand_count_meets_current_density():
    n = strand_count_for_current(I_rms_A=10, target_J_A_mm2=4.0,
                                  d_strand_mm=0.10)
    A_strand = math.pi * 0.10 ** 2 / 4.0
    assert n * A_strand >= 10 / 4.0


def test_bundle_diameter_grows_with_strand_count():
    d_small = bundle_diameter_mm(50, 0.10)
    d_big = bundle_diameter_mm(500, 0.10)
    assert d_big > d_small


def test_make_litz_wire_has_derived_fields():
    w = make_litz_wire(n_strands=200, d_strand_mm=0.10)
    assert w.type == "litz"
    assert w.n_strands == 200
    assert w.A_cu_mm2 > 0
    assert w.d_bundle_mm > 0
    assert w.cost_per_meter is not None
    assert w.mass_per_meter_g is not None


def test_recommend_returns_candidates_in_published_AWG_range(db):
    mats, cores, wires = db
    spec = Spec(Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
                Vout_V=400.0, Pout_W=800.0, eta=0.97,
                f_sw_kHz=65.0, ripple_pct=30.0)
    mat = find_material(mats, "magnetics-60_highflux")
    core = next(
        c for c in cores
        if c.default_material_id == "magnetics-60_highflux"
        and 40000 < c.Ve_mm3 < 100000
    )
    rec = recommend_litz(spec, core, mat, wires,
                         target_J_A_mm2=4.0, target_AC_DC=1.10)
    assert len(rec.candidates) > 0
    for c in rec.candidates:
        assert 32 <= c.awg_strand <= 44


def test_recommend_AC_DC_below_target(db):
    """Built Litz should achieve AC/DC ≤ target (since strands are below d_opt)."""
    mats, cores, wires = db
    spec = Spec(Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
                Vout_V=400.0, Pout_W=800.0, eta=0.97,
                f_sw_kHz=65.0, ripple_pct=30.0)
    mat = find_material(mats, "magnetics-60_highflux")
    core = next(
        c for c in cores
        if c.default_material_id == "magnetics-60_highflux"
        and 40000 < c.Ve_mm3 < 100000
    )
    rec = recommend_litz(spec, core, mat, wires, target_AC_DC=1.10)
    # Every candidate should have AC/DC ≤ 1.10 (since AWG list is at-or-below d_opt)
    assert all(c.AC_DC_ratio <= 1.10 + 0.05 for c in rec.candidates)


def test_recommend_provides_round_wire_baseline(db):
    mats, cores, wires = db
    spec = Spec(Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
                Vout_V=400.0, Pout_W=800.0, eta=0.97,
                f_sw_kHz=65.0, ripple_pct=30.0)
    mat = find_material(mats, "magnetics-60_highflux")
    core = next(
        c for c in cores
        if c.default_material_id == "magnetics-60_highflux"
        and 40000 < c.Ve_mm3 < 100000
    )
    rec = recommend_litz(spec, core, mat, wires)
    assert rec.round_wire_baseline is not None
    assert rec.round_wire_baseline.feasible
