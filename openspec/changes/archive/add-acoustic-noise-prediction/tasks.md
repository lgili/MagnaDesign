# Tasks — add-acoustic-noise-prediction

## Phase 1 — Material data

- [~] Add `magnetostrictive_lambda_s_ppm: Optional[float]` to the
      `Material` Pydantic model. *Deferred — kept the lookup as
      a hardcoded class-based table inside `acoustic/model.py`
      (`magnetostrictive_lambda_s_ppm(material) -> float`) so
      `.pfc` files continue to round-trip without a schema
      migration. The function inspects the material class /
      vendor and returns the calibrated baseline; the table can
      promote to a per-material JSON field later without
      breaking back-compat.*
- [x] Bundle baseline λ_s values for the curated materials
      (table baked into `acoustic/model.py`):
      - MnZn ferrites: 1 ppm.
      - NiZn ferrites: 30 ppm.
      - Powder cores (Kool Mµ / HighFlux / MPP): 1 ppm.
      - Silicon-steel laminations: 8 ppm.
      _Shipped in `5e013ea feat(acoustic): A-weighted SPL
      estimator (compressor-VFD focus)`._
- [~] Cite the datasheet source per material in the JSON.
      *Deferred — citations live in the function's docstring;
      promote to JSON when the schema migration above lands.*

## Phase 2 — Magnetostriction model

- [x] `pfc_inductor/acoustic/model.py`:
      - `_spl_magnetostriction_dba(...)` — SPL contribution at
        1 m using λ_s × B_pk² × geometry → surface vibration →
        radiated SPL through empirical efficiency.
      - Returns A-weighted dB; dominant frequency is 2·fsw
        when DC-biased (rectified magnetostriction) else fsw.
      _Shipped in `5e013ea`._
- [x] Hand-calc anchor in `tests/test_acoustic_model.py` —
      MnZn ferrite at typical 100 mT, 65 kHz lands within the
      ±3 dB(A) calibration band. _Shipped in `5e013ea`._

## Phase 3 — Winding Lorentz model

- [x] `acoustic/model.py:_spl_winding_lorentz_dba(...)` — force
      per unit length between adjacent layers carrying I_ac at
      fsw → mechanical excitation → SPL. Negligible for single-
      layer designs; dominates dense multi-layer Litz at high I.
      _Shipped in `5e013ea`._
- [x] Test: multi-layer high-I_ac design → Lorentz contribution
      is non-negligible. _Shipped in `tests/test_acoustic_model.py`._

## Phase 4 — Bobbin-resonance heuristic

- [x] `acoustic/model.py:_bobbin_resonance_boost_dB(...)` — beam-
      on-supports formula with PBT defaults (E ≈ 3 GPa,
      ρ ≈ 1300 kg/m³). When fsw or 2·fsw lands within ±10 % of
      a bobbin mode, boost SPL by +6 dB and tag mechanism as
      `"bobbin_resonance"`. _Shipped in `5e013ea`. Lives inline
      in `model.py` rather than `bobbin_resonance.py` since the
      heuristic is a single function and doesn't need a
      dedicated module._
- [x] Test: combination near the first bobbin mode → flagged +
      boost applied. _Shipped in `tests/test_acoustic_model.py`._

## Phase 5 — Aggregation + DesignResult

- [x] `acoustic/model.py::estimate_noise(...)` orchestrates the
      three contributions and returns `NoiseEstimate(dB_a_at_1m,
      dominant_frequency_Hz, headroom_to_threshold_dB,
      dominant_mechanism, contributors_dba)`.
      _Shipped in `5e013ea`._
- [~] `DesignResult.acoustic: Optional[NoiseEstimate]` populated
      by the engine. *Deferred — the engine output stays stable;
      the AcousticCard runs `estimate_noise` lazily from the
      already-computed result + spec + core + wire + material so
      the schema migration isn't needed.*

## Phase 6 — Optimizer integration

- [~] Add `"noise"` to `OptimizerFiltersBar.OBJECTIVES`.
      *Deferred — current optimizer ranking honours loss / temp
      / cost / volume which already correlates with quiet
      designs (lower B_pk + lower I_ac → both quieter and lower
      loss). Promoting noise to a first-class objective lands
      after the calibration phase has more bench data.*
- [~] Simple-optimizer + cascade reranker honour the new key.
      *Deferred — see above.*

## Phase 7 — UI: Analysis tab card

- [x] `ui/dashboard/cards/acoustic_card.py`:
      - Hero label: SPL value + dominant-tone frequency in kHz.
      - Dominant-mechanism subtitle.
      - Per-mechanism contribution table (Magnetostriction /
        Winding Lorentz / Bobbin resonance).
      - Headroom-to-threshold strip with colour bands (green
        ≥ 6 dB headroom, amber ≥ 0 dB, red below threshold).
      - Hidden when the engine reports `mechanism == "none"` so
        a degenerate spec doesn't show a misleading "0 dB(A)".
      _Shipped in `3dd80bc feat(ui/analise): Acoustic-noise card
      on the Analysis tab`. 7 tests in
      `tests/test_acoustic_card.py`._
- [x] Mounted as the 6th card on the Analysis tab (after the
      modulation envelope card).

## Phase 8 — Calibration via bench

- [~] In `add-validation-reference-set` notebooks, capture
      dB(A) at 1 m via a calibrated mic per design.
      *Deferred — gated on the validation reference set landing
      with physical bench data. Software path is ready; the
      ±3 dB(A) confidence interval lands when measurements do.*
- [~] Compare predicted vs. measured; calibration bug if
      delta > 3 dB(A). *Deferred — see above.*
- [~] Document accuracy ±3 dB(A) in docstring + `docs/acoustic.md`.
      *The card already carries the "±3 dB(A) — anechoic-mic
      measurement still required for certification" caveat
      inline; the dedicated docs page lands with Phase 9.*

## Phase 9 — Docs + release

- [~] `docs/acoustic.md`: physics summary, λ_s sources, model
      limits. *Deferred — Sphinx theory site (`da5c40e`) shipped
      without a dedicated acoustic chapter; lands with the next
      docs pass.*
- [~] CHANGELOG + README mention "Acoustic prediction".
      *Deferred — README + CHANGELOG sweep planned alongside
      the next release tag.*
