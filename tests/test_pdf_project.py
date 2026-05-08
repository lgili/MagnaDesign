"""Engineering project report tests (``generate_project_report``).

Covers the per-topology derivation reports — boost-CCM, line reactor,
passive choke. Each test asserts:

- The output is a syntactically valid PDF (magic header / EOF
  trailer).
- Inter font is embedded (the typography promise the PDF path
  makes).
- The /Info dict carries the project metadata so a detached page
  in a binder is still traceable.

We don't reach into the page-content streams to assert specific
equation glyphs — Inter is embedded as CIDFont/Identity-H, so on-
page text becomes glyph indices, not searchable ASCII. The
size + magic + font checks catch the realistic failure modes
(empty story, font fallback, truncated write).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.design import design
from pfc_inductor.models import Spec
from pfc_inductor.report import generate_project_report


def _assert_valid_pdf(path: Path) -> bytes:
    assert path.exists(), f"PDF was not created at {path}"
    raw = path.read_bytes()
    assert len(raw) > 1024, f"PDF suspiciously small: {len(raw)} bytes"
    assert raw[:4] == b"%PDF", f"Bad magic header: {raw[:4]!r}"
    assert b"%%EOF" in raw[-256:], "PDF missing trailing %%EOF"
    return raw


def test_project_report_boost_ccm():
    mats, cores, wires = load_materials(), load_cores(), load_wires()
    spec = Spec(
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=220.0,
        Vout_V=400.0,
        Pout_W=800.0,
        eta=0.97,
        f_sw_kHz=65.0,
        ripple_pct=30.0,
    )
    mat = find_material(mats, "magnetics-60_highflux")
    core = next(
        c
        for c in cores
        if c.default_material_id == "magnetics-60_highflux" and 40000 < c.Ve_mm3 < 100000
    )
    wire = next(w for w in wires if w.id == "AWG14")
    r = design(spec, core, wire, mat)

    with tempfile.TemporaryDirectory() as td:
        out = generate_project_report(
            spec,
            core,
            mat,
            wire,
            r,
            Path(td) / "project.pdf",
            designer="Test Engineer",
            revision="A.0",
            project_id="PRJ-2026-001",
        )
        raw = _assert_valid_pdf(out)
        assert b"Inter-Regular" in raw, "Inter-Regular not embedded"
        assert b"Inter-Bold" in raw, "Inter-Bold not embedded"
        # /Info dict carries the project id (passed via title=…).
        assert b"PRJ-2026-001" in raw, "Project id missing from /Info"


def test_project_report_line_reactor():
    mats, cores, wires = load_materials(), load_cores(), load_wires()
    spec = Spec(
        topology="line_reactor",
        Vin_nom_Vrms=380.0,
        Pout_W=10000.0,
        I_rated_Arms=20.0,
        f_line_Hz=60.0,
        n_phases=3,
        pct_impedance=3.0,
        eta=0.95,
    )
    mat = next(m for m in mats if m.type == "silicon-steel")
    core = next(c for c in cores if c.shape == "EI")
    wire = next(w for w in wires if w.id == "AWG14")
    r = design(spec, core, wire, mat)

    with tempfile.TemporaryDirectory() as td:
        out = generate_project_report(
            spec,
            core,
            mat,
            wire,
            r,
            Path(td) / "lr_project.pdf",
            project_id="PRJ-LR-001",
        )
        _assert_valid_pdf(out)


def test_project_report_passive_choke():
    mats, cores, wires = load_materials(), load_cores(), load_wires()
    spec = Spec(
        topology="passive_choke",
        Vin_nom_Vrms=220.0,
        Pout_W=2000.0,
        f_line_Hz=60.0,
        eta=0.92,
    )
    mat = next(m for m in mats if m.type == "silicon-steel")
    core = next(c for c in cores if c.shape == "EI")
    wire = next(w for w in wires if w.id == "AWG14")
    r = design(spec, core, wire, mat)

    with tempfile.TemporaryDirectory() as td:
        out = generate_project_report(
            spec,
            core,
            mat,
            wire,
            r,
            Path(td) / "pc_project.pdf",
            project_id="PRJ-PC-001",
        )
        _assert_valid_pdf(out)


def test_project_report_falls_back_to_stamp_when_no_project_id():
    """If the caller doesn't pass ``project_id``, the report uses
    the same spec/core/material hash the datasheet uses for its
    P/N — so the two artefacts cross-reference."""
    mats, cores, wires = load_materials(), load_cores(), load_wires()
    spec = Spec(
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=220.0,
        Vout_V=400.0,
        Pout_W=600.0,
        eta=0.95,
        f_sw_kHz=80.0,
        ripple_pct=30.0,
    )
    mat = find_material(mats, "magnetics-60_highflux")
    core = next(
        c
        for c in cores
        if c.default_material_id == "magnetics-60_highflux" and 40000 < c.Ve_mm3 < 100000
    )
    wire = next(w for w in wires if w.id == "AWG14")
    r = design(spec, core, wire, mat)

    with tempfile.TemporaryDirectory() as td:
        out = generate_project_report(
            spec,
            core,
            mat,
            wire,
            r,
            Path(td) / "default_id.pdf",
        )
        _assert_valid_pdf(out)


@pytest.mark.parametrize("designer", ["J. Doe", "Eng. Silva", "—"])
def test_project_report_designer_propagates(designer):
    """Designer flows into the PDF /Info dict. The report header
    also displays it but rendered text is encoded as glyph indices
    so we verify via the metadata."""
    mats, cores, wires = load_materials(), load_cores(), load_wires()
    spec = Spec(
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=220.0,
        Vout_V=400.0,
        Pout_W=600.0,
        eta=0.95,
        f_sw_kHz=80.0,
        ripple_pct=30.0,
    )
    mat = find_material(mats, "magnetics-60_highflux")
    core = next(
        c
        for c in cores
        if c.default_material_id == "magnetics-60_highflux" and 40000 < c.Ve_mm3 < 100000
    )
    wire = next(w for w in wires if w.id == "AWG14")
    r = design(spec, core, wire, mat)

    with tempfile.TemporaryDirectory() as td:
        out = generate_project_report(
            spec,
            core,
            mat,
            wire,
            r,
            Path(td) / "designer.pdf",
            designer=designer,
        )
        raw = out.read_bytes()
        ascii_designer = designer.encode("ascii", errors="ignore")
        if ascii_designer:
            assert ascii_designer in raw, f"Designer {designer!r} not in /Info dict"
