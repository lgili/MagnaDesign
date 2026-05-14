# 08 — Engine vs Direct Backend Parity

**Status**: LIVE — *the* most important contract to understand
**Code**: `design/engine.py:_resolve_gap_and_AL` ↔ `fea/direct/physics/reluctance_axi.py:solve_reluctance_from_core`
**Tests**: `tests/test_closed_path_no_autogap.py`

The project ships **two independent solvers** for the same problem:

1. **Analytical engine** (`design/engine.py`) — the design hot path.
   Runs `N` searches against `L_target`, `B_sat_limit`, `Ku_max`
   thousands of times per optimization sweep.
2. **Direct FEA backend** (this directory) — the validation path
   called after the engine settles. Sanity-checks the engine's
   answer against a more physically-grounded model.

When you feed them the same `(core, material, N, I, gap)`, they
**must** return the same `L` and `B_pk` to within numerical
precision. Any discrepancy is a bug. This file documents the
contract, the invariants that enforce it, and the history of how
we got it wrong before.

## 1. Why two paths exist

| Concern | Analytical engine | Direct FEA backend |
|---|---|---|
| Primary job | Design loop (sweep N, gap, …) | Validation after design lands |
| Cold-import cost | ~10 ms (no FEA imports) | ~50 ms |
| Per-solve cost | ~50 μs (Numba JIT) | ~400 μs (Python) |
| Outputs | L, B_pk, P_cu, P_core, T | + field PNGs, energy decomposition |
| Coupled physics | Steinmetz + Dowell + thermal | Same + reluctance / FEM option |
| Used by | Optimizer, cascade, Tweak dialog | "Validar" tab, PDF report, FEA gallery |

The engine is **fast and serial**: it has to evaluate 10⁵+ candidates
during a Bayesian optimization sweep. The direct backend is **deeper
and slower**: it produces artefacts (PNG heatmaps, energy
decomposition, mesh diagnostics) the UI surfaces.

If we collapsed them into one module, either:
- The engine becomes slow (FEA imports + result projection), or
- The direct backend loses its independence (any bug propagates to
  every optimizer iteration).

Keeping them separate is the right architectural choice — provided
they agree.

## 2. The contract (formal)

Given any tuple `(core, material, wire, N, I, gap_override)`, both
solvers must return:

```
|L_engine − L_direct|  /  L_direct   <   ε    (≤ 1 % typical; < 5 % worst)
|B_engine − B_direct|  /  B_direct   <   ε

method_engine = method_direct       (catalog_AL vs reluctance must match)
```

The threshold `ε` is benchmark-driven:

| Scope | ε target | Source |
|---|---:|---|
| Si-Fe / amorphous / nano closed cores | < 1 % | `test_line_reactor_si_fe_engine_vs_direct_agree` |
| Ferrite gapped boost-PFC | < 5 % | `test_ferrite_autogap_applies_roters_fringing` |
| Toroid powder + ferrite | < 1 % | sweep at `09-validation-benchmarks.md` |

## 3. The invariants that enforce the contract

There are four hard requirements baked into the code, each backed by
a test:

### 3a. Closed-path materials never get auto-gapped

```python
_CLOSED_PATH_MATERIAL_TYPES = frozenset(
    {"silicon-steel", "amorphous", "nanocrystalline"}
)
```

`design/engine.py:_CLOSED_PATH_MATERIAL_TYPES`. These laminations
ship as **closed magnetic paths by design** — high μ_i + high B_sat
means line-frequency reactors are sized by N alone, no gap needed.
Adding a gap only reduces L without saturation benefit.

Test: `test_silicon_steel_skip_autogap`.

### 3b. Closed shapes never get auto-gapped

```python
_CLOSED_PATH_SHAPES = frozenset({"toroid", "toroidal", "t"})
```

Toroids physically cannot host a discrete air gap — the catalog
`lgap_mm` (if non-zero) reflects a manufactured cut + epoxy
re-bond. The auto-gap path is bypassed.

Test: `test_closed_path_shapes_skip_autogap` (in the same module).

### 3c. The fringing formula is bit-for-bit identical

```python
# In design/engine.py (engine's copy):
def _fringing_factor_roters(lgap_mm, w_centerleg_mm) -> float:
    if lgap_mm <= 0 or w_centerleg_mm <= 0:
        return 1.0
    k = 1.0 + 2.0 * math.sqrt(lgap_mm / w_centerleg_mm)
    return max(1.0, min(k, 3.0))


# In fea/direct/physics/reluctance_axi.py (direct's copy):
def fringing_factor_roters(lgap_mm, w_centerleg_mm) -> float:
    # ... identical body ...
```

Two copies because `design.engine` cannot import `fea` (cold-start
cost). The parity is enforced by:

```python
def test_fringing_factor_matches_direct_backend_implementation():
    for lgap, w in [(0.5, 14), (3.4, 14.4), (5.6, 13.1), (10, 5), (0, 14)]:
        assert engine_k(lgap, w) == pytest.approx(direct_k(lgap, w))
```

### 3d. The gap-sizing iteration uses the same fringing factor

When the engine auto-sizes a gap for a saturating ferrite, it must
apply the same Roters factor the direct backend's reluctance solver
will apply later — otherwise the engine's reported `L` differs from
direct's `L_FEA`. The fixed-point iteration in
`_solve_lgap_with_fringing` handles this:

```
l_gap = (l_eff − l_e/μ_r) · k_fringe(l_gap)        (iterate)
```

(see `03-fringing-roters.md` §4 for the full derivation).

Test: `test_ferrite_autogap_applies_roters_fringing`.

## 4. Bug history — what happened before the fixes

This is the journal of how we got here. Each row is a real
disagreement found in May 2026 and the fix that closed it.

| Date | Case | `L%err` before | Root cause | Fix |
|---|---|---:|---|---|
| 2026-05 | Si-Fe EI3311 line reactor 30A | **+174 %** | Engine auto-gapped a closed Si-Fe lamination core, injecting a phantom 11.9 mm gap | `_CLOSED_PATH_MATERIAL_TYPES` gate |
| 2026-05 | Toroid 3C90 boost PFC | **+1577 %** | Engine auto-gapped a closed toroid; direct's toroidal solver ignored the phantom gap | `_CLOSED_PATH_SHAPES` gate |
| 2026-05 | Ferrite PQ40/40 boost PFC | **+120 %** | Engine sized gap with `k=1`; direct applied Roters `k=2.21` to the same gap | `_solve_lgap_with_fringing` iteration |
| 2026-05 | Ferrite ETD49 boost PFC | **+96 %** | Same as above | Same fix |

After the three fixes, the boost-PFC sweep on 29 feasible cores shows
median 0.22 %, max 6.3 %. (`09-validation-benchmarks.md` §3.)

## 5. The two "fast paths" — when they trigger and when they don't

Both solvers have a **catalog-AL fast path** that uses
`L = A_L · N² · μ_pct(H)` directly. The fast paths fire when:

| Condition | Engine | Direct |
|---|---|---|
| Powder material (`rolloff != None`) | ✅ fast path | ✅ fast path |
| Closed-path material/shape | ✅ fast path | ✅ fast path |
| Ferrite, catalog `lgap_mm > 0` | ✅ via `_resolve_gap_and_AL` (recomputes `AL_eff`) | ✅ if `gap_mm not in kwargs` |
| Ferrite, `lgap_mm == 0` (auto-gap) | Recomputes `AL_eff` after fringing iter | Fast path with that `AL_eff` |
| User overrides `gap_mm` | Recomputes `AL_eff` with fringing | Falls back to explicit reluctance |

The handshake is: **engine writes `AL_eff` into the `core` it passes
forward; direct reads that `AL_eff` and uses the fast path** — so
both arrive at the same `L`. The fringing is computed once (in the
engine) and consumed implicitly (by the direct backend's fast path
that takes the modified `AL`).

When the user overrides `gap_mm`, the contract is reversed: the
direct backend has more information (the actual gap), so it falls
back to explicit reluctance with Roters fringing. The engine's
analytical result may differ from the direct backend's by the
fringing factor (this is documented to the user as "design L vs FEA
L" in the validation panel).

## 6. The validation panel surfaces the parity

`FEAValidation` (in `pfc_inductor.fea.models`) carries both numbers:

```python
@dataclass
class FEAValidation:
    L_analytic_uH: float       # from engine.design (L_actual_uH)
    L_FEA_uH: float            # from direct backend
    L_pct_error: float         # (FEA − analytic) / analytic · 100

    B_pk_analytic_T: float
    B_pk_FEA_T: float
    B_pct_error: float
    ...
```

The UI shows both with a warning banner when `|L_pct_error| > 5 %`.
This is the **end-user-visible parity check** — it's not just a
debug log.

## 7. What to do when they disagree

If you see `|L_pct_error| > 5 %` in the validation panel:

1. **Is the design feasible?** Check `B_pk_T < 0.95 · B_sat_100C_T`
   and `N_turns < 500`. Infeasible designs are unstable comparisons.
2. **Is the gap pathological?** Check `gap_actual_mm < 0.3 · w_leg`.
   Above that ratio, the Roters model itself is the bottleneck — the
   factor is clamped at 3.0 and physical reality may differ.
3. **Is the catalog entry suspect?** A 70 %+ disagreement often
   points to a catalog import bug (see the Magnetics LP case in
   `10-known-limitations.md`).
4. **Did someone edit only one fringing function?** The bit-for-bit
   parity test should catch this, but if you skipped the test suite
   you'll get drift.
5. **Is `material.rolloff` populated unexpectedly?** Si-Fe / amorphous
   materials with a stray `rolloff` block will bypass the
   closed-path gate. Audit the catalog YAML.

## 8. Code map

| Concern | Engine side | Direct backend side |
|---|---|---|
| Auto-gap decision tree | `design/engine.py:_resolve_gap_and_AL` | n/a (consumes engine's `core`) |
| Closed-path material gate | `design/engine.py:_CLOSED_PATH_MATERIAL_TYPES` | n/a |
| Closed-path shape gate | `design/engine.py:_CLOSED_PATH_SHAPES` | n/a |
| Roters factor | `design/engine.py:_fringing_factor_roters` | `physics/reluctance_axi.py:fringing_factor_roters` |
| Fringing-aware iteration | `design/engine.py:_solve_lgap_with_fringing` | n/a |
| L computation | Numba kernel `engine.py:_build_solve_n_kernel` | `physics/reluctance_axi.py:solve_reluctance_from_core` |
| Bit-for-bit parity test | — | `tests/test_closed_path_no_autogap.py::test_fringing_factor_matches_direct_backend_implementation` |
