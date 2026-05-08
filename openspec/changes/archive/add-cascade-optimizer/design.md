# Design — Cascade optimizer

## Architecture

```
                    ┌──────────────────────────────────┐
                    │       CascadeOrchestrator         │
                    │ spec, db_snapshot, tier_thresholds│
                    │ parallelism, run_store            │
                    └─────────────┬────────────────────┘
                                  │
       ┌──────────┐  prune  ┌──────────┐  prune  ┌──────────┐
       │ Tier 0   │ ──────► │ Tier 1   │ ──────► │ Tier 2   │
       │ Feasibty │         │ Analytic │         │ Transient│
       └──────────┘         └──────────┘         └────┬─────┘
                                                      ▼
                                                ┌──────────┐
                                                │ Tier 3   │
                                                │ FEA stat │
                                                └────┬─────┘
                                                     ▼
                                                ┌──────────┐
                                                │ Tier 4   │
                                                │ FEA trans│
                                                └────┬─────┘
                                                     ▼
                                              RunStore (SQLite)
```

Each tier is a pure function `(Candidate, ConverterModel) →
TierResult` plus a pruning rule that drops candidates that violate
the tier's constraint or fall below a configurable rank.

## ConverterModel interface

The single abstraction that makes the cascade topology-agnostic.
Every topology implements this; the rest of the pipeline never
imports topology-specific code.

```python
class ConverterModel(Protocol):
    """Topology-aware adapter that the cascade pipeline drives."""

    name: str
    spec: Spec

    # ─── Tier 0 ──────────────────────────────────────────────
    # Cheap geometric / saturation envelope.
    def feasibility_envelope(
        self, core: Core, material: Material, wire: Wire
    ) -> FeasibilityEnvelope: ...

    # ─── Tier 1 ──────────────────────────────────────────────
    # Closed-form steady-state operating point. Reuses today's
    # analytical engine.
    def steady_state(
        self, core: Core, material: Material, wire: Wire,
        N: int, gap_mm: float | None,
    ) -> SteadyState: ...

    # ─── Tier 2 ──────────────────────────────────────────────
    # State-space derivatives for an ODE solver.
    def state_derivatives(
        self, t: float, x: np.ndarray, inductor: NonlinearInductor,
    ) -> np.ndarray: ...

    # Switching events (PWM transitions, diode commutations).
    def event_functions(self) -> list[EventFunction]: ...

    # Post-process a sampled waveform into design metrics.
    def loss_envelope(
        self, waveform: Waveform,
        core: Core, material: Material, wire: Wire,
    ) -> LossEnvelope: ...

    # ─── Tier 3/4 ────────────────────────────────────────────
    # FEA geometry hints (axisymmetric flag, gap definition).
    def fea_geometry_hints(self) -> FEAHints: ...
```

The Phase-A topology adapters implement `feasibility_envelope` and
`steady_state` only; the remaining methods raise
`NotImplementedError` until Phase B / C ships their tier. This is
the contract that lets us defer Tiers 2–4 without freezing the
foundation.

## NonlinearInductor — the bridge from material data to ODE state

A reusable component injected into Tier 2 (and Tier 4 when it
ships). Computes instantaneous L(i, T) by interpolating the
rolloff curve at H = N · i / le and applying the Steinmetz-
temperature correction. Hides material data from the converter
model so each topology's state-space stays free of material
lookups.

## Tier 0 — Feasibility envelope

Pure-Python integer/float arithmetic, vectorised over candidates
with NumPy. Filters:

1. **Window fit:** `N · A_wire ≤ Ku_max · W_a`.
2. **Saturation envelope:** `B_pk_estimate ≤ Bsat · (1 − margin)`,
   where `B_pk_estimate = µ_0 · µ_eff_min · N · I_pk / le` (no
   rolloff iteration — the lower bound is sufficient for a
   feasibility cut).
3. **AL sanity:** `L_min ≤ N² · AL ≤ L_max`, with `L_min` from
   topology + 50 % margin and `L_max = 4 · L_required`.
4. **Optional cost cap:** `total_mass · price_per_kg < cap`.

Throughput target: ≥ 1 M candidates/sec on a single core. With
four worker processes, the full database (50 mat × 1 008 cores ×
48 wires × N range) is filtered in well under one minute.

## Tier 1 — Analytical steady-state

Wraps today's `optimize/sweep.py::evaluate_design`. No semantic
changes; the cascade orchestrator simply feeds it the survivors
of Tier 0. Pruning rule: keep top-K by ranking objective,
configurable, default `K = 1 000`, objective = `total_loss`.

## Tier 2 — Transient ODE simulation

Two sub-components: the **simulator** (topology-agnostic) and the
**state-space model** (topology-specific).

### Simulator core

```python
def simulate_to_steady_state(
    model: ConverterModel,
    inductor: NonlinearInductor,
    t_max: float = 5 * line_period,
    rel_tol: float = 1e-4,
    steady_state_window: int = 3,    # last N line cycles
) -> Waveform: ...
```

Internals:

- `scipy.integrate.solve_ivp(method="LSODA")` for stiff segments.
- Event-driven step refinement at PWM transitions and diode
  commutations (`event_functions`).
- Steady-state detection: cycle-by-cycle peak comparison;
  declared converged when the last `steady_state_window` cycles
  agree within `rel_tol`.
- Output: waveform sampled at fixed Δt (Nyquist of `f_sw × 4`)
  plus captured cycle metadata.

### State-space examples

**Boost CCM (1-state model):**

```
di/dt = (v_in(t) − (1 − d) · V_out − i · R_dc) / L(i, T)
```

PFC line-cycle averaging done by sweeping `d(t)` along the line
period; per-switching-event simulation is also supported when the
user wants HF detail.

**Flyback (2-state coupled, future Phase B):**

```
di_pri/dt = (v_in − i_pri · R_pri) / L_pri(i_pri, T)     when SW closed
di_sec/dt = (−V_out − i_sec · R_sec) / L_sec(i_sec, T)   when SW open
```

States are linked by mutual inductance plus leakage `L_lk`
derived from material/geometry.

### Pruning

After Tier 2 evaluates K_2 candidates (default 1 000), keep top
K_3 = 50 by transient-corrected total loss. Designs that the
transient sim flags as saturating mid-cycle are dropped
regardless of rank.

## Tier 3 — Batched FEA

Wraps `fea/femmt_runner.py`. New `BatchedFEAExecutor` queues runs
through a single worker process: FEMMT spawns ONELAB and
concurrent runs collide on the temp directory, so the executor
must serialise.

The cascade compares the FEA-validated `L` and `B_pk` against the
analytical (Tier 1) and transient (Tier 2) predictions and flags
candidates where the three disagree by more than 15 %. Top-50
cost: ~25 minutes total on a typical workstation.

## Tier 4 — Transient FEA (opt-in)

FEMMT supports transient simulation via
`MagneticComponent.simulate_transient`. Driven only on user
request, only on the top-5 from Tier 3. Wall-clock 5 – 60 minutes
per candidate; this tier is for the final design that is going to
prototype.

## RunStore (SQLite)

```sql
CREATE TABLE runs (
  run_id      TEXT PRIMARY KEY,
  started_at  INTEGER,
  spec_hash   TEXT,             -- SHA-256 of canonical spec JSON
  db_versions TEXT,             -- JSON: {materials, cores, wires} hashes
  config      TEXT,             -- JSON: tier thresholds, K_i values
  status      TEXT              -- 'running' | 'cancelled' | 'done'
);

CREATE TABLE candidates (
  run_id         TEXT,
  candidate_id   INTEGER,
  core_id        TEXT,
  material_id    TEXT,
  wire_id        TEXT,
  N              INTEGER,
  gap_mm         REAL,
  highest_tier   INTEGER,        -- 0..4
  -- Per-tier metrics (all nullable)
  feasible_t0    INTEGER,        -- bool
  loss_t1_W      REAL,
  temp_t1_C      REAL,
  cost_t1_USD    REAL,
  loss_t2_W      REAL,
  saturation_t2  INTEGER,        -- bool
  L_t3_uH        REAL,
  Bpk_t3_T       REAL,
  L_t4_uH        REAL,
  notes          TEXT,           -- JSON: warnings, errors
  PRIMARY KEY (run_id, candidate_id)
);

CREATE INDEX idx_candidates_run  ON candidates(run_id);
CREATE INDEX idx_candidates_loss ON candidates(run_id, loss_t1_W);
```

Resumability: orchestrator detects `status='running'` from a
prior session, re-attaches to the same `run_id`, replays Tier 0
from the deterministic candidate generator, and skips candidates
already in the table. Crash recovery is automatic on next launch.

## Parallelism

| Tier | Model                                       | Default workers      |
|------|---------------------------------------------|----------------------|
| 0    | Vectorised NumPy on a single process        | 1 (already SIMD)     |
| 1    | `multiprocessing.Pool`, pickled spec + cand | `os.cpu_count()`     |
| 2    | Same pool; ODE solver per worker            | `os.cpu_count()`     |
| 3    | Single FEMMT queue                          | 1                    |
| 4    | Single FEMMT queue                          | 1                    |

Indicative throughput on an 8-core workstation:

- Tier 0: ~8 M cand/sec.
- Tier 1: ~16 k cand/sec — wall ≈ 1 min for 1 M Tier-0 survivors.
- Tier 2: ~80 cand/sec — wall ≈ 12 s for 1 k survivors.
- Tier 3: ~0.04 cand/sec — wall ≈ 25 min for 50.
- Tier 4: ~0.005 cand/sec — wall ≈ 50 min for 5.

End-to-end wall on a typical configuration: **~80 minutes** with
Tier 4 enabled, **~30 minutes** without.

## UI mock

```
┌─────────────────────────────────────────────────────────────┐
│ Cascade run 2026-05-06_14h32        [Cancel]  [Pause]       │
├─────────────────────────────────────────────────────────────┤
│ Tier 0  ████████████████████  Done       50 M → 487 k       │
│ Tier 1  █████████████░░░░░░░  78 %       running…           │
│ Tier 2  ░░░░░░░░░░░░░░░░░░░░  pending                       │
│ Tier 3  ░░░░░░░░░░░░░░░░░░░░  pending                       │
│ Tier 4  ░░░░░░░░░░░░░░░░░░░░  pending                       │
├─────────────────────────────────────────────────────────────┤
│ Top by total loss (live)                                    │
│  #  Core            Material      Wire    N   Loss   ΔT    │
│  1  KMU-77439-A7    Kool Mu 60µ   16 AWG  52  4.2 W  41 °C │
│  2  KMU-77930-A7    Kool Mu 60µ   16 AWG  48  4.4 W  43 °C │
│  …                                                          │
│                                                             │
│  [Promote selection to Tier 3]   [Open in design view]      │
└─────────────────────────────────────────────────────────────┘
```

Lives under `ui/workspace/cascade_page.py`. The existing
`OptimizeDialog` stays as the fast/lightweight path; the cascade
page is the heavy-duty one. A small "Run deep sweep" button in
`OptimizeDialog` routes the current spec to the cascade page.

## Open questions

1. **Tier 2 simulator framework.** `scipy.solve_ivp` is sufficient
   for boost and choke. For resonant topologies (LLC, two-state)
   we may want `casadi` or `assimulo` for speed. Defer the
   decision to Phase B and run a single-topology proof first.
2. **Database snapshotting.** Should a run capture a frozen copy
   of the materials/cores/wires used, or only their hashes?
   Frozen copy makes runs forever-reproducible but doubles disk
   usage for large sweeps. Lean toward hashes plus a deduplicated
   snapshot table keyed by hash.
3. **GPU acceleration?** Tier 2 batched ODEs could run on GPU via
   `diffrax` / JAX for a 10 – 100× speedup on mid K_2. Out of
   scope for Phase B; revisit if workstation wall time becomes
   painful.
4. **Cancellation semantics for Tier 3/4.** Mid-tier cancel —
   discard the in-flight FEA or wait for it? Lean toward "drain
   the in-flight candidate, then stop" to avoid orphaned ONELAB
   processes.
5. **Cross-run diff UI.** Useful or YAGNI? Two runs with the same
   spec hash but different DB versions are directly comparable
   and informative; add later if asked.
6. **Naming.** "Cascade" is the internal architecture term. The
   UI label could be "Otimizador profundo", "Deep sweep",
   "Brute-force optimizer", or stay "Cascade". TBD with the user
   when Phase A surfaces in the UI.
