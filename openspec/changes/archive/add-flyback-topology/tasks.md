# Tasks — add-flyback-topology

**Status: SHIPPED in commit `8cdeffe`** — phases 1-7 closed
end-to-end. Items marked ``[~]`` were deferred to follow-on
changes (multi-winding cartesian search, full IEC 62368
calculation, manufacturing-spec winding-sequence section).

## Phase 1 — Domain physics

- [x] `pfc_inductor/topology/flyback.py` (new):
  - [x] DCM design path:
        ``required_primary_inductance_uH``,
        ``primary_peak_current``, ``primary_rms_current``,
        ``secondary_*`` mirrors, ``demag_duty``.
  - [x] CCM design path:
        ``ccm_peak_currents``, ``ccm_rms_currents``,
        ``ccm_duty_cycle`` (volt-seconds balance).
  - [x] ``optimal_turns_ratio(spec)`` — equal-stress design rule.
  - [x] ``reflected_voltages(spec, n)``: returns
        ``(V_drain_pk, V_diode_pk)`` per spec.
  - [x] ``leakage_inductance_uH(Lp, layout, n_layers, core_shape)``
        — wraps the empirical lookup in ``physics/leakage.py``.
  - [x] ``snubber_dissipation_W(L_leak, Ip_pk, f_sw, V_clamp,
        n, Vout)``.
  - [x] ``waveforms(spec, Lp_uH, n, mode)`` — sample Ip(t) + Is(t)
        over ``n_periods`` switching cycles.
  - [x] ``estimate_thd_pct(spec)`` returns ``0.0`` (DC input).
- [x] `pfc_inductor/physics/leakage.py` (new) — empirical lookup
      table + per-shape correction hook + ±30 % uncertainty
      surfaced via ``leakage_uncertainty_pct``. Calibrated
      against TI SLUA535, Coilcraft Doc 158, Würth ANP034.
- [x] `pfc_inductor/models/spec.py`:
  - [x] Topology Literal extended.
  - [x] ``flyback_mode``, ``turns_ratio_n``, ``Vin_dc_V``,
        ``Vin_dc_min/max_V``, ``window_split_primary`` fields.
  - [x] Validator ensures ``flyback_mode`` and ``Vin_dc_V`` are
        consistent (Vin > 0 mandatory for flyback).
- [~] `pfc_inductor/models/core.py` — per-shape
      ``window_split_default_primary`` deferred. v1 uses the
      flat 0.45 default carried on ``Spec.window_split_primary``;
      shape-level calibration only matters once the cartesian
      window-fill check ships in the optimizer follow-on.
- [x] `tests/test_topology_flyback.py` (new) — 26 tests on the
      Erickson Ch. 6 fixture (12 V → 5 V, 10 W, 100 kHz, DCM).
- [x] `tests/test_physics_leakage.py` (new) — 13 tests pinning
      the empirical lookup to published vendor numbers.

## Phase 2 — Engine + cascade

- [x] `pfc_inductor/topology/flyback_model.py` — implements
      ``ConverterModel`` Protocol:
  - [x] ``feasibility_envelope`` runs primary-side
        ``core_quick_check`` (full two-winding window check is
        Tier 1's job inside ``design()``).
  - [x] ``steady_state`` runs the full ``design()`` path.
  - [x] ``state_derivatives`` is a 2-state ODE on ``(Ip, Is)``
        with three conduction phases (ON / DEMAG / IDLE in
        DCM, two phases in CCM).
  - [x] ``initial_state`` returns ``[0.0, 0.0]``.
- [x] `pfc_inductor/topology/registry.py` — register
      ``"flyback"`` → ``FlybackModel``.
- [x] `pfc_inductor/optimize/feasibility.py`:
  - [x] ``N_HARD_CAP_BY_TOPOLOGY["flyback"] = 200`` (primary).
  - [x] ``required_L_uH``, ``peak_current_A``, ``rated_current_A``
        dispatch.
  - [~] ``window_check_split`` helper deferred — the engine's
        single-winding window check covers the 90 % case for v1;
        the secondary-only failure mode lives in Tier 1's
        existing reasons stack.
- [x] `pfc_inductor/design/engine.py` — flyback branch:
  - [x] Pick ``Np`` to satisfy ``Lp = required Lp(spec)`` via
        the existing ``_solve_N`` (the engine treats Np as
        "the inductor's N").
  - [x] Pick ``Ns = Np / n`` (n from spec or
        ``optimal_turns_ratio``).
  - [x] Compute ``B_pk`` at ``Ip_pk`` end-of-ON.
  - [~] Per-winding window-fill check deferred (uses primary
        Ku × ``window_split_primary`` for v1).
  - [~] Per-winding Cu-loss split deferred — v1 reports the
        primary loss as ``losses.P_cu_dc_W`` plus a single
        ``P_snubber_W``; secondary Cu-loss appears in the
        ``Is_rms_A`` field for the engineer to spot-check.
  - [x] Estimate leakage inductance + snubber dissipation;
        ``L_leak_uH`` and ``P_snubber_W`` in the result.
  - [x] Emit ``V_drain_pk_V`` and ``V_diode_pk_V`` in the result.
- [x] `pfc_inductor/models/result.py`:
  - [x] Add fields:
        ``Lp_actual_uH``, ``Np_turns``, ``Ns_turns``,
        ``Ip_peak_A``, ``Ip_rms_A``, ``Is_peak_A``,
        ``Is_rms_A``, ``L_leak_uH``,
        ``V_drain_pk_V``, ``V_diode_pk_V``,
        ``P_snubber_W``, ``waveform_is_A``.
  - [~] ``N_turns`` aliasing ``Np_turns`` left as the existing
        contract — flyback writes both fields independently so
        no back-compat break is needed.

## Phase 3 — UI

- [x] `pfc_inductor/ui/dialogs/topology_picker.py`:
  - [x] Added ``("flyback", "Flyback (DCM/CCM)", None,
        "Isolated DC-DC, coupled inductor…")`` to ``_OPTIONS``.
  - [x] Picker grid grows naturally — 6 cards in two columns.
- [x] `pfc_inductor/ui/widgets/schematic.py`:
  - [x] ``_render_flyback`` with two highlighted coupled
        windings (dot convention + air-gap notch shown).
  - [x] Registered in ``_TOPOLOGY_RENDERERS``.
- [x] `pfc_inductor/ui/spec_panel.py`:
  - [x] Flyback shares the buck DC-input block (``sp_vin_dc``
        family). AC fields hidden when flyback is active.
  - [x] ``_apply_flyback_defaults_if_boostlike`` swaps to
        textbook 12 V → 5 V, 10 W, 100 kHz preset on first
        toggle.
  - [~] ``flyback_mode``, ``turns_ratio_n``,
        ``window_split_primary`` advanced section deferred —
        v1 designs use spec validator defaults (engine picks
        the optimal turns ratio when None).
- [x] `pfc_inductor/simulate/realistic_waveforms.py`:
  - [x] ``_flyback`` synth: Ip ramping during D, Is ramping
        during D₂. Returns ``RealisticWaveform`` with secondary
        in ``iL_extra``.
  - [x] Wired into dispatch.
- [x] `pfc_inductor/ui/dashboard/cards/formas_onda_card.py`:
  - [x] ``_plot_flyback_currents`` overlays Ip + Is on the
        top axis with the brand-accent + violet pair.
  - [~] Middle-axis ``v_drain(t)`` with leakage spike deferred —
        v1 falls through to the standard source-voltage plot;
        the V_drain_pk number is surfaced as a numeric field
        already.
- [~] `pfc_inductor/ui/widgets/resumo_strip.py` — V_stress KPI
      tile deferred to a follow-up UX pass.
- [~] `pfc_inductor/ui/dashboard/cards/perdas_card.py` —
      4-column loss split deferred (engine reports total
      P_snubber_W as a numeric, not yet a chart segment).
- [x] `tests/test_topology_picker.py` — picker has all required
      cards (containment check).

## Phase 4 — Reports

- [x] `pfc_inductor/report/datasheet.py`:
  - [x] ``_spec_rows_flyback`` — spec-input + operating-point
        rows (Lp, Np/Ns, Ip, Is, V_drain, V_diode, L_leak,
        P_snubber).
  - [x] ``_topology_label`` adds "Flyback Coupled Inductor".
  - [x] ``_SAFETY_FLYBACK`` block (IEC 62368-1 reinforced
        insulation checklist).
  - [~] 4-column (Cu pri / Cu sec / core / snubber) loss table
        deferred — v1 surfaces snubber dissipation alongside
        total losses, secondary Cu lives in the operating-point
        table.
  - [~] BOM auto-list of both wires + RCD components deferred
        to a follow-on change (needs a richer
        manufacturing-spec dataclass first).
- [x] `pfc_inductor/report/html_report.py` — flyback Vin DC +
      turns-ratio rows in the spec table.
- [~] `pfc_inductor/report/manufacturing_spec.py` — winding-
      sequence section deferred to its own change.
- [~] `pfc_inductor/standards/compliance_report.py` —
      isolation section integration deferred.

## Phase 5 — Optimizer + selection

- [x] `pfc_inductor/optimize/scoring.py`:
  - [x] Flyback μᵢ band scorer favours gapped power ferrite
        (1 500–5 000 µi).
  - [x] Wire scorer treats flyback's ``f_sw_kHz`` as the AC-loss
        frequency (Litz wins above 50 kHz).
- [~] `pfc_inductor/optimize/cascade/generators.py` cartesian
      over (mat × core × pri_wire × sec_wire) deferred —
      v1 cascade falls back to the analytical engine via
      ``FlybackModel.steady_state`` and the existing single-
      winding orchestrator. The full multi-winding sweep
      lives in a follow-on change.
- [~] ``viable_wires_for_spec`` returning *two* lists deferred
      for the same reason.

## Phase 6 — Docs + examples

- [x] `README.md` — Topologies table updated; flyback moved
      from "Planned" to "Available" alongside buck-CCM and
      interleaved boost.
- [~] `docs/POSITIONING.md` — flyback row deferred to a follow-
      up docs commit.
- [~] `docs/UI.md` — multi-winding spec rules deferred (the
      advanced section in spec_panel hasn't shipped yet).
- [~] `docs/topology-flyback.md` (new design-method writeup)
      deferred — proposal.md + design.md cover the same ground
      and live alongside the archived change.
- [x] `examples/flyback_12V_to_5V_10W.pfc` (USB-PD adapter
      preset).
- [~] `tests/test_cli_design.py` extension deferred.

## Phase 7 — Cross-cutting verification

- [x] Cross-topology regression: 98 tests pass on the
      flyback + leakage + buck-ccm + picker + cascade-protocol
      + design-engine + report set.
- [x] Engine smoke-test on a Thornton NEE-1366 IP12R gapped
      ferrite: feasible 12 V → 5 V flyback (Np=14, Ns=7,
      Ip_pk=4.7 A, Is_pk=9.3 A, V_drain_pk=38 V,
      T_winding=111 °C, total losses 0.76 W).
- [x] HTML datasheet renders all 8 expected sections (Flyback
      header, DCM mode, Lp row, snubber, V_drain, V_diode,
      reinforced safety, creepage row).
- [~] Visual baselines (light + dark themes) deferred.
- [~] Manufacturing-spec PDF deferred (its own change).
- [~] Cross-platform Win/Linux smoke deferred.
