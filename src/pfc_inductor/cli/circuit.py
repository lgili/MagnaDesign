"""``magnadesign circuit`` subcommand — circuit-simulator export.

Emits a saturable-inductor model in one of three formats — the
LTspice ``.subckt``, a PSIM Saturable-Inductor fragment, or a
Modelica package — for downstream simulation in the user's
preferred tool. The model preserves the engine's L(I) rolloff
fidelity, which a re-typed constant-L would lose.

Examples
--------

::

    magnadesign circuit project.pfc --format ltspice --out L_PFC.lib
    magnadesign circuit project.pfc --format psim    --out L_PFC.psim.txt
    magnadesign circuit project.pfc --format modelica --out PFC.mo
"""
from __future__ import annotations

from pathlib import Path

import click

from pfc_inductor.cli.exit_codes import ExitCode
from pfc_inductor.cli.utils import load_session, wrap_design_error
from pfc_inductor.design import design as run_design


_FORMATS = ("ltspice", "psim", "modelica")


def register(group: click.Group) -> None:
    """Register the ``circuit`` subcommand on the parent group."""
    group.add_command(_circuit_cmd)


@click.command(name="circuit")
@click.argument(
    "project_file",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(_FORMATS, case_sensitive=False),
    required=True,
    help="Simulator format. ``ltspice`` writes a `.subckt`, "
         "``psim`` writes a parameter fragment, ``modelica`` "
         "writes a complete `.mo` package.",
)
@click.option(
    "--out",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Destination file. Omit to print on stdout.",
)
@click.option(
    "--name",
    default="L_PFC",
    help="LTspice subcircuit name / Modelica package name. "
         "Ignored for PSIM (uses a fixed `SatL_PFC` element name).",
)
@click.option(
    "--n-points",
    type=int,
    default=25,
    help="Number of L(I) sample points (default 25). More gives "
         "a smoother lookup at the cost of larger file size.",
)
@wrap_design_error
def _circuit_cmd(
    project_file: Path,
    fmt: str,
    output_path: Path | None,
    name: str,
    n_points: int,
) -> int:
    """Export PROJECT_FILE as a circuit-simulator model.

    The exported file carries the engine's calibrated L(I)
    rolloff so the simulator sees the same saturation envelope
    production will. The default sweep is 0–1.5×I_pk; rolloff
    coefficients fall back to a flat-L table when the material
    has no rolloff data (most ferrites / nano-crystallines).
    """
    loaded = load_session(project_file)

    missing: list[str] = []
    if loaded.selected_material is None:
        missing.append("material")
    if loaded.selected_core is None:
        missing.append("core")
    if loaded.selected_wire is None:
        missing.append("wire")
    if missing:
        raise click.UsageError(
            f"Project has no selection for: {', '.join(missing)}. "
            f"Open the project in the GUI to pick the missing items "
            f"or hand-edit the `.pfc` selection block.",
        )

    result = run_design(
        loaded.spec,
        loaded.selected_core,
        loaded.selected_wire,
        loaded.selected_material,
    )

    fmt = fmt.lower()
    if fmt == "ltspice":
        from pfc_inductor.export.ltspice import to_ltspice_subcircuit
        text = to_ltspice_subcircuit(
            spec=loaded.spec, core=loaded.selected_core,
            wire=loaded.selected_wire,
            material=loaded.selected_material,
            result=result, name=name, n_points=n_points,
        )
    elif fmt == "psim":
        from pfc_inductor.export.psim import to_psim_fragment
        text = to_psim_fragment(
            spec=loaded.spec, core=loaded.selected_core,
            wire=loaded.selected_wire,
            material=loaded.selected_material,
            result=result, n_points=n_points,
        )
    else:  # modelica
        from pfc_inductor.export.modelica import to_modelica
        text = to_modelica(
            spec=loaded.spec, core=loaded.selected_core,
            wire=loaded.selected_wire,
            material=loaded.selected_material,
            result=result, package=name, n_points=n_points,
        )

    if output_path is None:
        click.echo(text)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text)
        click.echo(
            f"Wrote {fmt.upper()} circuit export → {output_path}",
            err=True,
        )

    return ExitCode.OK
