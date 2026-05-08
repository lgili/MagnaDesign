"""Per-topology material-type policy tests."""

from __future__ import annotations

import pytest

from pfc_inductor.models import Material
from pfc_inductor.models.material import (
    MaterialType,
    SteinmetzParams,
)
from pfc_inductor.topology.material_filter import (
    material_types_for_topology,
    materials_for_topology,
)


def _mat(type_: MaterialType, *, mid: str | None = None) -> Material:
    """Build a minimal Material; only `type` and `id` matter for the
    filter, the rest is just here to satisfy Pydantic."""
    return Material(
        id=mid or f"mat-{type_}",
        vendor="test",
        family="test",
        name=type_,
        type=type_,
        mu_initial=1000.0,
        Bsat_25C_T=1.0,
        Bsat_100C_T=0.9,
        steinmetz=SteinmetzParams(
            Pv_ref_mWcm3=100.0,
            alpha=1.5,
            beta=2.5,
        ),
    )


# ─── policy table ────────────────────────────────────────────────


def test_boost_ccm_accepts_high_frequency_families():
    accepted = material_types_for_topology("boost_ccm")
    assert "powder" in accepted
    assert "ferrite" in accepted
    assert "nanocrystalline" in accepted
    assert "amorphous" in accepted
    # Silicon-steel laminations are line-frequency only — eddy losses
    # would dominate at switching frequency.
    assert "silicon-steel" not in accepted


def test_passive_choke_targets_line_frequency_families():
    accepted = material_types_for_topology("passive_choke")
    assert "silicon-steel" in accepted
    assert "amorphous" in accepted
    assert "nanocrystalline" in accepted
    # Powder μ is too low for practical 60 Hz inductance; ferrites
    # are uneconomic at line frequency.
    assert "powder" not in accepted
    assert "ferrite" not in accepted


def test_line_reactor_uses_same_set_as_passive_choke():
    """Both are 50/60 Hz topologies and share the same material policy."""
    assert material_types_for_topology("line_reactor") == material_types_for_topology(
        "passive_choke"
    )


def test_unknown_topology_returns_empty_set():
    assert material_types_for_topology("not_a_topology") == frozenset()  # type: ignore[arg-type]


# ─── filter helper ───────────────────────────────────────────────


def test_filter_keeps_only_accepted_types_for_boost_ccm():
    catalogue = [
        _mat("powder", mid="p"),
        _mat("ferrite", mid="f"),
        _mat("silicon-steel", mid="ss"),
        _mat("nanocrystalline", mid="n"),
    ]
    out = materials_for_topology(catalogue, "boost_ccm")
    assert {m.id for m in out} == {"p", "f", "n"}


def test_filter_drops_powder_and_ferrite_for_line_reactor():
    catalogue = [
        _mat("powder", mid="p"),
        _mat("ferrite", mid="f"),
        _mat("silicon-steel", mid="ss"),
        _mat("amorphous", mid="a"),
    ]
    out = materials_for_topology(catalogue, "line_reactor")
    assert {m.id for m in out} == {"ss", "a"}


def test_filter_returns_input_unchanged_for_unknown_topology():
    """Missing policy entry must not silently empty the catalogue —
    a bug would otherwise hide behind an "no candidates" run."""
    catalogue = [_mat("powder"), _mat("ferrite")]
    out = materials_for_topology(catalogue, "not_a_topology")  # type: ignore[arg-type]
    assert {m.id for m in out} == {"mat-powder", "mat-ferrite"}


def test_filter_preserves_input_ordering():
    catalogue = [
        _mat("ferrite", mid="f1"),
        _mat("powder", mid="p1"),
        _mat("ferrite", mid="f2"),
    ]
    out = materials_for_topology(catalogue, "boost_ccm")
    assert [m.id for m in out] == ["f1", "p1", "f2"]


def test_filter_returns_empty_when_catalogue_has_no_matches():
    catalogue = [_mat("powder"), _mat("ferrite")]
    out = materials_for_topology(catalogue, "line_reactor")
    assert out == []


# ─── integration smoke against the real catalogue ───────────────


@pytest.mark.parametrize(
    "topology, expected_types",
    [
        ("boost_ccm", {"powder", "ferrite", "nanocrystalline", "amorphous"}),
        ("passive_choke", {"silicon-steel", "amorphous", "nanocrystalline"}),
        ("line_reactor", {"silicon-steel", "amorphous", "nanocrystalline"}),
    ],
)
def test_filter_against_loaded_catalogue(topology, expected_types):
    """End-to-end: load real catalog, ensure filter produces a
    sensible non-empty subset whose members all match the policy."""
    from pfc_inductor.data_loader import load_materials

    out = materials_for_topology(load_materials(), topology)
    assert out, f"no materials matched for {topology!r}"
    actual_types = {m.type for m in out}
    assert actual_types <= expected_types
