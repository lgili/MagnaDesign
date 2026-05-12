"""EI core as a 2-D axisymmetric half-meridian (round-leg approximation).

Why axisymmetric for an EI
==========================

A wound solenoid (which is what every PFC inductor is, regardless
of core shape) is **fundamentally not representable in 2-D
planar**. In planar 2-D the coil bundle on one side of the core
shows up as ``+J·ẑ`` and the bundle on the other side as ``-J·ẑ``,
which physically corresponds to **two parallel bus bars with
opposite currents**, not a multi-turn helical coil. The field
pattern that comes out is "go-and-return transmission line",
not "wound inductor with flux linkage" — see the |B| plot from
Phase 1.2 of the calibration debug, where flux stayed in the air
around the bundles instead of channeling through the iron.

The right 2-D simplification is **axisymmetric** (``2-D ax``):
treat the bobbin axis as the rotation axis, model a half-meridian
in the (r, z) plane, and let GetDP's ``VolAxiSqu`` Jacobian
implicitly revolve the geometry to recover the 3-D inductance.
This **is** the standard convention FEMMT uses for every core
shape, EI included — round-leg approximation is good enough for
inductance magnitudes (5-10 % off planar for a rectangular EI).

Geometry
========

Half-meridian in the (r, z) plane, ``r ≥ 0`` everywhere::

    z=total_h ┌─────────────────────┐
              │      top yoke       │
    z=yk+wh   ├─────┬─────────┬─────┤
              │ coil│         │ ol  │   wh = window height
              │     │  bobbin │     │   ol = outer leg
    z=yk      ├─────┴─────────┴─────┤
              │     bottom yoke     │
    z=0       └─────────────────────┘
              r=0  r_cl       r_ow   r_total

- ``r = 0`` is the **bobbin axis** — the centerline of the center
  leg.
- ``r ∈ [0, r_cl]`` is the **center leg** (solid iron).
- ``r ∈ [r_cl, r_cl + clearance]`` is the bobbin wall (air).
- ``r ∈ [r_cl + clearance, r_ow - clearance]`` is the **coil**
  cross-section.
- ``r ∈ [r_ow - clearance, r_ow]`` is air outside the coil.
- ``r ∈ [r_ow, r_total]`` is the **outer leg** (a cylindrical
  shell — the rectangular-leg approximation).

The coil current density flows in the **azimuthal** (``φ``)
direction in 3-D, but since we model only the (r, z) plane and
the bundle is uniform around the revolution, we encode it as a
scalar source ``J_φ = N·I / A_coil`` and rely on ``VolAxiSqu`` to
do the right thing.

Air gap is a horizontal slice (``z`` range) cutting the center
leg.

Why this is an approximation for EI
-----------------------------------

A real EI core has **rectangular** legs and yokes, not the
**cylindrical / annular shells** that axisymmetric revolution
produces. For an EI:

- The center leg is rectangular ``cl_w × cl_d``. We approximate
  with a cylinder of radius ``r_cl = sqrt(A_e / π)`` so the
  cross-sectional area matches.
- The outer legs are two **rectangular** pieces, one on each side
  of the windows. We approximate with one **cylindrical shell**
  of equivalent area.
- The flux path lengths in the yokes differ between the two
  representations (the real EI yokes are short, the cylindrical
  ones are longer at the outer radius).

For PFC inductor inductance values, the approximation is good to
~5-10 % — well within FEA-vs-analytical tolerances for design
work. Plane-2-D would be wrong by ~100 × (Phase 1.2 measurement).
The right "correct" alternative is full 3-D, which is 10-100 ×
slower than 2-D ax for negligible gain on a Saturday-night PFC
inductor.
"""

from __future__ import annotations

import math

from pfc_inductor.fea.direct.geometry.base import (
    CoreGeometry,
    GeometryBuildResult,
    RegionTag,
)
from pfc_inductor.fea.direct.models import EICoreDims


class EIAxisymmetricGeometry(CoreGeometry):
    """EI core, axisymmetric half-meridian variant.

    Same constructor signature as the planar :class:`EIGeometry`
    so the runner can pick between them based on a flag.
    """

    def __init__(
        self,
        dims: EICoreDims,
        lgap_mm: float = 0.0,
        bobbin_clearance_mm: float = 1.0,
    ) -> None:
        self.dims = dims
        self.lgap_mm = float(lgap_mm)
        self.bobbin_clearance_mm = float(bobbin_clearance_mm)

    # ------------------------------------------------------------------
    def build(self, gmsh_module, model_name: str) -> GeometryBuildResult:
        """Build the half-meridian in the (r, z) plane."""
        gmsh = gmsh_module
        d = self.dims

        SCALE = 1e-3
        # Derive axisymmetric radii from the EI's aggregate areas.
        # Center leg: circular cross-section with area = Ae.
        r_cl = math.sqrt(d.center_leg_w_mm * d.center_leg_d_mm / math.pi) * SCALE
        # Window radial extent = the window's rectangular width
        # (acceptable approximation for inductance).
        ww_w = d.window_w_mm * SCALE
        ww_h = d.window_h_mm * SCALE
        yoke = d.yoke_h_mm * SCALE
        # Outer leg: cylindrical shell with equivalent area to the
        # rectangular outer leg (2× the rect width × depth).
        Ae_outer = 2 * d.outer_leg_w_mm * d.center_leg_d_mm
        # For a thin shell of inner radius r1 and outer radius r2,
        # area = π(r2² - r1²). With r1 = r_cl + ww_w, solve for r2.
        r1 = r_cl + ww_w
        r2 = math.sqrt(r1 * r1 + Ae_outer * SCALE * SCALE / math.pi)
        # Total radial extent
        r_total = r2

        clearance = self.bobbin_clearance_mm * SCALE
        gap = self.lgap_mm * SCALE
        total_h = 2 * yoke + ww_h

        gmsh.model.add(model_name)

        # ---- Core: outer rectangle ------------------------------
        core_box = gmsh.model.occ.addRectangle(0.0, 0.0, 0.0, r_total, total_h)

        # ---- Window: a single rectangle (axisymmetric collapses
        # the two windows of a real EI into one annular window).
        win = gmsh.model.occ.addRectangle(r_cl, yoke, 0.0, ww_w, ww_h)

        # Cut the window out of the core.
        core_after, _ = gmsh.model.occ.cut(
            [(2, core_box)],
            [(2, win)],
            removeObject=True,
            removeTool=True,
        )
        core_tag = core_after[0][1]

        # ---- Air gap slice through the center leg ---------------
        gap_surface_tag = None
        if gap > 0.0:
            gap_z0 = yoke + (ww_h - gap) / 2.0
            gap_rect = gmsh.model.occ.addRectangle(0.0, gap_z0, 0.0, r_cl, gap)
            cut2, _ = gmsh.model.occ.cut(
                [(2, core_tag)],
                [(2, gap_rect)],
                removeObject=True,
                removeTool=False,
            )
            core_tag = cut2[0][1]
            gap_surface_tag = gap_rect

        # ---- Coil bundle: annular ring inside the window --------
        # Inner edge ``r_cl + clearance``, outer edge ``r_cl + ww_w
        # − clearance``, height ``yoke + clearance`` … ``yoke + ww_h
        # − clearance``.
        coil_w = ww_w - 2 * clearance
        coil_h = ww_h - 2 * clearance
        coil = gmsh.model.occ.addRectangle(r_cl + clearance, yoke + clearance, 0.0, coil_w, coil_h)

        # ---- Outer air box -------------------------------------
        AIR_FACTOR = 2.5
        air_w = r_total * AIR_FACTOR
        # Centered on the core in z, starts at r=0 (axisymmetric
        # constraint: nothing crosses the axis).
        air_h = total_h * AIR_FACTOR
        air_z0 = total_h / 2.0 - air_h / 2.0
        air_box = gmsh.model.occ.addRectangle(0.0, air_z0, 0.0, air_w, air_h)

        # ---- Fragment + track via output map -------------------
        fragments_in = [(2, core_tag), (2, air_box), (2, coil)]
        idx_gap = -1
        if gap_surface_tag is not None:
            idx_gap = len(fragments_in)
            fragments_in.append((2, gap_surface_tag))
        _out_all, out_map = gmsh.model.occ.fragment(fragments_in, [])
        gmsh.model.occ.synchronize()

        def _tags(out_entries):
            return [t for (dim, t) in out_entries if dim == 2]

        core_surfaces = _tags(out_map[0])
        air_surfaces = _tags(out_map[1])
        # Axisymmetric: only ONE coil (the annular ring). We tag it
        # as ``COIL_POS`` for the physics template's source-region
        # name; the ``-J·{a}`` Galerkin term sees a single source
        # region with positive current, which is correct for a
        # one-direction winding around the axis.
        coil_surfaces = _tags(out_map[2])
        gap_surfaces = _tags(out_map[idx_gap]) if idx_gap >= 0 else []

        if core_surfaces:
            gmsh.model.addPhysicalGroup(2, core_surfaces, RegionTag.CORE, name="Core")
        if gap_surfaces:
            gmsh.model.addPhysicalGroup(2, gap_surfaces, RegionTag.AIR_GAP, name="AirGap")
        if air_surfaces:
            gmsh.model.addPhysicalGroup(2, air_surfaces, RegionTag.AIR_OUTER, name="Air")
        if coil_surfaces:
            gmsh.model.addPhysicalGroup(2, coil_surfaces, RegionTag.COIL_POS, name="Coil_pos")
        # COIL_NEG group is intentionally absent in axisymmetric —
        # the physics template's Galerkin term over Coil_neg
        # contributes zero when the region is empty, which is the
        # correct behavior for a single-coil bobbin.

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
                abs(cx - air_w) < 1e-9
                or abs(cy - air_z0) < 1e-9
                or abs(cy - (air_z0 + air_h)) < 1e-9
            )
            # NOTE: do NOT include the r=0 edge — that's the
            # axis of symmetry, NOT a Dirichlet boundary. GetDP
            # handles axisymmetric r=0 implicitly when the
            # Jacobian is VolAxiSqu (A_z = 0 there is a natural
            # condition).
            if on_perimeter:
                outer_curves.append(tag)
        if outer_curves:
            gmsh.model.addPhysicalGroup(
                1, outer_curves, RegionTag.OUTER_BOUNDARY, name="OuterBoundary"
            )

        gmsh.model.occ.synchronize()
        return GeometryBuildResult(model_name=model_name)


def build_ei_axi(
    gmsh_module,
    *,
    core: object,
    lgap_mm: float | None = None,
    model_name: str = "ei_axi_inductor",
) -> GeometryBuildResult:
    """One-call builder for the axisymmetric EI variant."""
    dims = EICoreDims.from_core(core)
    effective_gap = float(lgap_mm if lgap_mm is not None else getattr(core, "lgap_mm", 0.0))
    geom = EIAxisymmetricGeometry(dims=dims, lgap_mm=effective_gap)
    return geom.build(gmsh_module, model_name)
