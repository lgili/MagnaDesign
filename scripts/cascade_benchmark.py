"""Cascade benchmark harness — Phase A baseline.

Runs the cascade against a fixed three-spec suite (boost CCM,
passive choke, line reactor) and records per-tier wall time +
top-5 candidates for each. The output is a single Markdown
report appended to ``docs/cascade-benchmarks.md`` for tracking
across releases.

Usage::

    uv run python scripts/cascade_benchmark.py
    uv run python scripts/cascade_benchmark.py --parallelism 1
    uv run python scripts/cascade_benchmark.py --output /tmp/bench.md

The script restricts the database slice to one curated material
per spec so it finishes in seconds (not the ~80 minutes of a
full cascade run). Phase B/C/D will gate on this same harness
extended with their respective tiers.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pfc_inductor.data_loader import load_cores, load_materials, load_wires
from pfc_inductor.models import Core, Material, Spec, Wire
from pfc_inductor.optimize.cascade import (
    CascadeConfig,
    CascadeOrchestrator,
    RunStore,
    TierProgress,
)


@dataclass
class BenchmarkSpec:
    """A single benchmark scenario."""

    name: str
    spec: Spec
    material_id: str
    description: str


@dataclass
class TierTiming:
    tier: int
    wall_seconds: float
    candidates_done: int


@dataclass
class TopRow:
    rank: int
    candidate_key: str
    core_id: str
    material_id: str
    wire_id: str
    loss_W: Optional[float]
    temp_C: Optional[float]


@dataclass
class BenchmarkResult:
    name: str
    description: str
    tier_timings: list[TierTiming]
    total_seconds: float
    n_candidates: int
    top_5: list[TopRow]
    final_status: str


def _bench_specs() -> list[BenchmarkSpec]:
    """Three calibrated scenarios — one per supported topology.

    The materials are chosen because the curated DB has both
    Steinmetz and rolloff calibrated for them.
    """
    boost = Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
        Vout_V=400.0, Pout_W=800.0, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
        T_amb_C=40.0, T_max_C=100.0, Ku_max=0.40, Bsat_margin=0.20,
    )
    choke = Spec(
        topology="passive_choke",
        Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
        Vout_V=400.0, Pout_W=400.0, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
        T_amb_C=40.0, T_max_C=100.0, Ku_max=0.40, Bsat_margin=0.20,
    )
    reactor = Spec(
        topology="line_reactor",
        Vin_min_Vrms=380.0, Vin_max_Vrms=440.0, Vin_nom_Vrms=400.0,
        f_line_Hz=60.0,
        Vout_V=600.0, Pout_W=20_000.0, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
        T_amb_C=40.0, T_max_C=100.0, Ku_max=0.40, Bsat_margin=0.20,
        n_phases=3, L_req_mH=1.0, I_rated_Arms=30.0,
    )
    return [
        BenchmarkSpec(
            name="boost-800W",
            spec=boost,
            material_id="magnetics-60_highflux",
            description="800 W boost-CCM PFC on Magnetics High Flux 60µ",
        ),
        BenchmarkSpec(
            name="choke-400W",
            spec=choke,
            material_id="magnetics-60_highflux",
            description="400 W passive line-frequency choke on High Flux 60µ",
        ),
        BenchmarkSpec(
            name="reactor-3ph",
            spec=reactor,
            material_id="magnetics-60_highflux",
            description="3φ 30 A line reactor (1 mH) on High Flux 60µ",
        ),
    ]


def _filter_db(
    materials: list[Material],
    cores: list[Core],
    wires: list[Wire],
    material_id: str,
) -> tuple[list[Material], list[Core], list[Wire]]:
    """Restrict the search to a single material's compatible cores +
    a small wire palette so the benchmark finishes in seconds."""
    mats = [m for m in materials if m.id == material_id]
    if not mats:
        raise SystemExit(
            f"benchmark: material {material_id!r} not in the curated DB",
        )
    cores_filtered = [c for c in cores if c.default_material_id == material_id]
    wires_filtered = [
        w for w in wires
        if w.id in {"AWG12", "AWG14", "AWG16", "AWG18"} and w.type == "round"
    ]
    return mats, cores_filtered, wires_filtered


def run_benchmark(
    bench: BenchmarkSpec,
    *,
    db_path: Path,
    parallelism: int,
) -> BenchmarkResult:
    materials_full = load_materials()
    cores_full = load_cores()
    wires_full = load_wires()
    materials, cores, wires = _filter_db(
        materials_full, cores_full, wires_full, bench.material_id,
    )

    store = RunStore(db_path)
    orch = CascadeOrchestrator(store, parallelism=parallelism)
    run_id = orch.start_run(bench.spec, CascadeConfig())

    tier_starts: dict[int, float] = {}
    tier_finishes: dict[int, float] = {}
    tier_done: dict[int, int] = {}

    def _cb(p: TierProgress) -> None:
        if p.tier not in tier_starts:
            tier_starts[p.tier] = time.perf_counter()
        if p.done == p.total:
            tier_finishes[p.tier] = time.perf_counter()
            tier_done[p.tier] = p.done

    overall_start = time.perf_counter()
    orch.run(run_id, bench.spec, materials, cores, wires, progress_cb=_cb)
    overall_elapsed = time.perf_counter() - overall_start

    timings = [
        TierTiming(
            tier=tier,
            wall_seconds=tier_finishes.get(tier, overall_start) - tier_starts[tier],
            candidates_done=tier_done.get(tier, 0),
        )
        for tier in sorted(tier_starts.keys())
    ]

    top_rows = store.top_candidates(run_id, n=5, order_by="loss_t1_W")
    top_5 = [
        TopRow(
            rank=i + 1,
            candidate_key=row.candidate_key,
            core_id=row.core_id,
            material_id=row.material_id,
            wire_id=row.wire_id,
            loss_W=row.loss_t1_W,
            temp_C=row.temp_t1_C,
        )
        for i, row in enumerate(top_rows)
    ]

    record = store.get_run(run_id)
    final_status = record.status if record is not None else "unknown"

    return BenchmarkResult(
        name=bench.name,
        description=bench.description,
        tier_timings=timings,
        total_seconds=overall_elapsed,
        n_candidates=store.candidate_count(run_id),
        top_5=top_5,
        final_status=final_status,
    )


_INTRO = """# Cascade benchmark

This document is regenerated by `scripts/cascade_benchmark.py`. It
captures the wall time and top-5 candidates produced by the cascade
optimizer on a fixed three-spec suite (boost CCM, passive choke,
3-phase line reactor), restricted to a single curated material so
the run finishes in seconds.

The suite is the gating artefact for Phase B / C / D. When a new
tier ships, this benchmark must be regenerated and the write-up
must show the new tier catching at least one design class the
prior tier missed (or, equally informative, prove that the tier is
unnecessary for these scenarios).

To regenerate:

```bash
uv run python scripts/cascade_benchmark.py --parallelism 4 --output docs/cascade-benchmarks.md
```

"""


def render_markdown(results: list[BenchmarkResult], *, parallelism: int) -> str:
    lines: list[str] = []
    lines.append(_INTRO)
    lines.append(f"## Run — {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append(f"Parallelism: **{parallelism}** worker(s).")
    lines.append("")
    for r in results:
        lines.append(f"## {r.name} — {r.description}")
        lines.append("")
        lines.append(f"- Status: `{r.final_status}`")
        lines.append(f"- Total wall: **{r.total_seconds:.2f} s**")
        lines.append(f"- Candidates evaluated: **{r.n_candidates}**")
        lines.append("")
        lines.append("| Tier | Wall [s] | Candidates done |")
        lines.append("|------|----------|-----------------|")
        for t in r.tier_timings:
            lines.append(f"| {t.tier} | {t.wall_seconds:.2f} | {t.candidates_done} |")
        lines.append("")
        lines.append("Top 5 by Tier 1 loss:")
        lines.append("")
        lines.append("| # | Core | Material | Wire | Loss [W] | ΔT [°C] |")
        lines.append("|---|------|----------|------|----------|---------|")
        for row in r.top_5:
            loss = f"{row.loss_W:.2f}" if row.loss_W is not None else "—"
            temp = f"{row.temp_C:.0f}" if row.temp_C is not None else "—"
            lines.append(
                f"| {row.rank} | `{row.core_id}` | `{row.material_id}` | "
                f"`{row.wire_id}` | {loss} | {temp} |",
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cascade benchmark harness")
    parser.add_argument(
        "--parallelism",
        type=int,
        default=1,
        help="Worker pool size (default: 1, sequential).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Markdown file to write (default: print to stdout).",
    )
    parser.add_argument(
        "--store-dir",
        type=Path,
        default=None,
        help="Directory for the per-run SQLite stores (default: a tmp dir).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of Markdown.",
    )
    args = parser.parse_args()

    store_dir = args.store_dir or Path("/tmp/cascade-bench")
    store_dir.mkdir(parents=True, exist_ok=True)

    results: list[BenchmarkResult] = []
    for bench in _bench_specs():
        db_path = store_dir / f"{bench.name}.db"
        # Fresh DB per scenario keeps numbers comparable run-to-run.
        if db_path.exists():
            db_path.unlink()
        print(f"running {bench.name} …", flush=True)
        r = run_benchmark(bench, db_path=db_path, parallelism=args.parallelism)
        print(f"  done in {r.total_seconds:.2f} s ({r.n_candidates} cand)", flush=True)
        results.append(r)

    if args.json:
        payload = {
            "parallelism": args.parallelism,
            "results": [
                {
                    "name": r.name,
                    "description": r.description,
                    "total_seconds": r.total_seconds,
                    "n_candidates": r.n_candidates,
                    "final_status": r.final_status,
                    "tier_timings": [
                        {"tier": t.tier, "wall_seconds": t.wall_seconds,
                         "candidates_done": t.candidates_done}
                        for t in r.tier_timings
                    ],
                    "top_5": [
                        {"rank": row.rank, "core_id": row.core_id,
                         "material_id": row.material_id, "wire_id": row.wire_id,
                         "loss_W": row.loss_W, "temp_C": row.temp_C}
                        for row in r.top_5
                    ],
                }
                for r in results
            ],
        }
        rendered = json.dumps(payload, indent=2, ensure_ascii=False)
    else:
        rendered = render_markdown(results, parallelism=args.parallelism)

    if args.output is None:
        print(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
