# 11 — Extending the Backend

**Status**: LIVE — recipe-driven
**Code**: see step-by-step pointers below

This is the **operational playbook for adding a new shape, material,
or physics** to the direct backend. Each section is a recipe:
inputs, steps, tests to write, gotchas. If you can't complete a
recipe in a couple of hours, ping back and we'll either expand the
recipe or remove the ambiguity in the underlying code.

---

## 1. Adding a new core shape

**Effort**: 2–4 hours for a shape similar to existing ones.

**Inputs you need**:
- The shape name (must match what `core.shape` carries, lowercased).
- Catalog `A_e`, `l_e`, `A_L`, plus enough geometry to compute
  `w_centerleg_mm` (or use `√A_e` if dimensions aren't published).
- One representative catalog YAML entry to use in tests.

### Steps

**1.1.** Decide which path the shape goes through:

| Path | When | Where to plug in |
|---|---|---|
| Toroidal closed-form | Closed magnetic path with `1/r` field | `_TOROIDAL_SHAPES` in `runner.py:105` |
| Reluctance (default) | Anything with `A_e` and `l_e` | already automatic |
| Axisymmetric FEM | Complex geometry needing field plots | `_AXI_SHAPES` in `runner.py:104` |

The reluctance path is **automatic for any shape with `A_e, l_e`**.
You only need code changes when the shape needs a closed-form
(toroidal) or full FEM treatment.

**1.2.** Add the shape to the appropriate set:

```python
# In src/pfc_inductor/fea/direct/runner.py:
_TOROIDAL_SHAPES = frozenset({"toroid", "toroidal", "t",
                               "your_new_shape"})       # if toroidal
_AXI_SHAPES = frozenset({"ei", "ee", "e", "pq", ...,
                          "your_new_shape"})            # if axi
```

**1.3.** If the shape is **closed by topology**, also add it to:

```python
# In src/pfc_inductor/design/engine.py:
_CLOSED_PATH_SHAPES = frozenset({"toroid", "toroidal", "t",
                                   "your_new_shape"})
```

Otherwise the engine will auto-gap it like a ferrite EE → see
`08-engine-vs-direct-parity.md` §4.

**1.4.** If using **toroidal closed-form**, supply the geometry:

`solve_toroidal` requires `OD`, `ID`, `HT`. If the catalog only ships
aggregate `A_e, l_e`, route through `solve_toroidal_aggregate` instead
(no code change — the dispatcher picks based on populated fields).

**1.5.** If using **full FEM**, add a geometry builder:

Create `src/pfc_inductor/fea/direct/geometry/<shape>.py` (or
`<shape>_axi.py` for axisymmetric). Subclass `CoreGeometry`,
implement `build(gmsh_module, model_name) → GeometryBuildResult`.
Use `ei.py` (planar) or `ei_axi.py` (axisymmetric) as templates.

**1.6.** Write the tests:

```python
# tests/test_direct_<shape>.py

def test_<shape>_reluctance_default_path():
    # Build a synthetic core with A_e, l_e, A_L
    # Call run_direct_fea(backend="reluctance")
    # Assert L matches A_L · N² × 10⁻³ within 1%
    ...

def test_<shape>_vs_catalog_A_L():
    # Load a real catalog entry
    # Assert L matches catalog A_L × N² within 5%
    ...

def test_<shape>_engine_vs_direct_parity():
    # Run engine.design + run_direct_fea
    # Assert L_pct_error < 5%
    ...
```

**1.7.** Update `09-validation-benchmarks.md` with a row for the
new shape in the "Catalog A_L · N²" oracle table.

### Gotchas

- If you forget step **1.3** for a closed shape, the parity test
  (1.6) will fail with a 100–200 % L_pct_error.
- If `w_centerleg_mm` can't be derived from `√A_e`, supply an
  explicit field. Roters extrapolates badly otherwise.
- For axisymmetric FEM (1.5), get the source-area correction right:
  `coil_area_m2 = A_2d × 2π · R_mean` — see `runner.py:309`. Off by
  a factor of `2π` is the most common Phase-1.5 calibration trap.

---

## 2. Adding a new material type

**Effort**: 30 min – 2 hours depending on rolloff data availability.

**Inputs you need**:
- Material type name (extends the `MaterialType` literal in
  `models/material.py`).
- Datasheet values: `μ_initial`, `B_sat_25C_T`, `B_sat_100C_T`.
- Steinmetz coefficients (`Pv_ref_mWcm3, alpha, beta`) for core loss.
- Optionally: `rolloff (a, b, c)` for DC-bias decay; `complex_mu_r`
  table for frequency-dependent dispersion.

### Steps

**2.1.** Add to the `MaterialType` literal:

```python
# In src/pfc_inductor/models/material.py:
MaterialType = Literal[
    "powder", "ferrite", "nanocrystalline", "amorphous",
    "silicon-steel", "your_new_type",
]
```

**2.2.** Decide if the material is closed-path:

For a closed magnetic path (high μ_i, high B_sat, no discrete gap by
design), add it to:

```python
# In src/pfc_inductor/design/engine.py:
_CLOSED_PATH_MATERIAL_TYPES = frozenset({
    "silicon-steel", "amorphous", "nanocrystalline",
    "your_new_type",
})
```

**2.3.** Decide which rolloff model to use:

| Model | Catalog field | Use when |
|---|---|---|
| None | `rolloff = None` | Material has flat μ until knee (ferrite, Si-Fe) |
| Magnetics 3-param fit | `rolloff = RolloffParams(a, b, c)` | DC-bias decay published |
| Soft polynomial knee | (no field; auto via `B/B_sat`) | Ferrite without published μ(H) |

**2.4.** Add at least one catalog material YAML and one catalog core
that uses it (in `data/materials/` and `data/cores/`).

**2.5.** Write tests:

```python
def test_<material_type>_uses_correct_path():
    mat = load_material("your-id")
    assert mat.type == "your_new_type"

def test_<material_type>_no_autogap_if_closed_path():
    # Build a core with this material
    # Run _resolve_gap_and_AL
    # Assert AL_eff == catalog AL (no overwrite)
```

### Gotchas

- The material-type filter at `topology/material_filter.py` maps each
  topology to allowed material types. **Update that file too** or
  your new material won't appear in the UI's material dropdown.
- If the material is a Si-Fe variant, make sure it's tagged
  `"silicon-steel"` (the canonical type) rather than a synonym —
  otherwise the closed-path gate misses it.

---

## 3. Adding a new physics module

**Effort**: 4–20 hours depending on complexity.

**Examples of what fits here**: AC-FEM solver, full hysteresis model,
ROM proxy, 3-D extension.

### Steps

**3.1.** Decide on the module's contract:
- What dataclass does it consume? (`DirectFeaResult`, `ReluctanceInputs`, etc.)
- What does it return? (`DirectFeaResult` extension, or new dataclass)

**3.2.** Create the module under `physics/<concern>.py` with a clear
opening docstring that links to the relevant doc file in this
directory. Mirror the existing physics modules' style.

**3.3.** Wire it into `runner.py`:
- If it composes onto a DC solve, add a `_apply_<concern>_if_requested`
  helper at the end of `run_direct_fea` (mirror
  `_apply_dowell_ac_if_requested`).
- If it replaces a DC solve, add a `backend` value (extend the
  dispatch tree in `runner.py:107`).

**3.4.** Add tests:

```python
# tests/test_direct_<concern>.py

def test_<concern>_basic_path():
    # Smoke test that returns at all
    ...

def test_<concern>_matches_engine_analytical():
    # Cross-check against any analytical equivalent
    ...

def test_<concern>_handles_edge_case_X():
    # Edge cases discovered during development
    ...
```

**3.5.** Document:

Add a new doc file `NN-<concern>.md` in this directory, following the
template:

```markdown
# NN — Concern Name

**Status**: LIVE / RESEARCH / FUTURE
**Code**: pointers
**Tests**: pointers

## Purpose
## Symbols
## Equations / Algorithm
## Validation
## Known Limitations
## Code Map
## References
```

**3.6.** Update `00-README.md`'s reading order to include the new
doc.

### Gotchas

- Don't import `gmsh` or `pyvista` eagerly in the module — keep it
  lazy. The reluctance path's 80 ms total wall budget assumes no FEA
  imports occur unless `backend="axi"` or `"planar"`.
- Don't bypass `models.DirectFeaResult` — even if your new physics
  returns extra fields, project them onto that dataclass at the
  module boundary. The cascade and UI assume the contract.

---

## 4. Adding a regression benchmark

**Effort**: 1 hour.

When you fix a bug or add coverage to a previously-untested case,
capture it as a new row in the benchmark sweep:

**4.1.** Add a case tuple to `scripts/benchmark_comprehensive.py`:

```python
cases = [
    ...,
    ("your-new-core-id", "Description", "Material type", "topology",
     N_expected_range),
]
```

**4.2.** Run the sweep, confirm the new case shows the expected
result, commit.

**4.3.** Update `09-validation-benchmarks.md` with the new row.

---

## 5. Adding a parity invariant

If you discover a new way the engine and direct backend can
disagree, formalize it as a test:

**5.1.** Add the test case to `tests/test_closed_path_no_autogap.py`
(or a more specific file if the concern is narrow).

**5.2.** Document the invariant in `08-engine-vs-direct-parity.md`
§3 as a numbered guarantee.

**5.3.** If the fix involves duplicated code (like the Roters
factor in two places), add a bit-for-bit parity test.

---

## 6. When NOT to extend

- **Don't add a fourth FEA backend.** Reluctance + axi FEM + planar
  FEM is enough. The next addition should be 3-D, not yet another
  2-D approximation.
- **Don't add per-shape physics overrides** unless the shape
  fundamentally breaks the assumptions of the reluctance model
  (only toroids meet this bar today).
- **Don't add catalog-specific kludges** in code. If a particular
  vendor's catalog ships pathological values (see Magnetics LP), fix
  it at import time, not in the solver.

---

## 7. Reviewing your change

Before merging:

- [ ] All tests pass (`uv run pytest -q`).
- [ ] Parity tests pass (`uv run pytest tests/test_closed_path_no_autogap.py`).
- [ ] Benchmark sweep regenerated and `09-validation-benchmarks.md`
  numbers updated if you touched physics.
- [ ] The relevant doc file in this directory is updated (new code
  goes into the right `NN-*.md`).
- [ ] No FEA-side imports leak into `design/engine.py`.

If you're unsure where a change belongs, default to:

1. **The narrowest scope** — start in `fea/direct/physics/`, not at
   the runner level.
2. **The most-tested path** — extend a test before changing the code
   it exercises.
3. **The doc first** — if you can't describe what you're about to
   change in a paragraph here, the change isn't ready.
