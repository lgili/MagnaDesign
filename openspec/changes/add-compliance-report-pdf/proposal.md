# Add compliance-report PDF (IEC 61000-3-2 / EN 55032 / UL 1411)

## Why

`tests/test_iec61000_3_2.py` already verifies that the line-reactor
topology meets the harmonic limits for Class A and Class D loads —
**the engine knows how to compute compliance, but the user has no
way to print a certificate**. For a product going to market the
engineer has to hand a certifying body (TÜV, Intertek, UL) a
formal compliance report, not a Python test result.

The PFC engineer's compliance burden, by region:

| Standard | Region | What it caps | Already in engine? |
|---|---|---|---|
| **IEC 61000-3-2** | EU + IEC | Per-harmonic line-current limits, Class A/B/C/D | ✓ partial |
| **EN 55032** | EU | Conducted EMI 150 kHz – 30 MHz | model needed |
| **UL 1411** | US | Class 2 / Class 3 transformer ratings | partial |
| **IEC 60335-1** | Appliances | Touch-current, isolation, hi-pot | partial |

Producing the report is a one-page-per-standard PDF plus the raw
data needed to satisfy a lab audit (per-harmonic table, scope
captures, calculation method). Vendors and quality engineers ask
for this on day-1 of certification engagement.

## What changes

A new "Compliance" tab in the Project workspace and an
`Export → Compliance report…` action that produces a single PDF
covering every standard the current spec implies (boost-PFC →
IEC 61000-3-2; line-reactor → EN 55032 + IEC 61000-3-2 Class A;
appliance → IEC 60335-1).

For each standard the report contains:

- **Header**: standard name + edition, applicable scope, date
  evaluated, MagnaDesign version + git SHA.
- **Inputs**: spec assumed (V_in band, I_pk, fsw, P_out class).
- **Method**: equation references (e.g. IEC 61000-3-2 §6.2.3),
  calculation chain.
- **Results**: per-harmonic table (1st through 40th) with
  measured / limit / margin / PASS-FAIL.
- **Plots**: harmonic spectrum bar chart, conducted-EMI
  estimate (when applicable).
- **Conclusion**: PASS / MARGINAL / FAIL summary; if MARGINAL or
  FAIL, lists which harmonics dominate so the engineer knows
  what to fix.

Compliance is **not blocking** — the report can be generated for
a non-compliant design (often necessary for documenting *why*
something is being escalated). The PASS/FAIL summary makes the
state unambiguous.

## Impact

- **New module**: `pfc_inductor/compliance/` with
  `iec61000_3_2.py` (extracted from the existing test logic),
  `en55032.py` (new, conducted-EMI model), `ul_1411.py`,
  `iec60335_1.py`.
- **Engine extension**: a `Compliance` model exposed in
  `DesignResult` carrying per-standard PASS/FAIL summaries +
  details. Optional and lazy: not computed unless requested.
- **PDF**: reuses the `reportlab` dependency added by
  `add-manufacturing-spec-export` (this proposal *follows* that
  one — order matters).
- **UI**: new "Compliance" tab inside ProjetoPage; a button on
  the Export tab.
- **Tests**: ~15 new across `tests/test_compliance_*` covering
  every standard's PASS/FAIL boundary with hand-calc anchors.
- **Capability added**: `compliance-reporting`.
- **Effort**: ~1 week (most physics already exists; PDF + EN 55032
  conducted-EMI estimate are the new code).
