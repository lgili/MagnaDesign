"""End-to-end design tests (regression: numbers should be in physically realistic range)."""
import pytest

from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.design import design
from pfc_inductor.models import Spec


@pytest.fixture
def db():
    return load_materials(), load_cores(), load_wires()


def test_800W_design_with_high_flux_60(db):
    """800W boost PFC, Magnetics High Flux 60u, AWG14, mid-size toroid.

    Expected (within tolerances):
    - L_required ~370 µH at low line worst case
    - I_pk_line ~14 A
    - B_pk well below Bsat
    - Total losses < 25 W (< 3% of P_out)
    """
    materials, cores, wires = db
    spec = Spec(
        Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
        Vout_V=400.0, Pout_W=800.0, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
        T_amb_C=40.0, T_max_C=100.0, Ku_max=0.40, Bsat_margin=0.20,
    )
    mat = find_material(materials, "magnetics-60_highflux")
    core = next(
        c for c in cores
        if c.default_material_id == "magnetics-60_highflux"
        and 40000 < c.Ve_mm3 < 100000
    )
    wire = next(w for w in wires if w.id == "AWG14")
    r = design(spec, core, wire, mat)

    assert 350 < r.L_required_uH < 400
    assert 13.0 < r.I_line_pk_A < 14.5
    assert 9.0 < r.I_line_rms_A < 10.5
    assert r.L_actual_uH >= r.L_required_uH * 0.99
    assert r.B_pk_T < r.B_sat_limit_T
    assert r.losses.P_total_W < 30, f"Total loss too high: {r.losses.P_total_W:.1f} W"


def test_design_warns_on_oversaturation(db):
    """Force a too-small core: expect saturation warning."""
    materials, cores, wires = db
    spec = Spec(
        Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
        Vout_V=400.0, Pout_W=2000.0, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
        T_amb_C=40.0, T_max_C=100.0, Ku_max=0.40, Bsat_margin=0.20,
    )
    mat = find_material(materials, "magnetics-60_highflux")
    # Pick a tiny core deliberately
    small = sorted(
        [c for c in cores if c.default_material_id == "magnetics-60_highflux"],
        key=lambda c: c.Ve_mm3,
    )[0]
    wire = next(w for w in wires if w.id == "AWG18")
    r = design(spec, small, wire, mat)
    # Either thermal blows up, saturation hits, or window utilization exceeds limit
    assert r.warnings, "Expected at least one warning for under-sized design"


def test_passive_choke_runs(db):
    """Passive line choke does not crash and gives sensible numbers."""
    materials, cores, wires = db
    spec = Spec(
        topology="passive_choke",
        Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
        Vout_V=400.0, Pout_W=400.0, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
        T_amb_C=40.0, T_max_C=100.0, Ku_max=0.40, Bsat_margin=0.20,
    )
    mat = find_material(materials, "magnetics-60_highflux")
    core = next(
        c for c in cores
        if c.default_material_id == "magnetics-60_highflux"
        and c.Ve_mm3 > 50000
    )
    wire = next(w for w in wires if w.id == "AWG14")
    r = design(spec, core, wire, mat)
    assert r.L_required_uH > 0
    assert r.N_turns >= 1
