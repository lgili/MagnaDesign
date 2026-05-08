"""``magnadesign design`` subcommand — single-point engine run.

Loads a `.pfc` file, runs the engine on the selected
material / core / wire, prints the headline KPIs the user would
otherwise read off the GUI's KPI strip. The fastest possible
"is this design feasible?" invocation.
"""
from __future__ import annotations

from pathlib import Path

import click

from pfc_inductor.cli.exit_codes import ExitCode
from pfc_inductor.cli.utils import emit, load_session, wrap_design_error
from pfc_inductor.design import design as run_design


def register(group: click.Group) -> None:
    """Register the subcommand on the parent CLI group."""
    group.add_command(_design_cmd)


@click.command(name="design")
@click.argument(
    "project_file",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
)
@click.option(
    "--pretty/--json",
    default=False,
    help="Render KPIs as a key-value table (--pretty) or as "
         "machine-readable JSON (default).",
)
@wrap_design_error
def _design_cmd(project_file: Path, pretty: bool) -> int:
    """Run the engine on PROJECT_FILE and print headline KPIs.

    PROJECT_FILE is a `.pfc` JSON snapshot saved by the GUI or
    the `magnadesign` CLI. The selected material / core / wire IDs
    in the file must resolve against the bundled catalogue —
    missing IDs raise a usage error.
    """
    loaded = load_session(project_file)

    # Selection sanity — without all three IDs we can't run the
    # engine. Surface the gap clearly instead of letting the
    # engine raise an opaque "core is None" deeper in the stack.
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

    # Headline KPIs — the same set the KPI strip and Resumo card
    # surface in the UI. Anything more granular (per-loss split,
    # convergence flags) is available via the `--full` flag we'll
    # add later or via the JSON output (which carries the whole
    # DesignResult.model_dump()).
    payload = {
        "project": loaded.project.name,
        "topology": loaded.spec.topology,
        "selection": {
            "material": loaded.selected_material.name,
            "core": loaded.selected_core.part_number,
            "wire": loaded.selected_wire.id,
        },
        "L_target_uH":   _round(result.L_required_uH, 2),
        "L_actual_uH":   _round(result.L_actual_uH, 2),
        "N_turns":       int(result.N_turns),
        "B_pk_mT":       _round(result.B_pk_T * 1000.0, 1),
        "B_sat_pct":     _round(
            (result.B_pk_T / result.B_sat_limit_T * 100.0)
            if result.B_sat_limit_T else 0.0,
            1,
        ),
        "T_winding_C":   _round(result.T_winding_C, 1),
        "T_rise_C":      _round(result.T_rise_C, 1),
        "P_total_W":     _round(result.losses.P_total_W, 3),
        "P_cu_W":        _round(result.losses.P_cu_total_W, 3),
        "P_core_W":      _round(result.losses.P_core_total_W, 3),
        "feasible":      bool(result.feasible)
                         if hasattr(result, "feasible")
                         else None,
        "warnings":      list(result.warnings) if result.warnings else [],
    }

    if pretty:
        # The "selection" sub-dict reads better flattened in
        # pretty mode — JSON consumers want the nested shape but
        # a stdout reader benefits from a flat key=value list.
        flat = {
            "project":      payload["project"],
            "topology":     payload["topology"],
            "material":     payload["selection"]["material"],
            "core":         payload["selection"]["core"],
            "wire":         payload["selection"]["wire"],
            **{k: v for k, v in payload.items()
               if k not in ("project", "topology", "selection")},
        }
        emit(flat, pretty=True)
    else:
        emit(payload, pretty=False)

    return ExitCode.OK


def _round(value: float, digits: int) -> float:
    """Defensive rounding — non-finite stays as-is for the JSON
    consumer to spot. (NaN/inf are valid signals from the engine
    when something diverged.)"""
    import math
    if not math.isfinite(value):
        return value
    return round(value, digits)
