# Cascade Optimization Capability

## ADDED Requirements

### Requirement: ConverterModel interface

The system SHALL provide a `ConverterModel` interface that any
topology implements to participate in the cascade pipeline. The
interface SHALL expose hooks for feasibility filtering, analytical
steady-state evaluation, transient state-space simulation,
post-processing waveforms into loss / temperature, and FEA
geometry hints.

#### Scenario: A new topology is added without changing cascade code

- **GIVEN** a developer implements `ConverterModel` for a buck-DCM
  converter and registers it in `topology/registry.py`
- **WHEN** the user opens the cascade page and selects "Buck (DCM)"
- **THEN** the cascade orchestrator runs all available tiers
  against the new topology with no changes to
  `optimize/cascade/`, `simulate/`, or `fea/` code

#### Scenario: A topology that has not yet implemented a higher tier

- **GIVEN** a topology adapter implementing only Tier 0–1 methods
  (Phase-A subset)
- **WHEN** the cascade is configured to run through Tier 2
- **THEN** Tiers 0–1 complete normally
- **AND** the orchestrator surfaces a clear message that this
  topology does not support Tier 2 yet, instead of crashing

### Requirement: Tier 0 — Feasibility filtering

The system SHALL filter candidate designs in Tier 0 using cheap
geometric and saturation-envelope checks (window fit, Bsat
margin, AL plausibility, optional cost cap), at a throughput of
at least 1 000 000 candidates per second on a single CPU core.

#### Scenario: Window-fit pruning

- **GIVEN** a Spec for a 1 500 W boost PFC and a wire whose copper
  area would require `N · A_wire > Ku_max · W_a` on a small
  toroid
- **WHEN** Tier 0 evaluates the candidate
- **THEN** the candidate is dropped before any analytical model
  runs

#### Scenario: Throughput

- **GIVEN** a candidate generator producing 10 000 000 candidates
- **WHEN** Tier 0 runs on a single CPU core
- **THEN** the run completes in under 10 seconds

### Requirement: Tier 1 — Analytical steady-state

The system SHALL evaluate Tier-0-feasible candidates with the
existing analytical pipeline (DC-bias rolloff, iGSE core loss,
Dowell AC copper loss, iterative thermal coupling) and rank the
survivors by a configurable objective.

#### Scenario: Tier 1 reproduces today's sweep

- **GIVEN** the same Spec and database used by today's
  `OptimizeDialog`
- **WHEN** the cascade runs Tiers 0–1 only
- **THEN** the top-10 designs match the `OptimizeDialog` top-10
  ordering with rank correlation greater than 0.99 (numerical
  noise excepted)

### Requirement: Tier 2 — Transient simulation

The system SHALL provide a transient ODE simulator that
integrates the converter's state-space with a non-linear
inductor model (L(i, T) from material rolloff and temperature)
and produces a steady-state waveform from which Tier 2 derives
transient-corrected loss and a saturation flag.

#### Scenario: Saturation caught that the analytical model missed

- **GIVEN** a candidate that Tier 1 marks feasible with
  `B_pk = 0.95 · Bsat` (no warning)
- **AND** whose true peak when simulated transiently exceeds
  `Bsat` due to gap fringing the analytical model does not
  capture
- **WHEN** Tier 2 evaluates the candidate
- **THEN** `saturation_t2` is True and the candidate is pruned
  from the top-N ranking

#### Scenario: Steady-state convergence

- **GIVEN** a feasible boost CCM design at 65 kHz
- **WHEN** Tier 2 simulates it
- **THEN** the integrator declares steady state within 5 line
  cycles
- **AND** the simulated peak current matches the analytical
  `I_pk` within 5 %

### Requirement: Tier 3 — Batched FEA validation

The system SHALL feed the Tier 2 top-50 designs to a batched
FEMMT magnetostatic runner and record the FEA-validated
inductance and peak flux density for each.

#### Scenario: Disagreement is surfaced

- **GIVEN** a candidate where Tier 1 and Tier 3 disagree on `L`
  by more than 15 %
- **WHEN** the cascade page renders the top-N table
- **THEN** the row shows a "T3 disagrees" warning badge
- **AND** the FEA number takes precedence in the displayed `L`

#### Scenario: Concurrent FEA runs do not collide

- **GIVEN** a Tier-3 batch of 50 candidates
- **WHEN** the executor runs them
- **THEN** at most one FEMMT process is active at any time
- **AND** no run fails due to ONELAB temp-directory contention

### Requirement: Tier 4 — Transient FEA (opt-in)

The system SHALL offer transient-FEA evaluation of the Tier-3
top-5 designs as an explicit user-confirmed action, given that
the operation can take more than one hour per candidate.

#### Scenario: User opts in to Tier 4

- **GIVEN** a completed cascade run with Tier 3 done
- **WHEN** the user clicks "Run Tier 4 on top-5"
- **AND** confirms the wall-time estimate dialog
- **THEN** Tier 4 runs sequentially on the top-5 candidates and
  writes results to the run store

#### Scenario: User does not opt in

- **GIVEN** a completed cascade run with Tier 3 done
- **WHEN** the user does not click the Tier 4 button
- **THEN** the cascade run completes successfully and the top-5
  rows show `L_t4_uH = NULL` with no warning

### Requirement: Persistent run store

The system SHALL persist every cascade run and every candidate's
tier metrics to a local SQLite database, recording the spec
hash, database content versions, tier configuration, and
per-candidate results. Runs SHALL be resumable after a crash
with no candidate re-evaluation.

#### Scenario: Resume after crash

- **GIVEN** a cascade run that has evaluated 50 000 of 200 000
  candidates and is then killed
- **WHEN** the user reopens the application and resumes the run
- **THEN** the orchestrator skips the 50 000 already in the
  store and continues from candidate 50 001 with no semantic
  difference from an uninterrupted run

#### Scenario: Spec hash mismatch refuses resume

- **GIVEN** a cascade run started against Spec A
- **WHEN** the user changes any field of Spec A and tries to
  resume
- **THEN** the orchestrator refuses to resume
- **AND** the user is offered the option to start a new run
  instead

### Requirement: Parallel execution

The system SHALL execute Tiers 0–2 in parallel across all
available CPU cores using a process pool. Tiers 3 and 4 SHALL
execute through a single FEA worker process to avoid ONELAB
temp-directory collisions.

#### Scenario: Pool sizing

- **GIVEN** an 8-core workstation
- **WHEN** the cascade orchestrator starts
- **THEN** Tiers 0–2 use a pool of 8 worker processes by default
- **AND** Tiers 3–4 use exactly 1 worker process

### Requirement: Live cascade UI

The system SHALL render a dedicated workspace page that shows
per-tier progress, a live-updating top-N table, and controls for
cancellation, pausing, promoting a candidate to a higher tier,
and opening a candidate in the standard design view.

#### Scenario: Live top-N updates

- **GIVEN** a cascade run in progress at Tier 1
- **WHEN** Tier 1 completes a new candidate that ranks better
  than the current top-10
- **THEN** the top-N table reflects the new ranking within 2
  seconds without user interaction

#### Scenario: Promote candidate to FEA

- **GIVEN** a candidate at the cascade page that has reached only
  Tier 1
- **WHEN** the user selects the row and clicks "Promote to Tier 3"
- **THEN** that single candidate is enqueued at Tier 3 regardless
  of its analytical rank
- **AND** its FEA result joins the row when complete

### Requirement: Cancellation

The system SHALL respond to a cancellation request within 5
seconds of the click, completing in-flight candidates and
writing them to the store before exit.

#### Scenario: Cancel mid-Tier 2

- **GIVEN** a cascade run actively executing Tier 2 across 8
  workers
- **WHEN** the user clicks "Cancel"
- **THEN** within 5 seconds, all 8 workers complete their
  current candidate and stop scheduling new ones
- **AND** the run is marked `status='cancelled'` in the store
- **AND** all completed candidates remain queryable

### Requirement: Reproducibility

The system SHALL associate every cascade run with a hash of the
Spec and content hashes of the materials, cores, and wires
databases, such that two runs with identical hashes are
guaranteed to produce identical top-N orderings (numerical noise
aside).

#### Scenario: Reproducible top-N

- **GIVEN** a cascade run completed with hashes
  (H_spec, H_mat, H_core, H_wire)
- **WHEN** the run is repeated with the same hashes on the same
  machine
- **THEN** the top-100 candidates appear in identical order
- **AND** per-row metrics agree with the first run within 0.1 %
  for each tier

### Requirement: Non-disruptive rollout

The cascade pipeline SHALL ship without breaking the existing
fast-path optimizer. The current `OptimizeDialog` SHALL keep its
public behaviour and `optimize/sweep.py::evaluate_design` SHALL
keep its signature so that all current `tests/test_optimize.py`
cases pass unchanged.

#### Scenario: Existing optimizer regression

- **GIVEN** the test suite at the commit that introduces Phase A
- **WHEN** `pytest tests/test_optimize.py` is run
- **THEN** every test passes without modification
