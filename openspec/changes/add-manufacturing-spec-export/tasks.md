# Tasks — add-manufacturing-spec-export

## Phase 1 — Winding-layout solver

- [ ] `pfc_inductor/manufacturing/winding_layout.py`:
      - `LayerPlan(turns_per_layer, n_layers, bobbin_used_pct,
        per_layer_dia_mm)` from `(N, wire, core)`.
      - Honours bobbin geometry (window height / breadth) and
        adds insulation tape thickness (default 0.05 mm Mylar)
        between layers.
      - Returns warnings when `bobbin_used_pct > 90 %` (will
        be hard to wind) or `< 30 %` (waste).
- [ ] `tests/test_winding_layout.py`: golden values for a 30-turn
      AWG 14 design on a Magnetics 60 µ HighFlux 47928 toroid.

## Phase 2 — Insulation system + acceptance tests

- [ ] `data/insulation_classes.json`: Class B (130 °C) / F (155 °C)
      / H (180 °C) per IEC 60085. Per-class tape Tg, dielectric
      strength.
- [ ] `data/hi_pot_calculators.json`: hi-pot test voltage per
      working voltage per IEC 61558 (`V_hipot = 2 × V_work + 1000`).
- [ ] `pfc_inductor/manufacturing/insulation_stack.py`:
      - `pick_class(spec)` → "B" / "F" / "H" based on `T_max + Margin`.
      - `acceptance_tests(spec, core, wire, design_result)` →
        `list[AcceptanceTest]` rows: name, condition, expected,
        tolerance, instrument.
- [ ] Reference IEC standards in code comments + the bundled JSON.

## Phase 3 — PDF writer

- [ ] Add `reportlab` to `pyproject.toml` deps.
- [ ] `pfc_inductor/manufacturing/pdf_writer.py`:
      - Cover page: revision block, designer, date, MagnaDesign
        version.
      - Mechanical drawing: dimensioned 2D projection (top + side)
        of the core, exported via matplotlib + reportlab embed.
      - Winding diagram: layer-by-layer color-coded view with
        tape stack-up callouts.
      - Air-gap detail: shim material + thickness, position
        diagram (when applicable).
      - Acceptance test table: one row per
        `acceptance_tests()` entry.
      - Signature block: designer / approver / vendor.
- [ ] Golden-file test using a deterministic seed for matplotlib
      rendering (`tests/golden/manufacturing/<id>.pdf`).

## Phase 4 — Excel writer

- [ ] `pfc_inductor/manufacturing/excel_writer.py`:
      - One sheet "Specs" with electrical / mechanical / acceptance
        rows (key, value, unit, tolerance).
      - One sheet "BOM" with vendor PN, qty, $/unit, total.
      - One sheet "Tests" mirroring the PDF acceptance plan.
- [ ] Test: round-trip read with `openpyxl` → verify cells.

## Phase 5 — UI integration

- [ ] `MainWindow._export_manufacturing()` handler.
- [ ] File → Export → "Manufacturing spec…" menu entry.
- [ ] Command palette: "Export manufacturing spec".
- [ ] Action button on the Export tab.
- [ ] Disabled state + tooltip when no `WorstCaseSummary` is
      cached: "Run Worst-case first — manufacturing spec embeds
      the envelope".
- [ ] Toast on success ("Manufacturing spec saved to …  · Open").

## Phase 6 — Docs + release

- [ ] `docs/manufacturing-spec.md`: example PDF screenshot, the
      vendor-portal happy-path workflow (RFQ ↔ spec ↔ quote).
- [ ] Sample PDFs for the three reference designs from
      `add-validation-reference-set` shipped under
      `docs/manufacturing/samples/`.
- [ ] CHANGELOG + README update.
