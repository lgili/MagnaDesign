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

- [ ] A.1.1 Define `ConverterModel` Protocol in
      `topology/protocol.py` with the methods listed in
      `design.md` (`feasibility_envelope`, `steady_state`,
      `state_derivatives`, `event_functions`, `loss_envelope`,
      `fea_geometry_hints`).
- [ ] A.1.2 Define associated DTOs as Pydantic models in
      `models/cascade.py`: `FeasibilityEnvelope`, `SteadyState`,
      `Waveform`, `LossEnvelope`, `FEAHints`, `Candidate`,
      `Tier0Result`, `Tier1Result`, `Tier2Result`, `Tier3Result`,
      `Tier4Result`.
- [ ] A.1.3 Adapt `topology/boost_ccm.py`,
      `topology/passive_choke.py`, `topology/line_reactor.py` to
      implement the Phase-A subset of the interface
      (`feasibility_envelope` + `steady_state`). The remaining
      methods raise `NotImplementedError` until Phase B / C.
- [ ] A.1.4 Topology registry: `topology/registry.py::all_models()`
      returns the available `ConverterModel` instances for a given
      Spec. Used by the UI to populate topology pickers.

### A.2 Tier 0 — Feasibility filter

- [ ] A.2.1 `optimize/cascade/tier0.py::filter_candidates(model,
      candidates) -> Iterator[Candidate]` — vectorised NumPy
      implementation of window fit, saturation envelope, AL
      sanity, optional cost cap. Throughput target ≥ 1 M cand/sec
      on a single core.
- [ ] A.2.2 Candidate generator
      `optimize/cascade/generators.py::cartesian(materials, cores,
      wires, N_range)` yielding `Candidate(core_id, material_id,
      wire_id, N, gap_mm)`. Lazy (no full materialisation in
      memory).
- [ ] A.2.3 Tests: regression on a manual spec where 9 cores are
      known infeasible due to window fit; assert Tier 0 drops
      exactly those.

### A.3 Tier 1 — Analytical evaluation (wraps existing sweep)

- [ ] A.3.1 `optimize/cascade/tier1.py::evaluate(model, candidate)
      -> Tier1Result` — calls `model.steady_state(...)` and
      packages the existing `DesignResult` into a `Tier1Result`
      row.
- [ ] A.3.2 `optimize/sweep.py::evaluate_design` becomes the
      reference implementation underneath; cascade calls it via
      the ConverterModel interface. No semantic regression in
      `OptimizeDialog`.
- [ ] A.3.3 Pruning policy: top-K by configurable objective.
      Default K = 1 000, objective = `total_loss`.

### A.4 RunStore — SQLite persistence

- [ ] A.4.1 `optimize/cascade/store.py::RunStore` with the schema
      from `design.md`. `runs` and `candidates` tables.
      Connection pool friendly to multi-process writers
      (WAL mode).
- [ ] A.4.2 Spec canonicalisation: `models/spec.py::Spec.
      canonical_hash()` for the `spec_hash` column.
- [ ] A.4.3 DB versioning: `data_loader.py::current_db_versions()`
      returns `{materials, cores, wires}` content hashes.
- [ ] A.4.4 Resume: orchestrator detects `status='running'` from a
      prior PID-tagged record and re-attaches.
- [ ] A.4.5 Tests: write 1 000 candidates, kill the process,
      restart, confirm zero re-evaluation and 1 000 rows present.

### A.5 Parallel orchestrator

- [ ] A.5.1 `optimize/cascade/orchestrator.py::CascadeOrchestrator`
      coordinates the tiers, owns the pool, owns the store.
- [ ] A.5.2 `multiprocessing.Pool` for tiers 0–1, with the model
      object pickled per worker. Use `concurrent.futures`
      interface.
- [ ] A.5.3 Cancellation: a `Cancel` event observed by workers
      between candidates; in-flight candidates are completed and
      written before exit. Response within 5 s.
- [ ] A.5.4 Pause / resume: orchestrator checkpoints after each
      tier; pause is "stop scheduling new work, drain in-flight,
      write".

### A.6 UI — Cascade page

- [ ] A.6.1 New sidebar entry routing to
      `ui/workspace/cascade_page.py`. Final label TBD with the
      user (working title: *Otimizador profundo*).
- [ ] A.6.2 Page layout: tier progress strip, top-N table, action
      bar (Cancel / Pause / Promote / Open in design view).
- [ ] A.6.3 Worker thread pulls from the RunStore at 1 Hz and
      refreshes the top-N table.
- [ ] A.6.4 Promote-to-T3 button enqueues a candidate at Tier 3
      regardless of analytical rank — for designs the engineer
      knows are special.
- [ ] A.6.5 Open-in-design-view: hydrates the main `Spec` +
      selected candidate into the existing dashboard.
- [ ] A.6.6 "Run deep sweep" button in the existing
      `OptimizeDialog` routes the current spec to the cascade
      page.
- [ ] A.6.7 Tests: launch a 100-candidate run on a stub spec,
      confirm the table populates and Cancel is responsive.

### A.7 Benchmark harness

- [ ] A.7.1 `scripts/cascade_benchmark.py` runs a fixed three-spec
      suite (one boost, one choke, one reactor) and records wall
      time per tier and final top-5 metrics.
- [ ] A.7.2 Document baseline numbers in
      `docs/cascade-benchmarks.md`. Phase B / C / D
      ship-readiness is gated on a write-up showing the new
      tier's uplift on this suite.

---

## Phase B — Tier 2 transient simulator

### B.1 Simulator core

- [ ] B.1.1 `simulate/integrator.py::simulate_to_steady_state(
      model, inductor, t_max, rel_tol, steady_state_window)
      -> Waveform`. Uses
      `scipy.integrate.solve_ivp(method="LSODA")` with adaptive
      step.
- [ ] B.1.2 Event detection: `model.event_functions()` provides
      crossings; the integrator refines the step at each event.
- [ ] B.1.3 Steady-state detection: peak comparison across the
      last `steady_state_window` cycles; converges within
      `rel_tol`.
- [ ] B.1.4 Tests: 1-state RL circuit with analytic step
      response; assert simulated peak within 0.5 % of closed
      form.

### B.2 NonlinearInductor

- [ ] B.2.1 `simulate/nonlinear_inductor.py::NonlinearInductor`
      with `L(i, T)` from rolloff + Steinmetz temperature
      correction. Cubic-spline interpolation of the rolloff
      curve.
- [ ] B.2.2 Tests: at low bias, `L = N² · AL` to within 0.1 %; at
      bias H = H_50%, `L` drops to 50 % ± 1 %.

### B.3 State-space models

- [ ] B.3.1 `topology/boost_ccm_model.py` — boost CCM
      `state_derivatives` and `event_functions` (PWM rising /
      falling).
- [ ] B.3.2 `topology/passive_choke_model.py` — passive choke
      sinusoidal-AC state-space with non-linear `L(i)`.
- [ ] B.3.3 `topology/line_reactor_model.py` — 1Ø and 3Ø reactor
      with diode bridge + DC-link cap.
- [ ] B.3.4 Tests per topology: simulated steady-state peak
      current matches analytical `I_pk` within 5 % for a feasible
      design.

### B.4 Tier 2 worker

- [ ] B.4.1 `optimize/cascade/tier2.py::evaluate(model, candidate,
      sim_config) -> Tier2Result` — runs `simulate_to_steady_state`
      and computes the loss envelope from the captured waveform.
- [ ] B.4.2 Saturation flag: any sample where
      `B(t) > Bsat · (1 − margin)` triggers
      `saturation_t2 = True`; the candidate is pruned regardless
      of rank.
- [ ] B.4.3 Pruning policy: top-K_3 by `loss_t2_W`. Default 50.
- [ ] B.4.4 Tests: a candidate that the analytical model says is
      feasible but is in fact saturating mid-cycle gets flagged
      (use a hand-picked design with `B_pk` near the limit).

### B.5 Benchmark gating

- [ ] B.5.1 Run the cascade benchmark suite; show that Tier 2
      catches at least one design class that the analytical model
      missed (e.g., gap-fringing-induced saturation, deep Litz
      proximity effect). Write up in `docs/cascade-benchmarks.md`.

---

## Phase C — Tier 3 batched FEA

### C.1 Batched FEA executor

- [ ] C.1.1 `fea/batched_runner.py::BatchedFEAExecutor` — single
      worker process, FIFO queue, ONELAB temp-dir isolation per
      run.
- [ ] C.1.2 `optimize/cascade/tier3.py::evaluate(model, candidate)
      -> Tier3Result` returning `L_t3_uH`, `Bpk_t3_T`,
      `solve_time_s`.
- [ ] C.1.3 Disagreement detection: compare T1 / T2 / T3
      inductance and flux; flag if max relative spread > 15 %.

### C.2 UI integration

- [ ] C.2.1 Tier 3 progress shown in the cascade page.
- [ ] C.2.2 Per-row badge in the top-N table: `aligned`, `T3
      disagrees`, `T3 failed` (mesh / solver error).

### C.3 Benchmark gating

- [ ] C.3.1 Show on the benchmark suite that Tier 3 corrects at
      least one design's ranking from the Tier 2 ordering.

---

## Phase D — Tier 4 transient FEA (opt-in only)

### D.1 Transient FEMMT

- [ ] D.1.1 `fea/transient_runner.py::run_transient(model,
      candidate, n_periods)` driving FEMMT's transient mode.
- [ ] D.1.2 Per-design wall-clock budget: 1 hour per candidate
      maximum, configurable.
- [ ] D.1.3 Output: full waveform + integrated losses.

### D.2 UI

- [ ] D.2.1 Tier 4 is opt-in: the "Run Tier 4 on top-5" button
      surfaces only after Tier 3 is done. Confirmation dialog
      with estimated wall time.
- [ ] D.2.2 Streaming output: per-period progress so the user
      can confirm the run hasn't hung.

### D.3 Benchmark gating

- [ ] D.3.1 Demonstrate one design where Tier 4 corrects a
      ranking decision from Tier 3 — or, equally informative,
      prove that on the benchmark suite the Tier 3 → Tier 4
      ranking is invariant and the tier is unnecessary for that
      class of designs (also a useful result, recorded in the
      benchmark doc).

---

## Cross-cutting

### X.1 Documentation

- [ ] X.1.1 `docs/cascade.md` — user-facing description, when to
      use, expected wall times per phase.
- [ ] X.1.2 README "What is supported today" matrix updated as
      each phase ships.
- [ ] X.1.3 `docs/POSITIONING.md` updated to note that the
      cascade is the higher-fidelity path; the fast `Optimizer`
      remains the daily driver.

### X.2 Telemetry

- [ ] X.2.1 Each cascade run logs a single line at completion:
      `run_id`, wall time per tier, candidates per tier,
      best-of-run total loss. Goes to
      `~/.local/share/pfc-inductor/cascade.log` (or the
      platformdirs equivalent).

### X.3 Migration

- [ ] X.3.1 `OptimizeDialog` stays as the fast path. The new
      "Run deep sweep" button at the bottom of `OptimizeDialog`
      routes to the cascade page with the current spec.
- [ ] X.3.2 No changes to the existing analytical pipeline;
      `evaluate_design` keeps its signature. Tests in
      `tests/test_optimize.py` remain green.
