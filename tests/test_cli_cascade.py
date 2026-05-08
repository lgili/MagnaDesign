"""``magnadesign cascade`` CLI tests.

The full end-to-end run takes ~30 s on a modern laptop (it
sweeps the whole catalogue through Tier 0 + Tier 1) so it lives
behind the ``slow`` marker. The dispatch / help / wiring tests
here run in milliseconds and gate every commit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def test_cascade_subcommand_registered() -> None:
    from pfc_inductor.cli import SUBCOMMANDS

    assert "cascade" in SUBCOMMANDS


def test_cascade_help_lists_options(cli_runner: CliRunner) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["cascade", "--help"])
    assert result.exit_code == 0
    for opt in (
        "--tier2-k",
        "--tier3-k",
        "--tier4-k",
        "--workers",
        "--store",
        "--top",
        "--rank",
        "--csv",
        "--pretty",
        "--json",
    ):
        assert opt in result.output, f"missing {opt} in help"


def test_cascade_help_carries_rank_choices(cli_runner: CliRunner) -> None:
    """Server-side ranks honoured by the SQLite store. ``volume``
    isn't in this list because it requires a JOIN to cores —
    the help points users at the GUI for that case."""
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["cascade", "--help"])
    for choice in ("loss", "temp", "cost", "loss_t2"):
        assert choice in result.output


def test_cascade_rejects_missing_project_file(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(
        cli,
        ["cascade", str(tmp_path / "nope.pfc")],
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


@pytest.mark.slow
def test_cascade_full_run_writes_top_n(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """End-to-end smoke — gated as ``slow`` because it sweeps the
    full catalogue through Tier 0 + Tier 1 (~30 s). Run with
    ``pytest -m slow``."""
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
        name="cascade-cli-test",
        spec=spec,
        material_id="magnetics-60_highflux",
        core_id="magnetics-c058777a2-60_highflux",
        wire_id="AWG14",
    )
    project_path = tmp_path / "test.pfc"
    save_project(project_path, pf)

    csv_path = tmp_path / "top.csv"
    store_path = tmp_path / "store.db"
    result = cli_runner.invoke(
        cli,
        [
            "cascade",
            str(project_path),
            "--top",
            "5",
            "--workers",
            "2",
            "--store",
            str(store_path),
            "--csv",
            str(csv_path),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["n_top"] == 5
    assert payload["status"] in ("done", "ok", "completed")
    # Top-N rows have the schema the UI cascade page consumes.
    for row in payload["top"]:
        assert "core_id" in row
        assert "material_id" in row
        assert "wire_id" in row
        assert "loss_t1_W" in row
    assert csv_path.is_file()
    assert store_path.is_file()
