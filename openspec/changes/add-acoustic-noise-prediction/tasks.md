# Tasks — add-acoustic-noise-prediction

## Phase 1 — Material data

- [ ] Add `magnetostrictive_lambda_s_ppm: Optional[float]` to the
      `Material` Pydantic model. Backward-compat default `None`.
- [ ] Bundle baseline λ_s values for the curated materials
      (`data/curated_materials.json` overlay):
      - MnZn ferrites: 0.5–2 ppm (per Ferroxcube / TDK datasheets).
      - NiZn ferrites: 25–35 ppm (significant — these hum loudly).
      - Powder cores (Kool Mµ / HighFlux / MPP): ~1 ppm.
      - Silicon-steel laminations: 7–9 ppm.
- [ ] Cite the datasheet source per material in the JSON (`x-pfc-
      inductor.lambda_s_source`).

## Phase 2 — Magnetostriction model

- [ ] `pfc_inductor/acoustic/model.py`:
      - `magnetostriction_spl(material, core, dB_pk_T, fsw_Hz)` →
        SPL contribution at 1 m. Uses λ_s × B_pk² × geometry to
        compute surface vibration amplitude, radiates through
        empirical efficiency (~10⁻⁴ for a small toroid).
      - Returns `(dB_a, dominant_freq)`. Dominant freq is 2·fsw
        when DC-biased (rectified magnetostriction) else fsw.
- [ ] Hand-calc anchor in `tests/test_acoustic_magnetostriction.py`:
      MnZn ferrite at 100 mT, 65 kHz → 35 dB(A) (within ±3).

## Phase 3 — Winding Lorentz model

- [ ] `acoustic/model.py:lorentz_spl(...)`:
      - Force per unit length between adjacent layers carrying
        I_ac at fsw → mechanical excitation → SPL.
      - Negligible for single-layer designs; dominates in dense
        multi-layer Litz at high I.
- [ ] Test: multi-layer 10 A AC design → predicted contribution
      is dominant.

## Phase 4 — Bobbin-resonance heuristic

- [ ] `acoustic/bobbin_resonance.py`:
      - `bobbin_modes(core, winding_layout)` → list of resonance
        frequencies estimated from beam-on-supports formula with
        the bobbin material's E and density (default: PBT,
        E ≈ 3 GPa, ρ ≈ 1300 kg/m³).
      - When fsw or 2·fsw lands within ±10 % of a bobbin mode,
        boost the SPL by +6 dB and tag mechanism as "bobbin_resonance".
- [ ] Test: known-bad combination (fsw at first bobbin mode) →
      flagged + dB boost applied.

## Phase 5 — Aggregation + DesignResult

- [ ] `acoustic/model.py:estimate_noise(...)` orchestrates the
      three contributions and returns
      `NoiseEstimate(dB_a_at_1m, dominant_frequencies_Hz,
       headroom_to_threshold_dB, dominant_mechanism)`.
- [ ] `DesignResult.acoustic: Optional[NoiseEstimate]` —
      populated by the engine when material has `lambda_s` set.
      Otherwise `None` and the UI surfaces a "no λ_s data" hint
      instead of a misleading number.

## Phase 6 — Optimizer integration

- [ ] Add `"noise"` to `OptimizerFiltersBar.OBJECTIVES` with hint
      "Quietest @ rated load — A-weighted SPL at 1 m".
- [ ] Both simple-optimizer `rank()` and cascade client-side
      reranker honour the new key.

## Phase 7 — UI: Analysis tab card

- [ ] `ui/dashboard/cards/acoustic_card.py`:
      - SPL gauge widget (0–60 dB(A), green ≤ 30, amber 30–45,
        red > 45).
      - Dominant-frequency mini bar chart.
      - Mechanism chip ("Magnetostriction" / "Winding" /
        "Bobbin resonance").
      - Threshold slider (defaults from spec.application_class).
- [ ] Mount as a 4th card on the Analysis tab.

## Phase 8 — Calibration via bench

- [ ] In `add-validation-reference-set` notebooks, capture
      dB(A) at 1 m via a calibrated mic per design.
- [ ] Compare predicted vs. measured; if delta > 3 dB(A) on any
      design, file a calibration bug.
- [ ] Document accuracy ±3 dB(A) in the model docstring + the
      `docs/acoustic.md` page.

## Phase 9 — Docs + release

- [ ] `docs/acoustic.md`: physics summary, λ_s sources, model
      limits (cooling fan / chassis vibration not included).
- [ ] CHANGELOG + README mention "Acoustic prediction".
