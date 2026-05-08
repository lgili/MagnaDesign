"""``magnadesign`` headless command-line interface.

This module is the dispatch entry point for every non-GUI workflow:
batch sweeps, CI regressions, vendor-pipeline integrations,
overnight cascades. Each subcommand is a thin wrapper around the
same Python API the GUI uses — no business logic lives here, just
argument parsing and output formatting.

Invocation
----------

    magnadesign --help
    magnadesign design project.pfc
    magnadesign sweep project.pfc --top 25 --rank loss
    magnadesign cascade project.pfc --tier2-k 50 --workers 4

Bare ``magnadesign`` with no subcommand still launches the GUI
(see :mod:`pfc_inductor.__main__`); the dispatch chooses CLI vs.
GUI based on whether the first argument matches a registered
subcommand.

Exit codes
----------

See :mod:`pfc_inductor.cli.exit_codes` — Unix-conventional so CI
pipelines can branch on result class (compliance fail vs. generic
error vs. usage error).
"""
from __future__ import annotations

import click

from pfc_inductor.cli.exit_codes import EXIT_CODES, ExitCode

# Subcommand modules expose a ``register(group)`` function so the
# top-level group's command list is discovered, not hard-coded —
# adding a new subcommand is "drop the file + import here".
from pfc_inductor.cli import design as _design_cmd
from pfc_inductor.cli import sweep as _sweep_cmd
from pfc_inductor.cli import worst_case as _worst_case_cmd

__all__ = [
    "cli",
    "main",
    "ExitCode",
    "EXIT_CODES",
]


def _print_version(ctx: click.Context, _param: click.Parameter,
                   value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    # Resolve from package metadata so the CLI tracks
    # ``pyproject.toml`` without a hardcoded duplicate.
    try:
        from importlib.metadata import version
        click.echo(f"magnadesign {version('magnadesign')}")
    except Exception:
        click.echo("magnadesign (version unavailable)")
    ctx.exit(0)


@click.group(
    help="MagnaDesign headless CLI — drive the design engine "
         "from scripts and CI pipelines.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--version",
    is_flag=True,
    callback=_print_version,
    expose_value=False,
    is_eager=True,
    help="Print the package version and exit.",
)
def cli() -> None:
    """Entry-point group. Subcommands are registered below."""


# Register every subcommand module on the group.
_design_cmd.register(cli)
_sweep_cmd.register(cli)
_worst_case_cmd.register(cli)


# Names of registered subcommands. Used by ``__main__.main`` to
# decide between CLI and GUI dispatch — a bare ``magnadesign`` (or
# one whose first argument doesn't match a known subcommand) opens
# the GUI for backward compatibility with the existing
# entry-point launchers and Windows shortcuts.
SUBCOMMANDS: frozenset[str] = frozenset(cli.commands.keys())


def main(argv: list[str] | None = None) -> int:
    """CLI dispatch entry-point.

    Returns the exit code from Click. Wrapped in a function so
    ``__main__.py`` can call it cleanly when it detects a CLI
    argument. Click normally calls ``sys.exit`` itself; we set
    ``standalone_mode=False`` to let the caller decide.
    """
    try:
        result = cli.main(args=argv, standalone_mode=False)
        # Click returns the subcommand's return value (int when
        # they call ctx.exit(code)) or 0 implicitly.
        return int(result) if isinstance(result, int) else ExitCode.OK
    except click.UsageError as exc:
        click.echo(f"Error: {exc.format_message()}", err=True)
        return ExitCode.USAGE_ERROR
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except SystemExit as exc:
        # Click subcommands sometimes raise SystemExit directly
        # (e.g. via ctx.exit). Normalise to an int.
        code = exc.code
        if code is None:
            return ExitCode.OK
        return int(code) if isinstance(code, int) else ExitCode.GENERIC_ERROR
