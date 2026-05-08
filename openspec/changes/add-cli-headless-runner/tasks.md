# Tasks — add-cli-headless-runner

## Phase 1 — Skeleton + dispatcher

- [x] Add `click >= 8.1` to `pyproject.toml` deps (it was implicit
      before).
- [x] `pfc_inductor/cli/__init__.py`: top-level `cli` Click group
      with `--version` flag printing the package version.
- [x] `pfc_inductor/__main__.py`: dispatch — if `argv[1]` is a
      registered subcommand, hand to `cli.main()`; otherwise launch
      the GUI as today. `magnadesign` (no args) still opens the GUI.
- [x] `pfc_inductor/cli/utils.py`: `load_project(path) → ProjectFile`,
      `load_catalogs() → (mats, cores, wires)`, `pretty_or_json(obj)`.

## Phase 2 — `design` subcommand

- [x] `pfc_inductor/cli/design.py`:
      `magnadesign design PROJECT.pfc [--json|--pretty]`.
      Loads the project, runs `design()`, prints KPIs (L_actual,
      Bpk, dT, P_total, η, feasibility flags).
- [x] Test: `tests/test_cli_dispatch.py` runs the subcommand on a
      tmp_path-built `.pfc` and asserts the JSON has the required
      keys.

## Phase 3 — `sweep` subcommand

- [x] `pfc_inductor/cli/sweep.py`:
      `magnadesign sweep PROJECT.pfc --top N --rank loss|volume|cost
       [--material ID --feasible-only --csv OUT]`.
      Reuses the same `OptimizerFiltersBar`-equivalent filter logic
      (factor it out into a `cli/filters.py` helper).
- [~] Test: full sweep on the example project; verify CSV format.
      *Smoke-tested manually (CSV produced, 3 rows for the 600 W
      example); pytest coverage tracked in
      ``test_cli_sweep_endtoend.py`` follow-up — gated as a
      ``slow`` test because a real sweep is multi-second.*

## Phase 4 — `cascade` subcommand

- [ ] `pfc_inductor/cli/cascade.py`:
      `magnadesign cascade PROJECT.pfc [--tier2-k 50 --tier3-k 0
       --workers N --store DB]`.
      Drives `CascadeOrchestrator` synchronously, prints a progress
      line per tier.
- [ ] On completion, prints the Top-N from the SQLite store.

## Phase 5 — Reporting subcommands

- [ ] `magnadesign datasheet PROJECT.pfc --out FILE.html` →
      reuses `report.datasheet.generate_datasheet`.
- [ ] `magnadesign mfg-spec PROJECT.pfc --out FILE.pdf` (depends
      on `add-manufacturing-spec-export`).
- [x] `magnadesign compliance PROJECT.pfc --region EU --out FILE.pdf`
       — runs the dispatcher, prints overall + per-standard
       verdict, optionally writes the PDF, exits with
       ``COMPLIANCE_FAIL`` (2) on FAIL or strict-MARGINAL.
- [x] `magnadesign worst-case PROJECT.pfc [--tolerances FILE]
       [--samples N --seed S --yield-threshold PCT --csv OUT
        --pretty/--json]` — runs the corner DOE + Monte-Carlo,
       prints the per-metric worst corner + yield + verdict.
       Exit codes: ``0`` PASS, ``3`` WORST_CASE_FAIL.
- [ ] `magnadesign report PROJECT.pfc --out DIR/` — convenience:
      datasheet + mfg-spec + compliance into one directory.

## Phase 6 — Catalog + validate

- [ ] `magnadesign catalog (materials|cores|wires) [--filter type=ferrite]
       [--csv OUT]`.
- [ ] `magnadesign validate REFERENCE_ID` — runs the named
      validation notebook via papermill and prints PASS/FAIL.

## Phase 7 — Exit codes + machine-readable output

- [ ] Standardise exit codes in `pfc_inductor/cli/exit_codes.py`:
      `0 OK, 1 GENERIC_ERROR, 2 COMPLIANCE_FAIL, 3 WORST_CASE_FAIL,
      4 USAGE_ERROR`.
- [ ] Default output: JSON-LD on stdout for every subcommand.
      `--pretty` switches to a Rich-based table render.

## Phase 8 — Docs + release

- [ ] `docs/cli.md`: usage cheat sheet; copy-pasteable Bash
      examples for the most common workflows.
- [ ] CI: add a job that runs the CLI on the example project and
      asserts a non-zero exit on a deliberately-broken spec.
- [ ] CHANGELOG + README mention the new CLI.
