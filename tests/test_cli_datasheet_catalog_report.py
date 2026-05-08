"""``magnadesign datasheet`` / ``catalog`` / ``report`` — CLI tests.

Three subcommands that round out the headless runner:

- ``datasheet`` writes a PDF or HTML datasheet to disk.
- ``catalog`` lists materials / cores / wires (JSON or CSV).
- ``report`` bundles datasheet + KPIs + (optionally) compliance
  into one directory.

Tests focus on shape (file produced, exit code, content
markers) rather than byte-level layout — datasheet format
details belong to the report module's own test suites.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def _write_boost_project(tmp_path: Path) -> Path:
    """Build a feasible 600 W boost-PFC `.pfc` project file."""
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
        name="cli-extras-boost",
        spec=spec,
        material_id="magnetics-60_highflux",
        core_id="magnetics-c058777a2-60_highflux",
        wire_id="AWG14",
    )
    project_path = tmp_path / "boost.pfc"
    save_project(project_path, pf)
    return project_path


# ---------------------------------------------------------------------------
# datasheet
# ---------------------------------------------------------------------------
def test_datasheet_help_lists_options(cli_runner: CliRunner) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["datasheet", "--help"])
    assert result.exit_code == 0
    for opt in ("--out", "--designer", "--revision", "--title"):
        assert opt in result.output, f"missing {opt} in help"


def test_datasheet_subcommand_registered() -> None:
    from pfc_inductor.cli import SUBCOMMANDS

    assert "datasheet" in SUBCOMMANDS


def test_datasheet_writes_pdf(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """`.pdf` extension → ReportLab native PDF written to disk."""
    from pfc_inductor.cli import cli

    project_path = _write_boost_project(tmp_path)
    out = tmp_path / "out.pdf"
    result = cli_runner.invoke(
        cli,
        ["datasheet", str(project_path), "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.is_file()
    assert out.stat().st_size > 5000
    assert out.read_bytes().startswith(b"%PDF-")


def test_datasheet_writes_html(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """Non-`.pdf` extension → HTML datasheet."""
    from pfc_inductor.cli import cli

    project_path = _write_boost_project(tmp_path)
    out = tmp_path / "out.html"
    result = cli_runner.invoke(
        cli,
        ["datasheet", str(project_path), "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.is_file()
    text = out.read_text()
    # HTML report starts with <!DOCTYPE> or <html>.
    assert "<html" in text.lower() or "<!doctype" in text.lower()


def test_datasheet_missing_project_is_usage_error(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    from pfc_inductor.cli import cli

    out = tmp_path / "out.pdf"
    result = cli_runner.invoke(
        cli,
        ["datasheet", str(tmp_path / "nope.pfc"), "--out", str(out)],
    )
    assert result.exit_code != 0
    assert (
        "not found" in result.output.lower()
        or "usage" in result.output.lower()
        or "error" in result.output.lower()
    )


# ---------------------------------------------------------------------------
# catalog
# ---------------------------------------------------------------------------
def test_catalog_help_lists_options(cli_runner: CliRunner) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["catalog", "--help"])
    assert result.exit_code == 0
    for opt in ("--filter", "--csv", "--limit"):
        assert opt in result.output, f"missing {opt} in help"


def test_catalog_subcommand_registered() -> None:
    from pfc_inductor.cli import SUBCOMMANDS

    assert "catalog" in SUBCOMMANDS


def test_catalog_materials_emits_json(cli_runner: CliRunner) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["catalog", "materials"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    # Bundled catalogue ships dozens of materials; require a
    # non-trivial number so a regression that breaks the loader
    # surfaces here.
    assert len(payload) > 5


def test_catalog_cores_emits_json(cli_runner: CliRunner) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["catalog", "cores"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert len(payload) > 5


def test_catalog_wires_emits_json(cli_runner: CliRunner) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["catalog", "wires"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert len(payload) > 5


def test_catalog_filter_narrows_result(cli_runner: CliRunner) -> None:
    """`--filter vendor=Magnetics` keeps only Magnetics rows."""
    from pfc_inductor.cli import cli

    full = cli_runner.invoke(cli, ["catalog", "cores"])
    full_payload = json.loads(full.stdout)
    filtered = cli_runner.invoke(
        cli,
        ["catalog", "cores", "--filter", "vendor=Magnetics"],
    )
    filtered_payload = json.loads(filtered.stdout)

    assert filtered.exit_code == 0
    assert 0 < len(filtered_payload) < len(full_payload)
    # Every kept row must carry the filter value somewhere.
    for row in filtered_payload:
        assert "magnetics" in str(row.get("vendor", "")).lower()


def test_catalog_csv_writes_file(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    from pfc_inductor.cli import cli

    out = tmp_path / "mats.csv"
    result = cli_runner.invoke(
        cli,
        ["catalog", "materials", "--csv", str(out)],
    )
    assert result.exit_code == 0
    assert out.is_file()
    assert out.stat().st_size > 0
    # First non-empty line is the header — must contain at least
    # a recognisable column.
    head = out.read_text().splitlines()[0]
    assert "," in head
    # Rows below the header.
    assert len(out.read_text().splitlines()) > 5


def test_catalog_limit_truncates(cli_runner: CliRunner) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(
        cli,
        ["catalog", "wires", "--limit", "3"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload) == 3


def test_catalog_unknown_resource_is_usage_error(
    cli_runner: CliRunner,
) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["catalog", "nonsense"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
def test_report_help_lists_options(cli_runner: CliRunner) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["report", "--help"])
    assert result.exit_code == 0
    for opt in ("--out", "--region", "--edition", "--designer", "--revision"):
        assert opt in result.output, f"missing {opt} in help"


def test_report_subcommand_registered() -> None:
    from pfc_inductor.cli import SUBCOMMANDS

    assert "report" in SUBCOMMANDS


def test_report_writes_minimal_bundle(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """No region → datasheet + KPI + manifest only."""
    from pfc_inductor.cli import cli

    project_path = _write_boost_project(tmp_path)
    out_dir = tmp_path / "bundle"
    result = cli_runner.invoke(
        cli,
        ["report", str(project_path), "--out", str(out_dir)],
    )
    assert result.exit_code == 0, result.output
    assert (out_dir / "datasheet.pdf").is_file()
    assert (out_dir / "kpi.json").is_file()
    assert (out_dir / "manifest.json").is_file()
    # No compliance report when --region wasn't passed.
    assert not list(out_dir.glob("compliance_*.pdf"))


def test_report_kpi_json_carries_design_keys(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """The KPI dump should mirror the ``design`` subcommand's
    payload — same shape, so a downstream script can read either
    interchangeably."""
    from pfc_inductor.cli import cli

    project_path = _write_boost_project(tmp_path)
    out_dir = tmp_path / "bundle"
    cli_runner.invoke(
        cli,
        ["report", str(project_path), "--out", str(out_dir)],
    )
    payload = json.loads((out_dir / "kpi.json").read_text())
    for key in (
        "project",
        "topology",
        "selection",
        "L_target_uH",
        "L_actual_uH",
        "B_pk_mT",
        "T_winding_C",
        "P_total_W",
    ):
        assert key in payload, f"missing KPI key {key!r}"


def test_report_manifest_carries_sha256(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """Every artefact must appear in the manifest with a
    SHA-256 — required for auditor-friendly bundle verification."""
    from pfc_inductor.cli import cli

    project_path = _write_boost_project(tmp_path)
    out_dir = tmp_path / "bundle"
    cli_runner.invoke(
        cli,
        ["report", str(project_path), "--out", str(out_dir)],
    )
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert "magnadesign_version" in manifest
    assert "generated_at" in manifest
    artefacts = manifest["artefacts"]
    names = {a["name"] for a in artefacts}
    assert "datasheet.pdf" in names
    assert "kpi.json" in names
    for a in artefacts:
        assert len(a["sha256"]) == 64  # SHA-256 hex
        assert a["size"] > 0


def test_report_with_region_writes_compliance_pdf(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """`--region EU` adds a compliance PDF and routes the exit
    code through the bundle's overall verdict."""
    from pfc_inductor.cli import cli

    project_path = _write_boost_project(tmp_path)
    out_dir = tmp_path / "bundle"
    result = cli_runner.invoke(
        cli,
        ["report", str(project_path), "--out", str(out_dir), "--region", "EU"],
    )
    assert (out_dir / "compliance_EU.pdf").is_file()
    # Boost-PFC carries IEC 61000-3-2 + EN 55032; verdict could
    # be PASS (exit 0) or FAIL (exit 2) depending on the engine's
    # current envelope — both are valid.
    assert result.exit_code in (0, 2)


def test_report_missing_project_is_usage_error(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(
        cli,
        ["report", str(tmp_path / "ghost.pfc"), "--out", str(tmp_path / "bundle")],
    )
    assert result.exit_code != 0
