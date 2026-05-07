# Cascade optimizer

The cascade is a **multi-tier brute-force search** over the entire
material × core × wire space. Every candidate flows through up to
four tiers; designs that fail a tier's constraint are dropped, and
survivors progress to the next, more expensive tier.

```
Tier 0  Feasibility envelope        — drop on window fit / Bsat / AL
Tier 1  Analytical steady state     — drop on warnings, rank by loss
Tier 2  Transient ODE (Phase B)     — catch saturation / proximity loss
Tier 3  Static FEA   (Phase C)      — second-source L and B_pk
Tier 4  Transient FEA (Phase D)     — final pre-prototype check
```

Phase A ships Tier 0 and Tier 1 plus the entire foundation
(`ConverterModel` interface, `RunStore`, parallel orchestrator,
benchmark harness). Tiers 2/3/4 land in their respective phases
gated on the benchmark uplift documented in
[`docs/cascade-benchmarks.md`](cascade-benchmarks.md).

## When to use the cascade vs. the regular optimizer

The existing `Otimizador` page (Pareto sweep) remains the **fast
path** for daily use — it returns in under a minute and answers
"what's the best design from this database for my spec?".

Use the cascade when:

- The analytical model is uncertain — large gap with fringing,
  deep saturation, dense Litz with proximity effects. Future
  Tier 2/3 will add second-source numbers.
- You want a persistent, resumable record of every candidate the
  search ever evaluated (the `RunStore` makes this auditable).
- You need to explore far beyond a single material — tens of
  thousands of (material × core × wire) combinations.

For a typical 800 W boost design with one curated material, the
Phase-A cascade finishes Tier 0 + Tier 1 in well under a second
on a 4-core workstation.

## Architecture

The cascade is built around a single `ConverterModel` Protocol that
every topology implements. The orchestrator never imports
topology-specific code; adding a new converter means adding one
class and registering it in `topology/registry.py`.

```
src/pfc_inductor/
  topology/
    protocol.py             # ConverterModel
    registry.py             # model_for(spec)
    boost_ccm_model.py
    passive_choke_model.py
    line_reactor_model.py
  optimize/cascade/
    orchestrator.py         # CascadeOrchestrator
    tier0.py                # feasibility envelope
    tier1.py                # analytical evaluator
    generators.py           # cartesian candidate generator
    store.py                # SQLite RunStore
  models/
    cascade.py              # Candidate, FeasibilityEnvelope, Tier{0,1}Result
  ui/workspace/
    cascade_page.py         # Qt UI
```

Tiers 2/3/4 live in their own modules under `simulate/` and
`fea/` and slot in via the Protocol; the orchestrator gains a
single new branch per tier.

## CLI usage

`scripts/cascade_cli.py` is the headless validation runner. It is
the recommended way to exercise the full pipeline before the GUI
integration lands. Subcommands:

| Subcommand | Purpose                                         |
|------------|-------------------------------------------------|
| `run`      | Start a fresh cascade run for a spec.           |
| `resume`   | Continue an interrupted run by `run_id`.        |
| `list`     | Enumerate cascade runs in the persistent store. |
| `top`      | Print the top-N candidates of a run.            |
| `stats`    | Per-tier breakdown (counts + reject reasons).   |
| `inspect`  | Full metadata + originating spec for a run.     |

The default store path is `<user-data-dir>/cascade.db` so runs
accumulate across CLI and (future) GUI invocations. Override with
`--store <path>`.

### Quick recipes

```bash
# Fresh run, scoped to one curated material (fast — minutes, not hours)
uv run python scripts/cascade_cli.py run \
    --topology boost_ccm --pout 800 --vout 400 --fsw 65 \
    --material magnetics-60_highflux --parallelism 4

# Full database sweep (≈ 1 M candidates; tens of minutes on 8 cores)
uv run python scripts/cascade_cli.py run --topology boost_ccm --pout 800

# Bring up history, drill into one
uv run python scripts/cascade_cli.py list
uv run python scripts/cascade_cli.py stats --run-id 20260506-2030-abc1
uv run python scripts/cascade_cli.py top   --run-id 20260506-2030-abc1 --n 20

# Continue an interrupted run
uv run python scripts/cascade_cli.py resume --run-id 20260506-2030-abc1
```

### Sample output

```
filter: material 'magnetics-60_highflux' (465→1 mat, 45 compatible cores)
run_id      : 20260506-210628-1b818150
spec_hash   : 9067dcfa51d9d4fd
topology    : boost_ccm
workers     : 4
materials   : 1
cores       : 45
wires       : 1433

Tier 0: 64485 / 64485 (100%)
Tier 1: 46163 / 46163 (100%)

status      : done
elapsed     : 121.14 s

Per-tier breakdown
------------------
  total candidates : 64485
  Tier 0 feasible  :  46163 (71.6%)
  Tier 0 rejected  :  18322 (28.4%)
      saturates              12891 (70.4%)
      window_overflow         5431 (29.6%)
  Tier 1 evaluated :  43745 (94.8% of T0 feasible)
  Tier 1 with loss :  43745 (engine returned a result)

Top 10 by Tier-1 loss
  #  core_id                            wire_id      N   loss_W  ΔT_°C   cost_$
  1  magnetics-c058777a2-60_highflux    AWG13       43     5.23     58     8.97
  ...
```

### Benchmark harness

The benchmark harness (used by Phase B/C/D ship-readiness
write-ups) lives separately at `scripts/cascade_benchmark.py`:

```bash
uv run python scripts/cascade_benchmark.py --parallelism 4 \
    --output docs/cascade-benchmarks.md
```

## UI usage

`CascadePage` is implemented as a workspace widget but
**intentionally not yet wired into the sidebar / `MainWindow`** —
that integration is gated on Phase A landing in production usage
to avoid disruption to the live UI surface. Tests in
`tests/test_cascade_page.py` cover the page lifecycle in headless
Qt, and the host that wants to embed it does so by:

```python
from pfc_inductor.ui.workspace import CascadePage
page = CascadePage()
page.set_inputs(spec, materials, cores, wires)
page.run()
```

## Resumability

Every cascade run carries a SHA-256 hash of the originating spec
plus content hashes of the materials/cores/wires JSON files. After
a crash, opening the same `RunStore` file and calling
`orchestrator.run()` with the same `run_id` skips every candidate
that already has a row — zero duplicate work, deterministic ordering.

## Wall-time expectations (Phase A)

These numbers are from the in-tree benchmark suite (one curated
material × ~20 compatible cores × 4 wires = 180 candidates per
scenario). See `docs/cascade-benchmarks.md` for the latest run.

| Tier   | Wall (sequential) | Wall (4 workers) |
|--------|-------------------|------------------|
| Tier 0 | ~50 ms            | ~50 ms (no pool) |
| Tier 1 | ~5 s              | ~1 s             |

Full-database wall times (50 mat × 1008 cores × 13 wires) are
expected to fall in the 1–10 minute range with `parallelism=8`;
those numbers will be measured when the orchestrator is exercised
against the full DB in Phase A.x.
