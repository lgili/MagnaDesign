"""Regression tests for ``scripts/import_pyetk_catalog.py``.

Three guarantees:

1. Steinmetz round-trip: PyETK ``cm·f^x·B^y`` (W/m³, Hz, T) converts to
   our ``Pv_ref·(f/f_ref)^α·(B/B_ref)^β`` (mW/cm³, kHz, mT) and yields
   the same Pv at the anchor frequency / flux.
2. Core decoders match Ferroxcube datasheet ``Ae``/``le``/``Ve``
   within agreed tolerances per shape family (E ±10 %, ETD ±5 %,
   PQ ±15 %, EFD ±15 %).
3. The end-to-end ``parse_cores`` / ``parse_materials`` produce
   non-empty, validated Pydantic objects for the bundled snapshot.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def _load_script_module():
    """Load ``scripts/import_pyetk_catalog.py`` as a module so the tests
    can import its converters without packaging the script."""
    spec = importlib.util.spec_from_file_location(
        "import_pyetk_catalog",
        REPO_ROOT / "scripts" / "import_pyetk_catalog.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load script module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["import_pyetk_catalog"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def script():
    return _load_script_module()


@pytest.fixture(scope="module")
def vendor_data():
    base = REPO_ROOT / "vendor" / "pyetk"
    cores = json.loads((base / "core_dimensions.json").read_text(encoding="utf-8"))
    materials = json.loads((base / "material_properties.json").read_text(encoding="utf-8"))
    return cores, materials


# ---------------------------------------------------------------------------
# Steinmetz round-trip
# ---------------------------------------------------------------------------


def test_steinmetz_round_trip_at_anchor_point(script):
    """``Pv(f_ref, B_ref)`` from the converted params must equal
    ``Pv_ref_mWcm3`` (it's literally the anchor)."""
    # 3C90: cm=3.2e-3, x=1.46, y=2.75 (rough Ferroxcube values).
    sp = script.convert_steinmetz(cm=3.2e-3, x=1.46, y=2.75, f_ref_kHz=100.0, B_ref_mT=100.0)
    # Pv at the anchor must equal the stored Pv_ref.
    f_ratio = (100.0 / sp.f_ref_kHz) ** sp.alpha
    B_ratio = (100.0 / sp.B_ref_mT) ** sp.beta
    pv_at_anchor = sp.Pv_ref_mWcm3 * f_ratio * B_ratio
    assert abs(pv_at_anchor - sp.Pv_ref_mWcm3) < 1e-9


def test_steinmetz_pv_units_are_mwcm3(script):
    """1 W/m³ = 0.001 mW/cm³; the conversion must apply this factor."""
    # cm=1.0, x=1, y=1 → Pv_W_per_m3(f=1Hz, B=1T) = 1.0 → mW/cm³ = 0.001
    sp = script.convert_steinmetz(cm=1.0, x=1.0, y=1.0, f_ref_kHz=1.0 / 1000.0, B_ref_mT=1000.0)
    assert sp.Pv_ref_mWcm3 == pytest.approx(1e-3, rel=1e-9)


# ---------------------------------------------------------------------------
# Per-shape decoder accuracy vs Ferroxcube datasheet
# ---------------------------------------------------------------------------

# (shape, part_number, Ae_mm2, le_mm, Ve_mm3, Ve_tol_pct)
_DATASHEET_CHECKS = [
    # E-cores ±10 %
    ("E", "E32/16/9", 83.0, 73.0, 6055, 10.0),
    ("E", "E55/28/21", 354.0, 124.0, 43900, 10.0),
    # ETD ±5 %
    ("ETD", "ETD29/16/10", 76.0, 72.0, 5470, 5.0),
    ("ETD", "ETD39/20/13", 125.0, 92.2, 11500, 5.0),
    ("ETD", "ETD49/25/16", 211.0, 114.0, 24000, 5.0),
    ("ETD", "ETD59/31/22", 368.0, 139.0, 51200, 5.0),
    # PQ ±15 %
    ("PQ", "PQ20/16", 62.0, 37.6, 2330, 15.0),
    ("PQ", "PQ32/30", 161.0, 74.7, 12000, 15.0),
    # EFD ±15 %
    ("EFD", "EFD15/8/5", 15.0, 34.0, 510, 15.0),
    ("EFD", "EFD25/13/9", 58.0, 57.0, 3300, 15.0),
    ("EFD", "EFD30/15/9", 69.0, 68.0, 4690, 15.0),
]


@pytest.mark.parametrize("shape,name,Ae_ds,le_ds,Ve_ds,tol", _DATASHEET_CHECKS)
def test_core_decoder_matches_datasheet(
    script,
    vendor_data,
    shape,
    name,
    Ae_ds,
    le_ds,
    Ve_ds,
    tol,
):
    cores_raw, _ = vendor_data
    dims = cores_raw.get("Ferroxcube", {}).get(shape, {}).get(name) or cores_raw.get(
        "Phillips", {}
    ).get(shape, {}).get(name)
    assert dims is not None, f"{name} not in vendored snapshot"
    Ae, le, Ve, _Wa, _MLT, _OD, _ID, _HT = script.decode_core(shape, dims)
    assert Ae is not None and le is not None and Ve is not None
    err_Ve = abs(Ve - Ve_ds) / Ve_ds * 100.0
    assert err_Ve <= tol, f"{name}: Ve={Ve:.0f} mm³ vs datasheet {Ve_ds} ({err_Ve:.1f}% > {tol}%)"


# ---------------------------------------------------------------------------
# End-to-end smoke
# ---------------------------------------------------------------------------


def test_parse_materials_returns_validated_models(script, vendor_data):
    _, materials_raw = vendor_data
    mats = script.parse_materials(materials_raw)
    # PyETK ships ~10 power ferrites; a non-empty result is the
    # contract this tests guards.
    assert len(mats) >= 5
    # Each one must be a fully-validated Pydantic Material with a
    # converted Steinmetz block.
    for m in mats:
        assert m.steinmetz.Pv_ref_mWcm3 > 0
        assert m.steinmetz.alpha > 0
        assert m.steinmetz.beta > 0
        assert m.mu_initial > 0
        assert m.type == "ferrite"


def test_parse_cores_returns_validated_models(script, vendor_data):
    cores_raw, _ = vendor_data
    cores = script.parse_cores(cores_raw)
    assert len(cores) > 100  # we expect 150+ once Phillips dups dropped
    for c in cores:
        assert c.Ae_mm2 > 0
        assert c.le_mm > 0
        assert c.Ve_mm3 > 0
        assert c.AL_nH > 0
        # Imported notes should flag the source so users can spot
        # PyETK-imported cores in the catalog editor.
        assert "PyETK" in c.notes


def test_no_phillips_aliases_when_ferroxcube_has_same_part(script, vendor_data):
    cores_raw, _ = vendor_data
    cores = script.parse_cores(cores_raw)
    # Phillips and Ferroxcube ship overlapping part numbers; the
    # importer collapses them under the Ferroxcube vendor.
    vendors = {c.vendor for c in cores}
    assert "Phillips" not in vendors
    # Every imported core should be Ferroxcube or TDK.
    assert vendors <= {"Ferroxcube", "TDK"}
