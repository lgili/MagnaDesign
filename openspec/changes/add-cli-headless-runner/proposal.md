# Add `magnadesign` CLI for headless design / sweep / cascade / report

## Why

The app today is GUI-first. The only CLI surface is
`magnadesign-setup`, which checks the FEA toolchain — there is no
way to drive a design loop without the GUI. That blocks several
real workflows:

1. **CI regression**: the validation reference set (see
   `add-validation-reference-set`) needs to drive the engine from
   notebooks; today it imports the Python API directly, which is
   fine for a notebook but awkward for a `Makefile` rule.
2. **Batch optimization**: an engineer with 30 candidate specs
   wants to sweep them overnight, dump the Top-N CSV per spec, and
   review in the morning. No GUI session can run unattended.
3. **Build automation**: a vendor's quoting pipeline that
   ingests `.pfc` files and emits manufacturing specs needs an
   `magnadesign export-mfg-spec foo.pfc out.pdf` invocation.
4. **Scripting**: users with non-trivial workflows (e.g. parameter
   sweeps over `Spec.fsw_kHz`) write Python scripts today; a
   stable CLI is a faster path for non-Python-fluent users.

## What changes

A new top-level `magnadesign` command with subcommands. It reuses
every existing entry point as a callable (Spec → DesignResult,
sweep, cascade, datasheet, manufacturing spec, compliance report)
without spawning Qt at all.

```
$ magnadesign --help
Usage: magnadesign [OPTIONS] COMMAND [ARGS]...

Commands:
  design         Run the engine on a .pfc file; print KPIs.
  sweep          Run the simple Pareto sweep; emit ranked CSV.
  cascade        Run the multi-tier cascade; persist to SQLite.
  datasheet      Generate the HTML datasheet.
  mfg-spec       Generate the manufacturing-spec PDF + Excel.
  compliance     Generate the compliance report PDF.
  worst-case     Run the worst-case envelope; emit summary CSV.
  validate       Run a validation notebook end-to-end.
  catalog        Inspect / dump materials | cores | wires.
  report         Multi-artefact: datasheet + mfg + compliance.
```

Driven by [Click](https://click.palletsprojects.com/) (already a
transitive dep). Output formats default to JSON / CSV (machine
readable); `--pretty` enables tables. Exit codes follow Unix
conventions: `0` = pass, `1` = generic failure, `2` = compliance
FAIL, `3` = worst-case FAIL — so CI scripts can branch.

GUI launch becomes one of the subcommands too: `magnadesign gui`
(equivalent to today's bare `magnadesign`). Bare invocation still
opens the GUI for backward compatibility.

## Impact

- **New module**: `pfc_inductor/cli/__init__.py` with one file
  per subcommand. Each subcommand is a thin wrapper around the
  same Python API the GUI uses; **no new physics or business
  logic**.
- **Entry-point change**: `pyproject.toml` `[project.scripts]`
  gets a new alias if needed, but `magnadesign` already maps to
  `__main__:main` — that main now dispatches: with no subcommand →
  GUI; with a subcommand → CLI.
- **Dependency**: `click >= 8.1` (4 KB binary, MIT). Already
  pulled in transitively but pinned here.
- **Tests**: `tests/test_cli_*` — one file per subcommand,
  exercising both happy path and exit codes; ~20 tests total.
- **Docs**: `docs/cli.md` with copy-paste examples.
- **Capability added**: `headless-cli`.
- **Effort**: ~1 week. Each subcommand is a 30-line shim around
  existing API plus a Click definition.
