# Tasks — add-vfd-modulation-workflow

## Phase 1 — Spec model

- [x] `pfc_inductor/models/modulation.py`:
      - `FswModulation` Pydantic v2 model (fsw_min_kHz,
        fsw_max_kHz, profile, n_eval_points, optional
        rpm_min/max, pole_pairs).
      - Helper `rpm_to_fsw(rpm, pole_pairs)` for ``rpm_band``
        profile (bundled K_CARRIER_RATIO=200, the IEC-friendly
        appliance-compressor default).
      - `from_rpm_band(...)` convenience constructor.
      - Validators: max > min, n_eval_points ∈ [2, 50],
        ``rpm_band`` profile requires the three RPM fields.
- [x] Spec extension: `Spec.fsw_modulation: Optional[FswModulation]`.
      Default `None` — every current `.pfc` round-trips unchanged.
      Re-exported from `pfc_inductor.models.__init__`.
- [x] `tests/test_modulation_workflow.py` covers backward-compat +
      new-feature round-trip via JSON serialisation.

## Phase 2 — BandedDesignResult

- [x] `pfc_inductor/models/banded_result.py`:
      - `BandedDesignResult(spec, band, nominal,
        worst_per_metric, flagged_points)` dataclass.
      - `BandPoint(fsw_kHz, result, failure_reason)`.
      - `aggregate_band()` builds it from a raw list, honouring
        ``edge_weighted=True`` for the dither profile.
      - `unwrap_for_kpi(result)` helper for legacy single-point
        consumers.
- [x] Tests cover hand-built bands, per-metric worst case, edge-
      weighted dither restriction, engine-failure absorption,
      ``unwrap_for_kpi`` shim on both shapes.

## Phase 3 — Engine integration

- [x] `pfc_inductor/modulation/engine.py`:
      - `eval_band(spec, core, wire, material)` iterates the
        band's fsw points, calls ``design()`` per point with a
        copy-and-update spec (immutable Pydantic), absorbs
        DesignError + arithmetic errors per point.
      - `design_or_band(spec, ...)` dispatcher routes to
        ``design()`` (single-point) or ``eval_band()`` (banded)
        based on ``spec.fsw_modulation``.
- [~] Module lives at `pfc_inductor/modulation/` (top-level)
      rather than `topology/modulation.py` — the wrapper is
      topology-agnostic and ``topology/`` is actively expanding
      with new topology files (buck, flyback, LCL); keeping the
      wrapper outside avoids merge churn.
- [~] Every caller of `design()` audited and migrated to
      `design_or_band` via `unwrap_for_kpi`. *Today only the
      modulation tests exercise both paths; UI callers continue
      to use `design()` directly until the Spec drawer's
      Modulation sub-form lands (Phase 4).*

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
