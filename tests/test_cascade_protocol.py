"""ConverterModel protocol & Phase-A topology adapters."""

from __future__ import annotations

import pytest

from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.models import Spec
from pfc_inductor.models.cascade import FeasibilityEnvelope
from pfc_inductor.topology.boost_ccm_model import BoostCCMModel
from pfc_inductor.topology.buck_ccm_model import BuckCCMModel
from pfc_inductor.topology.line_reactor_model import LineReactorModel
from pfc_inductor.topology.passive_choke_model import PassiveChokeModel
from pfc_inductor.topology.protocol import ConverterModel
from pfc_inductor.topology.registry import (
    TOPOLOGY_MODELS,
    model_for,
    registered_topologies,
)


@pytest.fixture(scope="module")
def db():
    return {
        "materials": load_materials(),
        "cores": load_cores(),
        "wires": load_wires(),
    }


def _pick_first(items, predicate):
    for item in items:
        if predicate(item):
            return item
    raise AssertionError("no item matched predicate")


# ────────────────────────────────────────────────────────────────
# Protocol satisfaction
# ────────────────────────────────────────────────────────────────


def test_boost_ccm_model_satisfies_protocol():
    spec = Spec(topology="boost_ccm")
    model = BoostCCMModel(spec)
    assert isinstance(model, ConverterModel)
    assert model.name == "boost_ccm"
    assert model.spec is spec


def test_passive_choke_model_satisfies_protocol():
    spec = Spec(topology="passive_choke")
    model = PassiveChokeModel(spec)
    assert isinstance(model, ConverterModel)
    assert model.name == "passive_choke"


def test_line_reactor_model_satisfies_protocol():
    spec = Spec(topology="line_reactor")
    model = LineReactorModel(spec)
    assert isinstance(model, ConverterModel)
    assert model.name == "line_reactor"


# ────────────────────────────────────────────────────────────────
# Spec-topology mismatch is caught at construction
# ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cls,wrong_topology",
    [
        (BoostCCMModel, "passive_choke"),
        (PassiveChokeModel, "boost_ccm"),
        (LineReactorModel, "boost_ccm"),
    ],
)
def test_model_rejects_mismatched_topology(cls, wrong_topology):
    with pytest.raises(ValueError, match="requires"):
        cls(Spec(topology=wrong_topology))


# ────────────────────────────────────────────────────────────────
# Tier 0 — feasibility envelope
# ────────────────────────────────────────────────────────────────

# Reference combo borrowed from `test_design_engine.py` — known-good in the curated DB.
_REF_MATERIAL_ID = "magnetics-60_highflux"
_REF_WIRE_ID = "AWG14"


def _ref_combo(db):
    material = find_material(db["materials"], _REF_MATERIAL_ID)
    core = _pick_first(
        db["cores"],
        lambda c: c.default_material_id == _REF_MATERIAL_ID and 40_000 < c.Ve_mm3 < 100_000,
    )
    wire = _pick_first(db["wires"], lambda w: w.id == _REF_WIRE_ID)
    return material, core, wire


def _boost_spec(Pout_W: float = 800.0) -> Spec:
    return Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=220.0,
        Vout_V=400.0,
        Pout_W=Pout_W,
        eta=0.97,
        f_sw_kHz=65.0,
        ripple_pct=30.0,
        T_amb_C=40.0,
        T_max_C=100.0,
        Ku_max=0.40,
        Bsat_margin=0.20,
    )


def test_feasibility_envelope_returns_feasible_for_valid_combo(db):
    """A 800 W boost-CCM combo on a mid-size High Flux 60 toroid should pass."""
    model = BoostCCMModel(_boost_spec(Pout_W=800.0))
    material, core, wire = _ref_combo(db)
    env = model.feasibility_envelope(core, material, wire)
    assert isinstance(env, FeasibilityEnvelope)
    assert env.feasible is True
    assert env.reasons == []


def test_feasibility_envelope_rejects_obviously_undersized_core(db):
    """A 3 kW spec on the smallest compatible core should be rejected."""
    model = BoostCCMModel(_boost_spec(Pout_W=3000.0))
    material = find_material(db["materials"], _REF_MATERIAL_ID)
    compatible = [c for c in db["cores"] if c.default_material_id == _REF_MATERIAL_ID]
    smallest = min(compatible, key=lambda c: c.Ve_mm3)
    wire = _pick_first(db["wires"], lambda w: w.id == _REF_WIRE_ID)
    env = model.feasibility_envelope(smallest, material, wire)
    assert env.feasible is False
    assert env.reasons


# ────────────────────────────────────────────────────────────────
# Tier 1 — steady_state delegates to the analytical engine
# ────────────────────────────────────────────────────────────────


def test_steady_state_returns_design_result(db):
    model = BoostCCMModel(_boost_spec(Pout_W=800.0))
    material, core, wire = _ref_combo(db)
    result = model.steady_state(core, material, wire)
    assert result.L_actual_uH > 0
    assert 1 <= result.N_turns <= 500
    assert result.losses.P_total_W >= 0


# ────────────────────────────────────────────────────────────────
# Registry
# ────────────────────────────────────────────────────────────────


def test_registry_lists_all_topologies():
    """The registry exposes every supported ``Spec.topology`` value.

    Was three when only AC topologies existed; ``add-buck-ccm-topology``
    added the synchronous DC-DC buck.
    """
    topos = registered_topologies()
    assert set(topos) == {
        "boost_ccm",
        "passive_choke",
        "line_reactor",
        "buck_ccm",
    }


def test_model_for_returns_matching_class():
    spec_boost = Spec(topology="boost_ccm")
    assert isinstance(model_for(spec_boost), BoostCCMModel)
    spec_choke = Spec(topology="passive_choke")
    assert isinstance(model_for(spec_choke), PassiveChokeModel)
    spec_reactor = Spec(topology="line_reactor")
    assert isinstance(model_for(spec_reactor), LineReactorModel)
    spec_buck = Spec(
        topology="buck_ccm",
        Vin_dc_V=12.0,
        Vin_dc_min_V=10.8,
        Vin_dc_max_V=13.2,
        Vout_V=3.3,
        Pout_W=10.0,
        eta=0.95,
        f_sw_kHz=500.0,
        ripple_ratio=0.30,
    )
    assert isinstance(model_for(spec_buck), BuckCCMModel)


def test_model_for_raises_on_unregistered_topology():
    spec = Spec(topology="boost_ccm")
    # Bypass Pydantic validation to inject an invalid topology value.
    object.__setattr__(spec, "topology", "fictitious")
    with pytest.raises(ValueError, match="No topology model registered"):
        model_for(spec)


def test_registry_table_keys_match_registered_topologies():
    assert set(TOPOLOGY_MODELS.keys()) == set(registered_topologies())
