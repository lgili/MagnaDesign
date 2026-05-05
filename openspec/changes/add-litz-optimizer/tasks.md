# Tasks — Litz wire optimizer

## 1. Math

- [x] 1.1 `optimize/litz.py::sullivan_strand_diameter(f_Hz, layers)` →
      d_strand = 2·δ(f_Hz) · √(η · π / (Nₗ²))  (Sullivan 1999, eq. 17).
- [x] 1.2 `litz.py::strand_count_for_current(I_rms, J_target_A_per_mm2,
      d_strand_mm)` → ceil(A_required / A_strand).
- [x] 1.3 `litz.py::bundle_diameter_mm(n_strands, d_strand, packing=0.7)`
      → bundle outer diameter incl. service factor.
- [x] 1.4 `litz.py::Wire_from_litz_construction(...) -> Wire` — builds
      a `Wire` model from raw construction.

## 2. Optimizer

- [x] 2.1 `litz.py::recommend(spec, core, target_J_A_mm2=4.0,
      target_AC_DC=1.10, max_strands=2000)` → returns best Litz `Wire`
      and DesignResult, plus a comparison vs the best round AWG wire from
      the existing DB.
- [x] 2.2 Search space: strand AWG ∈ [32..44] (d ≈ 0.05..0.20 mm).
      Strand count derived to hit `target_J_A_mm2`.
- [x] 2.3 Score: P_total_W subject to feasibility constraints
      (window utilization, T_winding ≤ T_max, Bsat margin).

## 3. UI

- [x] 3.1 Optimizer dialog: new tab "Litz" alongside "Núcleos × Fios".
- [x] 3.2 Inputs: target J [A/mm²] (default 4), target AC/DC ratio
      (default 1.10), max bundle diameter (mm).
- [x] 3.3 Output: best Litz construction with details (strand AWG/count,
      d_bundle, A_cu, AC/DC ratio at fsw); side-by-side with best
      round-wire result.
- [x] 3.4 "Save as new wire" button → writes to user-data wires.json
      via `data_loader.save_wires`.

## 4. DB editor enhancement

- [x] 4.1 In `ui/db_editor.py`, on the Wires tab, add an extra "Adicionar
      Litz" button that opens a small form (strand AWG, count, twist
      factor) and creates the entry programmatically.

## 5. Testing

- [x] 5.1 Unit test: Sullivan formula at 100 kHz, 1 layer → ~0.1 mm
      strand (within published range).
- [x] 5.2 Test: `recommend` for a 800 W boost CCM at 65 kHz returns a
      Litz with 100..400 strands of AWG 38..42 (sanity range).
- [x] 5.3 Test: AC/DC ratio of recommended Litz at fsw is within 1%
      of target.

## 6. Docs

- [x] 6.1 README: "Litz optimizer" feature note + reference to Sullivan.
