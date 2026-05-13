"""3-D magnetostatic — Phase 4.2 (deferred / future work).

Why this is its own phase: the analytical / axisymmetric path
shipped in Phases 2.5-2.7 covers every PFC inductor shape in the
catalog with ≤ 15 % vs FEMMT and ≤ 5 % vs catalog AL. The 3-D
path is the **leapfrog feature** — it captures the rectangular-leg
geometry of EE/EI cores directly (no cylindrical-shell
approximation), targeting the original ≤ 5 % vs FEMMT spec on
those cores.

Scope (when implemented):

1. 3-D tetrahedral mesh via Gmsh OCC (extrude the existing
   half-meridian geometry through the leg-depth dimension; rotate
   for axisymmetric shapes).
2. GetDP ``Hcurl_a_3D`` edge-element formulation — vector A on
   tet edges, B = curl A on faces.
3. Boundary conditions: ``A × n = 0`` on outer air box (the 3-D
   analog of the 2-D Dirichlet).
4. Standard postops: B_pk, energy, flux linkage, with proper
   3-D integration measures.

Implementation cost estimate: 3-5 sessions (the function-space
machinery is more complex; meshing 3-D requires careful tet
quality control; convergence at the gap edge is finicky).

Backend dispatch (planned): ``run_direct_fea(backend="3d")``
opt-in. Default stays ``"reluctance"`` since the analytical path
is faster and meets the catalog-AL parity requirement.

Acceptance gate: 3-D EI matches measurement to 3 % (vs the
~10–30 % cylindrical-shell ceiling); within 5 % of manufacturer
AL · N² datasheet value at zero bias.

The stub below raises ``NotImplementedError`` so callers see a
clean failure rather than silent wrong answers when they try
``backend="3d"``.
"""

from __future__ import annotations


def run_3d_solve_stub(*args, **kwargs):  # pragma: no cover — placeholder
    """Placeholder for the Phase 4.2 3-D magnetostatic solver.

    Raises ``NotImplementedError`` until the 3-D mode lands.
    """
    raise NotImplementedError(
        "3-D mode (Phase 4.2) is not yet implemented. The analytical "
        "reluctance solver (default) and the 2-D axisymmetric FEM "
        "(opt-in via backend='axi') cover every shape in the catalog "
        "with ≤ 15 % vs FEMMT. Phase 4.2 will deliver ≤ 5 % vs measurement "
        "on rectangular-leg EE/EI; track progress in the OpenSpec for "
        "replace-femmt-with-direct-fea."
    )


__all__ = ["run_3d_solve_stub"]
