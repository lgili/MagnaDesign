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

- [ ] `pfc_inductor/compliance/en55032.py`:
      - `estimate_conducted_emi(spec, core, wire, design_result)`
        — analytical envelope of the dV/dt × C_parasitic source,
        attenuated by the inductor's first-pole impedance.
      - Returns a `StandardResult` with limits per Class A / B
        (industrial vs residential) at 150 kHz – 30 MHz.
      - Documented as **estimate**, not certification — the model
        notes uncertainty and that final compliance requires LISN
        + spectrum-analyser measurement.
- [ ] `tests/test_compliance_en55032.py`: regress against three
      hand-calc points at 150 kHz, 1 MHz, 30 MHz.

## Phase 4 — UL 1411 + IEC 60335-1

- [ ] `pfc_inductor/compliance/ul_1411.py`: Class 2 / 3 transformer
      limits (V_oc, I_sc, energy). Returns `StandardResult`.
- [ ] `pfc_inductor/compliance/iec60335_1.py`: touch-current,
      isolation, hi-pot. Returns `StandardResult`.
- [ ] Tests on both with hand-calc anchors.

## Phase 5 — Standard selector

- [x] `pfc_inductor/compliance/dispatcher.py`:
      - `applicable_standards(spec, region)` returns the list of
        standards relevant to the spec's topology + region tag.
      - `evaluate(spec, core, wire, material, result, *, region,
         edition)` → `ComplianceBundle`.
      - Region table: `EU` / `Worldwide` / `BR` route through IEC
        61000-3-2; `US` returns an empty list (UL 1411 is queued
        for a follow-up commit).

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

- [ ] `ui/workspace/compliance_tab.py`: per-standard card with
      PASS/MARGINAL/FAIL chip, "Show details" expandable panel,
      "Generate report" button.
- [ ] Mount as a new tab in ProjetoPage.
- [ ] File → Export → "Compliance report…" plus command-palette
      entry "Export compliance report".
- [ ] Spec drawer gains a "Region" picker (`EU` / `US` / `BR` /
      `Worldwide`) so the dispatcher knows which standards to apply
      by default. Saves with `.pfc`.

## Phase 8 — Docs + release

- [ ] `docs/compliance.md`: standards covered, edition years,
      uncertainty of each estimate, limits of the EN 55032 model.
- [ ] Sample PDF for the 600 W boost reference design.
- [ ] CHANGELOG + README "Standards covered" matrix.
