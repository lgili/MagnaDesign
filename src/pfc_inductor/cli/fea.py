"""``magnadesign fea`` subcommand — run the direct FEA backend.

A no-frills entry point so designers can sanity-check the direct
backend against FEMMT (or just run it stand-alone) without writing
a full project file. Useful for:

- Quick "does the direct backend agree with FEMMT on my core?" runs.
- Benchmark scripting (loop over cores via shell).
- Diagnosing calibration regressions when porting catalog entries.

Examples
========

::

    # Quick check against FEMMT
    magnadesign fea tdkepcos-pq-4040-n87 \\
        --turns 39 --current 8.0 --compare

    # Direct-only, JSON output for piping
    magnadesign fea tdkepcos-pq-4040-n87 \\
        --turns 39 --current 8.0 --json

    # Toroidal — analytical path, ~37 µs solve
    magnadesign fea magnetics-c058150a2-125_highflux \\
        --turns 50 --current 2.5 --backend direct

By default uses the material's ``default_material_id``. Override
with ``--material``.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Optional

import click

from pfc_inductor.cli.exit_codes import ExitCode


def register(group: click.Group) -> None:
    """Register the subcommand on the parent CLI group."""
    group.add_command(_fea_cmd)


@click.command(name="fea")
@click.argument("core_id", type=str)
@click.option(
    "--material",
    "material_id",
    type=str,
    default=None,
    help="Override the material id (default: core.default_material_id).",
)
@click.option(
    "--wire",
    "wire_id",
    type=str,
    default="AWG18",
    show_default=True,
    help="Wire identifier (substring match against the wire catalog).",
)
@click.option(
    "--turns",
    "n_turns",
    type=int,
    required=True,
    help="Number of coil turns (typically 20-150 for PFC inductors).",
)
@click.option(
    "--current",
    "current_A",
    type=float,
    required=True,
    help="DC current through the coil in amperes.",
)
@click.option(
    "--gap-mm",
    type=float,
    default=None,
    help="Override the air gap in mm. Defaults to the catalog lgap_mm.",
)
@click.option(
    "--backend",
    type=click.Choice(["direct", "femmt", "both"]),
    default="direct",
    show_default=True,
    help="Which FEA backend to invoke. 'both' runs side-by-side.",
)
@click.option(
    "--compare/--no-compare",
    "compare",
    default=False,
    help="Shortcut for --backend=both with a comparison table.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON instead of the pretty table.",
)
@click.option(
    "--workdir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Persist GetDP artefacts here (default: temp dir, deleted on exit).",
)
def _fea_cmd(
    core_id: str,
    material_id: Optional[str],
    wire_id: str,
    n_turns: int,
    current_A: float,
    gap_mm: Optional[float],
    backend: str,
    compare: bool,
    as_json: bool,
    workdir: Optional[Path],
) -> int:
    """Run the direct (and optionally FEMMT) FEA backend on CORE_ID.

    CORE_ID is the catalog identifier of the core to model
    (e.g. ``tdkepcos-pq-4040-n87`` or
    ``magnetics-c058150a2-125_highflux``).
    """
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()

    try:
        core = next(c for c in cores if c.id == core_id)
    except StopIteration:
        raise click.UsageError(
            f"Core id {core_id!r} not found in catalog "
            f"({len(cores)} cores known). "
            f"Try `magnadesign catalog list` to enumerate."
        ) from None

    if material_id is None:
        material_id = core.default_material_id
    try:
        mat = next(m for m in mats if m.id == material_id)
    except StopIteration:
        raise click.UsageError(f"Material id {material_id!r} not found in catalog.") from None

    try:
        wire = next(w for w in wires if wire_id in w.id)
    except StopIteration:
        raise click.UsageError(f"Wire matching {wire_id!r} not found in catalog.") from None

    # Resolve backend selection
    if compare:
        backend = "both"

    run_direct = backend in ("direct", "both")
    run_femmt = backend in ("femmt", "both")

    if not run_direct and not run_femmt:
        raise click.UsageError(f"Unknown backend {backend!r}")

    # Run pipeline(s)
    if workdir is None:
        td = tempfile.TemporaryDirectory()
        wd = Path(td.name)
    else:
        wd = workdir
        wd.mkdir(parents=True, exist_ok=True)
        td = None

    payload: dict = {
        "core": core_id,
        "material": material_id,
        "wire": wire.id,
        "n_turns": n_turns,
        "current_A": current_A,
        "gap_mm": gap_mm,
        "backend": backend,
    }

    # When comparing both backends, ensure they see the SAME gap.
    # FEMMT picks up gap from result.gap_actual_mm (engine-sized); we
    # want the direct backend to use the same. If user passed
    # --gap-mm explicitly, that wins for both.
    design_result = None
    engine_gap_mm: Optional[float] = None
    if run_femmt and gap_mm is None:
        # Try to run design() to get the engine's auto-gap.
        try:
            from pfc_inductor.design import design
            from pfc_inductor.models import Spec

            spec = Spec()  # type: ignore[call-arg] — all fields default
            design_result = design(spec, core, wire, mat)  # type: ignore[arg-type]
            engine_gap_mm = getattr(design_result, "gap_actual_mm", None)
        except Exception:
            design_result = None

    effective_gap_mm = gap_mm if gap_mm is not None else engine_gap_mm

    if run_direct:
        from pfc_inductor.fea.direct.runner import run_direct_fea

        direct_wd = wd / "direct"
        direct_wd.mkdir(parents=True, exist_ok=True)
        direct_res = run_direct_fea(
            core=core,
            material=mat,
            wire=wire,
            n_turns=n_turns,
            current_A=current_A,
            workdir=direct_wd,
            gap_mm=effective_gap_mm,
        )
        payload["direct"] = {
            "L_dc_uH": direct_res.L_dc_uH,
            "B_pk_T": direct_res.B_pk_T,
            "B_avg_T": direct_res.B_avg_T,
            "energy_J": direct_res.energy_J,
            "mesh_n_elements": direct_res.mesh_n_elements,
            "mesh_n_nodes": direct_res.mesh_n_nodes,
            "solve_wall_s": direct_res.solve_wall_s,
        }

    if run_femmt:
        # FEMMT needs Spec + DesignResult to invoke; we built them
        # above when gap detection ran. If the engine failed (the
        # default Spec doesn't suit this core), surface a clean
        # diagnostic.
        from pfc_inductor.fea.femmt_runner import validate_design_femmt
        from pfc_inductor.fea.models import FEMMNotAvailable, FEMMSolveError
        from pfc_inductor.models import Spec

        femmt_wd = wd / "femmt"
        femmt_wd.mkdir(parents=True, exist_ok=True)
        if design_result is None:
            # Retry design() so we have a result for FEMMT (might
            # have skipped above if gap_mm was explicit).
            try:
                from pfc_inductor.design import design

                spec = Spec()  # type: ignore[call-arg] — all fields default
                design_result = design(spec, core, wire, mat)
            except Exception as exc:
                payload["femmt"] = {"error": f"design() failed: {type(exc).__name__}: {exc}"}
                run_femmt = False
        else:
            spec = Spec()  # type: ignore[call-arg] — all fields default

        if run_femmt and design_result is not None:
            # FEMMT uses result.gap_actual_mm, N_turns, and I_line_pk_A.
            # Pydantic models honor assignment when not frozen; we
            # rebuild the result via model_copy(update=...) to be
            # safe across Pydantic versions.
            try:
                updates = {
                    "N_turns": n_turns,
                    "I_line_pk_A": float(current_A),
                }
                if effective_gap_mm is not None:
                    updates["gap_actual_mm"] = float(effective_gap_mm)
                if hasattr(design_result, "model_copy"):
                    design_result = design_result.model_copy(update=updates)
                else:
                    for k, v in updates.items():
                        setattr(design_result, k, v)
            except Exception:
                pass

            # Ensure spec is bound for the call below — both branches
            # above may have set it, but Pyright can't follow.
            spec_for_femmt = locals().get("spec") or Spec()  # type: ignore[call-arg]

            try:
                femmt_res = validate_design_femmt(
                    spec=spec_for_femmt,
                    core=core,
                    wire=wire,
                    material=mat,
                    result=design_result,
                    output_dir=femmt_wd,
                )
                payload["femmt"] = {
                    "L_dc_uH": femmt_res.L_FEA_uH,
                    "B_pk_T": femmt_res.B_pk_FEA_T,
                    "solve_wall_s": getattr(femmt_res, "wall_s", None),
                    "error": None,
                }
            except (FEMMNotAvailable, FEMMSolveError) as exc:
                payload["femmt"] = {"error": f"{type(exc).__name__}: {exc}"}
            except Exception as exc:
                payload["femmt"] = {"error": f"{type(exc).__name__}: {exc}"}

    # Render output
    if as_json:
        click.echo(json.dumps(payload, indent=2, default=str))
    else:
        _render_pretty(payload)

    if td is not None:
        td.cleanup()
    return ExitCode.OK


def _render_pretty(payload: dict) -> None:
    """Pretty-print the comparison or single-backend result."""
    click.echo(f"\n  Core:     {payload['core']}")
    click.echo(f"  Material: {payload['material']}")
    click.echo(f"  Wire:     {payload['wire']}")
    click.echo(f"  Inputs:   N = {payload['n_turns']} turns, I = {payload['current_A']:.2f} A")
    if payload.get("gap_mm") is not None:
        click.echo(f"  Gap:      {payload['gap_mm']:.3f} mm (override)")
    click.echo()

    direct = payload.get("direct")
    femmt = payload.get("femmt")

    if direct and femmt:
        # Side-by-side table
        click.echo("  " + "-" * 70)
        click.echo(f"  {'metric':<14}  {'direct':>15}  {'femmt':>15}  {'|Δ|':>10}")
        click.echo("  " + "-" * 70)
        _row("L_dc [μH]", direct.get("L_dc_uH"), femmt.get("L_dc_uH"))
        _row("B_pk [T]", direct.get("B_pk_T"), femmt.get("B_pk_T"))
        click.echo("  " + "-" * 70)
        d_t = direct.get("solve_wall_s") or 0.0
        f_t = femmt.get("solve_wall_s") or 0.0
        click.echo(f"  {'wall [s]':<14}  {d_t:>15.6f}  {f_t:>15.4f}")
        if d_t > 0 and f_t > 0:
            click.echo(f"  {'speedup':<14}  {f_t / d_t:>15.1f}×")
        if femmt.get("error"):
            click.echo(f"\n  FEMMT note: {femmt['error']}")
    elif direct:
        click.echo("  Direct backend results:")
        for k, v in direct.items():
            if isinstance(v, float):
                if "wall" in k:
                    click.echo(f"    {k:<20} = {v:.6f} s")
                elif "L_dc" in k:
                    click.echo(f"    {k:<20} = {v:.4f} μH")
                elif "B_" in k:
                    click.echo(f"    {k:<20} = {v:.4f} T")
                elif "energy" in k:
                    click.echo(f"    {k:<20} = {v:.4e} J")
                else:
                    click.echo(f"    {k:<20} = {v:.4f}")
            else:
                click.echo(f"    {k:<20} = {v}")
    elif femmt:
        click.echo("  FEMMT backend results:")
        for k, v in femmt.items():
            click.echo(f"    {k:<20} = {v}")
    click.echo()


def _row(label: str, direct_val, femmt_val) -> None:
    """One line of the comparison table — None-safe."""
    d_str = f"{direct_val:>15.4f}" if isinstance(direct_val, (int, float)) else f"{'-':>15}"
    f_str = f"{femmt_val:>15.4f}" if isinstance(femmt_val, (int, float)) else f"{'-':>15}"
    if (
        isinstance(direct_val, (int, float))
        and isinstance(femmt_val, (int, float))
        and femmt_val != 0
    ):
        delta_pct = abs(direct_val - femmt_val) / abs(femmt_val) * 100.0
        d_str_delta = f"{delta_pct:>9.1f}%"
    else:
        d_str_delta = f"{'-':>10}"
    click.echo(f"  {label:<14}  {d_str}  {f_str}  {d_str_delta}")
