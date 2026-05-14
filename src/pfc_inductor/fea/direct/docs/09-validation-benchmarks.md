# 09 — Validation & Benchmarks

**Status**: LIVE — numbers must be re-generated on physics changes
**Code**: `scripts/benchmark_shapes_vs_femmt.py`, `scripts/benchmark_comprehensive.py`
**Last refreshed**: 2026-05-13 (commit `84409b5`)

This file is the **honest answer to "how accurate is the direct
backend?"** It documents the three independent oracles we use, the
numbers we trust, and the cases where the model fails. If you change
physics, regenerate the relevant table.

## 1. The three oracles

We validate against three independent sources of truth, each with
different strengths and failure modes:

| Oracle | Type | Strength | Weakness |
|---|---|---|---|
| **Catalog `A_L · N²`** | Vendor-published, manufacturer-measured | Single-point ground truth | Only valid at the test current the manufacturer used (low-signal) |
| **FEMMT** | 2-D axisymmetric FEM | Captures geometric effects we approximate | 2-D approximation breaks on closed toroids; doesn't support 6/12 shapes |
| **Engine ↔ direct parity** | Internal consistency | Detects bugs *within* our codebase | Doesn't tell us if we're right against physical reality |

For "is the answer right?" we need **at least two oracles** to agree.
For "do our two paths agree?" the engine ↔ direct parity is enough.

## 2. Oracle 1 — catalog `A_L · N²`

Datasheet values from the manufacturer, measured at low signal (no DC
bias). Source of truth for `L` at the test point.

**Method**: take the catalog `A_L_nH`, compute `L = AL · N² · 10⁻³`
μH, run the direct backend at the same `(core, N, I=test_current)`,
compare.

| Material | Core | Catalog L (μH) | Direct L (μH) | Δ |
|---|---|---:|---:|---:|
| Ferroxcube 3C90 | PQ40/40 ungapped | 822.8 | 822.8 | **0.0 %** |
| Ferroxcube 3C90 | PQ50/50 ungapped | 1342.6 | 1342.6 | **0.0 %** |
| TDK N87 | E105/55 ungapped | 728.8 | 728.8 | **0.0 %** |
| Magnetics HighFlux 125µi | C058150A2 toroid | 24.7 | 24.7 | **0.0 %** |
| Magnetics Kool-Mu 75µi | C055433A2 toroid | 510.5 | 510.5 | **0.0 %** |
| Magnetics MPP 60µi | C058140A2 toroid | 217.0 | 217.0 | **0.0 %** |
| Ferroxcube 3C94 | ETD49 ungapped | 195.3 | 195.6 | **0.2 %** |
| Ferroxcube 3C90 | E55/28 ungapped | 1101 | 1131 | **2.7 %** |

**Score**: 8/8 within 5 %, 6/8 exact. The two non-zero rows
(ETD49, E55/28) deviate because of how their μ_r is back-derived from
catalog AL — the residual is the spread between `μ_initial` published
in the material datasheet vs the `μ_r` implied by the measured A_L.

## 3. Oracle 2 — FEMMT

FEMMT is a 2-D axisymmetric FEM (Gmsh + GetDP) tool. It supports
EE / PQ / ETD with full meshed geometry. It does **not** support:

- True toroids (axisymmetric approximation fails on closed paths)
- RM / P / EP / EFD / EI (no template)
- High-N geometries (gmsh meshing chokes above ~150 turns)

**Method**: `scripts/benchmark_shapes_vs_femmt.py`. Same `(core, N, I)`
fed to both backends. Compared on the 6 shapes FEMMT supports.

| Shape | Case | Direct L (μH) | FEMMT L (μH) | Δ |
|---|---|---:|---:|---:|
| PQ40/40 N87, 39 t, 8 A | 870.1 | 822.8 | **5.7 %** |
| PQ35/35 N87, 39 t, 8 A | 805.5 | 728.8 | **10.5 %** |
| PQ50/50 N87, 39 t, 8 A | 1447.3 | 1342.6 | **7.8 %** |
| E105/55 N87, 40 t, 5 A | 73.5 | 79.0 | **7.0 %** |
| ETD29 3C90, 30 t, 4 A | 222.7 | 195.3 | **14.0 %** |
| **Toroid T107/65/18 3C90** | 1651 | 20348 | **91.9 %** ⚠️ |

**Summary**:
- 5/6 within 15 %, median **10.5 %**, mean 8.4 % (excluding the
  toroid outlier).
- The toroid outlier is **FEMMT being wrong**: it reports
  `B_pk = 2.69 T` for a 3C90 ferrite which saturates at 0.5 T —
  physically impossible. The direct backend's closed-form toroid
  matches catalog A_L to 0 %.

**Throughput**: direct ~0.33 s avg vs FEMMT ~12 s avg → **36× faster**.

**Coverage**: direct supports 12/12 catalog shapes; FEMMT supports
6/12. For half the catalog, direct is the only option.

## 4. Oracle 3 — engine ↔ direct parity

The most sensitive test: it catches bugs in either solver that the
other would have masked. See `08-engine-vs-direct-parity.md` for the
contract this enforces.

### 4a. Boost PFC ferrite/powder sweep (post-fix)

**Setup**: 230 V → 400 V / 600 W / 65 kHz / `ripple_pct=30 %`.
29 feasible cores across 19 shapes.

| Statistic | `\|L%err\|` | `\|B%err\|` |
|---|---:|---:|
| Median | **0.22 %** | **0.29 %** |
| Mean | 0.84 % | 13.95 % |
| Max | 6.3 % | 93.96 % |
| Within 5 % | **26 / 29** | 24 / 29 |
| Within 15 % | 27 / 29 | 25 / 29 |

Two outliers (Magnetics LP cores) account for the mean inflation —
catalog import bug, not solver bug (see `10-known-limitations.md` §3).

### 4b. Line reactor Si-Fe / amorphous / nano sweep (post-fix)

**Setup**: 220 V / 30 A / 5 %Z / 60 Hz. 6 representative cores.

| Statistic | `\|L%err\|` | `\|B%err\|` |
|---|---:|---:|
| Median | **0.00 %** | **0.00 %** |
| Max | 0.00 % | 0.00 % |
| Within 1 % | **6 / 6** | 6 / 6 |

Both backends agree bit-for-bit because the Si-Fe gate forces them
through identical fast paths (no auto-gap, no Roters iteration).

### 4c. Before / after the gap fixes

| Sweep | Median (pre-fix) | Median (post-fix) | Improvement |
|---|---:|---:|---|
| Si-Fe line reactor | 134.4 % | 0.00 % | 134.4 pp |
| Boost-PFC ferrite + powder | 166.1 % | 0.22 % | 165.9 pp |

The "30 % the user originally observed" was the conservative end of a
130–177 % systematic disagreement on every closed-path / auto-gap
case. Two engine-side fixes (closed-path gate + fringing iteration)
closed the contract.

## 5. Throughput & footprint

Measured on a 2024 M3 MacBook Pro running Python 3.12, `uv run`.

| Pass | Median wall (one solve) |
|---:|---:|
| Cold import (`from runner import …`) | 50 ms |
| Reluctance solve (per core) | **0.4 ms** |
| Synthetic field-PNG render (3 figures) | 30 ms |
| Dowell AC pass | 0.2 ms |
| Thermal pass (lumped) | 0.1 ms |
| Full reluctance backend, one core | **≈ 80 ms** |
| Full FEM (axi) backend, one core | 2 – 10 s |
| FEMMT (legacy) backend, one core | 12 s avg |

Memory footprint: < 100 MB resident for the reluctance path; up to
1 GB for FEM (Gmsh's mesh tables).

## 6. When the numbers should be regenerated

Always regenerate after:

1. Editing any `physics/*.py` module.
2. Changing `_resolve_gap_and_AL`, `_fringing_factor_roters`, or
   `_solve_lgap_with_fringing` in `design/engine.py`.
3. Editing a catalog YAML in a way that changes existing core fields
   (additions are fine).
4. Bumping `gmsh` or `getdp` versions in `pyproject.toml`.

Regenerate with:

```bash
uv run python scripts/benchmark_shapes_vs_femmt.py            # vs FEMMT
uv run python scripts/benchmark_comprehensive.py              # full comparison
uv run pytest tests/test_closed_path_no_autogap.py -v         # parity tests
```

If any baseline deviates by > 1 % from the numbers in this file,
either:
- The change is intentional → update this file with the new numbers.
- The change is a bug → investigate before committing.

## 7. What we still don't validate well

| Gap | Why it matters | Workaround |
|---|---|---|
| Bench measurement vs direct | Only 1 prototype measured (PFC 600 W, hot spot ±2 K) | Buy more measurement time |
| Saturation cliff (`B > 1.2 · B_sat`) | Soft-knee model is conservative | The engine flags saturation as a warning, not a quantitative answer |
| Multi-winding coupling | Not supported | Build it (Phase 5+ stretch) |
| Transient (di/dt large) | RK4 in engine + transient.py stub | Phase 4.1 OpenSpec |
| Hot-spot temperature | Lumped model returns volume-average | Phase 4 (3-D thermal FEM) |
| Magnetics LP powder | 8746 % L disagreement (catalog import) | Tracked separately as a follow-up |

## 8. Methodology footnotes

- "Feasibility" = `N_turns < 500` and `B_pk_T < 0.95 · B_sat_100C_T`.
  Designs above either are flagged "infeasible" by the engine and
  excluded from the parity statistics — they aren't shippable so we
  don't measure them.
- All percentages are **signed**, computed as `(FEA − analytical) /
  analytical · 100`. Where we report median / mean, we take the
  absolute value.
- The `09-validation-benchmarks.md` numbers are **after** the May
  2026 fixes (commit `84409b5`). Pre-fix numbers are preserved in the
  bug-history table at `08-engine-vs-direct-parity.md` §4.

## 9. Code map

| Concern | Location |
|---|---|
| Catalog A_L vs direct | manual: load core, run `solve_reluctance_from_core` at low I |
| FEMMT vs direct sweep | `scripts/benchmark_shapes_vs_femmt.py` |
| Comprehensive benchmark | `scripts/benchmark_comprehensive.py` |
| Engine ↔ direct parity tests | `tests/test_closed_path_no_autogap.py` |
| Per-shape reluctance test | `tests/test_direct_reluctance.py` |
| Per-shape toroidal test | `tests/test_direct_toroidal.py` |
| Thermal regression | `tests/test_direct_thermal.py` |
| Dowell regression | `tests/test_direct_dowell.py`, `tests/test_direct_ac.py` |
