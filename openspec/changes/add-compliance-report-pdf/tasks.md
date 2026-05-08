# Tasks — add-compliance-report-pdf

## Phase 1 — Compliance models

- [ ] `pfc_inductor/compliance/types.py`: `ComplianceResult`,
      `HarmonicResult(n, magnitude, limit, pct_margin, pass)`,
      `StandardResult(standard, edition, scope, summary, harmonics,
       conclusion)`. Pydantic.
- [ ] Surface `ComplianceResult` as a new optional field on
      `DesignResult.compliance: Optional[ComplianceResult]`.

## Phase 2 — IEC 61000-3-2

- [ ] Extract production logic from `tests/test_iec61000_3_2.py`
      into `pfc_inductor/compliance/iec61000_3_2.py`:
      - `evaluate(spec, design_result, line_class)` returns a
        `StandardResult`. `line_class` ∈ `{"A", "B", "C", "D"}`.
      - Reference Table 1–3 limits per IEC 61000-3-2:2018.
- [ ] `tests/test_compliance_iec61000_3_2.py`: PASS / FAIL anchors
      with the same data the existing test uses, plus boundary
      cases (just-under / just-over).

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

- [ ] `pfc_inductor/compliance/dispatcher.py`:
      - `applicable_standards(spec)` returns the list of standards
        relevant to the spec's topology + region tag.
      - `evaluate_all(spec, design_result, region)` → list of
        `StandardResult`.

## Phase 6 — PDF writer

- [ ] `pfc_inductor/compliance/pdf_writer.py` using `reportlab`
      (added by `add-manufacturing-spec-export`):
      - One section per standard.
      - Header card with PASS/FAIL stripe (green / amber / red).
      - Harmonic table (always 1–40 lines for 61000-3-2).
      - Bar chart (matplotlib → embed) of harmonics vs limits.
      - Conclusion footer with required follow-on actions for
        MARGINAL or FAIL ("LISN measurement required",
        "Snubber capacitor recommended" etc.).
- [ ] Golden-file tests for one PASS report + one FAIL report.

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
