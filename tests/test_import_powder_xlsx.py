"""Regression tests for ``scripts/import_powder_xlsx.py``.

The fixture ``tests/fixtures/powder_cores_sample.xlsx`` mirrors the
public Magnetics ``Inductor Designer`` Excel layout: headers like
``Part Number`` / ``Effective Area [cm²]`` / ``AL [nH/N²]``. It
includes one bad row (missing Ae) and one empty row to exercise the
defensive skips.

Three guarantees:

1. Column auto-detection picks the right slot for each canonical
   field (resolves the ``id`` vs ``ID`` ambiguity).
2. Unit detection converts ``cm²`` → mm², ``cm³`` → mm³, ``cm`` →
   mm so the Core model receives our internal SI-mm units.
3. End-to-end ``parse_xlsx`` returns validated Core objects with
   manufacturer-published values intact (Ae=0.245 cm² →
   24.5 mm², le=5.67 cm → 56.7 mm).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "powder_cores_sample.xlsx"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "import_powder_xlsx",
        REPO_ROOT / "scripts" / "import_powder_xlsx.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load script")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["import_powder_xlsx"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def script():
    return _load_script()


# ---------------------------------------------------------------------------
# Column / unit detection
# ---------------------------------------------------------------------------

def test_normalise_strips_unit_decoration(script):
    assert script._normalise("Effective Area [cm²]") == "effectiveareacm"
    assert script._normalise("AL [nH/N²]") == "alnhn"


def test_detect_columns_resolves_id_vs_inner_diameter(script):
    """`Part Number` and `Inner Diameter [mm]` both contain the
    substring ``id``. ``part_number`` must win that column race."""
    headers = [
        "Part Number", "Material", "Effective Area [cm²]",
        "Effective Path Length [cm]", "Inner Diameter [mm]",
    ]
    cols = script._detect_columns(headers)
    assert cols["part_number"] == 0
    # ``ID`` claims its own column (4), not column 0.
    assert cols.get("ID") == 4


def test_unit_detection_picks_cm_squared(script):
    headers = ["Part Number", "Effective Area [cm²]"]
    cols = script._detect_columns(headers)
    units = script._detect_units(headers, cols)
    assert units.Ae == "cm2"


def test_unit_detection_falls_back_to_default_when_header_silent(script):
    headers = ["Part Number", "Ae"]
    cols = script._detect_columns(headers)
    units = script._detect_units(headers, cols)
    assert units.Ae == "mm2"


# ---------------------------------------------------------------------------
# End-to-end via the synthetic fixture
# ---------------------------------------------------------------------------

def test_parse_xlsx_returns_three_valid_cores(script):
    if not FIXTURE.exists():
        pytest.skip(f"fixture missing: {FIXTURE}")
    stats = script.parse_xlsx(FIXTURE, vendor_default="Magnetics")[1]
    assert stats["imported"] == 3
    assert stats["skipped_empty"] == 1
    assert stats["skipped_bad"] == 1


def test_parse_xlsx_converts_cm_to_mm(script):
    """0058083A2 datasheet: Ae=0.245 cm² → 24.5 mm²; le=5.67 cm →
    56.7 mm. The unit conversion must apply correctly."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture missing: {FIXTURE}")
    cores, _ = script.parse_xlsx(FIXTURE, vendor_default="Magnetics")
    by_pn = {c.part_number: c for c in cores}
    c = by_pn["0058083A2"]
    assert abs(c.Ae_mm2 - 24.5) < 0.1
    assert abs(c.le_mm - 56.7) < 0.1
    # Ve: 1.39 cm³ → 1390 mm³.
    assert abs(c.Ve_mm3 - 1390.0) < 1.0
    # AL passes through unchanged (already in nH/N²).
    assert c.AL_nH == pytest.approx(63.0)


def test_parse_xlsx_tags_source(script):
    """Every imported entry must carry the powder_xlsx source tag
    so the loader's curated filter excludes it."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture missing: {FIXTURE}")
    cores, _ = script.parse_xlsx(FIXTURE, vendor_default="Magnetics")
    for c in cores:
        assert "Magnetics" in c.notes
        assert c.id.startswith("powder_xlsx-magnetics-")


def test_infer_shape_detects_iec_prefix(script):
    """``EE 24/24/8`` → ``EE`` (E-pair), ``ETD 39`` → ``ETD``."""
    assert script._infer_shape("EE 24/24/8") == "EE"
    assert script._infer_shape("ETD 39/20/13") == "ETD"
    assert script._infer_shape("0058083A2") == "T"  # default fallback
