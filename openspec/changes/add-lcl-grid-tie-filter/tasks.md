# Tasks — add-lcl-grid-tie-filter

LCL is the most complex of the 5 new topologies because it's the
first to need the multi-inductor architecture. Phase 1 is the
domain math; Phase 2 is the architectural change (multi-inductor
wrapper); Phases 3-7 mirror the other topology proposals.

## Phase 0 — Architecture: multi-inductor wrapper

**This is shared infrastructure that flyback also needs**, so
it's worth shipping cleanly even before the topology-specific
work starts.

- [ ] `pfc_inductor/models/result.py`:
  - [ ] New ``MultiInductorDesignResult`` dataclass with
        ``inductors: dict[str, DesignResult]``, ``aggregate:
        AggregateMetrics``, and back-compat property accessors
        that forward to the "primary" inductor.
- [ ] `pfc_inductor/design/engine.py`:
  - [ ] New ``design_multi(spec, cores, wires, materials)``
        entry point; ``cores`` etc. are dicts keyed by role.
  - [ ] Existing ``design()`` unchanged.
- [ ] `pfc_inductor/topology/protocol.py`:
  - [ ] Extend ``ConverterModel`` Protocol with optional
        ``inductor_roles() → list[str]`` (defaults to
        ``["primary"]`` so existing topologies don't change).
- [ ] `tests/test_multi_inductor_wrapper.py` (new) — back-compat
      forwards work; multi-inductor result equality.

## Phase 1 — Domain physics

- [ ] `pfc_inductor/topology/lcl_grid_tie.py` (new):
  - [ ] ``required_inverter_inductance_uH(spec)``.
  - [ ] ``required_filter_capacitance_uF(spec)``.
  - [ ] ``required_grid_inductance_uH(spec, L_inv_uH)``.
  - [ ] ``resonance_frequency_Hz(L_inv_uH, L_grid_uH, C_uF)``.
  - [ ] ``passive_damping_resistor_ohm(spec, C_uF, f_res_Hz)``.
  - [ ] ``filter_transfer_function(...)``.
  - [ ] ``predict_grid_thd_pct(...)`` — analytical PWM harmonic
        content × LCL transfer function.
  - [ ] ``estimate_thd_pct(spec, result)``.
- [ ] `pfc_inductor/physics/pwm_harmonics.py` (new) — Holmes-Lipo
      analytical Bessel-function expansion for SPWM and SVPWM.
      Returns ``dict[int, float]`` (harmonic index → magnitude
      in fraction of fundamental).
- [ ] `pfc_inductor/models/spec.py`:
  - [ ] Topology Literal extended.
  - [ ] ``f_grid_Hz``, ``V_grid_Vrms``, ``Vdc_V``, ``modulation``,
        ``target_thd_pct``, ``target_ripple_pct_inv``,
        ``splitting_ratio``, ``damping``, ``max_reactive_pct``.
- [ ] `tests/test_topology_lcl_grid_tie.py` (new) — Enphase IQ8
      and NREL 30 kW benchmarks.

## Phase 2 — Engine + cascade

- [ ] `pfc_inductor/topology/lcl_model.py` (new) — implements
      ``ConverterModel`` with ``inductor_roles() → ["L_inv",
      "L_grid"]``.
- [ ] `pfc_inductor/topology/registry.py` — register.
- [ ] `pfc_inductor/optimize/feasibility.py`:
  - [ ] ``N_HARD_CAP_BY_TOPOLOGY["lcl_grid_tie"] = 100`` per
        inductor.
  - [ ] Per-inductor required L dispatch.
- [ ] `pfc_inductor/design/engine.py`:
  - [ ] LCL branch dispatches via ``design_multi`` returning
        ``MultiInductorDesignResult``.
  - [ ] Compute resonance-frequency placement; warn if outside
        band.
  - [ ] Compute predicted grid-current THD.
- [ ] `tests/test_lcl_model.py` — Tier 0/1/2 cascade.

## Phase 3 — UI

- [ ] `pfc_inductor/ui/dialogs/topology_picker.py`:
  - [ ] Add LCL card.
- [ ] `pfc_inductor/ui/widgets/schematic.py`:
  - [ ] ``_render_lcl_grid_tie`` (system diagram with inverter +
        L_inv + C + L_grid + grid; both inductors highlighted).
- [ ] `pfc_inductor/ui/spec_panel.py`:
  - [ ] Show inverter / grid fields for LCL; hide PFC fields.
- [ ] `pfc_inductor/simulate/realistic_waveforms.py`:
  - [ ] ``_lcl_grid_tie`` synth: inverter-side iL with PWM
        ripple at f_sw, grid-side mostly-sine at f_grid.
  - [ ] Returns multi-inductor waveform bundle.
- [ ] `pfc_inductor/ui/dashboard/cards/formas_onda_card.py`:
  - [ ] LCL: top axis stacks i_inv + i_grid (different scales);
        middle axis shows v_grid; bottom axis is a **Bode plot**
        of ``H_LCL(f)`` (replacing the harmonic-spectrum bar
        chart).
- [ ] `pfc_inductor/ui/dashboard/cards/bh_loop_card.py`:
  - [ ] Renders 2 BH loops side-by-side (one per inductor) in
        the multi-inductor case.
- [ ] `pfc_inductor/ui/workspace/nucleo_selection_page.py`:
  - [ ] Two stacked Núcleo selection tables (one per inductor)
        when ``inductor_roles()`` returns more than one role.
- [ ] `pfc_inductor/ui/workspace/analise_page.py`:
  - [ ] When the design is multi-inductor, show all magnetic
        cards in a tabbed view (one tab per inductor).
- [ ] `tests/test_realistic_waveforms.py` — extend.
- [ ] `tests/test_topology_picker.py` — picker has 7 options now.

## Phase 4 — Standards

- [ ] `pfc_inductor/standards/ieee_1547.py` (new) — Table 4 limits.
- [ ] `pfc_inductor/standards/iec_61727.py` (new) — equivalent.
- [ ] `pfc_inductor/standards/iec_62109.py` (new) — checklist.
- [ ] `tests/test_standards_ieee_1547.py` (new).
- [ ] `tests/test_standards_iec_61727.py` (new).

## Phase 5 — Reports

- [ ] `pfc_inductor/report/datasheet.py`:
  - [ ] BOM expands per-phase × per-inductor.
  - [ ] New "Filter transfer function" section (Bode plot).
  - [ ] New compliance page (page 4) with per-harmonic
        prediction vs IEEE 1547 / IEC 61727 limits.
- [ ] `pfc_inductor/report/html_report.py` — equivalent.
- [ ] `pfc_inductor/standards/compliance_report.py`:
  - [ ] IEEE 1547 + IEC 61727 + IEC 62109 sections wired to
        the LCL design's predictions.

## Phase 6 — Optimizer + selection

- [ ] `pfc_inductor/optimize/cascade/generators.py`:
  - [ ] Generator for multi-inductor designs (yields one
        ``Candidate`` per inductor role).
  - [ ] Cartesian over (mat × core × wire) per role.
- [ ] `pfc_inductor/optimize/cascade/orchestrator.py`:
  - [ ] Tier 0/1 evaluators handle multi-inductor candidates.
- [ ] `pfc_inductor/optimize/scoring.py`:
  - [ ] LCL-tuned weights; aggregate scores across the two
        inductors.

## Phase 7 — Catalogs

- [ ] Verify the existing material database covers the iron-
      powder cores commonly used for LCL grid-side inductors.
      No catalog import expected.
- [ ] Future: add Metglas amorphous metal materials (separate
      change).

## Phase 8 — Docs + examples

- [ ] `docs/POSITIONING.md` — LCL row.
- [ ] `README.md` — Topologies table.
- [ ] `docs/topology-lcl-grid-tie.md` (new) — design method
      writeup, IEEE 1547 / IEC 61727 references, worked example.
- [ ] `docs/UI.md` — multi-inductor UI rules.
- [ ] `examples/lcl_30kW_3ph.pfc` (new).

## Phase 9 — Cross-cutting verification

- [ ] Full pytest suite — no regression on the existing 4
      topologies + buck-CCM + flyback (assuming those land
      first).
- [ ] Visual review per topology.
- [ ] Render the HTML datasheet for an LCL design end-to-end;
      verify the BOM has 6 magnetic-component rows for a 3-φ
      30 kW spec.
- [ ] Compliance report PDF generates IEEE 1547 / IEC 61727
      sections with per-harmonic predictions.
- [ ] Cross-platform smoke (Mac, Win, Linux Fusion).

## Feature flag

- [ ] Gate the entire LCL topology behind
      ``MAGNADESIGN_ENABLE_LCL=1`` env var until at least two
      real-world designs validate the predictions. Promote to
      always-on in v0.2.
