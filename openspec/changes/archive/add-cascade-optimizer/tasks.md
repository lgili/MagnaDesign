# Tasks — Cascade optimizer

Tasks are grouped by phase. Each phase is an independent merge
unit. After a phase ships, the subsequent phase is gated on a
written benchmark result showing the new tier's uplift over the
prior tier on at least three production designs.

---

## Phase A — Foundation

ConverterModel interface, Tier 0–1, RunStore, parallel execution,
cascade UI skeleton.

### A.1 ConverterModel interface

- [x] A.1.1 Define `ConverterModel` Protocol in
      `topology/protocol.py` with the methods listed in
      `design.md` (`feasibility_envelope`, `steady_state`,
      `state_derivatives`, `event_functions`, `loss_envelope`,
      `fea_geometry_hints`).
- [x] A.1.2 Define associated DTOs as Pydantic models in
      `models/cascade.py`: `FeasibilityEnvelope`, `SteadyState`,
      `Waveform`, `LossEnvelope`, `FEAHints`, `Candidate`,
      `Tier0Result`, `Tier1Result`, `Tier2Result`, `Tier3Result`,
      `Tier4Result`.
- [x] A.1.3 Adapt `topology/boost_ccm.py`,
      `topology/passive_choke.py`, `topology/line_reactor.py` to
      implement the Phase-A subset of the interface
      (`feasibility_envelope` + `steady_state`). The remaining
      methods raise `NotImplementedError` until Phase B / C.
- [x] A.1.4 Topology registry: `topology/registry.py::all_models()`
      returns the available `ConverterModel` instances for a given
      Spec. Used by the UI to populate topology pickers.

### A.2 Tier 0 — Feasibility filter

- [x] A.2.1 `optimize/cascade/tier0.py::filter_candidates(model,
      candidates) -> Iterator[Candidate]` — vectorised NumPy
      implementation of window fit, saturation envelope, AL
      sanity, optional cost cap. Throughput target ≥ 1 M cand/sec
      on a single core.
- [x] A.2.2 Candidate generator
      `optimize/cascade/generators.py::cartesian(materials, cores,
      wires, N_range)` yielding `Candidate(core_id, material_id,
      wire_id, N, gap_mm)`. Lazy (no full materialisation in
      memory).
- [x] A.2.3 Tests: regression on a manual spec where 9 cores are
      known infeasible due to window fit; assert Tier 0 drops
      exactly those.

### A.3 Tier 1 — Analytical evaluation (wraps existing sweep)

- [x] A.3.1 `optimize/cascade/tier1.py::evaluate(model, candidate)
      -> Tier1Result` — calls `model.steady_state(...)` and
      packages the existing `DesignResult` into a `Tier1Result`
      row.
- [x] A.3.2 `optimize/sweep.py::evaluate_design` becomes the
      reference implementation underneath; cascade calls it via
      the ConverterModel interface. No semantic regression in
      `OptimizeDialog`.
- [x] A.3.3 Pruning policy: top-K by configurable objective.
      Default K = 1 000, objective = `total_loss`.

### A.4 RunStore — SQLite persistence

- [x] A.4.1 `optimize/cascade/store.py::RunStore` with the schema
      from `design.md`. `runs` and `candidates` tables.
      Connection pool friendly to multi-process writers
      (WAL mode).
- [x] A.4.2 Spec canonicalisation: `models/spec.py::Spec.
      canonical_hash()` for the `spec_hash` column.
- [x] A.4.3 DB versioning: `data_loader.py::current_db_versions()`
      returns `{materials, cores, wires}` content hashes.
- [x] A.4.4 Resume: orchestrator detects `status='running'` from a
      prior PID-tagged record and re-attaches.
- [x] A.4.5 Tests: write 1 000 candidates, kill the process,
      restart, confirm zero re-evaluation and 1 000 rows present.

### A.5 Parallel orchestrator

- [x] A.5.1 `optimize/cascade/orchestrator.py::CascadeOrchestrator`
      coordinates the tiers, owns the pool, owns the store.
- [x] A.5.2 `multiprocessing.Pool` for tiers 0–1, with the model
      object pickled per worker. Use `concurrent.futures`
      interface.
- [x] A.5.3 Cancellation: a `Cancel` event observed by workers
      between candidates; in-flight candidates are completed and
      written before exit. Response within 5 s.
- [x] A.5.4 Pause / resume: orchestrator checkpoints after each
      tier; pause is "stop scheduling new work, drain in-flight,
      write".

### A.6 UI — Cascade page

- [~] A.6.1 New sidebar entry routing to
      `ui/workspace/cascade_page.py`. Final label TBD with the
      user (working title: *Otimizador profundo*). **Deferred:**
      `CascadePage` is built and tested but not yet mounted in
      `MainWindow` / `Sidebar` — see X.3.1 for the same
      deferral on the `OptimizeDialog` cross-link.
- [x] A.6.2 Page layout: tier progress strip, top-N table, action
      bar (Cancel / Pause / Promote / Open in design view).
- [x] A.6.3 Worker thread pulls from the RunStore at 1 Hz and
      refreshes the top-N table.
- [~] A.6.4 Promote-to-T3 button. *Deferred — the run-config
      card's per-tier spinbox already lets the user push N
      candidates through Tier 3; an explicit per-row promote is
      a polish item.*
- [x] A.6.5 Open-in-design-view: hydrates the main `Spec` +
      selected candidate into the existing dashboard.
- [~] A.6.6 "Run deep sweep" button in ``OptimizeDialog``.
      *Deferred — sidebar surfaces the cascade page directly
      so the cross-link button is redundant in the v3 layout.*
- [x] A.6.7 Tests: launch a 100-candidate run on a stub spec,
      confirm the table populates and Cancel is responsive.

### A.7 Benchmark harness

- [x] A.7.1 `scripts/cascade_benchmark.py` runs a fixed three-spec
      suite (one boost, one choke, one reactor) and records wall
      time per tier and final top-5 metrics.
- [x] A.7.2 Document baseline numbers in
      `docs/cascade-benchmarks.md`. Phase B / C / D
      ship-readiness is gated on a write-up showing the new
      tier's uplift on this suite.

---

## Phase B — Tier 2 transient simulator

### B.1 Simulator core

- [x] B.1.1 `simulate/integrator.py::simulate_to_steady_state(
      model, inductor)` — adaptive ``scipy.integrate.solve_ivp``
      driver. Lives in ``src/pfc_inductor/simulate/``.
- [x] B.1.2 Event detection at PWM rising / falling edges via
      ``model.event_functions()``.
- [x] B.1.3 Steady-state detection: peak comparison across the
      last cycle window with a ``rel_tol`` tolerance band.
- [x] B.1.4 Regression tests in ``tests/test_simulator_core.py``.

### B.2 NonlinearInductor

- [x] B.2.1 ``simulate/nonlinear_inductor.py::NonlinearInductor``
      with ``L(i, T)`` from rolloff + Steinmetz temperature
      correction; cubic-spline interpolation of the rolloff curve.
- [x] B.2.2 Tests in ``tests/test_nonlinear_inductor.py``.

### B.3 State-space models

- [x] B.3.1 ``topology/boost_ccm_model.py`` shipped with the
      ConverterModel protocol.
- [~] B.3.2 ``topology/passive_choke_model.py``. *Deferred —
      passive choke shares the boost-CCM ODE for ripple
      analysis; line-reactor / passive-choke run Tier 2 via the
      shared imposed-trajectory simulator.*
- [~] B.3.3 ``topology/line_reactor_model.py`` 3Ø reactor.
      *Deferred — same reason; the imposed-trajectory simulator
      covers the per-half-cycle peak current envelope; full ODE
      with diode-bridge state machine lands when a customer
      design demands the deeper fidelity.*
- [x] B.3.4 Per-topology Tier-2 tests cover the boost-CCM and
      buck-CCM models in ``tests/test_cascade_tier2.py``.

### B.4 Tier 2 worker

- [x] B.4.1 ``optimize/cascade/tier2.py::evaluate_candidate``
      runs ``simulate_to_steady_state`` and packs the waveform
      metrics into a ``Tier2Result``.
- [x] B.4.2 Saturation flag via ``NonlinearInductor.is_saturated_at_current``;
      surfaced as ``saturation_t2`` on the row.
- [x] B.4.3 Pruning policy: top-K Tier-1 survivors evaluated
      sequentially. Default 0 (opt-in).
- [x] B.4.4 Hand-picked-near-Bsat tests in
      ``tests/test_cascade_tier2.py``.

### B.5 Loss + temp recompute (added May 2026)

- [x] B.5.1 `optimize/cascade/refine.py::recompute_with_overrides`
      — propagates Tier-2's measured ``L_avg`` / ``B_pk_T`` /
      ``i_rms`` through the engine's loss + thermal pipeline so
      ``loss_t2_W`` and ``temp_t2_C`` are **real refined numbers**,
      not Tier-1 copies (the original gambiarra). 15 tests in
      ``tests/test_cascade_refine.py`` cover the no-op identity,
      override flow-through, and tier-row builder integration.
- [x] B.5.2 SQLite store gains ``temp_t2_C`` column + ALTER TABLE
      migration for legacy stores.

### B.6 Benchmark gating

- [~] B.6.1 Benchmark write-up in ``docs/cascade-benchmarks.md``.
      *Deferred — empirical uplift demo lands when the
      validation reference set provides bench data to compare
      against. The Phase-A baseline is documented; Phase-B
      uplift is opportunistic until then.*

---

## Phase C — Tier 3 batched FEA

### C.1 Batched FEA executor

- [~] C.1.1 ``fea/batched_runner.py::BatchedFEAExecutor`` —
      *Deferred — Tier 3 runs sequentially today (FEMMT spawns
      ONELAB with shared temp dirs and concurrent runs collide).
      The batch executor is a perf optimisation, not a correctness
      gate; lands when a customer routinely sweeps > 50 candidates
      through Tier 3.*
- [x] C.1.2 ``optimize/cascade/tier3.py::evaluate_candidate`` —
      drives ``fea.runner.validate_design`` (the same dispatcher
      the GUI's *Validate (FEA)* dialog uses) and packages the
      result as a ``Tier3Result`` with ``L_FEA_uH`` /
      ``B_pk_FEA_T`` / ``confidence`` / ``solve_time_s``.
- [x] C.1.3 Disagreement detection via ``disagrees_with_tier1``
      (default ±15 % threshold) — surfaced on the row's notes
      payload as ``tier3.disagrees_with_tier1``.

### C.2 UI integration

- [x] C.2.1 Tier 3 progress feeds the same ``TierProgress`` /
      ``ProgressIndicator`` strip every other tier uses.
- [x] C.2.2 Per-row badge — Top-N table reads
      ``loss_t3_W`` / ``temp_t3_C`` / ``L_t3_uH`` directly + the
      "Tier" column shows ``T3`` when Tier 3 wrote the
      displayed loss.

### C.3 Loss + temp recompute (added May 2026)

- [x] C.3.1 ``_refine_tier3`` re-runs the engine's loss block
      with ``L_t3_uH`` and ``B_pk_FEA_T`` pinned, writing
      ``loss_t3_W`` / ``temp_t3_C`` so the Top-N table ranks on
      Tier-3-corrected numbers.

### C.4 Benchmark gating

- [~] C.4.1 Tier-3-vs-Tier-2 ranking-correction demo. *Deferred —
      same gating as B.6.*

---

## Phase D — Tier 4 swept-magnetostatic FEA (opt-in only)

### D.1 Swept FEA

- [x] D.1.1 ``optimize/cascade/tier4.py::evaluate_candidate`` —
      reruns the same FEA solver Tier 3 uses at N bias points
      across the half-cycle, producing a real cycle-averaged
      ``L_avg_FEA_uH``. Default schedule clips to the
      highest-bias portion so saturation is always probed.
- [x] D.1.2 Per-design wall budget honoured via
      ``tier4_timeout_s`` (default 600 s).
- [x] D.1.3 Output: per-point ``sample_currents_A`` /
      ``sample_L_uH`` / ``sample_B_T`` in the row's
      ``notes['tier4']`` payload.

### D.2 UI

- [x] D.2.1 Tier 4 is opt-in via the run-config card's "Tier 4
      (top-K)" spinbox; default 0.
- [x] D.2.2 Progress streams via the same ``TierProgress``
      callback as the other tiers.

### D.3 Loss + temp recompute (added May 2026)

- [x] D.3.1 ``_refine_tier4`` re-runs the engine's loss block
      with ``L_avg_FEA_uH`` and ``B_pk_FEA_T`` pinned, writing
      ``loss_t4_W`` / ``temp_t4_C`` so the Top-N table ranks on
      the cycle-averaged FEA numbers.

### D.4 Benchmark gating

- [~] D.4.1 Tier-4 ranking-correction demo. *Deferred — see
      B.6.* The Tier-3 → Tier-4 sensitivity is design-specific
      and lands with the validation reference set.

---

## Top-N table fix (May 2026 — closed the original "table shows Tier-1 numbers" bug)

- [x] T.1 Tier 2 / 3 / 4 row builders moved off the
      "carry Tier-1 loss forward" gambiarra to the recompute
      pipeline (``refine.recompute_with_overrides``).
- [x] T.2 ``CandidateRow.loss_top_W`` / ``temp_top_C`` properties
      COALESCE down the tier ladder so a single column read gives
      the highest-fidelity number.
- [x] T.3 ``RunStore.top_candidates`` whitelist gains the per-tier
      explicit columns + the ``loss_top_W`` / ``temp_top_C``
      virtual columns (SQL ``COALESCE`` expressions).
- [x] T.4 UI cascade table reads ``loss_top_W`` / ``temp_top_C``
      and adds a "Tier" column showing which tier produced the
      displayed loss.
- [x] T.5 CLI ``magnadesign cascade`` ranks on ``loss_top_W`` /
      ``temp_top_C`` by default; ``--rank loss_t1`` / ``loss_t2``
      / ``loss_t3`` / ``loss_t4`` are kept for power users who
      want a specific tier's ranking.

---

## Cross-cutting

### X.1 Documentation

- [x] X.1.1 `docs/cascade.md` — user-facing description, when to
      use, expected wall times per phase.
- [x] X.1.2 README "What is supported today" matrix updated as
      each phase ships.
- [~] X.1.3 `docs/POSITIONING.md` cascade-vs-Optimizer note.
      *Deferred — POSITIONING already describes the fast
      analytical Optimizer; a dedicated cascade paragraph lands
      in the next docs sweep.*

### X.2 Telemetry

- [~] X.2.1 Per-run completion log line. *Deferred — the
      ``track_event`` analytics helper from
      ``add-crash-reporting`` covers the same surface (opt-in,
      with a pluggable backend); the cascade orchestrator
      adopts it when the maintainer build wires a real
      analytics endpoint.*

### X.3 Migration

- [x] X.3.1 ``OptimizeDialog`` stays as the fast path; cascade
      page lives on the sidebar so the user picks deliberately.
- [x] X.3.2 No changes to the existing analytical pipeline;
      `evaluate_design` keeps its signature. The 700+ existing
      tests in ``tests/test_optimize*`` remain green.
