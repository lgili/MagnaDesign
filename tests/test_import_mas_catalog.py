"""Tests for ``scripts/import_mas_catalog.py``.

Synthetic NDJSON sources keep these fast and hermetic — they don't touch
the vendored real catalog under ``vendor/openmagnetics-catalog/``.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import import_mas_catalog as imc  # type: ignore[import-not-found]  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic catalog fixture
# ---------------------------------------------------------------------------
def _write_ndjson(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def synthetic_source(tmp_path: Path) -> Path:
    src = tmp_path / "openmagnetics-catalog"
    src.mkdir()
    (src / "VERSION.txt").write_text(
        "OpenMagnetics MAS catalog\nCommit: deadbeef0000\n",
        encoding="utf-8",
    )
    _write_ndjson(src / "core_materials.ndjson", [
        {
            "name": "TestFerrite-A",
            "manufacturerInfo": {"name": "TestVendor"},
            "family": "MnZn",
            "material": "ferrite",
            "permeability": {"initial": 2400.0},
            "saturation": [
                {"temperature": 25, "magneticFluxDensity": 0.49},
                {"temperature": 100, "magneticFluxDensity": 0.39},
            ],
            "density": 4800.0,
            "volumetricLosses": [
                {
                    "method": "steinmetz",
                    "coefficients": {"k": 1.5, "alpha": 1.45, "beta": 2.6},
                    "referenceFrequency": 100000.0,
                    "referenceMagneticFluxDensity": 0.1,
                },
            ],
        },
        {
            "name": "PowderCore-X",
            "manufacturerInfo": {"name": "TestPowderCo"},
            "family": "MPP",
            "material": "powder",
            "permeability": {
                "complex": {"real": [{"frequency": 10_000.0, "value": 60.0}]},
            },
            "saturation": [
                {"temperature": 25, "magneticFluxDensity": 1.0},
            ],
        },
        {
            # missing permeability — must be skipped (falls back to None).
            "name": "BadMaterial",
            "manufacturerInfo": {"name": "BadCo"},
            "saturation": [],
        },
    ])
    _write_ndjson(src / "wires.ndjson", [
        {
            "name": "Round 1.5 - Grade 1",
            "type": "round",
            "material": "copper",
            "manufacturerInfo": {"name": "TestWireCo"},
            "conductingDiameter": {"nominal": 0.0015},
            "outerDiameter": {"minimum": 0.00154, "maximum": 0.00159},
        },
        {
            "name": "Litz 100x0.05",
            "type": "litz",
            "outerDiameter": {"minimum": 0.001, "maximum": 0.0011},
        },
        {
            "name": "Rect 2x0.8",
            "type": "rectangular",
            "conductingWidth": {"nominal": 0.002},
        },
    ])
    return src


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_dry_run_does_not_write(synthetic_source, tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    monkeypatch.setattr(imc, "OUT_DIR", out_dir)
    monkeypatch.setattr(imc, "REPO_ROOT", tmp_path)  # avoid real curated set
    code = imc.run_import(synthetic_source, dry_run=True)
    assert code == 0
    assert not out_dir.exists()


def test_catalog_writes_materials_and_wires(synthetic_source, tmp_path, monkeypatch):
    out_dir = tmp_path / "out" / "data" / "mas" / "catalog"
    monkeypatch.setattr(imc, "OUT_DIR", out_dir)
    monkeypatch.setattr(imc, "REPO_ROOT", tmp_path)  # no curated, no user overlay
    code = imc.run_import(synthetic_source, dry_run=False)
    assert code == 0
    mats = json.loads((out_dir / "materials.json").read_text())["materials"]
    wires = json.loads((out_dir / "wires.json").read_text())["wires"]

    # 2 valid materials (BadMaterial skipped) and 1 round wire (litz/rect skipped).
    assert len(mats) == 2
    assert len(wires) == 1

    # Every imported entry carries the source + version tag.
    for entry in mats + wires:
        ext = entry["x-pfc-inductor"]
        assert ext["source"] == "openmagnetics"
        assert ext["catalog_version"] == "deadbeef0000"


def test_curated_id_collision_is_skipped(synthetic_source, tmp_path, monkeypatch):
    """If the curated set already has an entry, the catalog one is dropped."""
    out_dir = tmp_path / "out" / "data" / "mas" / "catalog"
    curated_dir = tmp_path / "data" / "mas"
    curated_dir.mkdir(parents=True)
    # The slug of "TestVendor" + "TestFerrite-A" is "testvendor-testferrite-a".
    curated_dir.joinpath("materials.json").write_text(json.dumps({
        "materials": [
            {"x-pfc-inductor": {"id": "testvendor-testferrite-a"}},
        ],
    }))
    monkeypatch.setattr(imc, "OUT_DIR", out_dir)
    monkeypatch.setattr(imc, "REPO_ROOT", tmp_path)
    code = imc.run_import(synthetic_source, dry_run=False)
    assert code == 0
    mats = json.loads((out_dir / "materials.json").read_text())["materials"]
    ids = [m["x-pfc-inductor"]["id"] for m in mats]
    assert "testvendor-testferrite-a" not in ids
    assert any("testpowderco" in i for i in ids)


def test_user_overlay_id_collision_is_skipped(synthetic_source, tmp_path, monkeypatch):
    """User-data overlay always wins, even over a fresh import."""
    out_dir = tmp_path / "out" / "data" / "mas" / "catalog"
    user_dir = tmp_path / "user-data"
    user_dir.mkdir()
    user_dir.joinpath("materials.json").write_text(json.dumps({
        "materials": [
            {"x-pfc-inductor": {"id": "testpowderco-powdercore-x"}},
        ],
    }))
    monkeypatch.setattr(imc, "OUT_DIR", out_dir)
    monkeypatch.setattr(imc, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(imc, "_user_data_dir", lambda: user_dir)
    code = imc.run_import(synthetic_source, dry_run=False)
    assert code == 0
    mats = json.loads((out_dir / "materials.json").read_text())["materials"]
    ids = [m["x-pfc-inductor"]["id"] for m in mats]
    assert "testpowderco-powdercore-x" not in ids


def test_missing_source_dir_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(imc, "REPO_ROOT", tmp_path)
    code = imc.run_import(tmp_path / "does-not-exist", dry_run=False)
    assert code == 2


def test_initial_permeability_handles_complex_real_table():
    """The MAS schema sometimes ships only a frequency-dependent table."""
    perm = {
        "complex": {
            "real": [
                {"frequency": 1_000_000.0, "value": 9.5},
                {"frequency": 100_000.0, "value": 9.1},
            ],
        },
    }
    val = imc._initial_permeability(perm)
    # Should pick the lowest-frequency row (most "DC-like" we have).
    assert val == 9.1
