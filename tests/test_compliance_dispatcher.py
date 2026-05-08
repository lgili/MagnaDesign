"""Compliance dispatcher + PDF writer tests.

Covers the engine→standards bridge. The IEC 61000-3-2 numerical
limits already have their own coverage in
``test_iec61000_3_2.py``; this file exercises the dispatcher
glue (topology routing, harmonic-spectrum extraction, verdict
aggregation) and a PDF smoke test that asserts the file is
written + non-empty.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from pfc_inductor.compliance import (
    ComplianceBundle,
    StandardResult,
    applicable_standards,
    evaluate,
)
from pfc_inductor.compliance.pdf_writer import write_compliance_pdf
from pfc_inductor.data_loader import (
    ensure_user_data,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.design import design as run_design
from pfc_inductor.models import Spec


# ---------------------------------------------------------------------------
# Fixtures — module-scoped catalogue + paired feasible designs
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def catalogue():
    ensure_user_data()
    return load_materials(), load_cores(), load_wires()


@pytest.fixture(scope="module")
def line_reactor_design(catalogue):
    """Single-phase line reactor — the canonical IEC 61000-3-2
    Class D specimen. Feasible at the bundled C058777A2 + AWG14."""
    mats, cores, wires = catalogue
    spec = Spec(
        topology="line_reactor",
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vin_nom_Vrms=230,
        Pout_W=600, n_phases=1, L_req_mH=10.0,
        I_rated_Arms=2.6, T_amb_C=40,
    )
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores
                if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    result = run_design(spec, core, wire, mat)
    return spec, core, wire, mat, result


@pytest.fixture(scope="module")
def boost_design(catalogue):
    """Active boost-PFC — engine reports zero higher-order
    harmonics. Compliance dispatcher should land on PASS with a
    "trivially compliant + measurement still required" note."""
    mats, cores, wires = catalogue
    spec = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=65, ripple_pct=20, T_amb_C=40,
    )
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores
                if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    result = run_design(spec, core, wire, mat)
    return spec, core, wire, mat, result


# ---------------------------------------------------------------------------
# applicable_standards
# ---------------------------------------------------------------------------
def test_applicable_standards_includes_iec_for_eu_region(boost_design) -> None:
    spec = boost_design[0]
    assert "IEC 61000-3-2" in applicable_standards(spec, "EU")


def test_applicable_standards_excludes_iec_for_us_region(boost_design) -> None:
    """The US region routes through UL eventually; today the
    dispatcher only knows IEC, so US returns an empty list. This
    is a regression contract — when UL 1411 lands the test moves
    to assert UL is included, not that IEC is."""
    spec = boost_design[0]
    assert applicable_standards(spec, "US") == []


# ---------------------------------------------------------------------------
# evaluate — line reactor (real harmonic content)
# ---------------------------------------------------------------------------
def test_line_reactor_compliance_returns_iec_result(
    line_reactor_design,
) -> None:
    spec, core, wire, mat, result = line_reactor_design
    bundle = evaluate(spec, core, wire, mat, result,
                      project_name="lr-test", region="EU")
    assert isinstance(bundle, ComplianceBundle)
    assert bundle.project_name == "lr-test"
    assert len(bundle.standards) == 1
    assert bundle.standards[0].standard == "IEC 61000-3-2"


def test_line_reactor_iec_result_has_per_harmonic_rows(
    line_reactor_design,
) -> None:
    """A diode-rectified reactor produces measurable harmonic
    content at h=3, 5, 7, 9, 11 — every row in the result
    table must carry the schema the PDF writer expects."""
    spec, core, wire, mat, result = line_reactor_design
    bundle = evaluate(spec, core, wire, mat, result, region="EU")
    std = bundle.standards[0]
    assert std.rows, "expected at least one harmonic row"
    for label, value, limit, margin, passed in std.rows:
        assert label.startswith("n = ")
        assert value.endswith(" mA")
        assert limit.endswith(" mA")
        assert isinstance(margin, float)
        assert isinstance(passed, bool), (
            "passed must be a Python bool (numpy.bool_ trips JSON)"
        )


def test_line_reactor_overall_aggregates_per_standard(
    line_reactor_design,
) -> None:
    """The 1φ line reactor at 230 V / 600 W typically fails Class D
    at h=5 — covered by the existing iec61000_3_2 evaluator. The
    dispatcher's ``overall`` is the worst per-standard verdict,
    which here equals the single standard's verdict."""
    spec, core, wire, mat, result = line_reactor_design
    bundle = evaluate(spec, core, wire, mat, result, region="EU")
    assert bundle.overall == bundle.standards[0].conclusion


# ---------------------------------------------------------------------------
# evaluate — boost-PFC (no measurable higher-order harmonics)
# ---------------------------------------------------------------------------
def test_boost_pfc_passes_with_measurement_caveat(boost_design) -> None:
    """Active boost-PFC should land on PASS with the
    "LISN-measurement-still-required" note — that's the auditor-
    safe outcome when the engine cannot evaluate real harmonics."""
    spec, core, wire, mat, result = boost_design
    bundle = evaluate(spec, core, wire, mat, result, region="EU")
    std = bundle.standards[0]
    assert std.conclusion == "PASS"
    assert "LISN" in std.summary
    # No rows for the boost case — trivially compliant by
    # construction, the PDF writer's table reads as empty.
    assert std.rows == []


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def test_compliance_bundle_overall_picks_worst() -> None:
    """Synthetic bundle with mixed verdicts — the overall must
    be FAIL if any standard fails, else MARGINAL if any is
    marginal, else PASS."""
    bundle = ComplianceBundle(
        project_name="x", topology="boost_ccm", region="EU",
        standards=[
            StandardResult(standard="A", edition="1", scope="",
                           conclusion="PASS", summary=""),
            StandardResult(standard="B", edition="1", scope="",
                           conclusion="MARGINAL", summary=""),
            StandardResult(standard="C", edition="1", scope="",
                           conclusion="FAIL", summary=""),
        ],
    )
    assert bundle.overall == "FAIL"


def test_empty_bundle_overall_is_not_applicable() -> None:
    bundle = ComplianceBundle(
        project_name="x", topology="boost_ccm", region="EU",
        standards=[],
    )
    assert bundle.overall == "NOT APPLICABLE"


# ---------------------------------------------------------------------------
# PDF writer
# ---------------------------------------------------------------------------
def test_pdf_writer_produces_non_empty_file(
    line_reactor_design, tmp_path: Path,
) -> None:
    """Smoke test — full pipeline (engine → dispatcher → PDF).
    We don't assert PDF content (golden-file diffs would be too
    fragile across reportlab versions); we assert the file
    exists, parses as a PDF, and has at least one page worth of
    bytes."""
    spec, core, wire, mat, result = line_reactor_design
    bundle = evaluate(spec, core, wire, mat, result,
                      project_name="pdf-smoke", region="EU")
    out = write_compliance_pdf(
        bundle, tmp_path / "compliance.pdf",
        app_version="0.1.0", git_sha="abc1234",
    )
    assert out.is_file()
    payload = out.read_bytes()
    # ReportLab always emits a `%PDF-` header. Bytes >= 1 KB
    # rules out an "empty document with header only" failure
    # mode.
    assert payload.startswith(b"%PDF-"), "not a PDF"
    assert len(payload) > 5_000, f"PDF suspiciously small: {len(payload)} B"


def test_pdf_writer_handles_no_standards_gracefully(tmp_path: Path) -> None:
    """An empty bundle still produces a renderable cover page
    with a "no applicable standards" notice — the writer never
    raises on a no-op bundle."""
    bundle = ComplianceBundle(
        project_name="empty", topology="boost_ccm", region="US",
        standards=[],
    )
    out = write_compliance_pdf(
        bundle, tmp_path / "empty.pdf", app_version="0.1.0",
    )
    assert out.is_file()
    assert out.read_bytes().startswith(b"%PDF-")
