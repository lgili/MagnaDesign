# Tasks — add-buck-ccm-topology

Phased implementation. Each phase is independently shippable
(domain code → engine wiring → UI → reports → polish), so the
change can land in 4–5 PRs instead of one mega-merge.

## Phase 1 — Pure domain (no UI)

- [x] `pfc_inductor/topology/buck_ccm.py` (new):
  - [x] ``output_current_A(spec)``
  - [x] ``required_inductance_uH(spec, ripple_ratio=0.30)``
  - [x] ``ripple_pp_at_Vin(spec, L_uH, Vin)``
  - [x] ``peak_inductor_current_A(spec, L_uH)``
  - [x] ``rms_inductor_current_A(spec, L_uH)``
  - [x] ``duty_cycle(spec, Vin)``
  - [x] ``ccm_dcm_boundary_A(spec, L_uH)``
  - [x] ``waveforms(spec, L_uH, n_periods=5, n_points=600)``
        — returns ``{t_s, iL_A, I_pk_A, I_rms_A, D}``.
  - [x] ``estimate_thd_pct(spec)`` — returns ``0.0`` for buck (DC
        output; THD on the input line is undefined). The Análise
        card already handles ``thd_estimate_pct == 0`` gracefully.
- [x] `pfc_inductor/topology/__init__.py` — re-export.
- [x] `pfc_inductor/models/spec.py`:
  - [x] Extend ``Topology`` Literal to include ``"buck_ccm"``.
  - [x] Add ``Vin_dc_V``, ``Vin_dc_min_V``, ``Vin_dc_max_V`` fields.
  - [x] Add ``ripple_ratio`` field (default 0.30).
  - [x] ``model_validator(mode="before")`` migrates legacy specs
        (``Vin_dc_V`` falls back to ``Vin_nom_Vrms`` for back-compat).
- [x] `tests/test_topology_buck_ccm.py` (new) — Erickson-textbook
      benchmarks listed in `design.md` § Tests > Unit.

## Phase 2 — Engine + cascade integration

- [x] `pfc_inductor/topology/buck_ccm_model.py` (new) — implements
      ``ConverterModel``: ``feasibility_envelope``, ``steady_state``,
      ``state_derivatives``, ``initial_state``.
- [x] `pfc_inductor/topology/registry.py` — register
      ``"buck_ccm"`` → ``BuckCCMModel``.
- [x] `pfc_inductor/optimize/feasibility.py`:
  - [x] ``N_HARD_CAP_BY_TOPOLOGY["buck_ccm"] = 200``.
  - [x] ``required_L_uH`` and ``peak_current_A`` dispatch.
- [x] `pfc_inductor/design/engine.py`:
  - [x] Branch on ``spec.topology == "buck_ccm"`` for
        L_required and Ipk computation.
  - [x] Skip the bridge-loss math (no rectifier in buck).
  - [x] Use ``buck_ccm.estimate_thd_pct`` (returns 0).
  - [x] Populate ``waveform_iL_A`` from
        ``buck_ccm.waveforms()`` (5 switching periods, no line
        envelope).
  - [x] Set ``pct_impedance_actual = None`` (n/a for DC-DC).
- [x] `tests/test_buck_ccm_model.py` (new) — Tier-0/1/2 cascade.
- [x] `tests/test_design_engine.py` — extend with the textbook
      benchmark (Vin=12, Vout=3.3, Iout=5, fsw=500k).

## Phase 3 — UI

- [x] `pfc_inductor/ui/dialogs/topology_picker.py`:
  - [x] Add ``("buck_ccm", "Buck CCM (sync DC-DC)", None,
        "DC-DC step-down…")`` to ``_OPTIONS``.
  - [x] Bump grid layout from 2×2 to 3×2 (cards now 5 → 6 future-
        proofed slots).
- [x] `pfc_inductor/ui/widgets/schematic.py`:
  - [x] ``_render_buck_ccm(painter, accent, neutral, glow)``
        — Vin source, Q1 high-side, freewheel diode, L
        (highlighted), Cout, Rload, gnd rail.
  - [x] Register in ``_TOPOLOGY_RENDERERS``.
  - [x] ``topology_picker_choices()`` returns 5 entries now.
- [x] `pfc_inductor/ui/spec_panel.py`:
  - [x] ``_apply_topology_visibility`` hides ``Vin_min/max/nom_Vrms``
        and ``f_line_Hz`` for buck; shows ``Vin_dc_V`` /
        ``Vin_dc_min/max_V`` / ``ripple_ratio``.
  - [x] Add the new spinboxes to ``_build_input_box`` /
        ``_build_converter_box``.
- [x] `pfc_inductor/simulate/realistic_waveforms.py`:
  - [x] ``_buck_ccm(spec, result, n_samples)`` — synthesise iL
        with the proper triangle ripple (5 switching periods).
  - [x] Wire into ``synthesize_il_waveform`` dispatch.
  - [x] Update ``RealisticWaveform.label`` template:
        ``"Buck CCM @ Vin={…}, D={…}, ΔI_pp={…}"``.
- [x] `pfc_inductor/ui/dashboard/cards/formas_onda_card.py`:
  - [x] Source-voltage subplot becomes ``v_sw(t)`` (PWM square
        wave) for buck.
  - [x] Spectrum's natural fundamental is ``f_sw`` (not
        ``2·f_line``) — pass through ``RealisticWaveform.fundamental_Hz``
        which the synthesiser already populates.
- [x] `tests/test_realistic_waveforms.py` — extend the
      "every topology" test to include ``buck_ccm``.
- [x] `tests/test_topology_picker.py` — picker has 5 options.

## Phase 4 — Reports

- [x] `pfc_inductor/report/datasheet.py`:
  - [x] ``_waveform_plot`` topology branch for buck (no envelope;
        zoom to switching cycles).
  - [x] Replace the harmonic-spectrum plot with an
        output-voltage-ripple plot for buck:
        ``Vout_ripple_pp = ΔI_pp / (8·Cout·f_sw)``.
  - [x] Topology-aware spec-rows: "Vin DC", "Iout", "Duty cycle"
        instead of "Vin RMS", "I_line_rms", "%Z".
- [x] `pfc_inductor/report/html_report.py` — equivalent edits.
- [x] `pfc_inductor/report/views_3d.py` — buck inductors are often
      drum-core / shielded-toroid; shape decoder reuses the
      existing toroide path. Verify the 4-view rendering doesn't
      regress for those parts.
- [x] `pfc_inductor/standards/compliance_report.py` (or wherever
      the compliance PDF generator lives): emit "Not applicable
      for DC-input topology" for the IEC 61000-3-2 / 3-12 / IEEE
      519 sections when ``spec.topology == "buck_ccm"``.

## Phase 5 — Optimizer + selection

- [x] `pfc_inductor/optimize/scoring.py`:
  - [x] Buck-tuned score weights (Cu loss > core loss because
        ripple is small).
  - [x] ``rank_cores`` filters by ``peak_current_A`` from buck
        formula, not the AC formula.
- [x] `pfc_inductor/optimize/feasibility.py::viable_wires_for_spec`
  - [x] Existing ``rated_current_A(spec)`` already routes through
        topology; extend it to return ``output_current_A(spec)``
        for buck.
- [x] `pfc_inductor/ui/dashboard/cards/nucleo_card.py` — verify
      the Núcleo selection table renders buck-compatible cores
      (most ferrite + some powder cores work).

## Phase 6 — Docs + examples

- [x] `docs/POSITIONING.md` — add buck row to the topology matrix.
- [x] `README.md` — Topologies table screenshot refresh.
- [x] `docs/UI.md` — note the spec-panel field-visibility rules
      for DC vs AC topologies.
- [x] `examples/buck_5V_3A.pfc` (new) — bundled example for the
      CLI tutorial.
- [x] `tests/test_cli_design.py` — CLI smoke test on the new
      example file.

## Phase 7 — Cross-cutting verification

- [x] Run the full pytest suite — confirm no regression on the
      existing 4 topologies (3 boost-CCM + passive_choke +
      line_reactor 1φ + 3φ).
- [x] Visual review: render the Análise tab in light + dark for
      a buck design; spot-check the schematic, the waveform plot,
      the FFT bars, the THD tile (should read "—" or 0 since
      DC), the BH-loop card.
- [x] Cross-platform smoke: launch on Mac and Windows (Fusion
      style); confirm no rendering drift on the new picker grid.
- [x] Compile the HTML datasheet for a buck design end-to-end;
      open in a browser and verify section 3 layout.
