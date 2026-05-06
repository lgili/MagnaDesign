"""Cost model tests."""
import pytest

from pfc_inductor.data_loader import find_material, load_cores, load_materials, load_wires
from pfc_inductor.models import Spec
from pfc_inductor.optimize import sweep
from pfc_inductor.optimize.sweep import rank
from pfc_inductor.physics import (
    CU_DENSITY_KG_M3,
    estimate_cost,
    wire_length_m,
    wire_mass_per_meter_g,
)


@pytest.fixture(scope="module")
def db():
    return load_materials(), load_cores(), load_wires()


@pytest.fixture(scope="module")
def db_curated():
    """Curated-only wires for sweeps (catalog grew the wire DB ~30×)."""
    from pfc_inductor.data_loader import load_curated_ids
    mats = load_materials()
    cores = load_cores()
    wires = load_wires()
    cur = load_curated_ids("wires")
    if cur:
        wires = [w for w in wires if w.id in cur]
    return mats, cores, wires


def test_wire_length_formula():
    assert abs(wire_length_m(50, 100.0) - 5.0) < 1e-9
    assert wire_length_m(0, 100.0) == 0.0


def test_wire_mass_density(db):
    """AWG14 (A=2.08 mm²) should be ~18.6 g/m by physics."""
    _, _, wires = db
    awg14 = next(w for w in wires if w.id == "AWG14")
    expected = 2.08 * 1e-6 * CU_DENSITY_KG_M3 * 1000.0
    assert abs(wire_mass_per_meter_g(awg14) - expected) / expected < 0.05


def test_estimate_returns_none_when_costs_absent(db):
    mats, cores, wires = db
    mat = find_material(mats, "magnetics-60_highflux").model_copy(update={"cost_per_kg": None})
    core = next(c for c in cores if c.default_material_id == "magnetics-60_highflux")
    core_no_cost = core.model_copy(update={"cost_per_piece": None})
    wire = next(w for w in wires if w.id == "AWG14").model_copy(update={"cost_per_meter": None})
    assert estimate_cost(core_no_cost, wire, mat, N_turns=50) is None


def test_estimate_uses_per_piece_when_available(db):
    mats, cores, wires = db
    mat = find_material(mats, "magnetics-60_highflux")
    core = next(c for c in cores if c.default_material_id == "magnetics-60_highflux")
    core2 = core.model_copy(update={"cost_per_piece": 9.99})
    wire = next(w for w in wires if w.id == "AWG14")
    cost = estimate_cost(core2, wire, mat, N_turns=10)
    assert cost is not None
    assert abs(cost.core_cost - 9.99) < 1e-6


def test_estimate_wire_proportional_to_N_and_MLT(db):
    mats, cores, wires = db
    mat = find_material(mats, "magnetics-60_highflux")
    core = next(c for c in cores if c.default_material_id == "magnetics-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    c1 = estimate_cost(core, wire, mat, N_turns=50)
    c2 = estimate_cost(core, wire, mat, N_turns=100)
    # Wire portion doubles, core stays the same
    assert abs(c2.wire_cost - 2 * c1.wire_cost) / c1.wire_cost < 1e-6
    assert abs(c2.core_cost - c1.core_cost) < 1e-6


def test_demo_costs_loaded_for_curated_db(db):
    """Curated entries ship with demo costs; OpenMagnetics catalog rows don't.

    The catalog is upstream data we don't own and have no pricing for, so
    the cost assertion is scoped to ids that come from the curated set.
    """
    from pfc_inductor.data_loader import load_curated_ids

    mats, _, wires = db
    curated_mats = load_curated_ids("materials")
    curated_wires = load_curated_ids("wires")
    for m in mats:
        if m.id in curated_mats:
            assert m.cost_per_kg is not None, f"curated material {m.id} missing cost"
    for w in wires:
        if w.id in curated_wires:
            assert w.cost_per_meter is not None, f"curated wire {w.id} missing cost"


def test_optimizer_rank_by_cost(db_curated):
    mats, cores, wires = db_curated
    spec = Spec(Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
                Vout_V=400.0, Pout_W=800.0, eta=0.97,
                f_sw_kHz=65.0, ripple_pct=30.0)
    results = sweep(spec, cores, wires, mats, material_id="magnetics-60_highflux")
    feasible = [r for r in results if r.feasible]
    by_cost = rank(feasible, by="cost")
    costs = [r.total_cost for r in by_cost if r.total_cost is not None]
    for a, b in zip(costs, costs[1:], strict=False):
        assert a <= b + 1e-6


def test_optimizer_score_with_cost(db_curated):
    mats, cores, wires = db_curated
    spec = Spec(Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
                Vout_V=400.0, Pout_W=800.0, eta=0.97,
                f_sw_kHz=65.0, ripple_pct=30.0)
    results = sweep(spec, cores, wires, mats, material_id="magnetics-60_highflux")
    feasible = [r for r in results if r.feasible]
    ranked = rank(feasible, by="score_with_cost")
    assert len(ranked) == len(feasible)
