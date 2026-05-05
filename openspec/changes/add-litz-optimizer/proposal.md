# Add Litz wire optimizer

## Why

For PFC inductors above ~50 kHz, single-strand round wire incurs
significant skin-effect loss; Litz wire mitigates it but introduces
choices: strand gauge, strand count, twist construction, bundle diameter.
Today our wire database has a few hand-picked Litz entries and the
designer has to guess which fits the operating point.

Ferroxcube SFDT and Frenetic AI both ship Litz optimizers. The math is
well-established (Sullivan 1999, Hurley & Wölfle Ch. 8). It's a small,
self-contained module that drops into our existing `physics.dowell` and
`optimize.sweep`.

## What changes

- New module `optimize/litz.py` with:
  - `optimal_strand_diameter(f_Hz, target_AC_DC_ratio=1.10)` per Sullivan.
  - `optimal_strand_count(I_rms, target_J_A_per_mm2=4)`.
  - `recommend_litz(spec, core, candidate_wires)` returning the best
    Litz construction (or `None` if single-strand round is better).
- New tab "Otimizador de Litz" inside the optimizer dialog: instead of
  iterating discrete wire IDs, *generate* candidate Litz constructions on
  the fly and evaluate them.
- Wire DB editor: "New Litz wire" form that takes (strand AWG, count,
  twist factor) and computes A_cu, d_bundle, AC/DC factor at fsw, then
  saves it as a new entry.

## Impact

- Affected capabilities: NEW `litz-optimization`
- Affected modules: NEW `optimize/litz.py`, `optimize/sweep.py`
  (extension), `ui/optimize_dialog.py` (new tab/button), `ui/db_editor.py`
  (new Litz form), `physics/dowell.py` (no changes; we already model Litz).
- No new deps.
- Medium effort, mostly bound by good UX for the Litz form.
