"""Toroidal core as a 2-D axisymmetric half-meridian.

⚠️ IMPORTANT (Phase 1.8 discovery):

While toroidals are naturally rotationally symmetric in their
GEOMETRY, the physics of a WOUND toroidal inductor doesn't map
to our existing ``A_φ`` formulation. Here's the subtlety:

- A wound toroidal has wires wrapping AROUND the donut tube
  (perpendicular to the bobbin axis).
- Each turn forms a closed loop in the **(r, z) meridian
  plane**, distributed evenly in φ.
- The resulting magnetic field inside the iron is in the
  **φ direction** (azimuthal), going around the donut hole.

Our current ``MagnetostaticAxiTemplate`` solves for ``A_φ``
(out-of-plane potential), which gives ``B`` in the (r, z)
plane — *poloidal* field. That's correct for EI, pot, PQ
cores where the wires wrap around the bobbin axis and B is
poloidal. It is **wrong** for toroidals where wires wrap
around the cross-section and B is azimuthal.

A proper toroidal axisymmetric formulation needs:

- Vector potential ``A = A_r r̂ + A_z ẑ`` (in-plane components)
- ``B = curl(A)`` has only φ component
- Source current density also in (r, z) plane

This is a different problem class than the A_φ formulation we
ship. Adding it is Phase 2.x.

The geometry generator below stays in tree because:

1. The half-meridian shape (toroid rectangle + coil bundle +
   air box + tags) is correct geometry; the same cross-section
   will be used by the Phase 2.x toroidal-specific physics.
2. It validates that ``CoreGeometry`` ABC + ``RegionTag``
   pattern works for shapes other than EI.

Tested numerically (Phase 1.8): with the existing A_φ template
it gives ``L = 2522 μH`` vs ``L_analytical = 8022 μH`` for a
T106-class ferrite toroid (OD=27, ID=14, HT=11 mm, N=50,
μ_r=2300). 31 % of analytical — confirming the formulation
mismatch.

Geometry
========

Half-meridian in the (r, z) plane, ``r ≥ 0`` everywhere:

For a wound toroidal:

- ``OD_mm`` — outer diameter (across the donut).
- ``ID_mm`` — inner diameter (the hole through the middle).
- ``HT_mm`` — height (the donut's thickness, perpendicular to its
  symmetry axis).

The cross-section is a rectangle:

    (r_inner, z_bot) to (r_outer, z_top)
    where r_inner = ID_mm/2,  r_outer = OD_mm/2
          z_bot   = -HT_mm/2, z_top   = +HT_mm/2

The bobbin axis = the rotational symmetry axis of the donut. Wires
wrap around this axis at radius R_mean = (ID + OD) / 4.

Layout::

                  z=z_top  ┌──────────┐
                           │  toroid  │
                  z=z_bot  └──────────┘
                          r=r_in     r=out

The COIL bundle in the half-meridian view is a rectangular region
just OUTSIDE the toroid (wires wrap around it). For simplicity we
model the coil bundle ABOVE the toroid (positive z), since the
toroid is symmetric in z. The flux through the toroid then loops
through the toroid iron and closes around the bundle in air.

Actually — better convention: the **wound coil's cross-section
in the meridian plane is a rectangle that surrounds the
toroid's cross-section** (the wire wraps around the donut's
cross-section). In half-meridian view, this becomes a region
that "hugs" the toroid rectangle but is OUTSIDE it. For a
real-world toroidal winding, the wire bundle envelopes the
core completely.

Simplification for Phase 2 (linear-μ, gap-free)
-----------------------------------------------

Toroidals are typically gapped only by lamination joints; for
ferrites + powder cores they're often gapless. We model the
toroid as one solid ring with no air gap — flux circulates
freely through the iron at the speed of light (figuratively).

Air gap modeling for toroids is Phase 2.x — toroidal gaps come
as either:

- One discrete cut (e.g. via grinding) — same model as EI's
  rectangular slice but adapted to a curved geometry.
- Distributed (powder cores) — handled by ``μ_eff(B)`` already.

For Phase 1.8 we ship the gap-free version. ``lgap_mm = 0``
should give ``L → ∞`` analytically (limited only by finite
permeability), and a finite FEM value bounded by ``le/μr``.
"""

from __future__ import annotations

import math

from pfc_inductor.fea.direct.geometry.base import (
    CoreGeometry,
    GeometryBuildResult,
    RegionTag,
)


class ToroidalGeometry(CoreGeometry):
    """Toroidal core, 2-D axisymmetric half-meridian.

    Constructor takes the donut dimensions directly (OD, ID, HT)
    — no back-derivation needed, unlike the EI's heuristic
    ``EICoreDims.from_core``. Toroidals are well-described by
    these three numbers and the catalog ships them all.

    Parameters
    ----------
    OD_mm, ID_mm, HT_mm:
        Outer / inner diameter and height of the donut (mm).
    bobbin_clearance_mm:
        Air gap between the toroid surface and the coil bundle.
        Models the bobbin insulation thickness.
    coil_thickness_mm:
        Radial thickness of the wire bundle (mm). For typical
        single-layer windings this is the wire diameter; for
        thicker bundles it's the layered build-up.
    """

    def __init__(
        self,
        OD_mm: float,
        ID_mm: float,
        HT_mm: float,
        bobbin_clearance_mm: float = 0.3,
        coil_thickness_mm: float = 2.0,
    ) -> None:
        if OD_mm <= ID_mm:
            raise ValueError(f"OD ({OD_mm}) must exceed ID ({ID_mm})")
        if HT_mm <= 0.0:
            raise ValueError(f"HT must be > 0 (got {HT_mm})")
        self.OD_mm = float(OD_mm)
        self.ID_mm = float(ID_mm)
        self.HT_mm = float(HT_mm)
        self.bobbin_clearance_mm = float(bobbin_clearance_mm)
        self.coil_thickness_mm = float(coil_thickness_mm)

    # ------------------------------------------------------------------
    def build(self, gmsh_module, model_name: str) -> GeometryBuildResult:
        """Populate ``gmsh.model`` with the toroidal half-meridian."""
        gmsh = gmsh_module
        SCALE = 1e-3

        # Toroid cross-section (the donut's "tube" in the meridian
        # plane) is a rectangle.
        r_inner = self.ID_mm / 2.0 * SCALE
        r_outer = self.OD_mm / 2.0 * SCALE
        z_half = self.HT_mm / 2.0 * SCALE

        # Coil bundle: wraps around the toroid's cross-section. In
        # the half-meridian view we model it as a single rectangle
        # ABOVE the toroid (at z > z_half + clearance). This works
        # for inductance because of z-symmetry — the bottom half
        # would carry equal flux in the opposite direction and
        # cancel in the axisymmetric integral. Toroid windings are
        # commonly modelled this way in FEMMT/COMSOL examples.
        #
        # An alternative would be to model the coil as a thin ring
        # encircling the toroid cross-section (top + side + bottom
        # all wrapped), which is more realistic for a real toroidal
        # winding. We can switch to that in Phase 2.x for accuracy.
        # For Phase 1.8 the "coil above" convention is enough to
        # validate the formulation.
        clearance = self.bobbin_clearance_mm * SCALE
        # ``coil_thickness_mm`` reserved for Phase 2.x once the
        # toroidal-specific physics lands; currently we use a
        # square bundle ``coil_z_top - coil_z_bot = r_outer - r_inner``.
        coil_z_bot = z_half + clearance
        coil_z_top = coil_z_bot + (r_outer - r_inner)  # tall enough to be substantial
        # Coil's radial extent matches the toroid's cross-section width:
        coil_r_in = r_inner
        coil_r_out = r_outer

        gmsh.model.add(model_name)

        # ---- Toroid solid (the iron ring's meridian cross-section)
        toroid = gmsh.model.occ.addRectangle(r_inner, -z_half, 0.0, r_outer - r_inner, 2 * z_half)

        # ---- Coil bundle (above the toroid, in air) -------------
        coil = gmsh.model.occ.addRectangle(
            coil_r_in, coil_z_bot, 0.0, coil_r_out - coil_r_in, coil_z_top - coil_z_bot
        )

        # ---- Outer air box -------------------------------------
        # 2.5× the toroid size in both directions, centered.
        AIR_FACTOR = 2.5
        air_r = r_outer * AIR_FACTOR
        air_z_half = max(z_half, coil_z_top) * AIR_FACTOR
        air_box = gmsh.model.occ.addRectangle(0.0, -air_z_half, 0.0, air_r, 2 * air_z_half)

        # ---- Fragment + tag tracking ---------------------------
        _out_all, out_map = gmsh.model.occ.fragment(
            [(2, toroid), (2, air_box), (2, coil)],
            [],
        )
        gmsh.model.occ.synchronize()

        def _tags(out_entries):
            return [t for (dim, t) in out_entries if dim == 2]

        core_surfaces = _tags(out_map[0])
        air_surfaces = _tags(out_map[1])
        coil_surfaces = _tags(out_map[2])

        if core_surfaces:
            gmsh.model.addPhysicalGroup(2, core_surfaces, RegionTag.CORE, name="Core")
        if air_surfaces:
            gmsh.model.addPhysicalGroup(2, air_surfaces, RegionTag.AIR_OUTER, name="Air")
        if coil_surfaces:
            gmsh.model.addPhysicalGroup(2, coil_surfaces, RegionTag.COIL_POS, name="Coil_pos")

        # ---- Outer boundary -----------------------------------
        air_box_boundary = gmsh.model.getBoundary(
            [(2, t) for t in air_surfaces],
            combined=True,
            oriented=False,
            recursive=False,
        )
        outer_curves = []
        for dim, tag in air_box_boundary:
            if dim != 1:
                continue
            cx, cy, *_ = gmsh.model.occ.getCenterOfMass(dim, tag)
            on_perimeter = (
                abs(cx - air_r) < 1e-9
                or abs(cy - (-air_z_half)) < 1e-9
                or abs(cy - air_z_half) < 1e-9
            )
            # Do NOT include r=0 — that's the axisymmetric axis.
            if on_perimeter:
                outer_curves.append(tag)
        if outer_curves:
            gmsh.model.addPhysicalGroup(
                1, outer_curves, RegionTag.OUTER_BOUNDARY, name="OuterBoundary"
            )

        gmsh.model.occ.synchronize()

        # Stash key dimensions on the result for the runner to pick up
        # — the 2π·R_mean source-area correction needs R_mean of the
        # coil bundle.
        R_mean = (coil_r_in + coil_r_out) / 2.0
        result = GeometryBuildResult(model_name=model_name)
        # Hack: stash on the dataclass via __dict__ since it's frozen.
        # The runner type-checks gracefully; we just want the value out.
        object.__setattr__(result, "_R_mean_m", R_mean)
        object.__setattr__(
            result, "_A_coil_2d_m2", (coil_r_out - coil_r_in) * (coil_z_top - coil_z_bot)
        )
        return result


def build_toroidal(
    gmsh_module,
    *,
    core: object,
    model_name: str = "toroidal_inductor",
) -> GeometryBuildResult:
    """One-call builder. Reads ``OD_mm``/``ID_mm``/``HT_mm`` from ``core``.

    Raises ``ValueError`` if the catalog entry is missing dimensions
    (some EI/PQ cores have these fields ``None`` because they're
    not toroidals).
    """
    OD = getattr(core, "OD_mm", None)
    ID = getattr(core, "ID_mm", None)
    HT = getattr(core, "HT_mm", None)
    if OD is None or ID is None or HT is None:
        raise ValueError(
            f"Core {getattr(core, 'id', '?')} missing OD/ID/HT — "
            "is this a toroidal? (shape='{getattr(core, 'shape', '?')}')"
        )
    geom = ToroidalGeometry(OD_mm=OD, ID_mm=ID, HT_mm=HT)
    return geom.build(gmsh_module, model_name)


def analytical_L_uH_toroidal(
    *, n_turns: int, mu_r: float, OD_mm: float, ID_mm: float, HT_mm: float
) -> float:
    """Closed-form L for an ideal wound toroid: ``L = μ₀μr·N²·A/(2πR)``.

    Where:

    - ``A = HT × (OD - ID)/2`` is the cross-section area (m²).
    - ``R = (OD + ID)/4`` is the mean radius (m).
    - ``2π·R`` is the magnetic path length around the donut (m).

    No gap, no fringing, no saturation. Real toroidal inductors
    land within ~10-15 % of this formula for ferrite cores with
    ``μ_r > 1000``.
    """
    mu0 = 4 * math.pi * 1e-7
    A = (HT_mm * 1e-3) * ((OD_mm - ID_mm) / 2 * 1e-3)
    R = (OD_mm + ID_mm) / 4 * 1e-3
    return mu0 * mu_r * (n_turns**2) * A / (2 * math.pi * R) * 1e6
