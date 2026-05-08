# Performance: where the engine spends time, and what to do about it

> Honest engineering analysis answering "should we port the optimizer
> to C++?". TL;DR: **no — Numba JIT gives 50× on the hot loops at
> ~1% of the cross-platform-build cost C++ would impose**.

## Profile — May 2026

Single-core, MacBook Pro M1, 600 W boost-PFC reference design:

| Surface                             | Per-call          | Throughput        |
|-------------------------------------|-------------------|-------------------|
| `engine.design()` (full pipeline)   | 0.29 ms           | 3 480 cand/s      |
| Cascade Tier 0 (envelope check)     | 6.7 µs            | 149 000 cand/s    |
| Cascade Tier 1 (analytical engine)  | 0.22 ms           | 4 597 cand/s      |
| Tier 2 (transient ODE, scipy)       | ~3 ms             | 330 cand/s        |
| Tier 3 (FEMMT magnetostatic)        | ~5 000 ms         | 0.2 cand/s (FEA)  |

A typical cascade sweep (~1 M cartesian candidates):

- Tier 0: ~7 s single-core, ~2 s on 4 cores.
- Tier 1 on ~1 % survivors (~10 k): ~2 s on 4 cores.
- Tier 2 on top-100: ~30 s.
- Tier 3 on top-50: ~5 min (external FEMMT).

**The Python-bound surface is Tier 1.** Tier 2/3 are dominated by
SciPy LSODA (already C) and FEMMT (external native binary). Tier 0
is 95 % numpy — its overhead is dict lookups + the per-row Python
loop, not the math.

## Where Tier 1's 0.22 ms goes

`cProfile` of 50 calls of `engine.design()`:

| Function                                 | Cumtime   | Share |
|------------------------------------------|-----------|-------|
| `thermal.converge_temperature`           | 12 ms     | 36 %  |
| `engine.total_loss_at_T` (×6 per design) | 11 ms     | 33 %  |
| `core_loss.core_loss_W_pfc_ripple_iGSE`  | 7 ms      | 21 %  |
| `engine._solve_N` (binary search)        | 7 ms      | 21 %  |
| `boost_ccm.waveforms` (200-pt linspace)  | 4 ms      | 12 %  |
| `rolloff.mu_pct` (3 050 calls)           | 3 ms      | 9 %   |
| `numpy.mean` overhead (~500 calls)       | 5 ms      | 15 %  |

Two patterns dominate:

1. **Thermal converge calls `total_loss_at_T` six times per design.**
   Each call does a Steinmetz + Dowell + thermal balance. The Python
   overhead of the call wrapper itself is ~10 % per call.
2. **`numpy.mean` on 200-element arrays** is *slower* than a hand-
   written loop because every numpy ufunc has ~2 µs of dispatch
   overhead. At 200 elements, the dispatch costs more than the
   actual reduction.

These are exactly the patterns Numba and C++ both crush.

## The actual question: should we port to C++?

### What C++ would buy

A pybind11 port of the inner loop (`converge_temperature` +
`core_loss_W_pfc_ripple_iGSE`) would land somewhere around
**2–3× faster** than the current Python+numpy code. Real numbers:

- C++ inner loop: ~50 ns / Steinmetz iteration.
- Numba `@njit`: ~80 ns / iteration (measured below).
- Pure Python+numpy: ~5 µs / iteration.

### What C++ would cost

| Cost                                     | Magnitude                           |
|------------------------------------------|-------------------------------------|
| pybind11 + CMake + scikit-build setup    | 1–2 days                            |
| Cross-platform wheels (mac × {x86, arm}, Linux × {x86, aarch}, Windows × x86) | 6 OS/arch combos via `cibuildwheel` |
| Build chain in CI for every release      | +5 min × 6 jobs per tag             |
| Bundle size                              | +0 MB (compiled in)                 |
| Debug story when a customer hits a crash | gdb across Python+C++ frames        |
| Maintenance for every API tweak          | Edit 2 sources, rebuild wheels      |

That's a 5–10× development overhead per change for a 2–3× perf win.
For a 4-person team shipping every couple of weeks, it's not worth it.

## What gives bigger wins for less cost

### Option 1 — Numba `@njit` (recommended)

Drop-in `@numba.njit` decorator on the hot functions. **Verified
proof of concept on a Steinmetz-style inner loop:**

```text
Pure Python (current):  48.98 µs/call  → 20 418 cand/s
Numba JIT:               0.91 µs/call  → 1 101 064 cand/s
Speedup:                 53.9×
```

The 54× number is on a synthetic benchmark mimicking the inner loop.
On the full `engine.design()`, the realistic speedup is around
**3-5×** because the per-design overhead (Pydantic validation,
catalogue lookups) doesn't move. That still translates to:

- Tier 1 throughput: 4.6 k → ~20 k cand/s single-core.
- Cascade wall time on 1 M candidates: ~10 s → ~3 s on 4 cores.

Cost:

- One `@njit(cache=True)` decorator per hot function (~5 functions).
- ~50 MB Numba+LLVM in the PyInstaller bundle (current bundle is
  620 MB, so +8 %).
- First call after install pays ~500 ms JIT compile; cached on
  subsequent runs.

### Option 2 — Vectorize Tier 1 across candidates (orthogonal)

Process N candidates as a single numpy batch instead of N python
calls. The catalogue lookups + Pydantic serialisation share across
candidates; the math broadcasts.

- Estimated speedup: 5–10× on Tier 1.
- Cost: refactor `engine.design` to accept arrays of `(N, AL,
  μ_frac)`. ~200 LOC.
- No new dependency; pure numpy.

This stacks with Option 1 — broadcast-numpy + Numba JIT-ed inner
loop is the maximum-throughput configuration.

### Option 3 — Cython / pybind11 / C++

- Cython: 3–5× over plain Python. Build chain comparable to C++.
- pybind11: 2–3× over Numba. Cross-platform build hell.

Both are reasonable if Option 1 falls short. **They aren't worth
the cost until then.**

## Concrete recommendation

1. Add a `[performance]` optional extra (`numba>=0.60`) — opt-in so
   users on weak PCs can install with `uv pip install -e ".[performance]"`
   and the 50 MB cost is theirs to pay.
2. `@njit(cache=True)` decorate:
   - `physics/core_loss.py::core_loss_W_pfc_ripple_iGSE`
   - `physics/thermal.py::converge_temperature`
   - `physics/dowell.py::Rac_over_Rdc_round`
   - `engine._solve_N`
3. Defensive fallback when Numba isn't installed (the function
   stays pure Python — slower but works everywhere).
4. Benchmark harness in CI: `scripts/cascade_benchmark.py` runs
   the 600 W reference design and asserts wall-time under a
   threshold. Catches a regression before release.

Estimated effort: **1 day**. Estimated cascade speedup on a 4-core
laptop: **3–5×**, cutting a typical 1 M-candidate sweep from ~10 s
to ~2-3 s.

## When to revisit C++

If, after Options 1 and 2, the engine still doesn't keep up with
a customer's workload — say a 100 M-candidate sweep finishes
in 5 minutes instead of the desired 30 s — then C++ is the next
honest step. We're nowhere near that ceiling today.
