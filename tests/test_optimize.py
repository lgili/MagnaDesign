"""Sweep optimizer tests."""
from pfc_inductor.data_loader import (
    load_cores,
    load_curated_ids,
    load_materials,
    load_wires,
)
from pfc_inductor.models import Spec
from pfc_inductor.optimize import pareto_front, sweep
from pfc_inductor.optimize.sweep import rank


def _spec_800W():
    return Spec(
        Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
        Vout_V=400.0, Pout_W=800.0, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
        T_amb_C=40.0, T_max_C=100.0, Ku_max=0.40, Bsat_margin=0.20,
    )


def _curated_db():
    """Load curated-only materials/cores/wires.

    Tests that sweep across all wires would otherwise blow up after
    `add-mas-catalog-import` grew the wire database from 48 → 1430.
    """
    mats = load_materials()
    cores = load_cores()
    wires = load_wires()
    cur_w = load_curated_ids("wires")
    if cur_w:
        wires = [w for w in wires if w.id in cur_w]
    return mats, cores, wires


def test_sweep_returns_results_and_some_feasible():
    mats, cores, wires = _curated_db()
    results = sweep(_spec_800W(), cores, wires, mats,
                    material_id="magnetics-60_highflux")
    assert len(results) > 100
    feasible = [r for r in results if r.feasible]
    assert len(feasible) > 0


def test_pareto_is_subset_and_ordered():
    mats, cores, wires = _curated_db()
    results = sweep(_spec_800W(), cores, wires, mats,
                    material_id="magnetics-60_highflux")
    pareto = pareto_front(results)
    feasible = [r for r in results if r.feasible]
    assert all(p in feasible for p in pareto)
    # Pareto sorted by volume ascending => loss should be non-increasing as volume grows
    for a, b in zip(pareto, pareto[1:], strict=False):
        assert a.volume_cm3 <= b.volume_cm3
        assert a.P_total_W >= b.P_total_W - 1e-6


def test_rank_by_loss_orders_correctly():
    mats, cores, wires = _curated_db()
    results = sweep(_spec_800W(), cores, wires, mats,
                    material_id="magnetics-60_highflux")
    feasible = [r for r in results if r.feasible]
    sorted_ = rank(feasible, by="loss")
    for a, b in zip(sorted_, sorted_[1:], strict=False):
        assert a.P_total_W <= b.P_total_W + 1e-6


def test_sweep_drops_designs_that_hit_N_max_cap():
    """Designs where the engine ran out of turns (N == N_max) shouldn't
    pollute the results — they have meaningless Ku/T and would crowd
    the UI table.
    """
    from pfc_inductor.optimize.sweep import _N_MAX
    mats, cores, wires = _curated_db()
    results = sweep(_spec_800W(), cores, wires, mats,
                    material_id="magnetics-60_highflux")
    assert all(r.result.N_turns < _N_MAX for r in results), (
        "sweep should drop designs at the N_max cap"
    )
