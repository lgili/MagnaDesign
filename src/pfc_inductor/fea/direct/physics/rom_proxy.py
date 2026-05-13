"""Reduced-order model proxy — Phase 4.3 (deferred / future work).

Goal: a POD (proper orthogonal decomposition) or Krylov-based ROM
surrogate that runs in microseconds and agrees with the full
FEA within 5 % at typical PFC operating points. Used by the
cascade Tier 3 sweep to evaluate 100+ candidates without paying
a per-candidate FEM solve.

Why this is its own phase: building a useful ROM requires:

1. A high-fidelity training set — full FEM solves across the
   parameter space the cascade explores (μ_r, gap, N, I, f).
2. Mode selection — picking the dominant POD basis vectors that
   capture 95+ % of the energy.
3. Projection + reduced solve — Galerkin-project the FEM
   stiffness matrix onto the basis; solve the reduced system
   at runtime.

Current state: the **reluctance solver shipped in Phase 2.6 IS
effectively a ROM** — it's a 1-D-magnetic-circuit model with a
closed-form expression for L. It runs in microseconds and matches
FEMMT within 15 % across all catalog shapes. For the cascade's
"evaluate 100 candidates" use case, this is already production-
ready.

The full POD-ROM (Phase 4.3 as originally scoped) is therefore
**lower priority than Phase 4.2 (3-D mode)** — the analytical
ROM is in production; the FEM ROM would only buy value once the
3-D mode is the bottleneck. Marked as deferred.

If/when this lands, the dispatch surface is ``backend="rom"``
with a fall-back to ``"axi"`` when the ROM's confidence interval
exceeds a configurable threshold.
"""

from __future__ import annotations


def run_rom_solve_stub(*args, **kwargs):  # pragma: no cover — placeholder
    """Placeholder for the Phase 4.3 POD-ROM solver.

    Raises ``NotImplementedError``. The reluctance solver shipped
    in Phase 2.6 fulfils the cascade's "fast candidate eval" need;
    a full POD-ROM is only justified after Phase 4.2 (3-D mode)
    when the FEM becomes the bottleneck.
    """
    raise NotImplementedError(
        "ROM proxy (Phase 4.3) is not yet implemented. The reluctance "
        "solver (default `backend='reluctance'`) runs in microseconds "
        "and matches FEMMT within 15 % — it already serves the cascade's "
        "fast-candidate-eval requirement. A POD-ROM becomes valuable only "
        "after Phase 4.2 (3-D mode) lands as the high-accuracy reference."
    )


__all__ = ["run_rom_solve_stub"]
