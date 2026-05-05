"""Similar-parts finder tests."""
import pytest

from pfc_inductor.data_loader import load_cores, load_materials, find_material
from pfc_inductor.optimize import (
    SimilarityCriteria, find_equivalents,
)
from pfc_inductor.optimize.similar import _distance, _normalize_shape


@pytest.fixture(scope="module")
def db():
    return load_materials(), load_cores()


def test_distance_zero_for_identical_deltas():
    deltas = {"Ae": 0.0, "Wa": 0.0, "AL": 0.0, "mu_r": 0.0, "Bsat": 0.0}
    crit = SimilarityCriteria()
    assert _distance(deltas, crit) == 0.0


def test_distance_grows_with_deltas():
    crit = SimilarityCriteria()
    near = {"Ae": 1.0, "Wa": 1.0, "AL": 1.0, "mu_r": 1.0, "Bsat": 1.0}
    far = {"Ae": 5.0, "Wa": 5.0, "AL": 5.0, "mu_r": 5.0, "Bsat": 5.0}
    assert _distance(far, crit) > _distance(near, crit)


def test_normalize_shape():
    assert _normalize_shape("Toroid") == "toroid"
    assert _normalize_shape("ETD") == "etd"
    assert _normalize_shape("PQ 32/30") == "pq"
    assert _normalize_shape("E 100/60/28") == "e"
    assert _normalize_shape("EE 30") == "e"
    assert _normalize_shape("NEE 25/10/6") == "e"


def test_finds_alternatives_for_high_flux_target(db):
    """A known toroid with a HighFlux 60u sibling in XFlux 60u should match."""
    mats, cores = db
    target_core = next(
        c for c in cores
        if c.default_material_id == "magnetics-60_highflux"
        and 40000 < c.Ve_mm3 < 100000
    )
    target_mat = find_material(mats, "magnetics-60_highflux")
    matches = find_equivalents(target_core, target_mat, cores, mats)
    assert len(matches) >= 1, f"Expected ≥1 alternative for {target_core.part_number}"


def test_excludes_self(db):
    mats, cores = db
    target_core = cores[0]
    try:
        target_mat = find_material(mats, target_core.default_material_id)
    except KeyError:
        pytest.skip("first core's default material not in db")
    matches = find_equivalents(target_core, target_mat, cores, mats,
                               SimilarityCriteria(Ae_pct=50, Wa_pct=50, AL_pct=50,
                                                  mu_r_pct=50, Bsat_pct=50))
    assert all(m.core.id != target_core.id for m in matches)


def test_tighter_tolerance_reduces_count(db):
    mats, cores = db
    target_core = next(
        c for c in cores
        if c.default_material_id == "magnetics-60_highflux"
        and 40000 < c.Ve_mm3 < 100000
    )
    target_mat = find_material(mats, "magnetics-60_highflux")
    loose = find_equivalents(
        target_core, target_mat, cores, mats,
        SimilarityCriteria(Ae_pct=30, Wa_pct=40, AL_pct=40, mu_r_pct=30, Bsat_pct=30),
    )
    tight = find_equivalents(
        target_core, target_mat, cores, mats,
        SimilarityCriteria(Ae_pct=3, Wa_pct=3, AL_pct=3, mu_r_pct=3, Bsat_pct=3),
    )
    assert len(tight) <= len(loose), \
        "Tightening tolerance must not increase the match count"


def test_distance_is_zero_when_self_included(db):
    """Disabling exclude_self, the target itself must appear with distance 0."""
    mats, cores = db
    target_core = next(c for c in cores if c.shape == "Toroid" and c.Wa_mm2 > 200)
    try:
        target_mat = find_material(mats, target_core.default_material_id)
    except KeyError:
        pytest.skip("target's default material not loadable")
    matches = find_equivalents(
        target_core, target_mat, cores, mats,
        SimilarityCriteria(exclude_self=False),
    )
    self_match = next((m for m in matches if m.core.id == target_core.id), None)
    assert self_match is not None
    assert self_match.distance < 1e-6


def test_cross_material_flag(db):
    """When the database has the same part_number with another material,
    that variant is returned with is_same_part_number=True."""
    mats, cores = db
    # Find a part_number with multiple variants.
    from collections import defaultdict
    by_pn = defaultdict(list)
    for c in cores:
        by_pn[(c.vendor, c.part_number)].append(c)
    target_core = None
    for variants in by_pn.values():
        if len(variants) >= 2:
            target_core = variants[0]
            break
    assert target_core is not None
    try:
        target_mat = find_material(mats, target_core.default_material_id)
    except KeyError:
        pytest.skip("target material not loadable")
    matches = find_equivalents(
        target_core, target_mat, cores, mats,
        SimilarityCriteria(
            Ae_pct=30, Wa_pct=30, AL_pct=80, mu_r_pct=80, Bsat_pct=50,
            same_shape=False,
        ),
    )
    cross_matches = [m for m in matches if m.is_cross_material]
    assert len(cross_matches) >= 1, (
        f"Expected ≥1 cross-material match for {target_core.part_number}"
    )
