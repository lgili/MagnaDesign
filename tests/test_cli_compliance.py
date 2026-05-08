"""``magnadesign compliance`` — end-to-end CLI tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def _write_line_reactor_project(tmp_path: Path) -> Path:
    from pfc_inductor.models import Spec
    from pfc_inductor.project import ProjectFile, save_project

    spec = Spec(
        topology="line_reactor",
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vin_nom_Vrms=230,
        Pout_W=600, n_phases=1, L_req_mH=10.0,
        I_rated_Arms=2.6, T_amb_C=40,
    )
    pf = ProjectFile.from_session(
        name="cli-compliance-test",
        spec=spec,
        material_id="magnetics-60_highflux",
        core_id="magnetics-c058777a2-60_highflux",
        wire_id="AWG14",
    )
    project_path = tmp_path / "lr.pfc"
    save_project(project_path, pf)
    return project_path


def _write_boost_project(tmp_path: Path) -> Path:
    from pfc_inductor.models import Spec
    from pfc_inductor.project import ProjectFile, save_project

    spec = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=65, ripple_pct=20, T_amb_C=40,
    )
    pf = ProjectFile.from_session(
        name="cli-compliance-boost",
        spec=spec,
        material_id="magnetics-60_highflux",
        core_id="magnetics-c058777a2-60_highflux",
        wire_id="AWG14",
    )
    project_path = tmp_path / "boost.pfc"
    save_project(project_path, pf)
    return project_path


def test_compliance_help_lists_options(cli_runner: CliRunner) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["compliance", "--help"])
    assert result.exit_code == 0
    for opt in ("--region", "--edition", "--out",
                "--allow-marginal", "--strict", "--pretty", "--json"):
        assert opt in result.output, f"missing {opt} in help"


def test_compliance_subcommand_registered() -> None:
    from pfc_inductor.cli import SUBCOMMANDS
    assert "compliance" in SUBCOMMANDS


def test_compliance_line_reactor_fails(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    """1φ line reactor at 230 V / 600 W exceeds the Class D
    h=5 limit — the CLI returns the COMPLIANCE_FAIL exit code
    so CI pipelines can branch on it."""
    from pfc_inductor.cli import cli
    from pfc_inductor.cli.exit_codes import ExitCode

    project_path = _write_line_reactor_project(tmp_path)
    result = cli_runner.invoke(
        cli, ["compliance", str(project_path), "--region", "EU"],
    )
    payload = json.loads(result.stdout)
    assert payload["overall"] == "FAIL"
    assert result.exit_code == int(ExitCode.COMPLIANCE_FAIL)


def test_compliance_boost_passes_with_caveat(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    """Active boost-PFC has no measurable higher-order harmonics
    in the engine's analytical output — verdict PASS, exit 0."""
    from pfc_inductor.cli import cli

    project_path = _write_boost_project(tmp_path)
    result = cli_runner.invoke(
        cli, ["compliance", str(project_path), "--region", "EU"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["overall"] == "PASS"
    assert "LISN" in payload["standards"][0]["summary"]


def test_compliance_us_region_emits_warning(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    """US region today routes through no standard (UL 1411 is
    queued for a follow-up commit). The CLI exits 0 with a
    GitHub-Actions ``::warning::`` line so a CI script gets a
    visible signal that nothing was checked."""
    from pfc_inductor.cli import cli

    project_path = _write_boost_project(tmp_path)
    result = cli_runner.invoke(
        cli, ["compliance", str(project_path), "--region", "US"],
    )
    assert result.exit_code == 0
    assert "::warning::" in result.stderr or "::warning::" in result.output
    payload = json.loads(result.stdout)
    assert payload["overall"] == "NOT APPLICABLE"


def test_compliance_writes_pdf_to_out_path(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    from pfc_inductor.cli import cli

    project_path = _write_line_reactor_project(tmp_path)
    pdf_path = tmp_path / "compliance.pdf"
    result = cli_runner.invoke(
        cli,
        ["compliance", str(project_path),
         "--region", "EU", "--out", str(pdf_path)],
    )
    # Even though the line reactor FAILS, the PDF still gets
    # written — the writer is decoupled from the verdict so a
    # FAIL report is still saved (more useful than just the
    # exit code).
    assert pdf_path.is_file()
    assert pdf_path.read_bytes().startswith(b"%PDF-")
    assert result.exit_code != 0  # FAIL still surfaces


def test_compliance_pretty_mode_renders_human_summary(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    from pfc_inductor.cli import cli

    project_path = _write_line_reactor_project(tmp_path)
    result = cli_runner.invoke(
        cli,
        ["compliance", str(project_path),
         "--region", "EU", "--pretty"],
    )
    out = result.output
    assert "overall" in out
    assert "IEC 61000-3-2" in out
    # The pretty output shows per-row PASS / FAIL marks.
    assert "✓" in out or "✗" in out
