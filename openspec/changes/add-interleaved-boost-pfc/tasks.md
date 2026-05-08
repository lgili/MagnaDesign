# Tasks — add-interleaved-boost-pfc

This is the smallest of the 5 topology changes because it leans
heavily on the existing ``boost_ccm`` math — most of the work is
plumbing. **Depends on the multi-inductor wrapper from the LCL
change** (Phase 0 of `add-lcl-grid-tie-filter`); list it as a
dependency in the change's metadata.

## Phase 0 — Dependency

- [ ] Land the multi-inductor wrapper from
      `add-lcl-grid-tie-filter/tasks.md` § Phase 0 first, OR
      ship a minimal version of it here:
  - [ ] ``MultiInductorDesignResult`` with role-keyed inductors.
  - [ ] ``ConverterModel.inductor_roles() → list[str]``.
  - [ ] Engine ``design_multi`` entry point.

## Phase 1 — Domain physics

- [ ] `pfc_inductor/topology/interleaved_boost_pfc.py` (new):
  - [ ] ``per_phase_spec(spec)``.
  - [ ] ``required_inductance_uH(spec, Vin_Vrms)`` —
        delegates to ``boost_ccm`` after per-phase scaling.
  - [ ] ``line_peak_current_A`` and ``line_rms_current_A`` —
        per-phase delegations.
  - [ ] ``aggregate_input_ripple_pp(per_phase_pp, D, N)`` —
        Hwu-Yau closed form.
  - [ ] ``effective_input_ripple_frequency_Hz(f_sw_kHz, N)``.
  - [ ] ``estimate_thd_pct(spec)`` — boost-CCM value / √N.
- [ ] `pfc_inductor/models/spec.py`:
  - [ ] Topology Literal extended.
  - [ ] ``n_interleave: Literal[2, 3] = 2``.
  - [ ] Validator: ``n_interleave`` is required iff topology
        is ``"interleaved_boost_pfc"``.
- [ ] `tests/test_topology_interleaved_boost_pfc.py` (new):
  - [ ] ``test_per_phase_scales_pout``.
  - [ ] ``test_aggregate_ripple_cancels_at_natural_nulls``.
  - [ ] ``test_aggregate_ripple_at_worst_case``.
  - [ ] ``test_estimate_thd_better_than_single_phase``.

## Phase 2 — Engine + cascade

- [ ] `pfc_inductor/topology/interleaved_boost_pfc_model.py` (new):
  - [ ] ``inductor_roles()`` returns N entries.
  - [ ] ``feasibility_envelope`` runs boost-CCM check on per-
        phase spec.
  - [ ] ``steady_state`` runs boost-CCM design once and
        replicates into ``MultiInductorDesignResult``.
- [ ] `pfc_inductor/topology/registry.py` — register.
- [ ] `pfc_inductor/optimize/feasibility.py`:
  - [ ] ``N_HARD_CAP_BY_TOPOLOGY["interleaved_boost_pfc"] = 250``
        (per phase, same as single-phase boost).
  - [ ] ``required_L_uH``, ``peak_current_A`` dispatch via
        ``per_phase_spec``.
- [ ] `pfc_inductor/design/engine.py`:
  - [ ] Interleaved branch: build per-phase spec, run boost-CCM,
        replicate into multi-inductor result.
  - [ ] Compute aggregate ripple over a line cycle (sweep D).
  - [ ] Compute aggregate THD via the topology helper.
  - [ ] Compute manufacturing-tolerance imbalance warning.
  - [ ] Set ``aggregate.P_total = N · P_per_phase``.
- [ ] `tests/test_interleaved_boost_pfc_model.py` (new) — Tier 0/1/2.
- [ ] `tests/test_design_engine.py` — extend with 3 kW 2-phase
      benchmark.

## Phase 3 — UI

- [ ] `pfc_inductor/ui/dialogs/topology_picker.py`:
  - [ ] Add "Interleaved Boost PFC (2φ / 3φ)" card.
- [ ] `pfc_inductor/ui/widgets/schematic.py`:
  - [ ] ``_render_interleaved_boost_pfc`` with N parallel
        channels.
  - [ ] Register in ``_TOPOLOGY_RENDERERS``.
  - [ ] N=2 layout uses 2-channel diamond; N=3 uses 3-channel
        radial.
- [ ] `pfc_inductor/ui/spec_panel.py`:
  - [ ] Add ``n_interleave`` field (radio: 2 / 3) when
        topology is interleaved.
- [ ] `pfc_inductor/simulate/realistic_waveforms.py`:
  - [ ] ``_interleaved_boost_pfc`` synth: N per-phase iL traces
        at 360°/N offset + the summed input current.
  - [ ] Returns a multi-inductor waveform bundle.
- [ ] `pfc_inductor/ui/dashboard/cards/formas_onda_card.py`:
  - [ ] Top axis stacks N + 1 traces (per-phase + aggregate).
  - [ ] Bottom subplot's harmonic spectrum is of the
        **aggregate** current — the reduced PWM-band peak is
        the topology's signature.
- [ ] `pfc_inductor/ui/widgets/resumo_strip.py`:
  - [ ] Add a "Phases" KPI tile reading "× 2 (interleaved)" or
        "× 3 (interleaved)" so the user is reminded the design
        is per-phase.
- [ ] `pfc_inductor/ui/workspace/nucleo_selection_page.py`:
  - [ ] Show "× N" badge on the selected core for interleaved
        topologies.
- [ ] `tests/test_realistic_waveforms.py` — extend.
- [ ] `tests/test_topology_picker.py` — picker has 8 options now.

## Phase 4 — Reports

- [ ] `pfc_inductor/report/datasheet.py`:
  - [ ] Header explains "Per-phase design (× N identical units)".
  - [ ] Spec rows include ``n_interleave``, ``Per-phase Pout``.
  - [ ] Operating-point rows include both per-phase and
        aggregate columns (P, T_rise, etc.).
  - [ ] BOM lists the inductor with ``Quantity = N``.
  - [ ] **New plot**: input-current cancellation chart (per-
        phase iL + aggregate input + dashed single-phase
        reference).
- [ ] `pfc_inductor/report/html_report.py` — equivalent.
- [ ] `pfc_inductor/standards/compliance_report.py`:
  - [ ] Aggregate input current evaluated against IEC 61000-3-2
        / 3-12 / IEEE 519 (instead of per-phase).

## Phase 5 — Optimizer + selection

- [ ] `pfc_inductor/optimize/cascade/generators.py`:
  - [ ] Cartesian routes through ``per_phase_spec`` so the
        candidate enumeration sees the per-phase Pout.
- [ ] `pfc_inductor/optimize/scoring.py`:
  - [ ] Tweak weights: aggregate Pout is the same as
        single-phase, but the per-phase smaller core gets a
        size-scoring boost.

## Phase 6 — Docs + examples

- [ ] `docs/POSITIONING.md` — interleaved row.
- [ ] `README.md` — Topologies table.
- [ ] `docs/topology-interleaved-boost-pfc.md` (new) — design
      method + ripple-cancellation explanation +
      current-sharing matching guidance.
- [ ] `docs/UI.md` — interleaved-specific UI notes.
- [ ] `examples/interleaved_3kW_2phase.pfc` (new).

## Phase 7 — Cross-cutting verification

- [ ] Full pytest suite — no regression.
- [ ] Visual review per topology (light + dark).
- [ ] Render the HTML datasheet for a 3 kW 2-phase design;
      verify the BOM lists "Quantity = 2" for the inductor.
- [ ] Verify the cancellation chart visually matches the
      analytical ripple at D = 0.25 (worst case for N=2).
- [ ] Cross-platform smoke (Mac, Win, Linux Fusion).
