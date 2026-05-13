# FEA Backend — Migration Guide

This document covers the May 2026 cutover from FEMMT to the
in-tree **direct** FEA backend. Read it if any of these apply:

- You used FEMMT directly via ``pfc_inductor.fea.femmt_runner``.
- You're upgrading from a pre-Phase-5 release.
- You hit an edge case where the new direct backend disagrees with
  your old FEMMT-based reference and want to opt back temporarily.

## TL;DR

- **Default backend is now ``direct``.** Nothing to change for
  most users — the cascade Tier 3 + the ``Validate (FEA)``
  action both pick it up automatically.
- **FEMMT remains available** as an opt-in fallback through
  2026-11 via ``PFC_FEA_BACKEND=femmt`` or the UI selector under
  Configurações → FEA backend.
- **FEMMT will be soft-removed from the ``[fea]`` extra** at the
  2026-11 release. ``femmt`` and ``materialdatabase`` packages
  will no longer be installed by ``pip install
  pfc-inductor-designer[fea]``. The runner module
  (``femmt_runner.py``) is being moved to ``vendor/legacy/``.

## Why we moved away

FEMMT is great software, but it has costs we can no longer pay:

- **Cold-start tax** ~600 ms from a ``pkg_resources`` import
  on its top level (deprecated in setuptools ≥ 70 — we pin
  ``setuptools<70`` just to keep FEMMT alive).
- **SIGSEGV in C extensions** on edge geometries; we subprocess-
  wrap it, adding another ~150 ms.
- **Coverage gaps** — no toroidal support, no RM/P/EP/EFD; for
  any of these shapes FEMMT throws "Core shape 'generic' not yet
  supported". The direct backend covers all 12 shapes in our
  catalog.
- **Single-solve wall time** ~10 s typical, vs ~1 ms for the
  direct analytical path on the same case.
- **Calibration ceiling** — FEMMT models EE/PQ/ETD as
  cylindrical-shell axisymmetric, which has ~20-40 % residual vs
  measurement on rectangular-leg cores. We hit the same
  ceiling in our own Phase 2.0 FEM-axi attempt, and pivoted to
  analytical-first solvers that match the catalog AL × N²
  (manufacturer-measured) to ≤ 5 % on every shape that ships AL.

## What the direct backend ships

| Phase | Capability | Status |
|-------|------------|--------|
| 1     | Gmsh + GetDP pipeline for EI / axi | shipped (FEM, opt-in) |
| 2.0   | FEMMT side-by-side benchmark harness | shipped |
| 2.1   | AC harmonic (MagDyn) GetDP template | shipped |
| 2.5   | Toroidal closed-form B_φ solver | shipped (exact) |
| 2.5b  | Powder-core DC-bias rolloff | shipped |
| 2.5c  | Rolloff in axi/EI solver | shipped |
| 2.6   | Reluctance solver (Roters fringing) | shipped (default) |
| 2.7   | AL fast path (matches datasheet exactly) | shipped |
| 2.8   | Dowell AC resistance (skin + proximity) | shipped |
| 2.3   | Litz-wire extended Dowell | shipped |
| 2.4   | Foil winding (Ferreira) | shipped |
| 3.1   | Ferrite tanh saturation knee | shipped |
| 3.2α  | Lumped thermal (T_winding, T_core) | shipped |
| 3.3   | EM-thermal coupling loop | shipped |
| 4.1   | Transient i(t) RK4 stub | shipped |
| 5.1   | Dual-backend dispatch via env / UI | shipped |
| 5.2   | Cutover (direct as default) | shipped (this release) |
| 3.2β  | Thermal FEM | deferred (lumped meets the spec) |
| 4.2   | 3-D mode (rectangular-leg EI) | deferred (its own project) |
| 4.3   | POD-ROM proxy | deferred (reluctance covers the need) |
| 5.3   | FEMMT hard removal | scheduled 2026-11 |

## How to use the new backend

### From the GUI

1. Open **Configurações** in the sidebar.
2. Find the **FEA backend** card.
3. Default is **Direct** — no change needed.
4. To force FEMMT (for cross-check), select "FEMMT (force, …)".

The selection persists in QSettings and applies eagerly on next
launch — you don't have to re-open Configurações to apply.

### From the CLI

```bash
# Direct backend, full physics report
magnadesign fea tdkepcos-pq-4040-n87 \
  --turns 39 --current 8.0 \
  --frequency 130000 --layers 3

# Side-by-side with FEMMT (cross-check)
magnadesign fea tdkepcos-pq-4040-n87 \
  --turns 39 --current 8.0 --compare

# Force FEMMT
magnadesign fea tdkepcos-pq-4040-n87 \
  --turns 39 --current 8.0 --backend femmt
```

### From Python code

```python
from pfc_inductor.fea.direct.runner import run_direct_fea

out = run_direct_fea(
    core=core, material=material, wire=wire,
    n_turns=39, current_A=8.0,
    workdir=Path("/tmp/my_fea"),
    gap_mm=0.5,
    # Optional — adds AC + thermal to the result
    frequency_Hz=130_000.0, n_layers=3,
    P_cu_W=2.5, P_core_W=1.2, T_amb_C=40.0,
)
# out.L_dc_uH, out.B_pk_T, out.R_ac_mOhm, out.T_winding_C, ...
```

Or via the multi-backend dispatcher (env-controlled):

```python
import os
os.environ["PFC_FEA_BACKEND"] = "direct"   # default — or omit entirely
# os.environ["PFC_FEA_BACKEND"] = "femmt"  # opt-in fallback

from pfc_inductor.fea.runner import validate_design
fea_result = validate_design(spec, core, wire, material, design_result)
```

## Opting back to FEMMT

If you encounter a case where the direct backend disagrees with
your reference and you need to validate against FEMMT, three
options:

```bash
# Per-call (CLI):
magnadesign fea <core> --backend femmt --turns N --current I

# Per-session (env):
export PFC_FEA_BACKEND=femmt
magnadesign ...

# Persistent (UI):
# Configurações → FEA backend → "FEMMT (force, …)"
```

Please file an issue if you find a calibration disagreement —
the benchmark suite (``scripts/benchmark_shapes_vs_femmt.py``)
needs more curated cases.

## What changes for power users

### Imports

The legacy ``validate_design_femmt`` still works but emits a
``DeprecationWarning``:

```
DeprecationWarning: validate_design_femmt() is deprecated and
scheduled for removal in 2026-11. Use
pfc_inductor.fea.runner.validate_design() — it now defaults to
the in-tree direct backend. Set PFC_FEA_BACKEND=femmt to keep
using FEMMT until removal.
```

If you're calling FEMMT directly from project scripts, migrate to
the dispatcher. For the rare cases where you NEED FEMMT-specific
features (e.g. FEMMT's MaterialDataSource.Measurement) — those
stay accessible during the deprecation window.

### Configuration

The previous ``Auto`` default (shape-based dispatch) is still
available under the Configurações combo as **Auto (legacy: …)**.
Selecting it restores the pre-cutover behaviour (FEMMT for EE/PQ,
legacy FEMM for toroid at high N).

### CI / sweeps

The ``compare_backends`` test suite (Phase 2.0) keeps running on
every PR. ``scripts/benchmark_shapes_vs_femmt.py`` reproduces the
cross-shape table you see in the proposal — run it locally to
sanity-check after upgrades.

## Roadmap to 2026-11 (FEMMT removal)

- **Now (Phase 5.2)**: direct is the default; FEMMT is opt-in.
- **6 months**: validate in the field. If no critical
  regressions land at the issue tracker, proceed.
- **2026-11 (Phase 5.3)**:
  - Move ``pfc_inductor/fea/femmt_runner.py`` → ``vendor/legacy/femmt_runner.py``.
  - Remove ``femmt`` + ``materialdatabase`` from the ``[fea]``
    extra in ``pyproject.toml``.
  - Drop the ``setuptools<70`` pin.
  - Delete ``setup_deps/femmt_config.py`` and the
    ``_install_no_space_femmt_shim`` workaround.
  - Remove the FEMMT install probe from MainWindow's setup dialog.
  - Update ``README.md`` to mark FEMMT removed.

Users who want FEMMT after that date will need to install it
themselves and copy the legacy adapter out of
``vendor/legacy/``.
