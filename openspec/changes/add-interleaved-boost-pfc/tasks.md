# Tasks — add-interleaved-boost-pfc

Status: **shipped**. This was the smallest of the 5 topology
changes because it leans heavily on the existing ``boost_ccm``
math — most of the work was plumbing. The multi-inductor wrapper
from the LCL change was *not* required: the engine routes the
interleaved spec through a *per-phase* boost-CCM design and the
report layer surfaces the multiplier (× N) explicitly. This
keeps the result type unchanged and the BOM clearly states the
quantity per converter.

## Phase 1 — Domain physics — DONE

- [x] `pfc_inductor/topology/interleaved_boost_pfc.py` (new):
  - [x] ``per_phase_spec(spec)``.
  - [x] ``required_inductance_uH(spec, Vin_Vrms)`` —
        delegates to ``boost_ccm`` after per-phase scaling.
  - [x] ``line_peak_current_A`` and ``line_rms_current_A`` —
        per-phase delegations.
  - [x] ``aggregate_input_ripple_pp(per_phase_pp, D, N)`` —
        Hwu-Yau closed form.
  - [x] ``effective_input_ripple_frequency_Hz(f_sw_kHz, N)``.
  - [x] ``estimate_thd_pct(spec)`` — boost-CCM value / √N.
  - [x] ``ripple_cancellation_factor(D, N)`` — α(D, N) closed
        form (Hwu-Yau).
  - [x] ``worst_case_duty_for_ripple(N)``.
- [x] `pfc_inductor/models/spec.py`:
  - [x] Topology Literal extended.
  - [x] ``n_interleave: Literal[2, 3] = 2``.
  - [x] Validator: ``n_interleave`` required iff topology
        is ``"interleaved_boost_pfc"``.
- [x] `tests/test_topology_interleaved_boost_pfc.py` (new) —
      18 tests, all pass.

## Phase 2 — Engine + cascade — DONE

- [x] `pfc_inductor/topology/interleaved_boost_pfc_model.py` (new):
  - [x] ``feasibility_envelope`` / ``steady_state`` /
        ``initial_state`` / ``state_derivatives`` — all delegate
        to BoostCCMModel through ``per_phase_spec``.
- [x] `pfc_inductor/topology/registry.py` — registered.
- [x] `pfc_inductor/optimize/feasibility.py`:
  - [x] ``N_HARD_CAP_BY_TOPOLOGY["interleaved_boost_pfc"] = 250``.
  - [x] ``required_L_uH`` / ``peak_current_A`` dispatch via
        ``per_phase_spec``.
- [x] `pfc_inductor/topology/material_filter.py` — same family
      as boost_ccm.
- [x] `pfc_inductor/design/engine.py` — interleaved branch:
      build per-phase spec, recurse into boost_ccm, stamp
      "× N identical units (interleaved boost PFC, per-phase
      Pout = X W). Aggregate input ripple is suppressed by
      Hwu-Yau cancellation; the input filter sees ripple at
      N · f_sw." in result.notes.

## Phase 3 — UI — DONE

- [x] `pfc_inductor/ui/dialogs/topology_picker.py` — 2 entries
      (2-phase / 3-phase) with descriptive labels and
      schematics.
- [x] `pfc_inductor/ui/widgets/schematic.py` — render delegates
      to boost_ccm + "× N phases" badge.
- [x] `pfc_inductor/ui/spec_panel.py` — ``n_interleave`` field
      threaded through ``set_topology()`` / ``get_spec()``.
- [x] `pfc_inductor/ui/main_window.py` — picker open/close
      passes ``n_interleave``.

## Phase 4 — Reports — DONE

- [x] `pfc_inductor/report/datasheet.py`:
  - [x] Title "Interleaved Boost-PFC Inductor (per phase)".
  - [x] Spec rows: per-phase Pout + total Pout + N + Aggregate
        input ripple frequency = N · f_sw.
  - [x] BOM "Quantity per converter = N× this part (one per
        phase)" line at top of the BOM.
  - [x] Topology dispatches (`_waveform_plot`,
        `_switching_ripple_plot`, `_efficiency_curve_plot`,
        `_topology_section`, FAT plan saturation row, safety
        table) all extended to handle interleaved alongside
        boost_ccm.
- [x] `pfc_inductor/report/pdf_report.py` — equivalent
      adjustments to all dispatch points and `_spec_data_boost`.
- [x] `pfc_inductor/report/pdf_project.py`:
  - [x] Topology label updated.
  - [x] `_spec_input_data` shows N + per-phase + total Pout +
        aggregate ripple freq.
  - [x] `_section_topology_body` routes interleaved through
        boost-CCM body builder; `_body_boost_ccm` opens with an
        "Interleaved Boost-PFC — theory (N phases)" preamble +
        Hwu-Yau / Erickson references; the derivation chain
        runs on the per-phase Pout (so substituted equations
        match the printed numerical results), with a footnote
        on each substitution explaining the per-phase analysis.

## Phase 5 — Optimizer — IMPLICIT (engine recursion)

The cascade optimizer's per-spec inner loop now sees the
interleaved spec, but the engine's interleaved branch swaps it
for the per-phase spec at entry. So the candidate enumeration
naturally sees the smaller per-phase core size — no scoring
tweaks were needed.

## Phase 6 — Docs + examples — DONE

- [x] `docs/POSITIONING.md` — interleaved row.
- [x] `README.md` — Topologies table includes interleaved boost
      PFC; intro updated to "six topologies ship today".
- [x] `docs/topology/interleaved-boost-pfc.rst` (new) — full
      design method, Hwu-Yau cancellation derivation,
      effective ripple frequency, current-sharing guidance,
      bibliographic references.
- [x] `docs/index.rst` — TOC includes the new topology page.
- [x] `docs/user-guide/02-spec-drawer.md` — topology table
      + per-topology section for interleaved.
- [x] `docs/user-guide/03-core-selection.md` — note that
      interleaved shares the boost_ccm material filter.
- [x] `docs/user-guide/04-analysis-tab.md` — P-vs-L placeholder
      extends to interleaved.
- [x] `docs/user-guide/08-exports.md` — datasheet / project
      report layout entries describe the per-phase + N
      treatment and aggregate ripple chart.
- [x] `examples/interleaved_boost_3kW_2phase.pfc` (new).
- [x] `examples/interleaved_boost_11kW_3phase.pfc` (new).

## Phase 7 — Cross-cutting verification — DONE

- [x] Full pytest suite — see commit message.
- [x] Smoke test: HTML datasheet, PDF datasheet, project PDF
      all generate cleanly for a 3 kW 2-phase design.
- [x] Verified interleaved markers ("Interleaved", "phases",
      "per phase", "Quantity per converter", "360°/2",
      "Aggregate input ripple") all surface in the rendered
      HTML.
- [x] Engine numerical cross-check: a 3 kW 2-phase
      interleaved design produces identical per-phase numbers
      to a 1.5 kW single-phase boost-CCM design (L_required
      and N_turns match to the precision the engine reports).
