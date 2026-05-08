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

- [x] `ui/spec_panel.py` adds a collapsible "Modulation" section:
      - "Variable fsw" check-box.
      - Two QSpinBoxes (kHz_min, kHz_max).
      - Profile combo: "Uniform / Triangular dither / RPM-band".
      - When "RPM-band": rpm_min, rpm_max, pole-pairs spinboxes.
      - "Eval points" slider 2–20.
      _Shipped in `05ca06a feat(ui/spec): VFD modulation sub-form
      on the SpecPanel`._
- [x] Emits `changed` on any sub-field change so the dirty pill
      flips correctly.

## Phase 5 — Analysis tab integration

- [x] When `BandedDesignResult` is current, the Analysis tab
      shows three new line plots: `P_total(fsw)`, `B_pk(fsw)`,
      `dT(fsw)`. Each plot annotates the worst-case point.
      _Shipped in `d681ead feat(ui/analise): VFD modulation
      envelope card — per-fsw band plots`._
- [~] The `ResumoStrip` switches to worst-case values and the
      tooltip carries "Worst across fsw [4–25 kHz, 5 points]".
      *Deferred — the modulation envelope card carries the
      worst-case markers in-place, which already answers "what's
      the worst across the band". Promoting the strip to band-
      aware is queued behind a UX review and not blocking.*

## Phase 6 — Optimizer integration

- [~] `OptimizerEmbed._refresh_table()` ranks by `worst_case` when
      a band is active. *Deferred — the cascade re-rank covers
      this for the cascade orchestrator (`5bc7646`); the simple
      optimizer path stays single-point until a real bottleneck
      surfaces.*
- [x] `CascadeOrchestrator` band-aware re-rank — post-cascade
      step re-evaluates the surviving Tier-1 candidates across
      the band and re-ranks by worst-case before the user sees
      the Top-N. _Shipped in `5bc7646 feat(cascade): VFD
      band-aware re-rank as a post-cascade step`._
- [x] Top-N table reads the re-ranked store rows so the table is
      implicitly band-aware.

## Phase 7 — Datasheet + reports

- [x] Datasheet adds a "Modulation envelope" page when the active
      design is banded: the three curves plus a small worst-case
      summary table. _Shipped in `0271b8c feat(report): datasheet
      extras` via `report/extras.py::modulation_envelope_flowables`._
- [~] Compliance report evaluates IEC 61000-3-2 at every band
      point. *Deferred — IEC 61000-3-2 is line-cycle harmonics
      on the mains side, independent of the converter's
      switching frequency. Per-band-point evaluation collapses
      to the same answer as the nominal point. Re-opens if a
      future standard lands a switching-frequency-dependent
      criterion.*
- [~] Manufacturing spec carries a "Verified across fsw band" line.
      *Deferred — `add-manufacturing-spec-export` not yet
      shipped; the band annotation lands with that change.*

## Phase 8 — Docs + onboarding

- [~] `docs/modulation.md`: methodology, profile guidance,
      compressor-VFD recommended values. *Deferred — Sphinx
      theory site (`da5c40e`) shipped without a dedicated VFD
      chapter; lands with the next docs pass.*
- [~] Onboarding tour gains a 5th step. *Deferred — the
      Modulation surface lives one click away on the SpecPanel
      and is documented inline via field tooltips.*
- [~] CHANGELOG + README "VFD-aware design" bullet.
      *Deferred — README + CHANGELOG sweep planned alongside
      the next release tag.*
