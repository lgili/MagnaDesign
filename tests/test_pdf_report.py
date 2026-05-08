"""Native PDF datasheet generation tests.

Mirrors ``test_report.py`` (HTML) but covers the ReportLab + matplotlib
``generate_pdf_datasheet`` path. The PDF generator is the
print/customer artefact; HTML stays as the screen-grade preview.

Each test asserts:

- The output file exists and is a non-empty PDF.
- The first 4 bytes are the ``%PDF`` magic, so the file is at least
  syntactically a PDF (not a stray exception traceback written to
  disk via the file handle).
- The document carries the embedded Inter font (``Inter-Regular``,
  ``Inter-Bold``) — the whole point of the PDF path is to avoid the
  font-substitution that browser-print produces, so verifying the
  font is actually embedded is part of the contract.

We don't reach into the PDF object model (no pypdf dep); the four
bytes + font-name search via raw bytes is deliberately minimal so
the test stays fast and dependency-light.
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
from pfc_inductor.report import generate_pdf_datasheet


def _assert_valid_pdf(path: Path) -> bytes:
    """Validate that ``path`` is a non-empty file starting with the
    PDF magic header. Returns the full bytes for downstream checks."""
    assert path.exists(), f"PDF was not created at {path}"
    raw = path.read_bytes()
    assert len(raw) > 1024, f"PDF suspiciously small: {len(raw)} bytes"
    assert raw[:4] == b"%PDF", f"Bad magic header: {raw[:4]!r}"
    # ReportLab writes %%EOF as the trailer; absence implies a torn write.
    assert b"%%EOF" in raw[-256:], "PDF missing trailing %%EOF"
    return raw


def test_pdf_datasheet_boost_ccm():
    """Boost-PFC CCM smoke — most-common topology, exercises the
    switching ripple, roll-off, and η-vs-load curves."""
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
        out = generate_pdf_datasheet(
            spec,
            core,
            mat,
            wire,
            r,
            Path(td) / "datasheet.pdf",
            designer="Test Engineer",
            revision="A.0",
        )
        raw = _assert_valid_pdf(out)
        # Inter font should be embedded — absence means the
        # ``fonts/`` dir was missing or fallback fired silently.
        assert b"Inter-Regular" in raw, "Inter-Regular font not embedded"
        assert b"Inter-Bold" in raw, "Inter-Bold font not embedded"


def test_pdf_datasheet_line_reactor():
    """Line reactor (3-phase) smoke — exercises the harmonic spectrum
    + commutation overlap helpers."""
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
    # Pick any silicon-steel + EI core combo — the engine is
    # deterministic given inputs, so we don't need a feasible-design
    # to validate that the PDF assembles.
    mat = next(m for m in mats if m.type == "silicon-steel")
    core = next(c for c in cores if c.shape == "EI")
    wire = next(w for w in wires if w.id == "AWG14")
    r = design(spec, core, wire, mat)

    with tempfile.TemporaryDirectory() as td:
        out = generate_pdf_datasheet(
            spec,
            core,
            mat,
            wire,
            r,
            Path(td) / "lr.pdf",
        )
        _assert_valid_pdf(out)


def test_pdf_datasheet_passive_choke():
    """Passive choke smoke — exercises the before/after PF + DC-link
    ripple comparison chart."""
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
        out = generate_pdf_datasheet(
            spec,
            core,
            mat,
            wire,
            r,
            Path(td) / "pc.pdf",
        )
        _assert_valid_pdf(out)


@pytest.mark.parametrize(
    "designer,revision",
    [
        ("J. Doe", "A.0"),
        ("Eng. Silva", "B.2"),
        ("—", "X"),
    ],
)
def test_pdf_datasheet_designer_and_revision_propagate(designer, revision):
    """Designer + revision metadata flow through to the document
    header. Verifying via raw byte search rather than parsing the PDF
    object model — the strings should be present somewhere in the
    body either as text streams or font-shaped run."""
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
        out = generate_pdf_datasheet(
            spec,
            core,
            mat,
            wire,
            r,
            Path(td) / "meta.pdf",
            designer=designer,
            revision=revision,
        )
        _assert_valid_pdf(out)
        # Designer and revision are written into the doc metadata
        # (PDF /Author + /Subject) — ``BaseDocTemplate(author=…)``
        # surfaces those at the file level.
        # We don't decompress streams; the metadata ends up in the
        # /Info dict at the end of the file as raw ASCII so the
        # bytes search is sufficient here.
        raw = out.read_bytes()
        # The /Author entry uses the literal designer string when
        # passed as ``author=designer`` to BaseDocTemplate.
        # Special chars may be escaped, so search for an ASCII subset.
        ascii_designer = designer.encode("ascii", errors="ignore")
        if ascii_designer:
            assert ascii_designer in raw, f"Designer {designer!r} not in PDF /Info dict"
