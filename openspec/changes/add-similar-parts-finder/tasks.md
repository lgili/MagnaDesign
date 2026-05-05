# Tasks — Similar parts finder

## 1. Match logic

- [x] 1.1 `optimize/similar.py::SimilarityCriteria` dataclass:
      `Ae_pct=10, Wa_pct=15, AL_pct=20, mu_r_pct=20, Bsat_pct=15,
      same_shape=True, same_vendor=False, exclude_self=True`.
- [x] 1.2 `similar.py::find_equivalents(target_core, target_material,
      cores, materials, criteria) -> list[SimilarMatch]` →
      filters then ranks by composite distance.
- [x] 1.3 Distance metric: weighted Euclidean over normalized parameter
      deltas; weights configurable per criteria.

## 2. Cross-material variants

- [x] 2.1 For each candidate core, also enumerate "same shape + alternate
      material" by checking which materials the same vendor produces in
      the same family (e.g. Magnetics's HighFlux 60µ shape exists in
      Kool Mu 60µ, MPP 60µ, XFlux 60µ).
- [x] 2.2 Recompute the design quickly (sweep/run engine) for each
      cross-material option to surface the actual L/B/loss change.

## 3. UI

- [x] 3.1 Add "Achar similares" button to result panel header next to
      the core name.
- [x] 3.2 `ui/similar_parts_dialog.py` shows:
      - Top: the target core's KPIs
      - Below: scrollable table of matches (one row per match), columns
        for vendor, part number, Δ Ae %, Δ Wa %, Δ AL %, Δ Bsat %, $.
      - Clickable row → "Apply" button updates spec_panel.
- [x] 3.3 Filter widget: tolerance sliders, "same shape" toggle, "include
      cross-material" toggle.

## 4. Testing

- [x] 4.1 Test: target=Magnetics High Flux 60µ toroid 0058072A2, with
      defaults, returns ≥1 alternative from CSC, Magmattec, or Micrometals.
- [x] 4.2 Test: ranking distance is symmetric and zero for identical core
      (when exclude_self=False).
- [x] 4.3 Test: tightening tolerance to 5% reduces the match count.

## 5. Docs

- [x] 5.1 README: similar-parts feature note.
