"""Direct ONELAB (Gmsh + GetDP) backend — FEMMT-free finite-element pipeline.

Architecture overview
=====================

This subpackage is a from-scratch alternative to the FEMMT wrapper
(``pfc_inductor.fea.femmt_runner``). It targets the same job —
"given an inductor design, run a 2-D axisymmetric or planar FEA and
return L, energy, B_pk, and per-component losses" — but talks to
the underlying ONELAB stack directly:

- **Gmsh** (Python API, ``import gmsh``) for parametric geometry +
  unstructured mesh generation.
- **GetDP** (subprocess to the ``getdp`` binary shipped by ONELAB)
  for the actual FEM solve. Magnetostatic + AC harmonic + thermal
  problems are described in ``.pro`` template files we generate.
- **Our own** ``pfc_inductor.fea.pos_renderer`` for headless PNG
  rendering of the resulting ``.pos`` field views (reused from the
  FEMMT pipeline — pos files are universal Gmsh output).

Why bypass FEMMT
----------------

1. **Geometry control.** FEMMT's geometry generator is tied to a
   small set of pre-validated shapes (EE / ELP / PQ / toroidal /
   etc.). Custom topologies — gap distributions, asymmetric EI,
   foil windings on bobbins with offsets — require either patching
   FEMMT or going around it. Owning the ``.geo`` generation gives
   us a knob for every dimension.
2. **Performance.** ``femmt.MagneticComponent()`` construction +
   Pydantic validation adds ~500 ms before the solver even starts.
   In a sweep over 100 candidates that's 50 s of pure overhead. A
   direct pipeline trims init to ~50 ms.
3. **Output layout.** FEMMT hardcodes ``e_m/results/`` etc. We
   want every artifact under the project's working directory so
   the user can find PNGs alongside their reports.
4. **Custom probes + losses.** FEMMT reports an aggregate loss; we
   want per-region breakdowns (gap fringe loss, top-layer
   proximity loss, bottom-layer eddy loss) for PFC-specific
   reporting.
5. **No ``pkg_resources``.** FEMMT triggers a deprecation warning
   at import time and adds ~80 ms to cold start.

Boundaries
----------

This package is FEA only. It does NOT replace:

- ``pfc_inductor.design`` (the analytical engine — ~17 k cand/s
  Numba kernels for sweep work).
- ``pfc_inductor.physics`` (loss models, thermal correlations).
- ``pfc_inductor.fea.pos_renderer`` (kept; we feed it our own
  ``.pos`` output).

The runner (``pfc_inductor.fea.direct.runner``) returns the same
``FeaResult`` dataclass as ``fea.femmt_runner`` so the UI's
``FEAFieldGallery`` and the cascade Tier 3 pipeline can swap
backends transparently. See ``models.py`` for the contract.

Replacement strategy
--------------------

Incremental, shape by shape. Phase 1 = EI core, magnetostatic DC
only. Once that passes a 5-%-tolerance round-trip against FEMMT,
add EE, PQ, toroidal one at a time. AC harmonic + thermal follow
after geometry coverage is at parity.

Until then, ``pfc_inductor.fea.runner`` keeps FEMMT as the default
backend. The direct backend is opt-in via an explicit
``backend="direct"`` flag, so production runs are unaffected.
"""

from __future__ import annotations

__all__ = [
    "DirectFeaResult",
    "run_direct_fea",
]

# Lazy re-exports — keep the import surface small so ``from
# pfc_inductor.fea.direct import ...`` doesn't drag in Gmsh
# (~80 ms cold import) until the user actually requests a solve.


def __getattr__(name: str):
    if name == "DirectFeaResult":
        from pfc_inductor.fea.direct.models import DirectFeaResult

        return DirectFeaResult
    if name == "run_direct_fea":
        from pfc_inductor.fea.direct.runner import run_direct_fea

        return run_direct_fea
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
