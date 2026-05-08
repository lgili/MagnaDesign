"""``magnadesign sweep`` subcommand — Pareto sweep, ranked CSV.

Runs :func:`pfc_inductor.optimize.sweep` across the catalogue
(narrowed by user filters) and emits the top-N candidates as JSON
or CSV. The synchronous sibling of the GUI's ``OptimizerEmbed``;
suitable for CI pipelines that need to verify "the engineer's
preferred core still wins after the catalogue update".
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Optional

import click

from pfc_inductor.cli.exit_codes import ExitCode
from pfc_inductor.cli.utils import load_session, wrap_design_error
from pfc_inductor.optimize.sweep import rank, sweep
from pfc_inductor.topology.material_filter import materials_for_topology


# Same six keys the GUI's OptimizerFiltersBar exposes, re-stated
# here so the CLI doesn't drag in the Qt widget tree just to read
# the choices. Keep in lock-step with
# ``ui.widgets.optimizer_filters_bar.OBJECTIVES``.
RANK_KEYS = ("loss", "volume", "temp", "cost", "score", "score_with_cost")


def register(group: click.Group) -> None:
    group.add_command(_sweep_cmd)


@click.command(name="sweep")
@click.argument(
    "project_file",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
)
@click.option(
    "--top",
    default=25,
    show_default=True,
    type=click.IntRange(min=1, max=1000),
    help="Number of candidates to keep after ranking.",
)
@click.option(
    "--rank",
    "rank_key",
    type=click.Choice(RANK_KEYS, case_sensitive=False),
    default="loss",
    show_default=True,
    help="Objective the result is ordered by.",
)
@click.option(
    "--material",
    "material_filter",
    multiple=True,
    help="Restrict to specific material IDs (repeatable). "
         "Empty == all topology-eligible materials.",
)
@click.option(
    "--feasible-only/--all",
    default=True,
    show_default=True,
    help="Drop infeasible candidates from the ranked output.",
)
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write CSV output to this path instead of stdout JSON.",
)
@wrap_design_error
def _sweep_cmd(
    project_file: Path,
    top: int,
    rank_key: str,
    material_filter: tuple[str, ...],
    feasible_only: bool,
    csv_path: Optional[Path],
) -> int:
    """Run the simple Pareto sweep on PROJECT_FILE.

    Default behaviour mirrors the GUI's OptimizerEmbed defaults:
    filter materials by topology, restrict to compatible cores,
    only round wires, rank the survivors by loss, keep the top 25.
    """
    loaded = load_session(project_file)

    # Topology pre-filter — the cascade and GUI both apply this
    # upstream of the sweep, and the material catalogue carries
    # entries that are nonsense for one or another topology
    # (e.g. low-fsw laminations under a 65 kHz boost spec).
    eligible = materials_for_topology(loaded.materials, loaded.spec.topology)

    # User-requested materials further narrow the eligible set.
    # Empty `material_filter` means "all eligible".
    if material_filter:
        wanted = set(material_filter)
        eligible = [m for m in eligible if m.id in wanted]
        if not eligible:
            raise click.UsageError(
                f"None of the requested materials match the "
                f"topology-eligible set. Use `magnadesign catalog "
                f"materials` to see what's available.",
            )

    click.echo(
        f"sweeping {loaded.spec.topology} "
        f"({len(eligible)} materials × {len(loaded.cores)} cores × "
        f"{len(loaded.wires)} wires) ...",
        err=True,
    )

    # Reuse the same engine entry point the GUI worker uses. No
    # progress bar yet — TODO when the cascade-progress design
    # lands; for now the user sees a single "swept N" line at the
    # end.
    results = sweep(
        loaded.spec,
        loaded.cores,
        loaded.wires,
        eligible,
        only_compatible_cores=True,
    )

    n_total = len(results)
    n_feasible = sum(1 for r in results if r.feasible)
    if feasible_only:
        results = [r for r in results if r.feasible]

    ranked = rank(results, by=rank_key, feasible_first=True)[:top]
    click.echo(
        f"swept {n_total} candidates "
        f"({n_feasible} feasible) → keeping top {len(ranked)}",
        err=True,
    )

    rows = [_row_for(r) for r in ranked]

    if csv_path is not None:
        _write_csv(csv_path, rows)
        click.echo(f"CSV → {csv_path}", err=True)
        return ExitCode.OK

    # Default JSON output to stdout. Each row is an independent
    # dict so a downstream `jq` consumer can stream one at a time.
    import json
    json.dump(rows, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return ExitCode.OK


def _row_for(sweep_result) -> dict:
    """Flatten a ``SweepResult`` into a CSV/JSON-friendly row."""
    r = sweep_result.result
    return {
        "core_id":       sweep_result.core.id,
        "core_pn":       sweep_result.core.part_number,
        "wire_id":       sweep_result.wire.id,
        "material_id":   sweep_result.material.id,
        "material_name": sweep_result.material.name,
        "L_actual_uH":   round(r.L_actual_uH, 2),
        "N_turns":       int(r.N_turns),
        "B_pk_mT":       round(r.B_pk_T * 1000.0, 1),
        "T_rise_C":      round(r.T_rise_C, 1),
        "P_total_W":     round(r.losses.P_total_W, 4),
        "volume_cm3":    round(sweep_result.volume_cm3, 2),
        "cost":          (
            f"{sweep_result.cost.currency} {sweep_result.cost.total_cost:.2f}"
            if sweep_result.cost is not None else ""
        ),
        "feasible":      bool(sweep_result.feasible),
    }


# Canonical column set used by the CSV writer. Single source of
# truth for both the empty-result and populated cases — also
# documents the schema for downstream consumers (the same
# vocabulary appears in `_row_for` above).
_CSV_FIELDS: tuple[str, ...] = (
    "core_id", "core_pn", "wire_id", "material_id", "material_name",
    "L_actual_uH", "N_turns", "B_pk_mT", "T_rise_C",
    "P_total_W", "volume_cm3", "cost", "feasible",
)


def _write_csv(path: Path, rows: list[dict]) -> None:
    """Write rows as CSV. Empty result set still writes a header
    so downstream consumers don't need to special-case "0 rows"
    — they get a well-formed empty table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(_CSV_FIELDS))
        writer.writeheader()
        writer.writerows(rows)
