"""Tier 0 filter + candidate generator tests."""

from __future__ import annotations

import pytest

from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.models import Candidate, Spec
from pfc_inductor.optimize.cascade.generators import cartesian, cartesian_count
from pfc_inductor.optimize.cascade.tier0 import (
    evaluate_candidate,
    filter_candidates,
)
from pfc_inductor.topology.boost_ccm_model import BoostCCMModel


@pytest.fixture(scope="module")
def db():
    return {
        "materials": load_materials(),
        "cores": load_cores(),
        "wires": load_wires(),
    }


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


# ─── cartesian generator ───────────────────────────────────────────


def test_cartesian_yields_candidates_with_compatible_pairs(db):
    """Default config pairs every core with its default material only."""
    candidates = list(cartesian(db["materials"], db["cores"], db["wires"]))
    # Spot check: every yielded Candidate's (core, material) pair is compatible.
    cores_by_id = {c.id: c for c in db["cores"]}
    for cand in candidates[:50]:
        assert cores_by_id[cand.core_id].default_material_id == cand.material_id


def test_cartesian_count_matches_iteration(db):
    """`cartesian_count` must agree with consuming the iterator."""
    n = cartesian_count(db["materials"], db["cores"], db["wires"])
    assert n == sum(1 for _ in cartesian(db["materials"], db["cores"], db["wires"]))


def test_cartesian_only_round_wires_filter_consistent(db):
    """`only_round_wires=True` (default) yields ≤ the unfiltered count.

    The curated DB currently ships only round wires, so the two
    counts can be equal; the contract is that filtering does not
    add candidates.
    """
    n_round = cartesian_count(db["materials"], db["cores"], db["wires"])
    n_all = cartesian_count(
        db["materials"],
        db["cores"],
        db["wires"],
        only_round_wires=False,
    )
    assert n_round <= n_all


def test_cartesian_with_no_compatibility_filter_explodes_search_space(db):
    """`only_compatible_cores=False` should yield strictly more candidates."""
    n_compatible = cartesian_count(db["materials"], db["cores"], db["wires"])
    n_full = cartesian_count(
        db["materials"],
        db["cores"],
        db["wires"],
        only_compatible_cores=False,
    )
    assert n_full > n_compatible


# ─── Tier 0 evaluation ─────────────────────────────────────────────


def test_tier0_evaluate_candidate_returns_envelope(db):
    spec = _boost_spec()
    model = BoostCCMModel(spec)
    material = find_material(db["materials"], "magnetics-60_highflux")
    core = next(
        c
        for c in db["cores"]
        if c.default_material_id == material.id and 40_000 < c.Ve_mm3 < 100_000
    )
    wire = next(w for w in db["wires"] if w.id == "AWG14")
    cand = Candidate(core_id=core.id, material_id=material.id, wire_id=wire.id)

    result = evaluate_candidate(model, cand, core, material, wire)
    assert result.candidate is cand
    assert result.envelope.feasible is True


def test_tier0_filter_yields_one_result_per_input(db):
    spec = _boost_spec()
    model = BoostCCMModel(spec)
    materials_by_id = {m.id: m for m in db["materials"]}
    cores_by_id = {c.id: c for c in db["cores"]}
    wires_by_id = {w.id: w for w in db["wires"]}

    candidates = list(cartesian(db["materials"], db["cores"], db["wires"]))[:200]
    results = list(
        filter_candidates(
            model,
            candidates,
            materials_by_id,
            cores_by_id,
            wires_by_id,
        )
    )

    assert len(results) == len(candidates)
    # And the order matches.
    for cand, res in zip(candidates, results, strict=False):
        assert res.candidate.key() == cand.key()


def test_tier0_filter_drops_unknown_db_ids(db):
    """A candidate referencing a non-existent core gets a `missing_db_entry`."""
    spec = _boost_spec()
    model = BoostCCMModel(spec)
    cand = Candidate(core_id="ghost", material_id="ghost", wire_id="ghost")

    materials_by_id = {m.id: m for m in db["materials"]}
    cores_by_id = {c.id: c for c in db["cores"]}
    wires_by_id = {w.id: w for w in db["wires"]}

    [result] = list(
        filter_candidates(
            model,
            [cand],
            materials_by_id,
            cores_by_id,
            wires_by_id,
        )
    )
    assert result.envelope.feasible is False
    assert "missing_db_entry" in result.envelope.reasons


def test_tier0_filter_separates_feasible_from_infeasible(db):
    """An 800 W boost spec rejects some cores and accepts others.

    We sweep ALL materials × ALL cores (the cartesian generator pairs
    each core with its default material, so the product is bounded by
    the catalog's ``cores × default_material`` tuples). The wire
    dimension is restricted to a 3-wire sample so the search stays
    O(catalog) instead of O(catalog × all wires) — across the live
    MAS catalog the latter is ~14 M candidates which OOM-hangs CI
    runners. Tier 0 is wire-agnostic for the feasibility flag, so a
    small representative wire slice is sufficient to make the
    "some feasible / some infeasible" assertion.
    """
    spec = _boost_spec(Pout_W=800.0)
    model = BoostCCMModel(spec)
    materials_by_id = {m.id: m for m in db["materials"]}
    cores_by_id = {c.id: c for c in db["cores"]}
    sampled_wires = list(db["wires"])[:3]
    wires_by_id = {w.id: w for w in sampled_wires}

    candidates = list(cartesian(db["materials"], db["cores"], sampled_wires))
    results = list(
        filter_candidates(
            model,
            candidates,
            materials_by_id,
            cores_by_id,
            wires_by_id,
        )
    )
    feasible = [r for r in results if r.envelope.feasible]
    infeasible = [r for r in results if not r.envelope.feasible]
    assert feasible, "expected at least one feasible candidate across the whole DB"
    assert infeasible, "expected at least one infeasible candidate across the whole DB"


# ─── Performance smoke test ───────────────────────────────────────


def test_tier0_filter_throughput_reasonable(db):
    """Filtering 5 000 candidates must finish in well under one second.

    The tier 0 envelope is supposed to be cheap; this test catches a
    regression where someone slips a heavy computation into the
    quick-check path.
    """
    import time
    from itertools import islice

    spec = _boost_spec()
    model = BoostCCMModel(spec)
    materials_by_id = {m.id: m for m in db["materials"]}
    cores_by_id = {c.id: c for c in db["cores"]}
    wires_by_id = {w.id: w for w in db["wires"]}

    # ``islice`` over the generator — never materialise the whole
    # cartesian product. Even with the ``only_compatible_cores`` filter
    # the full product is ~14 M candidates against the live MAS
    # catalog; ``list(...)[:5000]`` allocated all 14 M Pydantic
    # ``Candidate`` instances first (minutes of GC pressure on a CI
    # runner, OOM on smaller machines) before the slice ran. The
    # fixed two-step form is O(5000) and preserves the sample.
    candidates = list(islice(cartesian(db["materials"], db["cores"], db["wires"]), 5000))
    start = time.perf_counter()
    consumed = sum(
        1
        for _ in filter_candidates(
            model,
            candidates,
            materials_by_id,
            cores_by_id,
            wires_by_id,
        )
    )
    elapsed = time.perf_counter() - start
    assert consumed == len(candidates)
    # 5 000 candidates in under 1 s on a developer workstation.
    assert elapsed < 1.0, f"Tier 0 too slow: {elapsed:.3f} s for 5 000 candidates"
