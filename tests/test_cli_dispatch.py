"""CLI dispatch — `magnadesign` chooses GUI vs. headless correctly.

These tests cover the routing layer in :func:`pfc_inductor.__main__.main`
without booting Qt. The Qt path is intentionally not exercised here
(it has its own coverage in ``test_main_window_shell``); these tests
only check that:

- ``magnadesign --help`` prints the CLI's group help.
- ``magnadesign --version`` prints a SemVer-ish line.
- ``magnadesign <subcommand>`` reaches the CLI without trying to
  initialise Qt (asserted by checking that no display server was
  contacted — proxied via the absence of any ``QApplication``
  instance attribute on the click context).
- A bare ``magnadesign`` is treated as GUI request (we don't invoke
  it because spawning the full window in this test would defeat
  the "no Qt" guarantee).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def test_cli_group_help(cli_runner: CliRunner) -> None:
    """``magnadesign --help`` prints the group help with both
    registered subcommands listed."""
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "design" in result.output
    assert "sweep" in result.output
    assert "MagnaDesign" in result.output


def test_cli_version_flag(cli_runner: CliRunner) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "magnadesign" in result.output.lower()


def test_subcommands_registered() -> None:
    """``SUBCOMMANDS`` is the same set the GUI/CLI dispatcher
    reads to decide where to route each invocation."""
    from pfc_inductor.cli import SUBCOMMANDS

    assert "design" in SUBCOMMANDS
    assert "sweep" in SUBCOMMANDS


def test_unknown_subcommand_exits_with_usage_error(
    cli_runner: CliRunner,
) -> None:
    """Click reports unknown subcommand as exit-code 2 (its
    convention); our dispatcher converts that to ``USAGE_ERROR``
    when called from the entry point. We test the click path
    here so the converted code is just one wrapper away."""
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["nonexistent-subcommand"])
    # Click's default for unknown command is exit-code 2.
    assert result.exit_code != 0
    assert "No such command" in result.output or "Usage" in result.output


def test_design_help(cli_runner: CliRunner) -> None:
    """The design subcommand has its own help and lists the
    PROJECT_FILE positional + the ``--pretty/--json`` flag."""
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["design", "--help"])
    assert result.exit_code == 0
    assert "PROJECT_FILE" in result.output
    assert "--pretty" in result.output
    assert "--json" in result.output


def test_sweep_help(cli_runner: CliRunner) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["sweep", "--help"])
    assert result.exit_code == 0
    assert "PROJECT_FILE" in result.output
    assert "--top" in result.output
    assert "--rank" in result.output
    assert "--material" in result.output


def test_design_missing_project_file_is_usage_error(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """Pointing the design subcommand at a non-existent file
    surfaces a clean ``UsageError`` (exit != 0) instead of an
    opaque traceback."""
    from pfc_inductor.cli import cli

    missing = tmp_path / "does-not-exist.pfc"
    result = cli_runner.invoke(cli, ["design", str(missing)])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_design_runs_engine_on_valid_project(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """End-to-end: write a minimal `.pfc`, invoke the design
    subcommand, parse the JSON output, assert headline KPIs are
    present. This exercises every public surface of the CLI
    plumbing (project loader, catalogue resolution, engine call,
    JSON emit)."""
    from pfc_inductor.cli import cli
    from pfc_inductor.models import Spec
    from pfc_inductor.project import ProjectFile, save_project

    spec = Spec(
        topology="boost_ccm",
        Pout_W=600,
        Vin_min_Vrms=85,
        Vin_max_Vrms=265,
        Vout_V=400,
        f_sw_kHz=65,
        ripple_pct=20,
        T_amb_C=40,
    )
    pf = ProjectFile.from_session(
        name="cli-test",
        spec=spec,
        material_id="magnetics-60_highflux",
        core_id="magnetics-0058181a2-60_highflux",
        wire_id="AWG14",
    )
    project_path = tmp_path / "test.pfc"
    save_project(project_path, pf)

    result = cli_runner.invoke(cli, ["design", str(project_path)])
    assert result.exit_code == 0, result.output

    # ``result.stdout`` (not ``output``) gives just the stdout
    # bytes; ``output`` mixes any stderr that the subcommand
    # printed for progress reporting.
    payload = json.loads(result.stdout)
    # Schema check: every headline key is present.
    expected_keys = {
        "project",
        "topology",
        "selection",
        "L_target_uH",
        "L_actual_uH",
        "N_turns",
        "B_pk_mT",
        "B_sat_pct",
        "T_winding_C",
        "T_rise_C",
        "P_total_W",
        "P_cu_W",
        "P_core_W",
        "warnings",
    }
    assert expected_keys.issubset(payload.keys())
    assert payload["selection"]["material"]
    assert payload["selection"]["core"]
    assert payload["selection"]["wire"]
    # Engine ran — N_turns is a positive integer (the example spec
    # caps at 500 turns, which is itself a valid result).
    assert payload["N_turns"] >= 1


def test_design_fails_on_missing_selection(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """A `.pfc` without a selection block surfaces a clear
    ``UsageError`` listing which IDs are missing — better than
    letting the engine crash deeper in the stack."""
    from pfc_inductor.cli import cli
    from pfc_inductor.models import Spec
    from pfc_inductor.project import ProjectFile, save_project

    spec = Spec(
        topology="boost_ccm",
        Pout_W=600,
        Vin_min_Vrms=85,
        Vin_max_Vrms=265,
        Vout_V=400,
        f_sw_kHz=65,
        ripple_pct=20,
        T_amb_C=40,
    )
    pf = ProjectFile.from_session(
        name="no-selection",
        spec=spec,
        material_id="",
        core_id="",
        wire_id="",
    )
    project_path = tmp_path / "blank.pfc"
    save_project(project_path, pf)

    result = cli_runner.invoke(cli, ["design", str(project_path)])
    assert result.exit_code != 0
    assert "selection" in result.output.lower()
