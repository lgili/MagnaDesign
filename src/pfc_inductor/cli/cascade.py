"""``magnadesign cascade`` subcommand — multi-tier brute-force.

Drives :class:`CascadeOrchestrator` synchronously. Tier 0 prunes
the candidate space in microseconds; Tier 1 runs the analytical
engine on survivors via a process pool; Tier 2 / 3 / 4 (transient
ODE / FEMMT / swept FEA) are opt-in via the ``--tier{2,3,4}-k``
flags.

Headless equivalent of the GUI's CascadePage. The store path
defaults to a per-user data dir (matching the GUI default), but
``--store /tmp/run.db`` lets a CI script keep its run isolated.

Surface
-------

  magnadesign cascade PROJECT.pfc \
      [--tier2-k 50] [--tier3-k 0] [--tier4-k 0] \
      [--workers 4] [--store FILE.db] \
      [--top N] [--rank loss|temp|cost] \
      [--csv OUT] [--pretty/--json]

Exit codes
----------

- ``0`` — Tier 0 + Tier 1 finished. Top-N is non-empty.
- ``1`` — generic error (engine / IO).
- ``4`` — usage error (missing project, bad selection ids).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

import click

from pfc_inductor.cli.exit_codes import ExitCode
from pfc_inductor.cli.utils import load_session, wrap_design_error
from pfc_inductor.topology.material_filter import materials_for_topology

# Server-side ORDER BY columns the SQLite store accepts. Anything
# off this list trips a ValueError; we narrow it here so the CLI's
# ``--rank`` choice gives the user the same defence.
#
# ``loss`` and ``temp`` map to the COALESCE virtual columns so the
# printed top-N reflects whichever tier produced each candidate's
# refined number — Tier-4 candidates rank by Tier-4 loss, Tier-2
# candidates by Tier-2 loss, Tier-1-only candidates by Tier 1, no
# mode-flipping. Per-tier explicit columns (``loss_t1`` ... ``loss_t4``)
# are kept for power users who want a specific tier's ranking.
_RANK_COLUMNS = (
    "loss",
    "temp",
    "cost",
    "loss_t1",
    "loss_t2",
    "loss_t3",
    "loss_t4",
)
_RANK_TO_COLUMN = {
    "loss": "loss_top_W",
    "temp": "temp_top_C",
    "cost": "cost_t1_USD",
    "loss_t1": "loss_t1_W",
    "loss_t2": "loss_t2_W",
    "loss_t3": "loss_t3_W",
    "loss_t4": "loss_t4_W",
}


def register(group: click.Group) -> None:
    group.add_command(_cascade_cmd)


@click.command(name="cascade")
@click.argument(
    "project_file",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
)
@click.option(
    "--tier2-k",
    "tier2_k",
    default=0,
    show_default=True,
    type=click.IntRange(min=0, max=2000),
    help="Top-K Tier-1 survivors to refine via Tier 2 (transient ODE). 0 disables.",
)
@click.option(
    "--tier3-k",
    "tier3_k",
    default=0,
    show_default=True,
    type=click.IntRange(min=0, max=500),
    help="Top-K to validate via Tier 3 (FEMMT magnetostatic). "
    "Requires the [fea] extra installed; 0 disables.",
)
@click.option(
    "--tier4-k",
    "tier4_k",
    default=0,
    show_default=True,
    type=click.IntRange(min=0, max=50),
    help="Top-K to sweep via Tier 4 (cycle-averaged FEA). 0 disables.",
)
@click.option(
    "--workers",
    default=0,
    show_default=False,
    type=click.IntRange(min=0),
    help="Parallel Tier-1 workers. 0 == auto-detect (min(4, cpu_count)).",
)
@click.option(
    "--store",
    "store_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="SQLite store path. Defaults to the per-user data dir "
    "(``~/Library/Application Support/MagnaDesign/cascade.db`` on "
    "macOS) so the GUI and CLI share history.",
)
@click.option(
    "--top",
    default=25,
    show_default=True,
    type=click.IntRange(min=1, max=1000),
    help="Number of candidates to print after the run.",
)
@click.option(
    "--rank",
    "rank_key",
    type=click.Choice(_RANK_COLUMNS, case_sensitive=False),
    default="loss",
    show_default=True,
    help="Server-side ORDER BY for the printed top-N. Volume / "
    "score variants need client-side reranking — use the "
    "GUI cascade page for those.",
)
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write the top-N as CSV (one row per candidate).",
)
@click.option(
    "--band-aware/--nominal-only",
    default=False,
    show_default=True,
    help="When set AND the project's spec carries an "
    "``fsw_modulation`` band, re-rank the printed top-N by "
    "worst-case loss across the band. Substitutes "
    "loss_t1_W / temp_t1_C with the band-worst value. "
    "Adds ~5× the engine time per candidate (band points + 1 "
    "lookup), affordable for top-N=25 typical.",
)
@click.option(
    "--pretty/--json",
    default=False,
    help="Render summary as a key-value table (--pretty) or as JSON (default).",
)
@click.pass_context
@wrap_design_error
def _cascade_cmd(
    ctx: click.Context,
    project_file: Path,
    tier2_k: int,
    tier3_k: int,
    tier4_k: int,
    workers: int,
    store_path: Optional[Path],
    top: int,
    rank_key: str,
    csv_path: Optional[Path],
    band_aware: bool,
    pretty: bool,
) -> int:
    """Run the multi-tier cascade on PROJECT_FILE.

    Tier 0 prunes feasibility (~5 µs per candidate). Tier 1 runs
    the analytical design engine in a process pool. Higher tiers
    are opt-in.
    """
    loaded = load_session(project_file)

    missing: list[str] = []
    if loaded.selected_material is None:
        missing.append("material")
    if loaded.selected_core is None:
        missing.append("core")
    if loaded.selected_wire is None:
        missing.append("wire")
    # The cascade doesn't actually USE the selection IDs (it sweeps
    # everything), but a missing selection signals a malformed
    # project file — surface it as a usage error rather than letting
    # the engine pick arbitrary defaults.
    if missing:
        click.echo(
            f"::warning::Project missing selection for: "
            f"{', '.join(missing)}. The cascade sweeps the full "
            f"catalogue regardless, but the project file should "
            f"still carry a baseline selection.",
            err=True,
        )

    # Lazy imports — keep the CLI startup Qt-free. The cascade
    # module pulls platformdirs + sqlite, both fine for headless.
    from platformdirs import user_data_dir

    from pfc_inductor.optimize.cascade import (
        CascadeConfig,
        CascadeOrchestrator,
        RunStore,
        TierProgress,
    )

    if store_path is None:
        store_path = (
            Path(
                user_data_dir("PFCInductorDesigner", "indutor"),
            )
            / "cascade.db"
        )
    store_path = store_path.expanduser().resolve()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store = RunStore(store_path)

    # Topology filter — the cascade is safe to run on the full
    # catalogue, but Tier 0 wastes microseconds on materials that
    # were never going to fit (e.g. a 65 kHz ferrite under a 60 Hz
    # line-reactor spec). The GUI applies this upstream; mirror
    # the call here.
    eligible_materials = materials_for_topology(
        loaded.materials,
        loaded.spec.topology,
    )

    config = CascadeConfig(
        tier2_top_k=tier2_k,
        tier3_top_k=tier3_k,
        tier4_top_k=tier4_k,
    )

    import os as _os

    parallelism = workers or min(4, _os.cpu_count() or 1)

    orch = CascadeOrchestrator(store=store, parallelism=parallelism)
    orch.reset_cancel()
    run_id = orch.start_run(loaded.spec, config)

    click.echo(
        f"cascade run {run_id} · workers={parallelism} · "
        f"tier2-k={tier2_k} tier3-k={tier3_k} tier4-k={tier4_k}",
        err=True,
    )

    # Progress callback prints one line per tier completion to
    # stderr. Tier 1 emits many intermediate updates; we throttle
    # to once-per-second so a 100k-candidate sweep doesn't spam
    # the CI log.
    state = {"last_emit": 0.0, "current_tier": -1}

    def _on_progress(tp: TierProgress) -> None:
        now = time.monotonic()
        is_finish = tp.done == tp.total and tp.total > 0
        is_new_tier = tp.tier != state["current_tier"]
        if is_new_tier or is_finish or (now - state["last_emit"]) >= 1.0:
            click.echo(
                f"  tier {tp.tier}: {tp.done}/{tp.total}",
                err=True,
            )
            state["last_emit"] = now
            state["current_tier"] = tp.tier

    t_start = time.perf_counter()
    try:
        orch.run(
            run_id,
            loaded.spec,
            eligible_materials,
            loaded.cores,
            loaded.wires,
            config,
            progress_cb=_on_progress,
        )
    except Exception as exc:
        click.echo(f"cascade failed: {type(exc).__name__}: {exc}", err=True)
        ctx.exit(int(ExitCode.GENERIC_ERROR))
        return int(ExitCode.GENERIC_ERROR)
    elapsed = time.perf_counter() - t_start

    record = store.get_run(run_id)
    rows = store.top_candidates(
        run_id,
        n=top,
        order_by=_RANK_TO_COLUMN[rank_key],
    )

    # Band-aware re-rank — opt-in + only meaningful when the
    # spec carries an ``fsw_modulation`` field. The helper is
    # a no-op when the spec is single-point, so the flag is
    # safe to leave on in CI scripts.
    if band_aware and loaded.spec.fsw_modulation is not None:
        from pfc_inductor.optimize.cascade.band_aware import (
            band_aware_rerank,
        )

        click.echo(
            f"band-aware re-rank: re-evaluating top-{len(rows)} "
            f"across {loaded.spec.fsw_modulation.n_eval_points} "
            f"fsw points...",
            err=True,
        )
        rows = band_aware_rerank(
            rows,
            loaded.spec,
            cores_by_id={c.id: c for c in loaded.cores},
            wires_by_id={w.id: w for w in loaded.wires},
            materials_by_id={m.id: m for m in eligible_materials},
        )

    payload = {
        "run_id": run_id,
        "store_path": str(store_path),
        "elapsed_s": round(elapsed, 2),
        "status": getattr(record, "status", "unknown"),
        "config": {
            "tier2_k": tier2_k,
            "tier3_k": tier3_k,
            "tier4_k": tier4_k,
            "workers": parallelism,
        },
        "top": [_row_to_dict(r) for r in rows],
        "n_top": len(rows),
    }

    if csv_path is not None:
        _write_csv(csv_path, rows)
        click.echo(f"top-N CSV → {csv_path}", err=True)

    if pretty:
        _emit_pretty(payload)
    else:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")

    return ExitCode.OK


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _row_to_dict(row) -> dict:
    """Serialise a candidate row for JSON / CSV consumers.

    Carries every per-tier loss + temp column so a downstream
    consumer can pick the tier they care about. The ``loss_W`` /
    ``temp_C`` keys hold the COALESCE'd highest-tier values so a
    quick top-N scanner doesn't need to know the cascade
    structure.
    """
    return {
        "candidate_key": row.candidate_key,
        "core_id": row.core_id,
        "material_id": row.material_id,
        "wire_id": row.wire_id,
        "N": row.N,
        "gap_mm": row.gap_mm,
        "highest_tier": row.highest_tier,
        # Highest-tier COALESCE — the canonical answer.
        "loss_W": row.loss_top_W,
        "temp_C": row.temp_top_C,
        # Per-tier breakdown, useful for auditing how much
        # refinement each tier introduced.
        "loss_t1_W": row.loss_t1_W,
        "temp_t1_C": row.temp_t1_C,
        "cost_t1_USD": row.cost_t1_USD,
        "loss_t2_W": row.loss_t2_W,
        "temp_t2_C": row.temp_t2_C,
        "loss_t3_W": row.loss_t3_W,
        "temp_t3_C": row.temp_t3_C,
        "L_t3_uH": row.L_t3_uH,
        "Bpk_t3_T": row.Bpk_t3_T,
        "loss_t4_W": row.loss_t4_W,
        "temp_t4_C": row.temp_t4_C,
        "L_t4_uH": row.L_t4_uH,
    }


def _write_csv(path: Path, rows) -> None:
    import csv

    # Column order mirrors ``_row_to_dict``. The ``loss_W`` /
    # ``temp_C`` columns come right after the identity fields so a
    # quick eyeball of the CSV in a spreadsheet shows the canonical
    # answer in the leftmost numeric columns.
    fieldnames = [
        "candidate_key",
        "core_id",
        "material_id",
        "wire_id",
        "N",
        "gap_mm",
        "highest_tier",
        "loss_W",
        "temp_C",
        "loss_t1_W",
        "temp_t1_C",
        "cost_t1_USD",
        "loss_t2_W",
        "temp_t2_C",
        "loss_t3_W",
        "temp_t3_C",
        "L_t3_uH",
        "Bpk_t3_T",
        "loss_t4_W",
        "temp_t4_C",
        "L_t4_uH",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(_row_to_dict(row))


def _emit_pretty(payload: dict) -> None:
    click.echo(f"run_id      {payload['run_id']}")
    click.echo(f"status      {payload['status']}")
    click.echo(f"elapsed     {payload['elapsed_s']:.2f} s")
    click.echo(f"workers     {payload['config']['workers']}")
    click.echo(f"top-N       {payload['n_top']} candidates")
    click.echo("")
    # The "tier" column shows which tier the loss / temp number
    # came from so the user knows whether they're reading a
    # Tier-1 analytical answer or a Tier-4 FEA-corrected one.
    click.echo(
        "rank  core                       material              wire   N    loss W   temp °C  tier"
    )
    click.echo("-" * 99)
    for i, r in enumerate(payload["top"], start=1):
        loss = r.get("loss_W") if r.get("loss_W") is not None else r["loss_t1_W"]
        temp = r.get("temp_C") if r.get("temp_C") is not None else r["temp_t1_C"]
        tier_badge = _tier_badge_for_row(r)
        click.echo(
            f"{i:4d}  {(r['core_id'] or '')[:24]:24s}  "
            f"{(r['material_id'] or '')[:20]:20s}  "
            f"{(r['wire_id'] or '')[:6]:6s}  "
            f"{r['N']:>3}  "
            f"{(f'{loss:.2f}' if loss is not None else '—'):>7}  "
            f"{(f'{temp:.0f}' if temp is not None else '—'):>7}  "
            f"{tier_badge:>4}"
        )


def _tier_badge_for_row(row: dict) -> str:
    """Mirror of :func:`...ui.workspace.cascade_page._tier_badge`
    over a JSON row dict — names the tier that produced the
    displayed Loss W / temp °C cell."""
    if row.get("loss_t4_W") is not None:
        return "T4"
    if row.get("loss_t3_W") is not None:
        return "T3"
    if row.get("loss_t2_W") is not None:
        return "T2"
    if row.get("loss_t1_W") is not None:
        return "T1"
    return "—"
