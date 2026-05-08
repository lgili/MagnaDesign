"""Circuit-simulator export — module + CLI tests.

Three exporters share the L(I) table builder; tests exercise the
table first, then assert each emitter produces a syntactically
plausible artefact (header comment block, expected keywords,
non-decreasing flux table). Round-trips into the actual
simulators belong to a separate manual-validation cycle —
unit tests stay format-aware but not simulator-bound.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def reference_design():
    """Boost-PFC reference specimen (same as other manufacturing
    tests). Re-built per module to avoid fixture cross-talk."""
    from pfc_inductor.data_loader import (
        ensure_user_data,
        load_cores,
        load_materials,
        load_wires,
    )
    from pfc_inductor.design import design as run_design
    from pfc_inductor.models import Spec

    ensure_user_data()
    mats = load_materials()
    cores = load_cores()
    wires = load_wires()
    spec = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=65, ripple_pct=20, T_amb_C=40,
    )
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores
                if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    result = run_design(spec, core, wire, mat)
    return spec, core, wire, mat, result


# ---------------------------------------------------------------------------
# L(I) curve builder
# ---------------------------------------------------------------------------
def test_L_vs_I_table_zero_current_returns_nominal(
    reference_design,
) -> None:
    """At I=0, L = N²·AL — no rolloff."""
    from pfc_inductor.export import L_vs_I_table

    _spec, core, _wire, mat, result = reference_design
    table = L_vs_I_table(
        material=mat, core=core,
        n_turns=int(result.N_turns),
        I_max=10.0, n_points=10,
    )
    assert table[0][0] == 0.0
    L0 = table[0][1]
    expected_L_uH = (
        int(result.N_turns) ** 2 * core.AL_nH * 1e-3
    )
    # Allow a 5 % tolerance for floating-point noise.
    assert L0 == pytest.approx(expected_L_uH * 1e-6, rel=0.05)


def test_L_vs_I_table_decreases_with_current(
    reference_design,
) -> None:
    """Powder cores (60 µ HighFlux) have a documented rolloff —
    L(I) should be monotonically non-increasing as bias rises."""
    from pfc_inductor.export import L_vs_I_table

    _spec, core, _wire, mat, result = reference_design
    table = L_vs_I_table(
        material=mat, core=core,
        n_turns=int(result.N_turns),
        I_max=20.0, n_points=20,
    )
    Ls = [L for _I, L in table]
    # Each adjacent pair must be non-increasing within numeric
    # tolerance — the engine never injects extra inductance under
    # bias.
    for prev, nxt in zip(Ls, Ls[1:]):
        assert nxt <= prev + 1e-12


def test_flux_vs_current_is_monotonic(reference_design) -> None:
    """Flux linkage λ = ∫₀^I L di must be monotonically non-
    decreasing — the integral of a non-negative function."""
    from pfc_inductor.export import flux_vs_current

    _spec, core, _wire, mat, result = reference_design
    table = flux_vs_current(
        material=mat, core=core,
        n_turns=int(result.N_turns),
        I_max=20.0, n_points=20,
    )
    fluxes = [f for _I, f in table]
    assert fluxes[0] == 0.0
    for prev, nxt in zip(fluxes, fluxes[1:]):
        assert nxt >= prev - 1e-15


def test_L_vs_I_table_handles_zero_imax(reference_design) -> None:
    """Degenerate I_max=0 shouldn't crash — emit a single 0-entry."""
    from pfc_inductor.export import L_vs_I_table

    _spec, core, _wire, mat, result = reference_design
    table = L_vs_I_table(
        material=mat, core=core,
        n_turns=int(result.N_turns),
        I_max=0.0,
    )
    assert table == [(0.0, 0.0)]


# ---------------------------------------------------------------------------
# LTspice emitter
# ---------------------------------------------------------------------------
def test_ltspice_emitter_includes_subckt_directive(
    reference_design,
) -> None:
    from pfc_inductor.export import to_ltspice_subcircuit

    spec, core, wire, mat, result = reference_design
    text = to_ltspice_subcircuit(
        spec=spec, core=core, wire=wire,
        material=mat, result=result, name="L_test",
    )
    assert ".subckt L_test" in text
    assert ".ends L_test" in text
    # Header carries the design provenance.
    assert "MagnaDesign" in text
    assert spec.topology in text
    assert core.part_number in text


def test_ltspice_emitter_table_has_pairs(reference_design) -> None:
    """The B-source table line must contain at least 5 (flux, I)
    comma pairs (we asked for 25 sweep points)."""
    from pfc_inductor.export import to_ltspice_subcircuit

    spec, core, wire, mat, result = reference_design
    text = to_ltspice_subcircuit(
        spec=spec, core=core, wire=wire,
        material=mat, result=result,
    )
    # Find the table line.
    table_line = next(
        line for line in text.splitlines()
        if "table(" in line.lower()
    )
    # Comma pairs — every other comma separates a (flux, I) pair.
    assert table_line.count(",") >= 10


# ---------------------------------------------------------------------------
# PSIM emitter
# ---------------------------------------------------------------------------
def test_psim_emitter_carries_flux_current_table(
    reference_design,
) -> None:
    from pfc_inductor.export import to_psim_fragment

    spec, core, wire, mat, result = reference_design
    text = to_psim_fragment(
        spec=spec, core=core, wire=wire,
        material=mat, result=result,
    )
    assert "MagnaDesign" in text
    assert "Flux_Current_Table" in text
    # Header lists the topology.
    assert spec.topology in text


def test_psim_emitter_table_is_monotone(reference_design) -> None:
    """Each non-comment line in the table block has two
    floats: current then flux. Flux must be monotonically
    non-decreasing."""
    from pfc_inductor.export import to_psim_fragment

    spec, core, wire, mat, result = reference_design
    text = to_psim_fragment(
        spec=spec, core=core, wire=wire,
        material=mat, result=result,
    )
    # Pull the inside of the table block.
    in_table = False
    pairs: list[tuple[float, float]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Flux_Current_Table = ("):
            in_table = True
            continue
        if not in_table:
            continue
        if stripped == ")":
            break
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            try:
                pairs.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    assert len(pairs) >= 5
    for prev, nxt in zip(pairs, pairs[1:]):
        assert nxt[1] >= prev[1] - 1e-15


# ---------------------------------------------------------------------------
# Modelica emitter
# ---------------------------------------------------------------------------
def test_modelica_emitter_carries_package_skeleton(
    reference_design,
) -> None:
    from pfc_inductor.export import to_modelica

    spec, core, wire, mat, result = reference_design
    text = to_modelica(
        spec=spec, core=core, wire=wire,
        material=mat, result=result, package="MyTest",
    )
    assert text.strip().startswith("within;")
    assert "package MyTest" in text
    assert "model PFCInductor" in text
    assert "end PFCInductor;" in text
    assert "end MyTest;" in text
    # Includes the L(I) lookup table.
    assert "CombiTable1Ds" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def _write_boost_project(tmp_path: Path) -> Path:
    from pfc_inductor.models import Spec
    from pfc_inductor.project import ProjectFile, save_project

    spec = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=65, ripple_pct=20, T_amb_C=40,
    )
    pf = ProjectFile.from_session(
        name="cli-circuit-boost",
        spec=spec,
        material_id="magnetics-60_highflux",
        core_id="magnetics-c058777a2-60_highflux",
        wire_id="AWG14",
    )
    project_path = tmp_path / "boost.pfc"
    save_project(project_path, pf)
    return project_path


def test_circuit_subcommand_registered() -> None:
    from pfc_inductor.cli import SUBCOMMANDS
    assert "circuit" in SUBCOMMANDS


def test_circuit_help_lists_options(cli_runner: CliRunner) -> None:
    from pfc_inductor.cli import cli

    result = cli_runner.invoke(cli, ["circuit", "--help"])
    assert result.exit_code == 0
    for opt in ("--format", "--out", "--name", "--n-points"):
        assert opt in result.output, f"missing {opt} in help"


def test_circuit_writes_ltspice_to_disk(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    from pfc_inductor.cli import cli

    project_path = _write_boost_project(tmp_path)
    out = tmp_path / "L_PFC.lib"
    result = cli_runner.invoke(
        cli,
        ["circuit", str(project_path),
         "--format", "ltspice", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.is_file()
    text = out.read_text()
    assert ".subckt L_PFC" in text
    assert ".ends L_PFC" in text


def test_circuit_writes_psim_to_disk(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    from pfc_inductor.cli import cli

    project_path = _write_boost_project(tmp_path)
    out = tmp_path / "L_PFC.psim.txt"
    result = cli_runner.invoke(
        cli,
        ["circuit", str(project_path),
         "--format", "psim", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.is_file()
    assert "Flux_Current_Table" in out.read_text()


def test_circuit_writes_modelica_to_disk(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    from pfc_inductor.cli import cli

    project_path = _write_boost_project(tmp_path)
    out = tmp_path / "PFC.mo"
    result = cli_runner.invoke(
        cli,
        ["circuit", str(project_path),
         "--format", "modelica",
         "--out", str(out), "--name", "MagnaPFC"],
    )
    assert result.exit_code == 0, result.output
    text = out.read_text()
    assert "package MagnaPFC" in text
    assert "end MagnaPFC;" in text


def test_circuit_stdout_when_no_out_flag(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    """Omitting `--out` prints the text on stdout."""
    from pfc_inductor.cli import cli

    project_path = _write_boost_project(tmp_path)
    result = cli_runner.invoke(
        cli, ["circuit", str(project_path), "--format", "ltspice"],
    )
    assert result.exit_code == 0
    assert ".subckt" in result.stdout


def test_circuit_unknown_format_is_usage_error(
    cli_runner: CliRunner, tmp_path: Path,
) -> None:
    from pfc_inductor.cli import cli

    project_path = _write_boost_project(tmp_path)
    result = cli_runner.invoke(
        cli,
        ["circuit", str(project_path),
         "--format", "spiceopus"],
    )
    assert result.exit_code != 0
