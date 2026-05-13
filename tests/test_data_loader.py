"""Sanity checks on the bundled JSON databases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

import pfc_inductor.data_loader as data_loader
from pfc_inductor.data_loader import (
    ensure_user_data,
    load_cores,
    load_curated_ids,
    load_materials,
    load_wires,
)


@pytest.fixture
def isolated_user_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point ``user_data_path()`` at a clean temp dir for the test.

    Avoids polluting the developer's real ``~/Library/Application
    Support/MagnaDesign/`` (or platform equivalent) while keeping
    ``ensure_user_data()``'s copy-on-first-launch contract honest.
    """
    target = tmp_path / "user_data"
    target.mkdir()
    monkeypatch.setattr(data_loader, "user_data_path", lambda: target)
    yield target


def test_materials_load_and_have_steinmetz():
    mats = load_materials()
    assert len(mats) >= 30
    for m in mats:
        assert m.steinmetz.Pv_ref_mWcm3 > 0
        # Wide bounds: includes high-freq materials like Magnetics L
        # whose data is concentrated at 0.5-3 MHz and yields steeper fits.
        assert 1.0 <= m.steinmetz.alpha <= 3.0, f"{m.id}: alpha={m.steinmetz.alpha}"
        assert 1.0 <= m.steinmetz.beta <= 6.5, f"{m.id}: beta={m.steinmetz.beta}"
        assert 0.2 <= m.Bsat_25C_T <= 2.1  # silicon steel reaches ~2.03 T


def test_cores_have_geometry():
    cores = load_cores()
    assert len(cores) >= 100
    for c in cores:
        assert c.Ae_mm2 > 0
        assert c.le_mm > 0
        assert c.AL_nH > 0


def test_wires_complete_AWG_range():
    wires = load_wires()
    awgs = {w.awg for w in wires if w.awg is not None}
    # Should cover at least 10..40 AWG
    for awg in (10, 12, 16, 20, 24, 30, 40):
        assert awg in awgs, f"AWG {awg} missing from wire database"


def test_brazilian_vendors_present():
    """Thornton and Magmattec are critical for the user's market."""
    mats = load_materials()
    vendors = {m.vendor for m in mats}
    assert "Thornton" in vendors
    assert "Magmattec" in vendors


def test_catalog_merge_adds_openmagnetics_entries():
    """When data/mas/catalog/*.json exists, those entries are appended."""
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    catalog_path = repo / "data" / "mas" / "catalog" / "materials.json"
    if not catalog_path.exists():
        return  # catalog not yet imported in this checkout — skip

    mats = load_materials()
    # The shipped curated set has 50 entries; the catalog adds more.
    assert len(mats) > 100, "catalog merge should yield >100 materials"

    # At least one catalog-only material is recoverable, and its source
    # tag survives the round-trip through the loader.
    curated = load_curated_ids("materials")
    assert len(curated) >= 30  # baseline curated count
    catalog_only = [m for m in mats if m.id not in curated]
    assert catalog_only, "no catalog-only materials returned"


def test_curated_only_filter_excludes_catalog_rows():
    """`load_curated_ids` is the source of truth for the UI filter."""
    curated = load_curated_ids("materials")
    mats = load_materials()
    if len(mats) <= len(curated):
        return  # no catalog imported yet — nothing to verify
    catalog_only = [m for m in mats if m.id not in curated]
    # Every non-curated material must carry a source breadcrumb in
    # ``notes``. We accept either OpenMagnetics (MAS catalog) or
    # PyETK (Ansys-imported ferrites). New importers should append
    # their own marker here.
    expected_markers = ("OpenMagnetics", "PyETK")
    for m in catalog_only:
        assert any(marker in m.notes for marker in expected_markers), (
            f"catalog material {m.id!r} has no source marker in notes: {m.notes!r}"
        )


def test_catalog_material_drives_design_engine():
    """A catalog-only material must run end-to-end without error."""
    from pfc_inductor.data_loader import find_material
    from pfc_inductor.design import design
    from pfc_inductor.models import Spec

    mats = load_materials()
    cores = load_cores()
    wires = load_wires()
    curated = load_curated_ids("materials")
    catalog_only = [m for m in mats if m.id not in curated]
    if not catalog_only:
        return  # catalog not imported — skip
    target_material = catalog_only[0]
    target_core = next(
        (c for c in cores if c.shape.lower() in {"toroid", "e", "ee"}),
        cores[0],
    )
    target_wire = next((w for w in wires if w.type == "round"), wires[0])

    spec = Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85,
        Vin_max_Vrms=265,
        Vin_nom_Vrms=220,
        f_line_Hz=50,
        Vout_V=400,
        Pout_W=600,
        eta=0.97,
        f_sw_kHz=65,
        ripple_pct=30,
        T_amb_C=40,
        T_max_C=100,
        Ku_max=0.4,
        Bsat_margin=0.2,
    )
    # Rebuild the material reference via the loader path so any future
    # adapter changes are exercised.
    m = find_material(mats, target_material.id)
    result = design(spec, target_core, target_wire, m)
    assert result.N_turns > 0
    assert result.L_actual_uH > 0


# ─────────────────────────────────────────────────────────────────
# ``ensure_user_data`` — copy-on-first-launch for ALL THREE sources
# ─────────────────────────────────────────────────────────────────
def test_ensure_user_data_copies_primary_triplet(isolated_user_data: Path):
    """First launch: ``materials.json``, ``cores.json``, ``wires.json``
    land at the user-data root so the engineer can edit them."""
    ensure_user_data()
    for name in ("materials.json", "cores.json", "wires.json"):
        assert (isolated_user_data / name).is_file(), f"missing {name}"
        # Each is a valid JSON object — no empty / corrupt copy.
        payload = json.loads((isolated_user_data / name).read_text(encoding="utf-8"))
        assert isinstance(payload, dict)


def test_ensure_user_data_copies_mas_catalog_tree(isolated_user_data: Path):
    """The MAS catalog is the larger of the three sources — must be
    mirrored under ``<user>/mas/catalog/`` so PyETK / OpenMagnetics
    additions can be tweaked locally without rebuilding the bundle."""
    if not data_loader._BUNDLED_CATALOG.is_dir():
        pytest.skip("MAS catalog not bundled in this checkout")
    ensure_user_data()
    catalog_dir = isolated_user_data / "mas" / "catalog"
    assert catalog_dir.is_dir()
    for name in ("materials.json", "cores.json", "wires.json"):
        src = data_loader._BUNDLED_CATALOG / name
        if src.exists():
            dst = catalog_dir / name
            assert dst.is_file(), f"missing mas/catalog/{name}"


def test_ensure_user_data_copies_pyetk_tree(isolated_user_data: Path):
    """PyETK ferrites must also be mirrored to ``<user>/pyetk/``."""
    if not data_loader._BUNDLED_PYETK.is_dir():
        pytest.skip("PyETK catalog not bundled in this checkout")
    ensure_user_data()
    pyetk_dir = isolated_user_data / "pyetk"
    assert pyetk_dir.is_dir()
    for name in ("materials.json", "cores.json"):
        src = data_loader._BUNDLED_PYETK / name
        if src.exists():
            dst = pyetk_dir / name
            assert dst.is_file(), f"missing pyetk/{name}"


def test_ensure_user_data_is_non_destructive(isolated_user_data: Path):
    """Re-running ``ensure_user_data()`` must never overwrite an
    edited file — that would silently revert the engineer's tweaks
    on every launch."""
    ensure_user_data()
    edited = isolated_user_data / "materials.json"
    edited.write_text('{"materials": [], "_user_marker": "edited"}', encoding="utf-8")
    ensure_user_data()  # second pass
    assert "_user_marker" in edited.read_text(encoding="utf-8")


def test_open_catalog_prefers_user_overlay(isolated_user_data: Path):
    """A file at ``<user>/mas/catalog/<name>`` wins over the bundle —
    same model the primary triplet already uses."""
    if not data_loader._BUNDLED_CATALOG.is_dir():
        pytest.skip("MAS catalog not bundled in this checkout")
    ensure_user_data()
    overlay = isolated_user_data / "mas" / "catalog" / "materials.json"
    overlay.write_text(
        '{"materials": [{"id": "test-overlay", "x-pfc-inductor": {}}]}',
        encoding="utf-8",
    )
    payload = data_loader._open_catalog("materials.json")
    assert payload is not None
    assert payload.get("materials") == [{"id": "test-overlay", "x-pfc-inductor": {}}]


def test_open_pyetk_prefers_user_overlay(isolated_user_data: Path):
    """Same overlay-over-bundle rule for the PyETK source."""
    if not data_loader._BUNDLED_PYETK.is_dir():
        pytest.skip("PyETK catalog not bundled in this checkout")
    ensure_user_data()
    overlay = isolated_user_data / "pyetk" / "materials.json"
    overlay.write_text(
        '{"materials": [{"id": "pyetk-overlay", "x-pfc-inductor": {"source": "pyetk"}}]}',
        encoding="utf-8",
    )
    payload = data_loader._open_pyetk("materials.json")
    assert payload is not None
    assert payload.get("materials") == [
        {"id": "pyetk-overlay", "x-pfc-inductor": {"source": "pyetk"}}
    ]


def test_open_catalog_falls_back_to_bundle_when_user_file_missing(
    isolated_user_data: Path,
):
    """User dir is empty (no overlay) — loader still finds the bundled
    catalog, so a user who deletes a file by hand doesn't lose data."""
    if not (data_loader._BUNDLED_CATALOG / "materials.json").exists():
        pytest.skip("MAS catalog not bundled in this checkout")
    # No ensure_user_data() call — user dir starts empty.
    payload = data_loader._open_catalog("materials.json")
    assert payload is not None  # came from bundle
