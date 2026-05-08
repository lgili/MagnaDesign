# Tasks — add-worst-case-tolerance-doe

## Phase 1 — Tolerance modelling

- [x] `pfc_inductor/worst_case/tolerances.py`:
      - `Tolerance(name, kind, p3sigma_pct, distribution)` Pydantic
        model. Distributions: `gaussian`, `uniform`, `triangle`.
      - `ToleranceSet`: collection of `Tolerance`s, loadable from
        JSON / YAML.
      - Bundled `DEFAULT_TOLERANCES` ships an IPC + IEC blend
        (AL ±8 %, Bsat ±5 %, µ_r ±25 %, wire ø ±2 %, T_amb 25–55 °C,
        Vin ±10 %, Pout 50–130 %). Each carries a citation to its
        source so an auditor can trace the assumption back.
- [~] Spec extension: `Spec.tolerance_set: Optional[str]` (filename),
      with backward-compat default `None` → "all tolerances zero".
      *Deferred to a follow-up — the engine wraps `design()` from
      outside the Spec for now, which keeps `.pfc` files
      backward-compat without a model migration.*

## Phase 2 — Corner DOE engine

- [x] `pfc_inductor/worst_case/engine.py`:
      - `WorstCaseConfig(full_factorial_max_n, metrics_to_track)`.
      - `evaluate_corners(spec, core, wire, material, tolerances)`
        returns a `WorstCaseSummary` with
        `corners: tuple[CornerResult, ...]`, `nominal`, and
        `worst_per_metric: dict[metric_name, CornerResult]`.
      - For N ≤ 4 evaluates every 3^N corner; for N > 4 falls back
        to fractional factorial (2^N edges + centre + per-axis ±).
        Bundled 7-tolerance set runs in **~30 ms / 143 corners**.
      - DesignError + arithmetic errors absorbed per corner —
        `n_corners_failed` lets the caller see breakage without
        the DOE crashing.
- [x] `tests/test_worst_case_engine.py`: 11 tests covering empty
      sets, full factorial sizing, fractional sizing, the
      "thermal worst case is hot-ambient + high-load" engineering
      anchor, and graceful engine-failure handling.

## Phase 3 — Monte-Carlo yield

- [x] `pfc_inductor/worst_case/monte_carlo.py`:
      - `simulate_yield(spec, core, wire, material, tolerances,
         n_samples=1000, seed=0)` → `YieldReport(pct_pass,
         n_engine_error, fail_modes)`.
      - `numpy.random.default_rng(seed)` for reproducibility —
        same seed → same report (required for CI regression).
      - Default pass criterion: T_winding ≤ T_max, B_pk ≤ Bsat·(1−margin),
        Ku ≤ Ku_max, P_total ≤ 10 % Pout. Override via `pass_fn`.
      - Fail modes bucketed and sorted high-to-low.
- [x] `tests/test_worst_case_engine.py`: zero-tolerance → 100 %
      yield, seed reproducibility, hot-T_max regime produces
      buckets.

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
