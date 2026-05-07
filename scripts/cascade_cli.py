"""cascade_cli.py — headless validation runner for the cascade optimizer.

Lets you exercise the full cascade pipeline (Tier 0 → Tier 1 today,
plus future Tiers 2/3/4 as they ship) from the command line, against
the same persistent SQLite store the GUI will eventually use. This
is the recommended way to validate the cascade end-to-end before
the UI integration lands.

Subcommands:

    run       Start a fresh cascade run for a spec.
    resume    Continue an interrupted run by `run_id`.
    list      Enumerate cascade runs in the store.
    top       Print the top-N candidates of a run (Tier-1 ranking).
    inspect   Show full metadata + originating spec for a run.
    stats     Per-tier breakdown of one run (counts + reject reasons).

Quick start:

    # 800 W boost PFC, restricted to High Flux 60µ for a fast first run
    uv run python scripts/cascade_cli.py run \\
        --topology boost_ccm --pout 800 --vout 400 --fsw 65 \\
        --material magnetics-60_highflux --parallelism 4

    # Everything: full DB sweep across all 50 materials
    uv run python scripts/cascade_cli.py run --topology boost_ccm --pout 800

    # See what we've already run
    uv run python scripts/cascade_cli.py list

    # Inspect the breakdown of a specific run
    uv run python scripts/cascade_cli.py stats --run-id 20260506-2030-abc1
    uv run python scripts/cascade_cli.py top   --run-id 20260506-2030-abc1 --n 20

The store path defaults to ``<user-data-dir>/cascade.db`` so runs
accumulate across CLI and GUI invocations. Override with ``--store``.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from platformdirs import user_data_dir

from pfc_inductor.data_loader import load_cores, load_materials, load_wires
from pfc_inductor.models import Spec
from pfc_inductor.optimize.cascade import (
    CandidateRow,
    CascadeConfig,
    CascadeOrchestrator,
    RunStore,
    TierProgress,
)

# ─── Defaults ───────────────────────────────────────────────────────

def default_store_path() -> Path:
    return Path(user_data_dir("PFCInductorDesigner", "indutor")) / "cascade.db"


# ─── Spec construction ─────────────────────────────────────────────

def _build_spec_from_args(args: argparse.Namespace) -> Spec:
    """Materialise a `Spec` from CLI flags or a JSON file.

    `--spec` (JSON file) wins over individual flags; everything else
    falls back to `Spec`'s defaults.
    """
    if args.spec_file is not None:
        return Spec.model_validate_json(Path(args.spec_file).read_text(encoding="utf-8"))

    kwargs: dict[str, object] = {"topology": args.topology}
    optional = {
        "Vin_min_Vrms": args.vin_min,
        "Vin_max_Vrms": args.vin_max,
        "Vin_nom_Vrms": args.vin_nom,
        "Vout_V": args.vout,
        "Pout_W": args.pout,
        "eta": args.eta,
        "f_sw_kHz": args.fsw,
        "ripple_pct": args.ripple,
        "f_line_Hz": args.fline,
        "T_amb_C": args.tamb,
        "T_max_C": args.tmax,
        "Ku_max": args.ku,
        "Bsat_margin": args.bsat_margin,
        "n_phases": args.phases,
        "L_req_mH": args.l_req,
        "I_rated_Arms": args.i_rated,
    }
    kwargs.update({k: v for k, v in optional.items() if v is not None})
    return Spec(**kwargs)  # type: ignore[arg-type]


def _load_db(args: argparse.Namespace):
    """Load the database; optionally restrict to one material / wire id.

    Restricting to a single material drops the search space ~50× and is
    the recommended way to validate the cascade quickly.
    """
    materials = load_materials()
    cores = load_cores()
    wires = load_wires()
    if args.material:
        before = len(materials)
        materials = [m for m in materials if m.id == args.material]
        if not materials:
            sys.exit(f"error: material id {args.material!r} not in database")
        cores = [c for c in cores if c.default_material_id == args.material]
        print(
            f"filter: material {args.material!r} ({before}→1 mat, "
            f"{len(cores)} compatible cores)",
            file=sys.stderr,
        )
    if args.wire:
        before_w = len(wires)
        wires = [w for w in wires if w.id == args.wire]
        if not wires:
            sys.exit(f"error: wire id {args.wire!r} not in database")
        print(f"filter: wire {args.wire!r} ({before_w}→1 wire)", file=sys.stderr)
    return materials, cores, wires


# ─── Pretty-printing ────────────────────────────────────────────────

def _print_top(rows: list[CandidateRow]) -> None:
    if not rows:
        print("(no Tier-1 results yet)")
        return
    headers = ("#", "core_id", "material_id", "wire_id", "N", "loss_W", "ΔT_°C", "cost_$")
    widths = (3, 40, 28, 8, 4, 7, 5, 8)
    fmt = "  ".join(f"{{:>{w}}}" if i in (0, 4, 5, 6, 7) else f"{{:<{w}}}"
                    for i, w in enumerate(widths))
    sep = "-" * (sum(widths) + 2 * (len(widths) - 1))
    print(fmt.format(*headers))
    print(sep)
    for i, r in enumerate(rows, 1):
        n = str(r.N) if r.N is not None else "—"
        loss = f"{r.loss_t1_W:.2f}" if r.loss_t1_W is not None else "—"
        temp = f"{r.temp_t1_C:.0f}" if r.temp_t1_C is not None else "—"
        cost = f"{r.cost_t1_USD:.2f}" if r.cost_t1_USD is not None else "—"
        print(fmt.format(
            i,
            _truncate(r.core_id, 40),
            _truncate(r.material_id, 28),
            _truncate(r.wire_id, 8),
            n, loss, temp, cost,
        ))


def _truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[: width - 1] + "…"


@dataclass
class CascadeStats:
    """Tier-by-tier counts pulled straight from the SQLite store."""

    total: int
    tier0_feasible: int
    tier0_rejected: int
    tier1_evaluated: int
    tier1_with_loss: int
    reject_reasons: dict[str, int] = field(default_factory=dict)


def _gather_stats(store: RunStore, run_id: str) -> CascadeStats:
    """Tier-by-tier counts + reject reasons. Pure SQL, no full hydration."""
    with store._connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM candidates WHERE run_id = ?", (run_id,),
        ).fetchone()["n"]
        t0_feasible = conn.execute(
            "SELECT COUNT(*) AS n FROM candidates "
            "WHERE run_id = ? AND feasible_t0 = 1",
            (run_id,),
        ).fetchone()["n"]
        t0_rejected = conn.execute(
            "SELECT COUNT(*) AS n FROM candidates "
            "WHERE run_id = ? AND feasible_t0 = 0",
            (run_id,),
        ).fetchone()["n"]
        t1_evaluated = conn.execute(
            "SELECT COUNT(*) AS n FROM candidates "
            "WHERE run_id = ? AND highest_tier >= 1",
            (run_id,),
        ).fetchone()["n"]
        t1_with_loss = conn.execute(
            "SELECT COUNT(*) AS n FROM candidates "
            "WHERE run_id = ? AND loss_t1_W IS NOT NULL",
            (run_id,),
        ).fetchone()["n"]

        # Reject-reason breakdown — parse the JSON `notes` column.
        reason_rows = conn.execute(
            "SELECT notes FROM candidates "
            "WHERE run_id = ? AND feasible_t0 = 0 AND notes IS NOT NULL",
            (run_id,),
        ).fetchall()
    reason_counts: Counter[str] = Counter()
    for row in reason_rows:
        try:
            payload = json.loads(row["notes"])
        except (TypeError, json.JSONDecodeError):
            continue
        for reason in payload.get("reasons", []):
            reason_counts[str(reason)] += 1
    return CascadeStats(
        total=int(total),
        tier0_feasible=int(t0_feasible),
        tier0_rejected=int(t0_rejected),
        tier1_evaluated=int(t1_evaluated),
        tier1_with_loss=int(t1_with_loss),
        reject_reasons=dict(reason_counts),
    )


def _print_stats(stats: CascadeStats) -> None:
    def _pct(part: int, whole: int) -> str:
        return f"{100.0 * part / whole:.1f}%" if whole > 0 else "—"

    print(f"  total candidates : {stats.total}")
    print()
    print(f"  Tier 0 feasible  : {stats.tier0_feasible:>6} "
          f"({_pct(stats.tier0_feasible, stats.total)})")
    print(f"  Tier 0 rejected  : {stats.tier0_rejected:>6} "
          f"({_pct(stats.tier0_rejected, stats.total)})")
    if stats.reject_reasons:
        for reason, count in sorted(stats.reject_reasons.items(), key=lambda kv: -kv[1]):
            print(f"      {reason:<22}{count:>6} ({_pct(count, stats.tier0_rejected)})")
    print()
    print(f"  Tier 1 evaluated : {stats.tier1_evaluated:>6} "
          f"({_pct(stats.tier1_evaluated, stats.tier0_feasible)} of T0 feasible)")
    print(f"  Tier 1 with loss : {stats.tier1_with_loss:>6} "
          f"(engine returned a result)")


# ─── Progress callback ─────────────────────────────────────────────

class _ConsoleProgress:
    """Throttled in-place progress printer for `progress_cb`."""

    def __init__(self, min_interval_s: float = 0.10) -> None:
        self._last = 0.0
        self._last_tier: Optional[int] = None
        self._min = min_interval_s

    def __call__(self, p: TierProgress) -> None:
        now = time.perf_counter()
        is_finished = p.done == p.total
        if not is_finished and (now - self._last) < self._min:
            return
        self._last = now
        # Newline when we move to a new tier.
        if self._last_tier is not None and self._last_tier != p.tier:
            sys.stderr.write("\n")
        self._last_tier = p.tier
        pct = (100 * p.done // max(p.total, 1)) if p.total else 0
        sys.stderr.write(
            f"\rTier {p.tier}: {p.done:>7d} / {p.total:<7d} ({pct:>3d}%)   ",
        )
        sys.stderr.flush()
        if is_finished:
            sys.stderr.write("\n")
            sys.stderr.flush()


# ─── Subcommands ────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> int:
    spec = _build_spec_from_args(args)
    materials, cores, wires = _load_db(args)
    if not materials:
        sys.exit("error: no materials to evaluate")
    if not cores:
        sys.exit("error: no cores to evaluate")
    if not wires:
        sys.exit("error: no wires to evaluate")

    store_path = args.store or default_store_path()
    store = RunStore(store_path)
    orch = CascadeOrchestrator(store, parallelism=args.parallelism)
    config = CascadeConfig(
        K_1=args.k1,
        only_compatible_cores=not args.no_compat_filter,
        only_round_wires=not args.allow_litz,
    )
    run_id = orch.start_run(spec, config)

    print(f"run_id      : {run_id}", file=sys.stderr)
    print(f"store       : {store_path}", file=sys.stderr)
    print(f"spec_hash   : {spec.canonical_hash()[:16]}", file=sys.stderr)
    print(f"topology    : {spec.topology}", file=sys.stderr)
    print(f"workers     : {orch.parallelism}", file=sys.stderr)
    print(f"materials   : {len(materials)}", file=sys.stderr)
    print(f"cores       : {len(cores)}", file=sys.stderr)
    print(f"wires       : {len(wires)}", file=sys.stderr)
    print(file=sys.stderr)

    cb = _ConsoleProgress()
    started = time.perf_counter()
    try:
        orch.run(run_id, spec, materials, cores, wires, config, progress_cb=cb)
    except KeyboardInterrupt:
        sys.stderr.write("\n[interrupted] cancelling run; rows preserved.\n")
        orch.cancel()
        store.update_status(run_id, "cancelled")
        return 130

    elapsed = time.perf_counter() - started
    record = store.get_run(run_id)
    status = record.status if record is not None else "unknown"

    print(file=sys.stderr)
    print(f"status      : {status}", file=sys.stderr)
    print(f"elapsed     : {elapsed:.2f} s", file=sys.stderr)
    print(file=sys.stderr)

    stats = _gather_stats(store, run_id)
    print("Per-tier breakdown")
    print("------------------")
    _print_stats(stats)
    print()
    print(f"Top {args.top} by Tier-1 loss")
    print("------------------")
    rows = store.top_candidates(run_id, n=args.top, order_by="loss_t1_W")
    _print_top(rows)

    if args.json_out is not None:
        payload = {
            "run_id": run_id,
            "status": status,
            "elapsed_s": elapsed,
            "spec_hash": spec.canonical_hash(),
            "stats": asdict(stats),
            "top": [
                {
                    "rank": i + 1, "core_id": r.core_id,
                    "material_id": r.material_id, "wire_id": r.wire_id,
                    "N": r.N, "loss_t1_W": r.loss_t1_W,
                    "temp_t1_C": r.temp_t1_C, "cost_t1_USD": r.cost_t1_USD,
                }
                for i, r in enumerate(rows)
            ],
        }
        Path(args.json_out).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nwrote {args.json_out}", file=sys.stderr)
    return 0 if status == "done" else 1


def cmd_resume(args: argparse.Namespace) -> int:
    store_path = args.store or default_store_path()
    store = RunStore(store_path)
    record = store.get_run(args.run_id)
    if record is None:
        sys.exit(f"error: run_id {args.run_id!r} not in store")
    if record.status == "done":
        print(f"run {args.run_id} already complete; nothing to resume",
              file=sys.stderr)
        return 0

    spec = record.spec()
    config = CascadeConfig(**{
        k: v for k, v in record.config.items()
        if k in {"K_1", "only_compatible_cores", "only_round_wires"}
    })
    materials, cores, wires = _load_db(args)

    orch = CascadeOrchestrator(store, parallelism=args.parallelism)
    print(f"resuming    : {args.run_id}", file=sys.stderr)
    print(f"already done: {store.candidate_count(args.run_id)} candidates",
          file=sys.stderr)
    print(file=sys.stderr)

    cb = _ConsoleProgress()
    started = time.perf_counter()
    try:
        orch.run(args.run_id, spec, materials, cores, wires, config, progress_cb=cb)
    except KeyboardInterrupt:
        sys.stderr.write("\n[interrupted] cancelling run; rows preserved.\n")
        orch.cancel()
        store.update_status(args.run_id, "cancelled")
        return 130
    elapsed = time.perf_counter() - started
    record = store.get_run(args.run_id)
    print(file=sys.stderr)
    print(f"status      : {record.status if record else 'unknown'}", file=sys.stderr)
    print(f"elapsed     : {elapsed:.2f} s", file=sys.stderr)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    store_path = args.store or default_store_path()
    if not store_path.exists():
        print(f"(no store at {store_path})")
        return 0
    store = RunStore(store_path)
    runs = store.list_runs()
    if not runs:
        print("(no runs)")
        return 0
    print(f"{'run_id':<24}  {'status':<10}  {'cands':>7}  {'spec':<10}  topology")
    print("-" * 80)
    for r in runs:
        n = store.candidate_count(r.run_id)
        spec = r.spec()
        print(
            f"{r.run_id:<24}  {r.status:<10}  {n:>7}  "
            f"{r.spec_hash[:8]}…   {spec.topology}",
        )
    return 0


def cmd_top(args: argparse.Namespace) -> int:
    store_path = args.store or default_store_path()
    store = RunStore(store_path)
    rows = store.top_candidates(args.run_id, n=args.n, order_by=args.by)
    _print_top(rows)
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    store_path = args.store or default_store_path()
    store = RunStore(store_path)
    record = store.get_run(args.run_id)
    if record is None:
        sys.exit(f"error: run_id {args.run_id!r} not in store")
    print(f"run_id      : {record.run_id}")
    print(f"started_at  : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(record.started_at))}")
    print(f"status      : {record.status}")
    print(f"pid         : {record.pid}")
    print(f"spec_hash   : {record.spec_hash}")
    print("db_versions :")
    for kind, h in record.db_versions.items():
        print(f"  {kind:<10} {h[:16]}…")
    print(f"config      : {json.dumps(record.config)}")
    print(f"candidates  : {store.candidate_count(record.run_id)}")
    print()
    print("Spec (round-tripped from store):")
    print(json.dumps(record.spec().model_dump(mode='json'), indent=2, ensure_ascii=False))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    store_path = args.store or default_store_path()
    store = RunStore(store_path)
    if store.get_run(args.run_id) is None:
        sys.exit(f"error: run_id {args.run_id!r} not in store")
    stats = _gather_stats(store, args.run_id)
    print(f"Stats for run {args.run_id}")
    print("------------------")
    _print_stats(stats)
    if args.json:
        print()
        print(json.dumps(asdict(stats), indent=2, ensure_ascii=False))
    return 0


# ─── Argument parser ────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cascade_cli",
        description=__doc__.split("\n\n", 1)[0] if __doc__ else None,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--store", type=Path, default=None,
        help=f"SQLite store path (default: {default_store_path()})",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── run ──────────────────────────────────────────────────────
    p_run = sub.add_parser("run", help="Start a fresh cascade run.")
    p_run.add_argument(
        "--spec", dest="spec_file", default=None,
        help="Load Spec from this JSON file (overrides individual flags).",
    )
    p_run.add_argument(
        "--topology", choices=("boost_ccm", "passive_choke", "line_reactor"),
        default="boost_ccm",
    )
    # Numeric flags — `None` means "use Spec defaults".
    for flag, dest in (
        ("--vin-min", "vin_min"),    ("--vin-max", "vin_max"),
        ("--vin-nom", "vin_nom"),    ("--vout", "vout"),
        ("--pout", "pout"),          ("--eta", "eta"),
        ("--fsw", "fsw"),            ("--ripple", "ripple"),
        ("--fline", "fline"),
        ("--tamb", "tamb"),          ("--tmax", "tmax"),
        ("--ku", "ku"),              ("--bsat-margin", "bsat_margin"),
        ("--l-req", "l_req"),        ("--i-rated", "i_rated"),
    ):
        p_run.add_argument(flag, dest=dest, type=float, default=None)
    p_run.add_argument("--phases", type=int, default=None,
                       help="Line-reactor phases (1 or 3)")
    p_run.add_argument("--material", default=None,
                       help="Restrict to a single material id")
    p_run.add_argument("--wire", default=None,
                       help="Restrict to a single wire id")
    p_run.add_argument("--parallelism", type=int, default=4)
    p_run.add_argument("--k1", type=int, default=1000)
    p_run.add_argument("--top", type=int, default=10,
                       help="Top-N rows printed at the end (default 10)")
    p_run.add_argument("--no-compat-filter", action="store_true",
                       help="Pair every core with every material (slow!)")
    p_run.add_argument("--allow-litz", action="store_true",
                       help="Include Litz wires in the sweep")
    p_run.add_argument("--json-out", type=Path, default=None,
                       help="Also dump a JSON summary to this path")
    p_run.set_defaults(func=cmd_run)

    # ── resume ───────────────────────────────────────────────────
    p_resume = sub.add_parser(
        "resume", help="Continue an interrupted run by run_id.",
    )
    p_resume.add_argument("--run-id", required=True)
    p_resume.add_argument("--material", default=None)
    p_resume.add_argument("--wire", default=None)
    p_resume.add_argument("--parallelism", type=int, default=4)
    p_resume.set_defaults(func=cmd_resume)

    # ── list ─────────────────────────────────────────────────────
    p_list = sub.add_parser("list", help="List cascade runs in the store.")
    p_list.set_defaults(func=cmd_list)

    # ── top ──────────────────────────────────────────────────────
    p_top = sub.add_parser("top", help="Print top-N candidates for a run.")
    p_top.add_argument("--run-id", required=True)
    p_top.add_argument("--n", type=int, default=20)
    p_top.add_argument(
        "--by", default="loss_t1_W",
        choices=("loss_t1_W", "temp_t1_C", "cost_t1_USD", "loss_t2_W"),
    )
    p_top.set_defaults(func=cmd_top)

    # ── inspect ──────────────────────────────────────────────────
    p_insp = sub.add_parser("inspect", help="Show full metadata for a run.")
    p_insp.add_argument("--run-id", required=True)
    p_insp.set_defaults(func=cmd_inspect)

    # ── stats ────────────────────────────────────────────────────
    p_stats = sub.add_parser(
        "stats", help="Per-tier breakdown of one run (counts + reasons).",
    )
    p_stats.add_argument("--run-id", required=True)
    p_stats.add_argument("--json", action="store_true",
                         help="Also dump the breakdown as JSON.")
    p_stats.set_defaults(func=cmd_stats)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
