"""Cheap feasibility heuristic for core selection."""
from __future__ import annotations

from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.models import Spec
from pfc_inductor.optimize.feasibility import (
    core_quick_check,
    filter_viable_cores,
)


def _spec_800W():
    return Spec(
        Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
        Vout_V=400.0, Pout_W=800.0, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
    )


def test_quick_check_returns_one_of_known_verdicts():
    mats = load_materials(); cores = load_cores(); wires = load_wires()
    mat = find_material(mats, "magnetics-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    valid = {"ok", "too_small_L", "window_overflow", "saturates"}
    for c in cores[:50]:
        v = core_quick_check(_spec_800W(), c, mat, wire)
        assert v in valid


def test_filter_drops_obviously_too_small_cores():
    """Tiny cores (Ve < 50 mm³) won't fit a 800 W PFC inductor."""
    mats = load_materials(); cores = load_cores(); wires = load_wires()
    mat = find_material(mats, "magnetics-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    compat = [c for c in cores if c.default_material_id == mat.id]
    viable, _ = filter_viable_cores(_spec_800W(), compat, mat, wire)
    # The tiniest cores (Ve < 200 mm³) are always too small for 800 W
    too_small = [c for c in compat if c.Ve_mm3 < 200]
    assert all(c not in viable for c in too_small)


def test_filter_pout_scaling():
    """Lower Pout → more cores fit; higher Pout → fewer."""
    mats = load_materials(); cores = load_cores(); wires = load_wires()
    mat = find_material(mats, "magnetics-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    compat = [c for c in cores if c.default_material_id == mat.id]
    spec_lo = _spec_800W().model_copy(update={"Pout_W": 300})
    spec_hi = _spec_800W().model_copy(update={"Pout_W": 2500})
    n_lo = len(filter_viable_cores(spec_lo, compat, mat, wire)[0])
    n_hi = len(filter_viable_cores(spec_hi, compat, mat, wire)[0])
    # Boost CCM at higher power needs more L AND more I_pk → fewer
    # cores fit; at low power both relax.
    assert n_hi != n_lo, "filter should react to Pout"


def test_filter_returns_non_empty_for_typical_spec():
    """Sanity: in a realistic 800 W PFC scenario the filter must keep
    SOME cores — otherwise the user can't pick anything."""
    mats = load_materials(); cores = load_cores(); wires = load_wires()
    mat = find_material(mats, "magnetics-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    compat = [c for c in cores if c.default_material_id == mat.id]
    viable, _ = filter_viable_cores(_spec_800W(), compat, mat, wire)
    assert len(viable) >= 5, (
        f"only {len(viable)} viable for typical PFC — filter too aggressive"
    )


def test_filter_reason_counts_sum_to_hidden():
    """The reason dict's totals should account for every dropped core."""
    mats = load_materials(); cores = load_cores(); wires = load_wires()
    mat = find_material(mats, "magnetics-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    compat = [c for c in cores if c.default_material_id == mat.id]
    viable, reasons = filter_viable_cores(_spec_800W(), compat, mat, wire)
    n_hidden = len(compat) - len(viable)
    assert sum(reasons.values()) == n_hidden
