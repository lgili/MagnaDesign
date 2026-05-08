# Add manufacturing-spec export (vendor-quotable PDF / Excel)

## Why

The HTML datasheet generated today is targeted at the **engineer
who designed the inductor**. It documents the design's electrical
characteristics, thermal behaviour, BOM costs and 3D views. It does
**not** answer the question a magnetics-vendor (Pulse, Würth,
TDK-EPC, custom-wind shops) needs answered to **quote and produce
the part**:

- Layer-by-layer winding sequence, with turn count per layer.
- Bobbin/core fitting tolerances.
- Air-gap shim spec (material, thickness, position).
- Insulation system: tape between layers, dielectric class,
  required hi-pot test voltage and dwell.
- Acceptance test plan: turn ratio, DC resistance, inductance
  (at frequencies + bias), hi-pot, IR.
- Marking + traceability (date code, lot, vendor PN).

Without these outputs, every prototype hand-off requires the
engineer to write a one-off Word document. Adoption inside a
formal supplier-quoting process is blocked: vendors return RFQs
unanswered when the spec is incomplete.

## What changes

A new `manufacturing/` module that takes the same
`(Spec, Core, Wire, Material, DesignResult)` tuple the datasheet
takes and emits two artefacts:

1. **`<part>_mfg_spec.pdf`** — IPC-A-610-style winding spec sheet.
   Single PDF (4–6 pages) covering: cover sheet with revision
   block; mechanical drawing (CAD-style, dimensioned); winding
   diagram (per-layer, color-coded), insulation stack-up; gap
   detail; acceptance test plan; signature block.
2. **`<part>_mfg_spec.xlsx`** — flat Excel file with one row per
   acceptance test for ERP / supplier portals that ingest tabular
   data instead of PDF.

A new "Generate manufacturing spec" entry lands under
**File → Export** (and in the command palette). The button is
**enabled only when worst-case has run** — the manufacturing spec
embeds the worst-case envelope, so it can't be generated from a
nominal-only design (forcing the team to do due diligence first).

## Impact

- **New module**: `pfc_inductor/manufacturing/` with
  `winding_layout.py`, `insulation_stack.py`, `pdf_writer.py`
  (using `reportlab`), `excel_writer.py` (using `openpyxl`,
  already a dep).
- **Bobbin / mechanical drawing**: reuse the parametric meshes
  from `visual/core_3d.py`, projected to 2D via matplotlib.
- **Insulation system**: bundled `data/insulation_classes.json`
  (Class B/F/H per IEC 60085, hi-pot V per IEC 61558).
- **New dependency**: `reportlab` (~1 MB; LGPL 2.1; widely used).
- **UI**: new menu entry + command palette command.
- **Tests**: `tests/test_manufacturing_*` — golden-file PDF/XLSX
  with stable-output settings; ~5 tests.
- **Capability added**: `manufacturing-export`.
- **Effort**: ~1 week (PDF layout dominates).
- **Closes**: vendor RFQ loop. After this lands, an engineer can
  go from spec → vendor-ready quote in 30 seconds.
