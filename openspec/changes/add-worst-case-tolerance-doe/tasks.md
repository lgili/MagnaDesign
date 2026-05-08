# Tasks — add-worst-case-tolerance-doe

## Phase 1 — Tolerance modelling

- [ ] `pfc_inductor/worst_case/tolerances.py`:
      - `Tolerance(name, kind, p3sigma_pct, distribution)` Pydantic
        model. Distributions: `gaussian`, `uniform`, `triangle`.
      - `ToleranceSet`: collection of `Tolerance`s, loadable from
        JSON / YAML.
      - Standard sets bundled in `data/tolerances/`:
        `ipc-2221.json`, `iec-60401-3.json`, `vendor-conservative.json`.
- [ ] Spec extension: `Spec.tolerance_set: Optional[str]` (filename),
      with backward-compat default `None` → "all tolerances zero".
      Add round-trip test for `.pfc` serialisation.

## Phase 2 — Corner DOE engine

- [ ] `pfc_inductor/worst_case/engine.py`:
      - `WorstCaseConfig(corners: Literal["3^3", "3^4", "min-max"], …)`.
      - `evaluate_corners(spec, core, wire, material, tolerances)` →
        returns `list[CornerResult]` where each `CornerResult` has
        the corner's `(V_in, T_amb, AL_delta, Bsat_delta, …)` and
        the resulting `DesignResult`.
      - Identify per-metric worst case: returns
        `WorstCaseSummary` with `worst_dT_corner`, `worst_Bpk_corner`,
        `worst_loss_corner`.
- [ ] `tests/test_worst_case_engine.py`: regression on a known
      design — verify `worst_dT_corner` matches hand-calc.

## Phase 3 — Monte-Carlo yield

- [ ] `pfc_inductor/worst_case/monte_carlo.py`:
      - `simulate_yield(spec, core, wire, material, tolerances,
         n_samples=10_000)` → `YieldReport(pct_pass, fail_modes,
         per_metric_distributions)`.
      - Use `numpy.random.Generator` with a fixed seed for
        reproducibility (same spec + tolerance file → same yield).
      - Each fail-mode bucketed: "Bsat exceeded", "ΔT exceeded",
        "Ku exceeded", etc.
- [ ] `tests/test_monte_carlo.py`: with `tolerances=zero`, expected
      yield is 100 %; with absurd tolerances, expected yield drops.

## Phase 4 — UI surface (Worst-case tab)

- [ ] `ui/workspace/worst_case_tab.py`:
      - Tolerance picker (combo of bundled sets + "Custom…" opens
        an editor dialog).
      - Corner-DOE button: runs in worker thread, populates a
        small table of corners with PASS/FAIL chips.
      - Yield button: runs Monte-Carlo, shows the `pct_pass`
        prominently (big number, color-coded > 95 % green / 90–95 %
        amber / < 90 % red), plus a fail-mode pie chart.
      - Sensitivity table: top-5 dominant tolerance contributors
        per metric, sorted by impact.
- [ ] Mount as a new tab in `ProjetoPage` between "Validate" and
      "Export".
- [ ] Tests: `tests/test_worst_case_tab.py` (UI populates
      correctly when fed a stub `WorstCaseSummary`).

## Phase 5 — Cascade integration

- [ ] `CascadeConfig.worst_case_check: bool = False` (opt-in).
- [ ] When on, after each Tier-1 evaluation, run the corner DOE
      and store `worst_case_status` ("pass" | "margin" | "fail")
      in the SQLite store.
- [ ] Top-N table gains a "WC" column showing the worst-case
      status; sortable.
- [ ] Update `CandidateRow` model + store schema migration
      (add `worst_case_status TEXT NULL`).

## Phase 6 — Datasheet integration

- [ ] If a `WorstCaseSummary` is present at report time, the
      datasheet adds a "Worst-case envelope" section with the four
      corners + the yield estimate. Hidden if no summary computed.

## Phase 7 — Docs + release

- [ ] `docs/worst-case.md`: methodology, tolerance source citations
      (IPC-2221, IEC 60401-3), recommended corner choice.
- [ ] Onboarding tour gains a 4th step: "Production-ready: run
      worst-case before exporting" once a design is computed.
- [ ] CHANGELOG entry; reference in README under "Industrial-grade".
