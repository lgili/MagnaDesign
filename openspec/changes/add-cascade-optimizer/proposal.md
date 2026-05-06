# Add cascade optimizer — multi-tier brute-force inductor design search

## Why

The current `optimize/sweep.py` evaluates designs with the analytical
steady-state pipeline (iGSE + Dowell + iterative thermal) and ranks
them by loss / volume / temperature / cost. That is fast (~2 000
designs/sec) and good enough for typical PFC, but in practice the
user runs into three ceilings:

1. **Single fidelity tier.** When the analytical model is uncertain
   (large gap with fringing, deep saturation, dense Litz with
   heavy proximity effects), there is no automatic second source.
   The user has to open `Validate (FEA)` one design at a time.
2. **Single converter shape.** The sweep is parameterised by spec +
   topology adapter, but there is no abstraction for a converter
   *simulation model*. New topologies (buck, flyback, LLC) require
   bespoke analytical adapters; they cannot be plugged in as a
   state-space description.
3. **No persistence and no large-scale exploration.** Sweeps run in
   process memory; results vanish on close. There is no way to run
   an overnight search over the full database, resume after a
   crash, or diff two runs.

We want a brute-force search engine that is genuinely deep:
millions-of-candidates analytical pruning, transient ODE simulation
of a smaller cohort, FEA cross-check at the top, and full transient
FEA on the final survivors — all driven by a single converter
model the user supplies.

## What changes

A new module tree under `optimize/cascade/` orchestrating a
**4-tier evaluation pipeline**:

| Tier | Method                                              | Cost / candidate | Volume in → out  |
|------|-----------------------------------------------------|------------------|------------------|
| 0    | Geometric fit, Bsat envelope, AL plausibility       | < 10 µs          | 50 M → 500 k     |
| 1    | Analytical: iGSE + Dowell + thermal (today's sweep) | ~1 ms            | 500 k → 1 k      |
| 2    | Transient ODE with non-linear µ(H, T)               | 100 ms – 1 s     | 1 k → 50         |
| 3    | FEMMT magnetostatic on the top survivors            | 5 – 30 s         | 50 → 5           |
| 4    | FEMMT transient on the top survivors (opt-in)       | 1 – 60 min       | 5 → 1            |

The pipeline rests on three foundations that are reused across
every tier:

- A **`ConverterModel` interface** that all topologies implement to
  expose state-space derivatives, switching events, and a loss
  envelope. Today's `topology/*` adapters become the analytical
  half of this interface; the simulation half is added per
  topology.
- A **`RunStore`** persistence layer (SQLite) that records every
  candidate with full provenance (spec hash, DB versions, tier
  reached, all metrics) so sweeps are resumable, comparable across
  days, and inspectable after the fact.
- A **process-pool execution layer** that parallelises Tier 0/1/2
  on CPU cores and serialises Tier 3/4 through a FEMMT-aware
  queue.

A **dedicated cascade workspace page** (separate from the existing
`OptimizeDialog`) shows per-tier progress, a top-N table updating
in real time, cancellation, and one-click promotion of any
candidate to a higher tier.

Each tier is independently shippable. Tier 0–1 plus the
`ConverterModel` interface and `RunStore` form the foundation;
Tiers 2 / 3 / 4 land in subsequent phases as their value is
validated on real designs.

## Impact

- **Affected capabilities:** NEW `cascade-optimization`. The
  existing `optimize/sweep.py` is reused as the Tier 1 worker —
  its public surface stays stable; the cascade orchestrator wraps
  it. `OptimizeDialog` continues to be the fast, lightweight path.
- **Affected modules:** NEW `optimize/cascade/` (orchestrator,
  storage, executors); NEW `simulate/` (ODE solver, integrators,
  PWM event detection); NEW `topology/<name>_model.py` per
  topology (state-space implementations); additions to `fea/`
  (batched runner with worker pool, optional transient driver);
  NEW `ui/workspace/cascade_page.py`.
- **New dependencies:** none required for Tiers 0–1. Tier 2 uses
  `scipy.integrate` (already a project dependency). Tiers 3/4
  reuse the existing FEMMT pipeline. Persistence uses stdlib
  `sqlite3`.
- **Risk:** XL. The largest change since the v3 shell rewrite.
  Mitigation is the phased rollout: Tier 0–1 + interface + store
  ship first as a non-breaking refactor of `sweep.py`. Each
  subsequent tier is gated by a measured uplift on a calibrated
  benchmark suite of three production designs.
- **Scope guardrail (ADR 0001):** This change answers Yes to
  Question 2 ("higher-fidelity calculation of an existing
  capability") and Question 3 ("topology coverage"). The
  `ConverterModel` interface stays converter-shaped; the change
  does **not** open the door to generic FEM tooling or
  generic-magnetics scope creep. Topology adapters that do not
  describe a power converter (e.g., generic 60 Hz line reactors
  decoupled from a converter context) remain explicit non-targets.

## Phasing

- **Phase A (foundation, ships first):** ConverterModel interface,
  RunStore, Tier 0 feasibility, Tier 1 wraps existing sweep,
  parallel execution, cascade UI skeleton with live top-N table.
- **Phase B:** Tier 2 transient ODE simulator, with state-space
  models for the three currently shipped topologies (boost CCM,
  passive choke, line reactor).
- **Phase C:** Tier 3 batched FEA (FEMMT magnetostatic), automatic
  promotion of Tier 2 top-50.
- **Phase D:** Tier 4 transient FEA (FEMMT transient mode),
  reserved for top-5 designs and only when the user opts in
  (wall-clock can exceed one hour per candidate).

Each phase is its own merge unit. Phases B / C / D are gated on a
benchmark write-up showing the new tier's uplift on the cascade
benchmark suite.
