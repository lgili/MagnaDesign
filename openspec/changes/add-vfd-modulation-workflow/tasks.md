# Tasks — add-vfd-modulation-workflow

## Phase 1 — Spec model

- [ ] `pfc_inductor/models/modulation.py`:
      - `FswModulation` Pydantic model (fsw_min_kHz, fsw_max_kHz,
        profile, n_eval_points, optional rpm_min/max, pole_pairs).
      - Helper `rpm_to_fsw(rpm, pole_pairs)` for `rpm_band` profile.
      - Validators: max ≥ min, n_eval_points ∈ [2, 50].
- [ ] Spec extension: `Spec.fsw_modulation: Optional[FswModulation]`.
      Default `None` — every current `.pfc` round-trips unchanged.
- [ ] `tests/test_spec_modulation_roundtrip.py`: backward-compat +
      new-feature round-trip via `.pfc` save/load.

## Phase 2 — BandedDesignResult

- [ ] `pfc_inductor/models/banded_result.py`:
      - `BandedDesignResult(spec, band: list[BandPoint], worst_case,
         nominal, flagged_points)`.
      - `BandPoint(fsw_kHz, design: DesignResult)`.
      - Convenience accessors: `worst_loss`, `worst_dT`, `worst_Bpk`.
- [ ] `tests/test_banded_result_aggregation.py`: hand-built band,
      verify worst-case extraction.

## Phase 3 — Engine integration

- [ ] `pfc_inductor/topology/modulation.py`:
      - `eval_band(spec, core, wire, material) → BandedDesignResult`
        when `spec.fsw_modulation is not None`. Iterates fsw points,
        calls `design()` per point, aggregates.
- [ ] `design()` dispatcher: route to `eval_band` when modulation
      is set; else single-point as today. Return type union.
- [ ] All callers of `design()` audited: most accept either kind
      via a `result.worst_case if banded else result` shim. Add a
      `unwrap_for_kpi(result)` helper to centralise.

## Phase 4 — Spec drawer UI

- [ ] `ui/spec_panel.py` adds a collapsible "Modulation" section:
      - "Variable fsw" check-box.
      - Two QSpinBoxes (kHz_min, kHz_max).
      - Profile combo: "Uniform / Triangular dither / RPM-band".
      - When "RPM-band": rpm_min, rpm_max, pole-pairs spinboxes.
      - "Eval points" slider 2–20.
- [ ] Emits `changed` on any sub-field change so the dirty pill
      flips correctly (matching the `add-cascade-optimizer` pattern).

## Phase 5 — Analysis tab integration

- [ ] When `BandedDesignResult` is current, the Analysis tab
      shows three new line plots: `P_total(fsw)`, `B_pk(fsw)`,
      `dT(fsw)`. Each plot annotates the worst-case point.
- [ ] The `ResumoStrip` switches to worst-case values and the
      tooltip carries "Worst across fsw [4–25 kHz, 5 points]"
      so the user knows it's not the nominal.

## Phase 6 — Optimizer integration

- [ ] `OptimizerEmbed._refresh_table()` ranks by `worst_case` when
      a band is active.
- [ ] `CascadeOrchestrator` Tier-1 evaluates the band per
      candidate (cost: × `n_eval_points`). Add a perf note in the
      run-config card so the user sees the multiplier.
- [ ] Top-N table gains a "Band ΔT" column when active showing
      the worst-case ΔT.

## Phase 7 — Datasheet + reports

- [ ] Datasheet adds a "Modulation envelope" page when the active
      design is banded: the three curves plus a small worst-case
      summary table.
- [ ] Compliance report (`add-compliance-report-pdf`) evaluates
      IEC 61000-3-2 at every band point and reports the worst.
- [ ] Manufacturing spec carries a "Verified across fsw band" line
      in the acceptance test plan when active.

## Phase 8 — Docs + onboarding

- [ ] `docs/modulation.md`: methodology, when to use which profile,
      compressor-VFD recommended values (4–25 kHz triangular,
      5 points minimum).
- [ ] Onboarding tour gains a 5th step pointing out the modulation
      option for VFD users.
- [ ] CHANGELOG + README "VFD-aware design" bullet.
