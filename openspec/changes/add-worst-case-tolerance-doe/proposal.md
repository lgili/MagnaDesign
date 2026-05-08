# Add worst-case + production-tolerance DOE engine

## Why

The current `design()` solves a single nominal operating point and
its iterative thermal coupling. Production reality has variations
the nominal solve doesn't see:

- **Line voltage**: the spec captures `Vin_min/Vin_max` but the
  engine evaluates only at low-line. High-line stresses Bsat
  differently (lower duty, higher peak ripple — less DC bias but
  more flux swing).
- **Ambient temperature**: spec carries `T_amb_C` but real product
  ships into 5–55 °C ambients depending on geography.
- **Component tolerances**: powder-core AL is ±8 % (vendor-typical),
  Bsat is ±5 %, ferrite μ_r is ±25 % per IEC 60401-3, wire diameter
  is ±2 % per IPC. The nominal spec assumes all tolerances at zero.
- **Pout swing**: compressor inverters operate from idle (~50 W) to
  peak (~Pout_rated × 1.3), and the loss / saturation / thermal
  worst case sits at neither extreme.

An engineer signing off for production has to defend: "across every
realistic combination of line × ambient × tolerance × load, every
unit shipped will pass." Today they do this in Excel, by hand, for
each new core; it's slow and easy to miss a corner. An auditor
under IATF 16949 will ask for the worst-case envelope explicitly.

## What changes

A new `WorstCaseEngine` that takes a `Spec` + a tolerance file +
a `WorstCaseConfig` and runs the existing `design()` over a
**Design-of-Experiments grid** (typically 3³–3⁴ corners), reporting:

- **Worst-case violator per metric**: which (V_in, T_amb, AL,
  Bsat, …) combination drove ΔT to its peak / Bpk closest to
  saturation / loss to its peak.
- **Yield estimate**: Monte-Carlo over the tolerance distributions
  (default 10 k samples), reports `pct_pass = N(all metrics in
  spec) / N_total` so the team can quote "expected first-pass
  yield 96.4 %" before they build.
- **Sensitivity table**: per-metric per-input partial-derivatives
  (numeric) so the engineer sees which parameter dominates and can
  prioritise tightening only what matters.

UI surface: a new **Worst-case** tab in the Project workspace,
parallel to "Analysis" / "Validate" / "Export". Default tolerance
values come from a bundled `data/tolerances.json` (IPC + IEC + a
typical vendor-conservative set); the user can edit per project
and the values save with the `.pfc`.

A new **Compliance** column lands on the cascade Top-N table:
"PASS @ corner" / "MARGIN low" / "FAIL — Bsat at hot/high-line"
so optimizer survivors are already filtered for production
viability, not just nominal performance.

## Impact

- **New module**: `pfc_inductor/worst_case/` with `engine.py`,
  `tolerances.py`, `monte_carlo.py`.
- **New UI page**: `ui/workspace/worst_case_tab.py` (mounts inside
  ProjetoPage as a tab).
- **Cascade integration**: optional flag in `CascadeConfig`
  (`worst_case_check: bool = False`) — when on, every Tier-1
  survivor is re-evaluated at the four extreme corners.
- **Spec extension**: `Spec` gains `tolerance_set: Optional[str]`
  (filename in `data/tolerances/`).
- **No engine breaking changes** — `design()` stays single-point;
  the worst-case engine *wraps* it.
- **Tests**: ~10 new in `tests/test_worst_case_*`.
- **Capability added**: `worst-case-envelope`.
- **Effort**: ~1 week of work.
