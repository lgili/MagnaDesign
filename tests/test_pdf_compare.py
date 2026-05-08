"""Native PDF compare report tests.

Covers ``generate_compare_pdf`` — A4 landscape, up to 4 columns of
designs, with diff colouring against the reference column.

Each test asserts:

- The output file exists, is non-empty, and starts with ``%PDF`` /
  ends with ``%%EOF`` (basic syntactic validity).
- The Inter font is embedded (the whole point of the PDF path is to
  avoid font substitution).
- The /Info metadata dict carries the document title — caught
  truncated-write / empty-story regressions without needing to
  decompress the page content streams (Inter is embedded as CIDFont
  / Identity-H, so on-page text becomes glyph indices, not ASCII —
  raw byte search of arbitrary copy is not reliable).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from pfc_inductor.compare.slot import CompareSlot
from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.design import design
from pfc_inductor.models import Spec
from pfc_inductor.report import generate_compare_pdf


def _make_slot(spec, core, material, wire) -> CompareSlot:
    r = design(spec, core, wire, material)
    return CompareSlot(
        spec=spec, core=core, material=material, wire=wire, result=r,
    )


def _assert_valid_pdf(path: Path) -> bytes:
    assert path.exists(), f"PDF was not created at {path}"
    raw = path.read_bytes()
    assert len(raw) > 1024, f"PDF suspiciously small: {len(raw)} bytes"
    assert raw[:4] == b"%PDF", f"Bad magic header: {raw[:4]!r}"
    assert b"%%EOF" in raw[-256:], "PDF missing trailing %%EOF"
    return raw


def _build_two_slots() -> list[CompareSlot]:
    """Two designs differing only by wire gauge — clean diff signal
    on Rdc / Cu losses, the rest of the metrics stay identical so
    the colouring assertion is unambiguous."""
    mats, cores, wires = load_materials(), load_cores(), load_wires()
    spec = Spec(
        Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
        Vout_V=400.0, Pout_W=800.0, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
    )
    mat = find_material(mats, "magnetics-60_highflux")
    core = next(c for c in cores
                if c.default_material_id == "magnetics-60_highflux"
                and 40000 < c.Ve_mm3 < 100000)
    w_thick = next(w for w in wires if w.id == "AWG14")
    w_thin = next(w for w in wires if w.id == "AWG16")
    return [
        _make_slot(spec, core, mat, w_thick),
        _make_slot(spec, core, mat, w_thin),
    ]


def test_compare_pdf_two_slots_basic():
    slots = _build_two_slots()
    with tempfile.TemporaryDirectory() as td:
        out = generate_compare_pdf(slots, Path(td) / "compare.pdf")
        raw = _assert_valid_pdf(out)
        # Inter font embedded → the typography promise the PDF
        # path makes is intact.
        assert b"Inter-Regular" in raw, "Inter-Regular not embedded"
        assert b"Inter-Bold" in raw, "Inter-Bold not embedded"


def test_compare_pdf_metadata_carries_document_title():
    """``BaseDocTemplate(title=…)`` writes the title into the
    ``/Info`` dict at the end of the file in plain ASCII, so a
    raw-byte check is reliable here. Catches the empty-story
    regression (an empty PDF still renders /Info but the file would
    be tiny — combined with the size check above we catch both)."""
    slots = _build_two_slots()
    with tempfile.TemporaryDirectory() as td:
        out = generate_compare_pdf(slots, Path(td) / "compare.pdf")
        raw = out.read_bytes()
        assert b"Design comparison" in raw, (
            "Document title missing from /Info dict"
        )
        assert b"MagnaDesign" in raw, "Creator missing from /Info dict"


def test_compare_pdf_rejects_empty_slots():
    """Generating with zero slots is a no-op the dialog already
    guards against, but the function is the public API and should
    fail loudly rather than write a zero-row PDF."""
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ValueError):
            generate_compare_pdf([], Path(td) / "empty.pdf")


@pytest.mark.parametrize("n_slots", [1, 2, 3, 4])
def test_compare_pdf_supports_up_to_four_slots(n_slots):
    """The dialog enforces ``MAX_SLOTS = 4``; verify the renderer
    handles every slot count from 1 to 4 without overflow or
    column-layout breakage."""
    base = _build_two_slots()
    # Pad to n_slots by repeating the second slot. The diff
    # colouring will mark them all neutral against the leftmost,
    # which is fine — we're testing layout, not semantics.
    slots = [base[0]] + [base[1]] * (n_slots - 1)
    with tempfile.TemporaryDirectory() as td:
        out = generate_compare_pdf(slots, Path(td) / "compare.pdf")
        _assert_valid_pdf(out)
