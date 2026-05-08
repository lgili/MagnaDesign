"""``magnadesign worst-case`` subcommand.

Runs the corner DOE + Monte-Carlo yield estimator on a `.pfc`
project file and prints the headline numbers (per-metric worst
corner, yield, fail-mode buckets). The CLI bridge that closes
the engine + UI gap until the dedicated Worst-case tab lands —
CI pipelines and vendor-quoting integrations can already verify
"is the design production-ready?" today.

Exit codes
----------

- ``0`` — every tracked metric stays inside its acceptance
  envelope at every corner, AND the Monte-Carlo pass-rate is
  above ``--yield-threshold``. Default threshold 95 %.
- ``3`` (``WORST_CASE_FAIL``) — at least one corner violates
  the envelope, OR the yield falls below the threshold.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from pfc_inductor.cli.exit_codes import ExitCode
from pfc_inductor.cli.utils import load_session, wrap_design_error
from pfc_inductor.worst_case import (
    DEFAULT_TOLERANCES,
    ToleranceSet,
    evaluate_corners,
    simulate_yield,
)


def register(group: click.Group) -> None:
    group.add_command(_worst_case_cmd)


@click.command(name="worst-case")
@click.argument(
    "project_file",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
)
@click.option(
    "--tolerances",
    "tolerance_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="JSON file describing a custom ToleranceSet. When omitted "
         "the bundled IPC + IEC + vendor defaults apply.",
)
@click.option(
    "--samples",
    default=1000,
    show_default=True,
    type=click.IntRange(min=10, max=100_000),
    help="Number of Monte-Carlo samples for the yield estimate.",
)
@click.option(
    "--seed",
    default=0,
    show_default=True,
    type=int,
    help="RNG seed — same seed → same yield report (CI regression).",
)
@click.option(
    "--yield-threshold",
    default=95.0,
    show_default=True,
    type=click.FloatRange(min=0.0, max=100.0),
    help="Pass-rate (in percent) below which the run exits with "
         f"code {int(ExitCode.WORST_CASE_FAIL)}.",
)
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write the per-corner CSV to this path (one row per "
         "DOE point with deltas + headline metrics).",
)
@click.option(
    "--pretty/--json",
    default=False,
    help="Render summary as a key-value table instead of JSON.",
)
@wrap_design_error
def _worst_case_cmd(
    project_file: Path,
    tolerance_path: Optional[Path],
    samples: int,
    seed: int,
    yield_threshold: float,
    csv_path: Optional[Path],
    pretty: bool,
) -> int:
    """Run the corner DOE + Monte-Carlo on PROJECT_FILE.

    Headline output (JSON by default):

    \b
        {
          "n_corners": 143,
          "worst": {
            "T_winding_C": {"corner": "AL=-1, ...", "value": 103.4},
            "B_pk_T":      {"corner": "...",        "value": 0.384},
            ...
          },
          "yield": {
            "samples": 1000,
            "pass_rate": 96.4,
            "fail_modes": {"T_winding": 23, "Bsat": 11}
          },
          "verdict": "PASS"
        }

    The verdict is ``PASS`` when every corner is feasible AND
    the yield meets ``--yield-threshold``; otherwise ``FAIL``.
    """
    loaded = load_session(project_file)

    missing = []
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
            f"first.",
        )

    # Resolve the tolerance set: custom JSON path or bundled default.
    tolerance_set = (
        ToleranceSet.from_path(tolerance_path)
        if tolerance_path is not None
        else DEFAULT_TOLERANCES
    )

    click.echo(
        f"corner DOE: {len(tolerance_set.tolerances)} tolerances, "
        f"running...",
        err=True,
    )
    summary = evaluate_corners(
        loaded.spec,
        loaded.selected_core,
        loaded.selected_wire,
        loaded.selected_material,
        tolerance_set,
    )
    click.echo(
        f"  → {summary.n_corners_evaluated} corners, "
        f"{summary.n_corners_failed} engine failures",
        err=True,
    )

    click.echo(
        f"Monte-Carlo: {samples} samples, seed={seed}",
        err=True,
    )
    yield_report = simulate_yield(
        loaded.spec,
        loaded.selected_core,
        loaded.selected_wire,
        loaded.selected_material,
        tolerance_set,
        n_samples=samples,
        seed=seed,
    )

    pass_rate_pct = yield_report.pass_rate * 100.0
    every_corner_feasible = (
        summary.n_corners_failed == 0
        and _all_corners_within_envelope(summary, loaded)
    )
    yield_meets_threshold = pass_rate_pct >= yield_threshold
    verdict = (
        "PASS" if (every_corner_feasible and yield_meets_threshold)
        else "FAIL"
    )

    payload = {
        "project":     loaded.project.name,
        "topology":    loaded.spec.topology,
        "tolerances":  tolerance_set.name,
        "n_corners":   summary.n_corners_evaluated,
        "n_failed":    summary.n_corners_failed,
        "worst": {
            metric: {
                "corner": cr.label,
                "value":  _read_metric_value(cr, metric),
            }
            for metric, cr in summary.worst_per_metric.items()
        },
        "yield": {
            "samples":         yield_report.n_samples,
            "pass_rate":       round(pass_rate_pct, 2),
            "fail_modes":      yield_report.fail_modes,
            "engine_errors":   yield_report.n_engine_error,
        },
        "thresholds": {
            "yield_pct": yield_threshold,
        },
        "verdict": verdict,
    }

    if csv_path is not None:
        _write_corner_csv(csv_path, summary)
        click.echo(f"per-corner CSV → {csv_path}", err=True)

    if pretty:
        _emit_pretty_summary(payload)
    else:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")

    return ExitCode.OK if verdict == "PASS" else ExitCode.WORST_CASE_FAIL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _read_metric_value(corner_result, metric: str) -> Optional[float]:
    if corner_result is None or corner_result.result is None:
        return None
    res = corner_result.result
    # Same lookup logic as in worst_case.engine — top-level attr
    # falls back to ``losses.<attr>`` for the common loss shorthand.
    val = getattr(res, metric, None)
    if val is None and hasattr(res, "losses"):
        val = getattr(res.losses, metric, None)
    if isinstance(val, (int, float)):
        return round(float(val), 4)
    return None


def _all_corners_within_envelope(summary, loaded) -> bool:
    """A corner is "in envelope" when every per-metric worst-case
    is itself below the project's pass criteria. Reuses the same
    rules the Monte-Carlo default `_default_pass_fn` applies, so
    the corner verdict and the yield verdict can't disagree on the
    same metric."""
    from pfc_inductor.worst_case.monte_carlo import _default_pass_fn

    for cr in summary.corners:
        if cr.result is None:
            return False
        passed, _reasons = _default_pass_fn(
            cr.result, loaded.spec, loaded.selected_material,
        )
        if not passed:
            return False
    return True


def _write_corner_csv(path: Path, summary) -> None:
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "label", "feasible",
        "T_winding_C", "T_rise_C", "B_pk_T", "P_total_W", "N_turns",
        "failure_reason",
    ]
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for cr in summary.corners:
            row = {"label": cr.label}
            if cr.result is None:
                row["feasible"] = False
                row["failure_reason"] = cr.failure_reason or "engine error"
                for k in ("T_winding_C", "T_rise_C",
                          "B_pk_T", "P_total_W", "N_turns"):
                    row[k] = ""
            else:
                row["feasible"] = True
                row["failure_reason"] = ""
                row["T_winding_C"] = round(float(cr.result.T_winding_C), 2)
                row["T_rise_C"] = round(float(cr.result.T_rise_C), 2)
                row["B_pk_T"] = round(float(cr.result.B_pk_T), 4)
                row["P_total_W"] = round(float(cr.result.losses.P_total_W), 4)
                row["N_turns"] = int(cr.result.N_turns)
            writer.writerow(row)


def _emit_pretty_summary(payload: dict) -> None:
    """Render the headline summary in a human-friendly key-value
    layout. The fail-modes bucket gets one line per mode so it's
    scannable in a terminal."""
    click.echo(f"project       {payload['project']}")
    click.echo(f"topology      {payload['topology']}")
    click.echo(f"tolerances    {payload['tolerances']}")
    click.echo(f"corners       {payload['n_corners']}  "
               f"(failed: {payload['n_failed']})")
    click.echo("")
    click.echo("worst per metric:")
    for metric, info in payload["worst"].items():
        click.echo(f"  {metric:14s}  {info['value']!r:>12}  ← {info['corner']}")
    click.echo("")
    yld = payload["yield"]
    click.echo(f"yield         {yld['pass_rate']:.2f} % "
               f"({yld['samples']} samples, "
               f"seed-reproducible)")
    if yld["fail_modes"]:
        click.echo("fail modes:")
        for mode, count in yld["fail_modes"].items():
            click.echo(f"  {mode:12s}  {count}")
    click.echo("")
    verdict = payload["verdict"]
    marker = "✓" if verdict == "PASS" else "✗"
    click.echo(f"verdict       {marker} {verdict}")
