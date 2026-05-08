# Tasks — add-manufacturing-spec-export

All shipped in `65b6ada feat(manufacturing): vendor-quotable
spec export — PDF + XLSX + CLI` plus follow-ups for the CLI
(``magnadesign mfg-spec``).

## Phase 1 — Winding-layout solver

- [x] `pfc_inductor/manufacturing/winding_layout.py` —
      ``plan_winding(core, wire, n_turns)`` returns a
      ``WindingPlan`` with per-layer breakdown, bobbin fill %,
      stack height + warnings (overfill > 90 %, underfill < 30 %,
      won't-fit > 100 %). Honours bobbin geometry (toroid
      ``π·ID`` + radial window; EE/ETD ``HT × Wa/HT``); falls
      back to ``ID = 2·√(Wa/π)`` for MAS-imported toroids that
      ship without OD/ID.
- [x] `tests/test_manufacturing.py` covers the happy path,
      zero-turns / overfill / underfill warning emission, and
      the geometry-fallback branch.

## Phase 2 — Insulation system + acceptance tests

- [~] `data/insulation_classes.json`. *Deferred — the lookup
      table lives inline in `insulation_stack.py` as a frozen
      ``INSULATION_CLASSES`` dict so the consumer doesn't pay
      a JSON-load cost on every CLI invocation. Promote to JSON
      when the table grows past ~10 rows; today it covers IEC
      60085 Class A / B / F / H.*
- [~] `data/hi_pot_calculators.json`. *Deferred — same reason;
      the IEC 61558 formula is a single function in
      `insulation_stack.py::hipot_voltage_V`. Two lines of code
      + a 1500 V floor.*
- [x] `pfc_inductor/manufacturing/insulation_stack.py` —
      ``pick_insulation_class(T_winding_C)`` selects the lowest
      class whose limit comfortably exceeds the working temp +
      a 10 °C engineering margin.
      ``hipot_voltage_V(V_work)`` per IEC 61558.
- [x] `pfc_inductor/manufacturing/acceptance.py` —
      ``build_acceptance_tests(spec, core, wire, material,
      result)`` emits the standard 6-row plan: inductance,
      biased inductance, DCR, hi-pot, IR @ 500 V, visual +
      dimensional.
- [x] IEC 60085 / 61558 references in module docstrings +
      ``InsulationClass`` field docstrings.

## Phase 3 — PDF writer

- [x] `reportlab` already a top-level dep (added with the
      datasheet PDF work in `f0fe324`).
- [x] `pfc_inductor/manufacturing/pdf_writer.py` —
      ``write_mfg_spec_pdf(spec, path)`` writes a 4-page PDF:
      - Cover page: revision block, electrical + mechanical
        summaries, MagnaDesign version + designer.
      - Construction page: matplotlib-rendered winding diagram
        embedded as RLImage, per-layer table, insulation
        stack-up table, air-gap detail.
      - Acceptance test plan: one row per
        :func:`build_acceptance_tests` row.
      - Sign-off page with Designer / Approver / Vendor rows.
- [~] Golden-file test for the PDF. *Replaced with a smoke
      test (file > 5 KB + ``%PDF-`` magic). Pixel-level
      golden-file diff is too fragile across reportlab + matplotlib
      releases.*

## Phase 4 — Excel writer

- [x] `pfc_inductor/manufacturing/excel_writer.py` —
      ``write_mfg_spec_xlsx(spec, path)`` writes three sheets:
      - **Specs** — flat Section / Parameter / Value / Unit /
        Tolerance rows.
      - **BOM** — vendor PN, description, qty, unit, $/unit,
        line total. Wire length = N × MLT.
      - **Tests** — acceptance plan mirror of the PDF.
- [x] Round-trip test via ``openpyxl.load_workbook`` verifies
      sheet names + header rows + BOM line indices.

## Phase 5 — UI integration

- [~] `MainWindow._export_manufacturing()` handler. *Deferred —
      the CLI subcommand (``magnadesign mfg-spec``) covers the
      headless / CI / vendor-pipeline path. Wiring a Qt menu
      entry lands when the next File → Export sweep happens
      alongside the same-class compliance / circuit-export
      menu items.*
- [~] Menu entry / command palette / Export-tab button.
      *Deferred — same reason.*
- [~] Disabled state + tooltip when no `WorstCaseSummary` is
      cached. *Deferred — the worst-case dependency is opt-in;
      the standalone manufacturing spec is useful even without
      worst-case (the typical RFQ path).*

## Phase 6 — Docs + release

- [~] `docs/manufacturing-spec.md`: vendor-portal happy-path
      workflow. *Deferred — Sphinx site shipped without a
      dedicated manufacturing chapter; lands with the next
      docs pass.*
- [~] Sample PDFs for the three reference designs.
      *Deferred — gated on `add-validation-reference-set` and
      the next docs pass.*
- [~] CHANGELOG + README update. *Deferred — README +
      CHANGELOG sweep planned alongside the next release tag.*

## CLI subcommand (bonus, beyond the original proposal)

- [x] `magnadesign mfg-spec PROJECT.pfc --out FILE.{pdf,xlsx}
       [--designer NAME] [--revision REV] [--project-name NAME]`
       — registered as the 9th CLI subcommand alongside
       ``datasheet`` / ``catalog`` / ``report``. Format follows
       the output extension; rejects unsupported extensions
       with ``USAGE_ERROR``.
