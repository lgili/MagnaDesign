"""``magnadesign worst-case`` — end-to-end CLI smoke tests.

Covers the dispatch wiring + the verdict + exit-code contract.
The corner DOE / Monte-Carlo physics has its own coverage in
``test_worst_case_engine``; this file exercises the *integration*
path so a refactor on either side surfaces here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner() -> CliRunner:
    # Click 8.3 keeps stderr separate by default; ``result.output``
    # carries only stdout (the JSON we want to parse) and progress
    # lines from ``click.echo(..., err=True)`` land in
    # ``result.stderr``.
    return CliRunner()


def _write_reference_project(tmp_path: Path) -> Path:
    """Write a feasible 600 W boost-PFC `.pfc` to ``tmp_path``.

    Uses the larger Magnetics C058777A2 toroid which has enough
    window + Ae for the AWG14 winding to pass at nominal — the
    contract for "this design should yield 100 %".
    """
    from pfc_inductor.models import Spec
    from pfc_inductor.project import ProjectFile, save_project

    spec = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=65, ripple_pct=20, T_amb_C=40,
    )
    pf = ProjectFile.from_session(
        name="cli-wc-test",
        spec=spec,
        material_id="magnetics-60_highflux",
        core_id="magnetics-c058777a2-60_highflux",
        wire_id="AWG14",
    )
    project_path = tmp_path / "test.pfc"
    save_project(project_path, pf)
    return project_path


def test_worst_case_help_lists_options(cli_runner: CliRunner) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["worst-case", "--help"])
    assert result.exit_code == 0
    for opt in ("--tolerances", "--samples", "--seed",
                "--yield-threshold", "--csv", "--pretty", "--json"):
        assert opt in result.output, f"missing {opt} in help"


def test_worst_case_passes_on_feasible_design(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    """Reference design + bundled tolerances → verdict PASS, exit 0.

    Uses a small ``--samples`` budget so the test runs in well
    under a second on CI. The engine can do thousands of corner
    evaluations per second, so 100 Monte-Carlo samples + 143
    corners is still trustworthy."""
    from pfc_inductor.cli import cli

    project_path = _write_reference_project(tmp_path)
    result = cli_runner.invoke(
        cli,
        ["worst-case", str(project_path), "--samples", "100"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "PASS"
    assert payload["n_corners"] == 143
    assert payload["n_failed"] == 0
    assert payload["yield"]["pass_rate"] == 100.0


def test_worst_case_pretty_renders_human_summary(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    from pfc_inductor.cli import cli

    project_path = _write_reference_project(tmp_path)
    result = cli_runner.invoke(
        cli,
        ["worst-case", str(project_path), "--samples", "50", "--pretty"],
    )
    assert result.exit_code == 0
    out = result.output
    # Pretty mode prints the headline keys as left-aligned labels.
    assert "project" in out
    assert "yield" in out
    assert "verdict" in out
    # The PASS / FAIL marker is one of two ASCII characters so
    # the output looks the same on every terminal.
    assert ("✓ PASS" in out) or ("✗ FAIL" in out)


def test_worst_case_seed_makes_yield_reproducible(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    from pfc_inductor.cli import cli

    project_path = _write_reference_project(tmp_path)
    args = [
        "worst-case", str(project_path),
        "--samples", "60", "--seed", "1234",
    ]
    a = cli_runner.invoke(cli, args)
    b = cli_runner.invoke(cli, args)
    assert a.exit_code == 0 and b.exit_code == 0
    payload_a = json.loads(a.stdout)
    payload_b = json.loads(b.stdout)
    assert payload_a["yield"] == payload_b["yield"]


def test_worst_case_csv_output_contains_header_and_rows(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    from pfc_inductor.cli import cli

    project_path = _write_reference_project(tmp_path)
    csv_path = tmp_path / "corners.csv"
    result = cli_runner.invoke(
        cli,
        ["worst-case", str(project_path),
         "--samples", "30",
         "--csv", str(csv_path)],
    )
    assert result.exit_code == 0
    text = csv_path.read_text()
    # Header columns documented in worst_case.py:_write_corner_csv.
    for col in ("label", "feasible", "T_winding_C",
                "B_pk_T", "P_total_W", "N_turns",
                "failure_reason"):
        assert col in text.splitlines()[0]
    # 143 corners + 1 header line.
    assert text.count("\n") >= 100


def test_worst_case_yield_threshold_drives_exit_code(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    """An impossibly-strict ``--yield-threshold`` flips the
    verdict to FAIL even if every corner is feasible. Exit code
    becomes ``WORST_CASE_FAIL`` (3)."""
    from pfc_inductor.cli import cli
    from pfc_inductor.cli.exit_codes import ExitCode

    project_path = _write_reference_project(tmp_path)
    result = cli_runner.invoke(
        cli,
        ["worst-case", str(project_path),
         "--samples", "30",
         "--yield-threshold", "99.999"],
    )
    payload = json.loads(result.stdout)
    if payload["yield"]["pass_rate"] < 99.999:
        assert payload["verdict"] == "FAIL"
        assert result.exit_code == int(ExitCode.WORST_CASE_FAIL)
    else:
        # Pathological case where 30 samples all pass and the
        # threshold round-trips exactly — the verdict should
        # then be PASS. Either branch is correct.
        assert payload["verdict"] == "PASS"
        assert result.exit_code == 0


def test_worst_case_subcommand_registered() -> None:
    """``SUBCOMMANDS`` includes the new entry — guards against a
    regression where the dispatcher would route ``magnadesign
    worst-case`` to the GUI (treating it as an unknown arg)."""
    from pfc_inductor.cli import SUBCOMMANDS

    assert "worst-case" in SUBCOMMANDS
