# Tasks — add-buck-ccm-topology

Phased implementation. Each phase is independently shippable
(domain code → engine wiring → UI → reports → polish), so the
change can land in 4–5 PRs instead of one mega-merge.

## Phase 1 — Pure domain (no UI)

- [ ] `pfc_inductor/topology/buck_ccm.py` (new):
  - [ ] ``output_current_A(spec)``
  - [ ] ``required_inductance_uH(spec, ripple_ratio=0.30)``
  - [ ] ``ripple_pp_at_Vin(spec, L_uH, Vin)``
  - [ ] ``peak_inductor_current_A(spec, L_uH)``
  - [ ] ``rms_inductor_current_A(spec, L_uH)``
  - [ ] ``duty_cycle(spec, Vin)``
  - [ ] ``ccm_dcm_boundary_A(spec, L_uH)``
  - [ ] ``waveforms(spec, L_uH, n_periods=5, n_points=600)``
        — returns ``{t_s, iL_A, I_pk_A, I_rms_A, D}``.
  - [ ] ``estimate_thd_pct(spec)`` — returns ``0.0`` for buck (DC
        output; THD on the input line is undefined). The Análise
        card already handles ``thd_estimate_pct == 0`` gracefully.
- [ ] `pfc_inductor/topology/__init__.py` — re-export.
- [ ] `pfc_inductor/models/spec.py`:
  - [ ] Extend ``Topology`` Literal to include ``"buck_ccm"``.
  - [ ] Add ``Vin_dc_V``, ``Vin_dc_min_V``, ``Vin_dc_max_V`` fields.
  - [ ] Add ``ripple_ratio`` field (default 0.30).
  - [ ] ``model_validator(mode="before")`` migrates legacy specs
        (``Vin_dc_V`` falls back to ``Vin_nom_Vrms`` for back-compat).
- [ ] `tests/test_topology_buck_ccm.py` (new) — Erickson-textbook
      benchmarks listed in `design.md` § Tests > Unit.

## Phase 2 — Engine + cascade integration

- [ ] `pfc_inductor/topology/buck_ccm_model.py` (new) — implements
      ``ConverterModel``: ``feasibility_envelope``, ``steady_state``,
      ``state_derivatives``, ``initial_state``.
- [ ] `pfc_inductor/topology/registry.py` — register
      ``"buck_ccm"`` → ``BuckCCMModel``.
- [ ] `pfc_inductor/optimize/feasibility.py`:
  - [ ] ``N_HARD_CAP_BY_TOPOLOGY["buck_ccm"] = 200``.
  - [ ] ``required_L_uH`` and ``peak_current_A`` dispatch.
- [ ] `pfc_inductor/design/engine.py`:
  - [ ] Branch on ``spec.topology == "buck_ccm"`` for
        L_required and Ipk computation.
  - [ ] Skip the bridge-loss math (no rectifier in buck).
  - [ ] Use ``buck_ccm.estimate_thd_pct`` (returns 0).
  - [ ] Populate ``waveform_iL_A`` from
        ``buck_ccm.waveforms()`` (5 switching periods, no line
        envelope).
  - [ ] Set ``pct_impedance_actual = None`` (n/a for DC-DC).
- [ ] `tests/test_buck_ccm_model.py` (new) — Tier-0/1/2 cascade.
- [ ] `tests/test_design_engine.py` — extend with the textbook
      benchmark (Vin=12, Vout=3.3, Iout=5, fsw=500k).

## Phase 3 — UI

- [ ] `pfc_inductor/ui/dialogs/topology_picker.py`:
  - [ ] Add ``("buck_ccm", "Buck CCM (sync DC-DC)", None,
        "DC-DC step-down…")`` to ``_OPTIONS``.
  - [ ] Bump grid layout from 2×2 to 3×2 (cards now 5 → 6 future-
        proofed slots).
- [ ] `pfc_inductor/ui/widgets/schematic.py`:
  - [ ] ``_render_buck_ccm(painter, accent, neutral, glow)``
        — Vin source, Q1 high-side, freewheel diode, L
        (highlighted), Cout, Rload, gnd rail.
  - [ ] Register in ``_TOPOLOGY_RENDERERS``.
  - [ ] ``topology_picker_choices()`` returns 5 entries now.
- [ ] `pfc_inductor/ui/spec_panel.py`:
  - [ ] ``_apply_topology_visibility`` hides ``Vin_min/max/nom_Vrms``
        and ``f_line_Hz`` for buck; shows ``Vin_dc_V`` /
        ``Vin_dc_min/max_V`` / ``ripple_ratio``.
  - [ ] Add the new spinboxes to ``_build_input_box`` /
        ``_build_converter_box``.
- [ ] `pfc_inductor/simulate/realistic_waveforms.py`:
  - [ ] ``_buck_ccm(spec, result, n_samples)`` — synthesise iL
        with the proper triangle ripple (5 switching periods).
  - [ ] Wire into ``synthesize_il_waveform`` dispatch.
  - [ ] Update ``RealisticWaveform.label`` template:
        ``"Buck CCM @ Vin={…}, D={…}, ΔI_pp={…}"``.
- [ ] `pfc_inductor/ui/dashboard/cards/formas_onda_card.py`:
  - [ ] Source-voltage subplot becomes ``v_sw(t)`` (PWM square
        wave) for buck.
  - [ ] Spectrum's natural fundamental is ``f_sw`` (not
        ``2·f_line``) — pass through ``RealisticWaveform.fundamental_Hz``
        which the synthesiser already populates.
- [ ] `tests/test_realistic_waveforms.py` — extend the
      "every topology" test to include ``buck_ccm``.
- [ ] `tests/test_topology_picker.py` — picker has 5 options.

## Phase 4 — Reports

- [ ] `pfc_inductor/report/datasheet.py`:
  - [ ] ``_waveform_plot`` topology branch for buck (no envelope;
        zoom to switching cycles).
  - [ ] Replace the harmonic-spectrum plot with an
        output-voltage-ripple plot for buck:
        ``Vout_ripple_pp = ΔI_pp / (8·Cout·f_sw)``.
  - [ ] Topology-aware spec-rows: "Vin DC", "Iout", "Duty cycle"
        instead of "Vin RMS", "I_line_rms", "%Z".
- [ ] `pfc_inductor/report/html_report.py` — equivalent edits.
- [ ] `pfc_inductor/report/views_3d.py` — buck inductors are often
      drum-core / shielded-toroid; shape decoder reuses the
      existing toroide path. Verify the 4-view rendering doesn't
      regress for those parts.
- [ ] `pfc_inductor/standards/compliance_report.py` (or wherever
      the compliance PDF generator lives): emit "Not applicable
      for DC-input topology" for the IEC 61000-3-2 / 3-12 / IEEE
      519 sections when ``spec.topology == "buck_ccm"``.

## Phase 5 — Optimizer + selection

- [ ] `pfc_inductor/optimize/scoring.py`:
  - [ ] Buck-tuned score weights (Cu loss > core loss because
        ripple is small).
  - [ ] ``rank_cores`` filters by ``peak_current_A`` from buck
        formula, not the AC formula.
- [ ] `pfc_inductor/optimize/feasibility.py::viable_wires_for_spec`
  - [ ] Existing ``rated_current_A(spec)`` already routes through
        topology; extend it to return ``output_current_A(spec)``
        for buck.
- [ ] `pfc_inductor/ui/dashboard/cards/nucleo_card.py` — verify
      the Núcleo selection table renders buck-compatible cores
      (most ferrite + some powder cores work).

## Phase 6 — Docs + examples

- [ ] `docs/POSITIONING.md` — add buck row to the topology matrix.
- [ ] `README.md` — Topologies table screenshot refresh.
- [ ] `docs/UI.md` — note the spec-panel field-visibility rules
      for DC vs AC topologies.
- [ ] `examples/buck_5V_3A.pfc` (new) — bundled example for the
      CLI tutorial.
- [ ] `tests/test_cli_design.py` — CLI smoke test on the new
      example file.

## Phase 7 — Cross-cutting verification

- [ ] Run the full pytest suite — confirm no regression on the
      existing 4 topologies (3 boost-CCM + passive_choke +
      line_reactor 1φ + 3φ).
- [ ] Visual review: render the Análise tab in light + dark for
      a buck design; spot-check the schematic, the waveform plot,
      the FFT bars, the THD tile (should read "—" or 0 since
      DC), the BH-loop card.
- [ ] Cross-platform smoke: launch on Mac and Windows (Fusion
      style); confirm no rendering drift on the new picker grid.
- [ ] Compile the HTML datasheet for a buck design end-to-end;
      open in a browser and verify section 3 layout.
