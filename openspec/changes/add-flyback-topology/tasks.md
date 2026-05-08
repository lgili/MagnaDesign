# Tasks — add-flyback-topology

Phased so domain physics + engine integration can land before the
multi-winding UI / catalog work, which is the heaviest piece.

## Phase 1 — Domain physics

- [ ] `pfc_inductor/topology/flyback.py` (new):
  - [ ] DCM design path:
        ``required_primary_inductance_uH``,
        ``primary_peak_current``, ``primary_rms_current``,
        ``secondary_*`` mirrors, ``demag_duty``.
  - [ ] CCM design path:
        ``ccm_peak_currents``, ``ccm_rms_currents``,
        ``ccm_duty_cycle`` (volt-seconds balance).
  - [ ] ``optimal_turns_ratio(spec)`` — equal-stress design rule.
  - [ ] ``reflected_voltages(spec, n)``: returns
        ``(V_drain_pk, V_diode_pk)`` per spec.
  - [ ] ``leakage_inductance_estimate(core, Np, Ns, layout)`` —
        empirical lookup table (sandwich / simple / poor) keyed
        by core shape; ships table + interpolation rule.
  - [ ] ``snubber_dissipation_W(L_leak, Ip_pk, f_sw, V_clamp,
        n, Vout)``.
  - [ ] ``waveforms(spec, Lp_uH, n, mode)`` — sample Ip(t) + Is(t)
        over ``n_periods`` switching cycles.
  - [ ] ``estimate_thd_pct(spec)`` returns ``0.0`` (DC input).
- [ ] `pfc_inductor/physics/leakage.py` (new) — ports the
      empirical lookup table from above + a calibration
      docstring with vendor app-note references (TI SLUA535,
      Coilcraft Doc 158, Würth ANP034).
- [ ] `pfc_inductor/models/spec.py`:
  - [ ] Topology Literal extended.
  - [ ] ``flyback_mode``, ``turns_ratio_n``, ``Vin_dc_V``,
        ``Vin_dc_min/max_V``, ``window_split_primary`` fields.
  - [ ] Validator ensures ``flyback_mode`` and ``Vin_dc_V`` are
        consistent (Vin > 0 mandatory for flyback).
- [ ] `pfc_inductor/models/core.py` — add optional
      ``window_split_default_primary: float = 0.45`` to the
      ``Core`` model so per-shape calibration can override the
      global default in a future change without breaking
      existing core JSON files.
- [ ] `tests/test_topology_flyback.py` (new) — TI UCC28780 EVM
      benchmark (DCM, 12 V → 5 V, 10 W, 100 kHz, ferrite EFD25).
- [ ] `tests/test_physics_leakage.py` (new) — empirical lookup
      table values for each core shape match published numbers
      within ±20 %.

## Phase 2 — Engine + cascade

- [ ] `pfc_inductor/topology/flyback_model.py` — implements
      ``ConverterModel`` Protocol:
  - [ ] ``feasibility_envelope`` checks both windings' window
        fill, primary and secondary RMS within wire ratings,
        reflected-voltage stress within FET / diode SOA.
  - [ ] ``steady_state`` runs the full ``design()`` path.
  - [ ] ``state_derivatives`` is the 2-state ODE
        ``(Ip, Is)`` with the four conduction phases.
  - [ ] ``initial_state`` returns ``[0.0, 0.0]``.
- [ ] `pfc_inductor/topology/registry.py` — register
      ``"flyback"`` → ``FlybackModel``.
- [ ] `pfc_inductor/optimize/feasibility.py`:
  - [ ] ``N_HARD_CAP_BY_TOPOLOGY["flyback"] = 200`` (primary).
  - [ ] ``required_L_uH``, ``peak_current_A`` dispatch.
  - [ ] New helper ``window_check_split(spec, core, Np, Ns,
        primary_wire, secondary_wire)`` that returns reasons for
        each side that fails.
- [ ] `pfc_inductor/design/engine.py` — flyback branch:
  - [ ] Pick ``Np`` to satisfy ``Lp = required Lp(spec)``.
  - [ ] Pick ``Ns = Np / n`` (n from spec or
        ``optimal_turns_ratio``).
  - [ ] Compute ``B_pk`` at ``Ip_pk`` end-of-ON.
  - [ ] Validate window fill on **both** windings.
  - [ ] Compute Cu loss for **both** windings; emit
        ``P_Cu_pri`` and ``P_Cu_sec`` separately in the report.
  - [ ] Estimate leakage inductance + snubber dissipation; add
        ``P_snubber`` to the loss table.
  - [ ] Emit ``V_drain_pk`` and ``V_diode_pk`` in the result.
- [ ] `pfc_inductor/models/result.py`:
  - [ ] Add fields:
        ``Lp_actual_uH``, ``Np_turns``, ``Ns_turns``,
        ``Ip_peak_A``, ``Ip_rms_A``, ``Is_peak_A``,
        ``Is_rms_A``, ``L_leak_uH``,
        ``V_drain_pk_V``, ``V_diode_pk_V``,
        ``P_snubber_W``.
  - [ ] Existing ``N_turns`` aliases ``Np_turns`` for back-compat.
- [ ] `tests/test_flyback_model.py` — Tier 0/1/2 cascade.
- [ ] `tests/test_design_engine.py` extension — TI EVM benchmark
      end-to-end via ``design()``.

## Phase 3 — UI

- [ ] `pfc_inductor/ui/dialogs/topology_picker.py`:
  - [ ] Add ``("flyback", "Flyback (DCM/CCM)", None,
        "Isolated DC-DC, coupled inductor…")`` to ``_OPTIONS``.
  - [ ] Picker grid 3×2 (with buck-CCM at 5 cards becomes 6).
- [ ] `pfc_inductor/ui/widgets/schematic.py`:
  - [ ] ``_render_flyback`` with two highlighted coupled
        windings (dot convention shown).
  - [ ] Register in ``_TOPOLOGY_RENDERERS``.
- [ ] `pfc_inductor/ui/spec_panel.py`:
  - [ ] Show ``flyback_mode``, ``turns_ratio_n``,
        ``window_split_primary`` (advanced section, collapsed
        by default).
  - [ ] Hide AC fields when flyback is active.
- [ ] `pfc_inductor/simulate/realistic_waveforms.py`:
  - [ ] ``_flyback`` synth: Ip ramping during D, Is ramping
        during D₂, both zero in idle (DCM) or non-zero floor
        (CCM). Returns ``RealisticWaveform`` with both Ip and
        Is in ``iL_extra``.
  - [ ] Wire into dispatch.
- [ ] `pfc_inductor/ui/dashboard/cards/formas_onda_card.py`:
  - [ ] Top axis stacks Ip + Is (two colours) for flyback.
  - [ ] Middle axis shows v_drain(t) (square wave + leakage
        spike, modelled as decaying exponential).
- [ ] `pfc_inductor/ui/widgets/resumo_strip.py`:
  - [ ] Add a "V_stress" KPI tile that reads ``V_drain_pk_V``
        for flyback (else stays "—").
- [ ] `pfc_inductor/ui/dashboard/cards/perdas_card.py`:
  - [ ] Loss-bar segments split into ``P_Cu_pri``, ``P_Cu_sec``,
        ``P_core``, ``P_snubber``.
- [ ] `tests/test_realistic_waveforms.py` — extend.
- [ ] `tests/test_topology_picker.py` — picker has 6 options.

## Phase 4 — Reports

- [ ] `pfc_inductor/report/datasheet.py`:
  - [ ] Topology-aware spec rows.
  - [ ] Operating-point table includes both windings.
  - [ ] Loss table 4-column (Cu pri / Cu sec / core / snubber).
  - [ ] Waveform plot stacks Ip + Is.
  - [ ] BOM section lists both wires + RCD snubber + diode.
- [ ] `pfc_inductor/report/html_report.py` — equivalent.
- [ ] `pfc_inductor/report/manufacturing_spec.py` (if it exists,
      else open a follow-on change):
  - [ ] Winding-sequence section (P, S, sandwich P-S-P, etc.).
  - [ ] Bobbin layer count + insulation tape between windings.
- [ ] `pfc_inductor/standards/compliance_report.py`:
  - [ ] New "Isolation" section for flyback (creepage /
        clearance checklist; v1 is checklist-only — full
        calculation is a future change).

## Phase 5 — Optimizer + selection

- [ ] `pfc_inductor/optimize/scoring.py`:
  - [ ] Flyback-tuned weights (peak current matters more than
        RMS because energy storage drives saturation).
- [ ] `pfc_inductor/optimize/cascade/generators.py`:
  - [ ] Cartesian over (mat × core × pri_wire × sec_wire) for
        flyback. Initial heuristic: pick sec_wire by turns
        ratio + window split (Option A from proposal).
- [ ] `pfc_inductor/optimize/feasibility.py::viable_wires_for_spec`
  - [ ] Returns *two* lists (primary candidates + secondary
        candidates) for flyback. The orchestrator pairs them.

## Phase 6 — Docs + examples

- [ ] `docs/POSITIONING.md` — flyback row.
- [ ] `README.md` — Topologies table.
- [ ] `docs/UI.md` — multi-winding spec rules.
- [ ] `docs/topology-flyback.md` (new) — design-method writeup.
- [ ] `examples/flyback_5V_2A.pfc` (new).
- [ ] `tests/test_cli_design.py` — CLI on the example.

## Phase 7 — Cross-cutting verification

- [ ] Full pytest suite — no regressions on the existing 4
      topologies.
- [ ] Visual review per topology (light + dark themes).
- [ ] Render the HTML datasheet for a flyback design end-to-end;
      verify the BOM lists both wires.
- [ ] Manufacturing spec PDF (if available) with winding-sequence
      section.
- [ ] Cross-platform smoke (Mac, Win, Linux Fusion).
