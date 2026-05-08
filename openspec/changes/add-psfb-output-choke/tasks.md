# Tasks — add-psfb-output-choke

PSFB output choke is the simplest of the 5 topology proposals
because the math reuses ``buck_ccm`` after a frequency multiplier.
Phases mirror the buck-CCM proposal almost exactly.

## Phase 1 — Domain physics

- [ ] `pfc_inductor/topology/psfb_output_choke.py` (new):
  - [ ] ``effective_switching_frequency_Hz(spec)``.
  - [ ] ``effective_duty_at_Vsec(spec, Vsec_pk)``.
  - [ ] ``output_current_A(spec)``.
  - [ ] ``required_inductance_uH(spec, ripple_ratio=0.30)``.
  - [ ] ``peak_inductor_current_A(spec, L_uH)``.
  - [ ] ``rms_inductor_current_A(spec, L_uH)``.
  - [ ] ``waveforms(spec, L_uH, n_periods=5, n_points=600)``.
  - [ ] ``estimate_thd_pct(spec) → 0.0``.
- [ ] `pfc_inductor/models/spec.py`:
  - [ ] Topology Literal extended.
  - [ ] ``Vsec_pk_V``, ``Vsec_pk_min_V``, ``Vsec_pk_max_V``,
        ``D_max`` fields.
- [ ] `tests/test_topology_psfb_output_choke.py` (new):
  - [ ] ``test_effective_frequency_doubles_primary``.
  - [ ] ``test_required_L_halves_vs_buck_at_same_fsw``.
  - [ ] ``test_peak_current_buck_style``.
  - [ ] ``test_estimate_thd_returns_zero``.
  - [ ] Bel Power telecom benchmark (12 V / 125 A / 100 kHz).

## Phase 2 — Engine + cascade

- [ ] `pfc_inductor/topology/psfb_output_choke_model.py` (new) —
      ``ConverterModel`` with ``inductor_roles() → ["L_out"]``.
- [ ] `pfc_inductor/topology/registry.py` — register.
- [ ] `pfc_inductor/optimize/feasibility.py`:
  - [ ] ``N_HARD_CAP_BY_TOPOLOGY["psfb_output_choke"] = 50``
        (output chokes rarely need many turns at high f_sw_eff).
  - [ ] ``required_L_uH``, ``peak_current_A`` dispatch.
- [ ] `pfc_inductor/design/engine.py`:
  - [ ] PSFB branch: design at ``f_sw_eff = 2 · f_sw_kHz · 1e3``.
  - [ ] No bridge-loss math (DC input, no rectifier on the
        primary side from this engine's perspective).
  - [ ] Set ``pct_impedance_actual = None``.
  - [ ] Result includes ``f_sw_eff_Hz`` so downstream UI / report
        code reads the right number.
- [ ] `tests/test_psfb_output_choke_model.py` — Tier 0/1/2.

## Phase 3 — UI

- [ ] `pfc_inductor/ui/dialogs/topology_picker.py`:
  - [ ] Add "PSFB output choke (high-power isolated DC-DC)" card.
- [ ] `pfc_inductor/ui/widgets/schematic.py`:
  - [ ] ``_render_psfb_output_choke`` with greyed-out primary
        block + highlighted output choke + rectifier + Cout +
        Rload.
- [ ] `pfc_inductor/ui/spec_panel.py`:
  - [ ] Show ``Vsec_pk_V``, ``D_max``.
  - [ ] **New**: "Compute Vsec_pk from transformer" mini-dialog
        — takes Vin range + N_pri + N_sec, fills the field.
  - [ ] Hide AC-line / PFC fields.
- [ ] `pfc_inductor/simulate/realistic_waveforms.py`:
  - [ ] ``_psfb_output_choke`` synth: triangle on DC at
        ``f_sw_eff``.
- [ ] `pfc_inductor/ui/dashboard/cards/formas_onda_card.py`:
  - [ ] Top axis: iL triangle.
  - [ ] Middle axis: secondary-side rectified PWM (square wave
        at ``2 · f_sw``).
  - [ ] Bottom axis: harmonic spectrum at ``2·f_sw, 4·f_sw, …``.
- [ ] `pfc_inductor/ui/widgets/resumo_strip.py`:
  - [ ] Add a "f_sw effective" KPI tile reading
        ``"2 · f_sw = X kHz"`` for PSFB.
- [ ] `tests/test_realistic_waveforms.py` — extend.
- [ ] `tests/test_topology_picker.py` — picker has 9 options.

## Phase 4 — Reports

- [ ] `pfc_inductor/report/datasheet.py`:
  - [ ] Section 2 caption: "Inductor effective frequency:
        2 · f_sw_primary = {…} kHz".
  - [ ] Replace rolloff plot with waveform plot at f_sw_eff
        (or keep rolloff if a powder material is selected —
        unusual for PSFB but possible).
  - [ ] Replace harmonic-spectrum-vs-IEC plot with output-
        voltage-ripple plot (same as buck-CCM).
- [ ] `pfc_inductor/report/html_report.py` — equivalent.
- [ ] `pfc_inductor/standards/compliance_report.py`:
  - [ ] Same "Not applicable for DC-input topology" stance as
        buck-CCM.

## Phase 5 — Optimizer + selection

- [ ] `pfc_inductor/optimize/scoring.py`:
  - [ ] PSFB-tuned weights: AC core loss matters MORE than buck
        because of the high f_sw_eff. Penalise high-loss
        materials at high B_pk_AC; favour low-Pv ferrite.

## Phase 6 — Docs + examples

- [ ] `docs/POSITIONING.md` — PSFB row.
- [ ] `README.md` — Topologies table.
- [ ] `docs/topology-psfb-output-choke.md` (new) — design method,
      effective-frequency-doubling explanation, transformer-
      design pointer, telecom-rectifier reference.
- [ ] `docs/UI.md` — PSFB-specific UI notes (Vsec_pk helper).
- [ ] `examples/psfb_12V_125A.pfc` (new).

## Phase 7 — Cross-cutting verification

- [ ] Full pytest suite — no regression.
- [ ] Visual review per topology.
- [ ] Render the HTML datasheet for a PSFB design end-to-end;
      verify the ``f_sw_eff`` callout is present.
- [ ] Confirm the harmonic-spectrum bottom subplot's first peak
      lands at ``2 · f_sw`` (regression catch for the
      effective-frequency plumbing).
- [ ] Cross-platform smoke (Mac, Win, Linux Fusion).
