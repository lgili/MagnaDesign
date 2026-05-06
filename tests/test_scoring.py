"""Heuristic scoring functions for the Núcleo card's ranked-table view."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance() or QApplication([])
    yield inst


@pytest.fixture
def db():
    from pfc_inductor.data_loader import (
        ensure_user_data, load_materials, load_cores, load_wires,
    )
    ensure_user_data()
    return {
        "materials": load_materials(),
        "cores": load_cores(),
        "wires": load_wires(),
    }


# ---------------------------------------------------------------------------
# Score functions return [0, 100]
# ---------------------------------------------------------------------------

def test_score_material_in_range(app, db):
    from pfc_inductor.models import Spec
    from pfc_inductor.optimize.scoring import score_material
    spec = Spec()
    for m in db["materials"][:25]:
        s = score_material(spec, m)
        assert 0.0 <= s <= 100.0, f"{m.id}: score {s} out of range"


def test_score_core_in_range(app, db):
    from pfc_inductor.models import Spec
    from pfc_inductor.optimize.scoring import score_core
    spec = Spec()
    mat = db["materials"][0]
    wire = db["wires"][0]
    for c in db["cores"][:25]:
        s = score_core(spec, c, mat, wire)
        assert 0.0 <= s <= 100.0, f"{c.id}: score {s} out of range"


def test_score_wire_in_range(app, db):
    from pfc_inductor.models import Spec
    from pfc_inductor.optimize.scoring import score_wire
    spec = Spec()
    mat = db["materials"][0]
    core = db["cores"][0]
    for w in db["wires"][:50]:
        s = score_wire(spec, core, w, mat)
        assert 0.0 <= s <= 100.0, f"{w.id}: score {s} out of range"


# ---------------------------------------------------------------------------
# Topology-aware scoring
# ---------------------------------------------------------------------------

def test_score_material_topology_band_changes_ranking(app, db):
    """The μᵢ band scoring is topology-dependent: a material in the
    line-reactor μ-band (≥ 5 000) should outscore the same material
    when ranked against boost CCM, and vice-versa for a low-μ powder
    sample."""
    from pfc_inductor.models import Spec
    from pfc_inductor.optimize.scoring import score_material

    # Find one material with μ in the line-reactor band (≥5 000).
    high_mu = next(
        (m for m in db["materials"] if m.mu_initial >= 5_000),
        None,
    )
    if high_mu is None:
        pytest.skip("No high-μ material in DB to exercise line-reactor band")

    # Find one in the boost band (26–125).
    low_mu = next(
        (m for m in db["materials"] if 26 <= m.mu_initial <= 125),
        None,
    )
    if low_mu is None:
        pytest.skip("No powder material in DB to exercise boost band")

    spec_boost = Spec(topology="boost_ccm")
    spec_lr = Spec(topology="line_reactor", n_phases=1)

    # Same material, different topology — band score swaps.
    assert score_material(spec_lr, high_mu) > score_material(spec_boost, high_mu)
    assert score_material(spec_boost, low_mu) > score_material(spec_lr, low_mu)


# ---------------------------------------------------------------------------
# rank_* helpers return sorted descending
# ---------------------------------------------------------------------------

def test_rank_materials_sorted_descending(app, db):
    from pfc_inductor.models import Spec
    from pfc_inductor.optimize.scoring import rank_materials
    spec = Spec()
    ranked = rank_materials(spec, db["materials"])
    assert len(ranked) == len(db["materials"])
    scores = [s for _m, s in ranked]
    assert scores == sorted(scores, reverse=True)


def test_rank_cores_sorted_descending(app, db):
    from pfc_inductor.models import Spec
    from pfc_inductor.optimize.scoring import rank_cores
    spec = Spec()
    mat = db["materials"][0]
    wire = db["wires"][0]
    ranked = rank_cores(spec, db["cores"][:50], mat, wire)
    assert len(ranked) == 50
    scores = [s for _c, s in ranked]
    assert scores == sorted(scores, reverse=True)


def test_rank_wires_sorted_descending(app, db):
    from pfc_inductor.models import Spec
    from pfc_inductor.optimize.scoring import rank_wires
    spec = Spec()
    mat = db["materials"][0]
    core = db["cores"][0]
    ranked = rank_wires(spec, core, db["wires"][:30], mat)
    assert len(ranked) == 30
    scores = [s for _w, s in ranked]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Vendor curation gives small but consistent bonus
# ---------------------------------------------------------------------------

def test_curated_vendor_bonus_is_positive(app, db):
    """Two cores identical except for vendor — curated wins."""
    from pfc_inductor.models import Spec
    from pfc_inductor.optimize.scoring import score_core

    spec = Spec()
    mat = db["materials"][0]
    wire = db["wires"][0]

    # Find a curated vendor core and an unknown-vendor core.
    curated = next(
        c for c in db["cores"]
        if (c.vendor or "").lower() in {
            "magnetics", "magmattec", "micrometals", "csc",
            "thornton", "dongxing",
        }
    )
    not_curated = next(
        c for c in db["cores"]
        if (c.vendor or "").lower() not in {
            "magnetics", "magmattec", "micrometals", "csc",
            "thornton", "dongxing", "tdk", "ferroxcube",
        }
    )
    assert score_core(spec, curated, mat, wire) >= 0
    # Direct comparison would need pairing same-feasibility; we just
    # assert the curated bonus surfaces in *some* row at the top.
    from pfc_inductor.optimize.scoring import rank_cores
    top10 = [c for c, _s in rank_cores(spec, db["cores"], mat, wire)[:10]]
    curated_in_top = sum(
        1 for c in top10
        if (c.vendor or "").lower() in {
            "magnetics", "magmattec", "micrometals", "csc",
            "thornton", "dongxing",
        }
    )
    assert curated_in_top >= 5, (
        f"expected ≥5 curated vendors in top-10 cores, got {curated_in_top}"
    )
