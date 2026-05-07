"""Smoke tests for `scripts/cascade_cli.py`.

End-to-end coverage of the CLI subcommands against an isolated
temporary store. Subprocess invocation is used so the tests
exercise argparse, exit codes, and stdout/stderr formatting.

Marked `slow` because each subprocess invocation imports the full
world (PySide6, pyvista, scipy, the materials/cores/wires DB) and
runs a real cascade. Skipped by default; run with
``uv run pytest -m slow``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "cascade_cli.py"


def _run(args: list[str], *, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=REPO, env=env, timeout=300,
    )


def test_cli_help_lists_subcommands():
    out = _run(["--help"])
    assert out.returncode == 0
    for sub in ("run", "resume", "list", "top", "inspect", "stats"):
        assert sub in out.stdout


def test_cli_list_on_empty_store_is_friendly(tmp_path: Path):
    store = tmp_path / "cascade.db"
    out = _run(["--store", str(store), "list"])
    assert out.returncode == 0, out.stderr
    assert "no" in out.stdout.lower()


def test_cli_run_executes_and_exits_zero(tmp_path: Path):
    """Restrict to one material to keep the run fast."""
    store = tmp_path / "cascade.db"
    out = _run([
        "--store", str(store),
        "run",
        "--topology", "boost_ccm",
        "--pout", "800",
        "--material", "magnetics-60_highflux",
        "--parallelism", "1",
        "--top", "5",
    ])
    assert out.returncode == 0, f"stderr:\n{out.stderr}"
    assert "run_id" in out.stderr
    assert "Per-tier breakdown" in out.stdout
    assert "Top 5 by Tier-1 loss" in out.stdout
    # Tier-0 and Tier-1 counters should both be present.
    assert "Tier 0" in out.stdout
    assert "Tier 1" in out.stdout


def test_cli_run_emits_json_summary(tmp_path: Path):
    store = tmp_path / "cascade.db"
    json_path = tmp_path / "summary.json"
    out = _run([
        "--store", str(store),
        "run",
        "--topology", "boost_ccm",
        "--pout", "800",
        "--material", "magnetics-60_highflux",
        "--parallelism", "1",
        "--top", "3",
        "--json-out", str(json_path),
    ])
    assert out.returncode == 0, out.stderr
    payload = json.loads(json_path.read_text())
    assert payload["status"] == "done"
    assert "run_id" in payload
    assert "stats" in payload
    assert payload["stats"]["tier1_evaluated"] >= 1
    # `dataclass` -> JSON keeps the attribute names as keys.
    assert "reject_reasons" in payload["stats"]
    assert len(payload["top"]) <= 3


def test_cli_run_then_list_then_top(tmp_path: Path):
    store = tmp_path / "cascade.db"
    # Step 1 — kick off a run.
    run_out = _run([
        "--store", str(store),
        "run",
        "--topology", "boost_ccm", "--pout", "800",
        "--material", "magnetics-60_highflux",
        "--parallelism", "1", "--top", "5",
    ])
    assert run_out.returncode == 0, run_out.stderr

    # Step 2 — `list` should show one done row.
    list_out = _run(["--store", str(store), "list"])
    assert list_out.returncode == 0, list_out.stderr
    assert "done" in list_out.stdout
    # Extract the run_id from the first non-header row.
    data_lines = [ln for ln in list_out.stdout.splitlines()
                  if ln and not ln.startswith(("run_id", "-"))]
    assert data_lines, list_out.stdout
    run_id = data_lines[0].split()[0]
    assert run_id  # non-empty

    # Step 3 — `top` should emit a non-empty table with that run_id.
    top_out = _run(["--store", str(store), "top", "--run-id", run_id, "--n", "3"])
    assert top_out.returncode == 0, top_out.stderr
    assert "core_id" in top_out.stdout

    # Step 4 — `stats` should expose tier counts.
    stats_out = _run([
        "--store", str(store), "stats",
        "--run-id", run_id, "--json",
    ])
    assert stats_out.returncode == 0, stats_out.stderr
    assert "Tier 0 feasible" in stats_out.stdout
    # The JSON tail must parse and reflect the same numbers.
    json_block = stats_out.stdout[stats_out.stdout.index("{"):]
    parsed = json.loads(json_block)
    assert parsed["total"] >= 1


def test_cli_inspect_round_trips_spec(tmp_path: Path):
    store = tmp_path / "cascade.db"
    _run([
        "--store", str(store),
        "run",
        "--topology", "boost_ccm", "--pout", "800",
        "--material", "magnetics-60_highflux",
        "--parallelism", "1", "--top", "1",
    ])
    list_out = _run(["--store", str(store), "list"])
    run_id = next(
        ln.split()[0] for ln in list_out.stdout.splitlines()
        if ln and not ln.startswith(("run_id", "-"))
    )
    insp = _run(["--store", str(store), "inspect", "--run-id", run_id])
    assert insp.returncode == 0, insp.stderr
    assert "spec_hash" in insp.stdout
    assert "topology" in insp.stdout


def test_cli_inspect_unknown_run_exits_nonzero(tmp_path: Path):
    store = tmp_path / "cascade.db"
    # `list` first ensures the store exists.
    _run(["--store", str(store), "list"])
    out = _run(["--store", str(store), "inspect", "--run-id", "does-not-exist"])
    assert out.returncode != 0
    assert "not in store" in out.stderr


@pytest.mark.parametrize("topology,extras", [
    ("passive_choke", ["--pout", "400"]),
    ("line_reactor", ["--phases", "3", "--vin-nom", "400",
                      "--l-req", "1.0", "--i-rated", "30"]),
])
def test_cli_runs_all_three_topologies(tmp_path: Path, topology, extras):
    store = tmp_path / "cascade.db"
    out = _run([
        "--store", str(store),
        "run", "--topology", topology,
        "--material", "magnetics-60_highflux",
        "--parallelism", "1", "--top", "3",
        *extras,
    ])
    assert out.returncode == 0, f"{topology} failed:\n{out.stderr}\n{out.stdout}"
    assert "Per-tier breakdown" in out.stdout
