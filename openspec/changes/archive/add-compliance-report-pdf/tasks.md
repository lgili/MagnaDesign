# Tasks — add-compliance-report-pdf

## Phase 1 — Compliance models

- [x] `pfc_inductor/compliance/dispatcher.py`: `StandardResult`
      (standard, edition, scope, conclusion, summary, rows[],
      notes[], extras), `ComplianceBundle` (project_name,
      topology, region, standards[], `overall` aggregator),
      `ConclusionLabel` Literal. Plain dataclasses — Pydantic
      not needed since these don't round-trip through `.pfc`.
- [~] Surface `ComplianceResult` as a new optional field on
      `DesignResult.compliance`. *Deferred — bundling lives in a
      separate module so the engine output stays stable
      across versions.*

## Phase 2 — IEC 61000-3-2

- [x] The production logic was already in
      `src/pfc_inductor/standards/iec61000_3_2.py` (Class D
      limit tables + `evaluate_compliance`); the dispatcher
      wraps it. Engine→standards bridge:
      - `_resolve_harmonic_pct` calls
        `topology.line_reactor.harmonic_amplitudes_pct` for
        line_reactor / passive_choke.
      - Active boost-PFC returns flat fundamental-only spectrum
        (engine's analytical bound). Conclusion lands on PASS
        with a "LISN-measurement-still-required" note so an
        auditor sees the gap.
      - Boundary-aware verdict: 0 checks → PASS+caveat, all
        pass + worst margin < 10 % → MARGINAL, fail → FAIL.
      - Editions 4.0 + 5.0 wired through to the standards
        evaluator.
- [x] `tests/test_compliance_dispatcher.py` (10 tests): PASS /
      FAIL boundary cases, harmonic-row schema, bundle
      aggregation, US-region (no standards) path, empty bundle,
      PDF smoke test.

## Phase 3 — EN 55032 conducted EMI

- [x] `pfc_inductor/standards/en55032.py`:
      - `estimate_conducted_emi(spec, core, wire, design_result,
        filter_attenuation_dB=60)` — analytical envelope of the
        dV/dt × C_parasitic source, attenuated by the inductor's
        first-pole impedance with an opt-in two-stage CISPR
        Class B filter default (60 dB).
      - Returns a `StandardResult` with limits per Class A / B
        at 150 kHz – 30 MHz.
      - Carries the LISN + spectrum-analyser caveat as a note
        regardless of pass / fail.
      _Shipped in `dc99d38 feat(compliance): EN 55032 conducted-
      EMI evaluator + dispatcher hook`._
- [x] Hand-calc anchors at 150 kHz, 1 MHz, 30 MHz cover the
      regression. _Shipped in `dc99d38`._

## Phase 4 — UL 1411 + IEC 60335-1

- [x] `pfc_inductor/standards/ul1411.py`: §39.2 + §40
      temperature-rise envelope per insulation class
      (A=65 °C, B=90 °C, F=115 °C, H=140 °C) plus the hipot
      formula `2·V_work + 1000`. Returns `UlReport` translated
      to `StandardResult` by the dispatcher; routed for US +
      Worldwide regions.
      _Shipped in `360053a feat(compliance): UL 1411 envelope
      check + dispatcher hook`. 13 tests in
      `tests/test_ul1411.py`._
- [~] `pfc_inductor/standards/iec60335_1.py`: touch-current,
      isolation, hi-pot. *Deferred — touch-current envelope
      requires bobbin creepage / clearance dimensions which
      aren't first-class fields on Core / Wire today. Lands
      with a follow-up that promotes those geometric details
      into the model.*
- [x] Tests on UL 1411 with hand-calc anchors. _Shipped._

## Phase 5 — Standard selector

- [x] `pfc_inductor/compliance/dispatcher.py`:
      - `applicable_standards(spec, region)` returns the list of
        standards relevant to the spec's topology + region tag.
      - `evaluate(spec, core, wire, material, result, *, region,
         edition)` → `ComplianceBundle`.
      - Region table: `EU` / `Worldwide` / `BR` route through
        IEC 61000-3-2 + EN 55032; `US` / `Worldwide` route
        through UL 1411 + EN 55032. Bundle aggregates the worst
        per-standard verdict.

## Phase 6 — PDF writer

- [x] `pfc_inductor/compliance/pdf_writer.py` using ``reportlab``:
      - Cover page with overall verdict marker (green / amber /
        red) + applicable-standards table + MagnaDesign version.
      - One section per standard with the verdict strip,
        per-row harmonic table (n / measured / limit / margin /
        result), inline pass/fail colouring on the result cell.
      - Matplotlib bar chart (measured vs IEC limit overlay)
        embedded as PNG flowable when ``extras.harmonic_pct``
        is present.
      - Free-form notes section (LISN-measurement caveats,
        reference voltage / power factor, edition reference).
      - Per-page footer: project + page-of-N + MagnaDesign
        version + git SHA short hash. Auditable.
- [~] Golden-file tests for one PASS report + one FAIL report.
      *Smoke-tested only (`PDF starts with %PDF-` + size > 5 KB)
      — golden-file diff is too fragile across reportlab
      versions. Visual regression via the 600 W reference
      design's PDF lands with the validation reference set.*

## Phase 7 — UI

- [x] `ui/workspace/compliance_tab.py`: per-standard card with
      colour-coded verdict strip (PASS green / MARGINAL amber /
      FAIL red, left-border accent), per-row harmonic table
      (n / measured / limit / margin / result with red-green
      colouring), free-form notes section. Hero strip aggregates
      the bundle's overall verdict.
- [x] Mount as a new tab in ProjetoPage between "Worst-case"
      and "Export" — completes the audit-flow ordering.
- [x] Region picker (Worldwide / EU / BR / US) + IEC edition
      picker (5.0 / 4.0) live inside the tab so a user can flip
      regions without leaving the workspace.
- [x] "Export PDF…" button on the tab — calls
      ``write_compliance_pdf`` with the current bundle.
- [x] Tests: `tests/test_compliance_tab.py` (5 tests) — default
      state, region-combo coverage, bundle render, empty-bundle
      graceful handling, project-name propagation.
- [~] Spec drawer "Region" picker that saves with `.pfc`.
      *Deferred — tab-local picker covers the workflow; persisting
      the region in the project file lands when ``Spec.region``
      gets a Pydantic field (separate change).*
- [~] File → Export → "Compliance report…" menu + command palette
      entry. *Today only the in-tab button is wired; menu shortcut
      lands with the next batch of menu/command-palette polish.*

## Phase 8 — Docs + release

- [x] `docs/theory/compliance.rst` — Sphinx chapter covering
      IEC 61000-3-2, EN 55032, and UL 1411 with derivations,
      limits, and per-standard caveats. _Shipped in `da5c40e`
      as part of the Theory of Operation site._
- [~] Sample PDF for the 600 W boost reference design.
      *Deferred — the CLI subcommand
      `magnadesign compliance ... --out file.pdf` produces the
      report on demand; bundling a checked-in sample lands when
      the validation reference set lands.*
- [~] CHANGELOG + README "Standards covered" matrix.
      *Deferred — README + CHANGELOG sweep planned alongside
      the next release tag.*
