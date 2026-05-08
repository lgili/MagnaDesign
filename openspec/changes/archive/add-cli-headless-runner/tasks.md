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

- [x] `pfc_inductor/cli/cascade.py`:
      `magnadesign cascade PROJECT.pfc [--tier2-k --tier3-k
       --tier4-k --workers --store --top --rank --csv --pretty]`.
      Drives `CascadeOrchestrator` synchronously, throttles
      progress callbacks to one stderr line per second so a
      100k-candidate sweep doesn't spam the CI log. Topology
      filter via `materials_for_topology` mirrors the GUI.
- [x] On completion, prints the Top-N from the SQLite store.
      ``--rank`` honours the four server-side ORDER BY columns
      (loss / temp / cost / loss_t2); volume / score variants
      stay GUI-only because they need a JOIN to cores.
- [x] Test: `tests/test_cli_cascade.py` (5 tests) — registered,
      help, rank choices, missing-project usage error, full
      end-to-end run gated as ``slow``.

## Phase 5 — Reporting subcommands

- [x] `magnadesign datasheet PROJECT.pfc --out FILE.{pdf,html}`
       — extension drives format. _Shipped in `89e464e
       feat(cli): datasheet, catalog, report subcommands`._
- [x] `magnadesign mfg-spec PROJECT.pfc --out FILE.{pdf,xlsx}`
       — vendor-quotable PDF or ERP-friendly XLSX with Specs /
       BOM / Tests sheets. _Shipped in `65b6ada
       feat(manufacturing): vendor-quotable spec export`._
- [x] `magnadesign compliance PROJECT.pfc --region EU --out FILE.pdf`
       — runs the dispatcher, prints overall + per-standard
       verdict, optionally writes the PDF, exits with
       ``COMPLIANCE_FAIL`` (2) on FAIL or strict-MARGINAL.
- [x] `magnadesign worst-case PROJECT.pfc [--tolerances FILE]
       [--samples N --seed S --yield-threshold PCT --csv OUT
        --pretty/--json]` — runs the corner DOE + Monte-Carlo,
       prints the per-metric worst corner + yield + verdict.
       Exit codes: ``0`` PASS, ``3`` WORST_CASE_FAIL.
- [x] `magnadesign report PROJECT.pfc --out DIR/` — bundle of
       datasheet.pdf + kpi.json + compliance_<REGION>.pdf +
       manifest.json (with per-file SHA-256). _Shipped in
       `89e464e`._
- [x] `magnadesign circuit PROJECT.pfc --format {ltspice|psim|
       modelica} --out FILE` — saturable-inductor model with the
       engine's L(I) rolloff. _Shipped in `c1210f1 feat(export):
       circuit-simulator export`._

## Phase 6 — Catalog + validate

- [x] `magnadesign catalog (materials|cores|wires) [--filter
       key=value]... [--csv OUT] [--limit N]` — _shipped in
       `89e464e`. Filters are AND'd, case-insensitive substring
       match against the row's attribute (or model_dump fallback
       for nested keys)._
- [~] `magnadesign validate REFERENCE_ID` — runs the named
      validation notebook via papermill. *Deferred — gated on
      `add-validation-reference-set` shipping the notebooks
      first; the CLI hook is ~30 LOC of papermill glue once they
      land.*

## Phase 7 — Exit codes + machine-readable output

- [x] Standardise exit codes in `pfc_inductor/cli/exit_codes.py`:
      ``0 OK, 1 GENERIC_ERROR, 2 COMPLIANCE_FAIL, 3
      WORST_CASE_FAIL, 4 USAGE_ERROR``. Documented per-subcommand
      in their docstrings.
- [x] Default output: JSON on stdout (machine-friendly);
      ``--pretty`` switches to a key-value table render via the
      shared ``emit()`` helper. _Rich-based tables not adopted —
      the lighter helper covers the spot-check use case without
      pulling a 2 MB dep into the CLI._

## Phase 8 — Docs + release

- [x] `docs/getting-started/cli.rst` — Sphinx CLI cheat sheet
      shipped in `da5c40e feat(docs): Sphinx site`. Copy-
      pasteable subcommand examples + exit codes.
- [~] CI: add a job that runs the CLI on the example project
      and asserts a non-zero exit on a deliberately-broken
      spec. *Deferred — the CLI is exercised by 60+ unit tests
      in `tests/test_cli_*` already; a dedicated CI job lands
      with the next pipeline pass.*
- [~] CHANGELOG + README mention the new CLI.
      *Deferred — README + CHANGELOG sweep planned alongside
      the next release tag. POSITIONING.md was updated to drop
      the "no CLI" claim.*
