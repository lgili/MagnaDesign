"""EI core 2-D planar cross-section in Gmsh.

Geometry
========

We model the EI core as it appears in a 2-D **cross-section
through the magnetic axis** — looking at the side of the core
with the bobbin axis going left-to-right (out of the page in the
3-D view). This is the standard FEA simplification for inductors:

    y=core_h                        ┌──────────────────┐
                                    │      yoke        │
    y=yoke_h+window_h               ├──┬───┬─┬───┬──┐
                                    │  │win│cl │win│ow│
    y=yoke_h                        ├──┴───┴─┴───┴──┤
                                    │      yoke        │
    y=0                             └──────────────────┘
                                  x=0                  x=total_w

The air gap (when ``lgap_mm > 0``) is a horizontal slice cutting
the **center leg** halfway up — the canonical gap geometry for an
EI with a single discrete gap.

The winding occupies both windows. By right-hand convention the
left-window bundle carries current INTO the page (``COIL_POS``)
and the right-window bundle carries it OUT (``COIL_NEG``); the
total ampere-turns is ``N·I`` per window with opposite signs, so
the net MMF around the magnetic circuit equals ``2·N·I/2 = N·I``
as expected from a single-coil bobbin.

The outer air box is a rectangle ~3× the core size, centered on
the core. ``A = 0`` Dirichlet on its outer boundary makes the
problem well-posed (flux returns inside; no perimeter leakage
mentioned).

Why planar and not axisymmetric
-------------------------------

An EI is **not** axisymmetric — the cross-section we draw is the
true 2-D projection. Axisymmetric (`2-D ax`) is reserved for
toroidals and round-leg pot cores; using it on an EI would
double-count fluxes through the outer legs.

Per-unit-depth quantities (energy, L) come out of the 2-D solve
and the runner multiplies by ``center_leg_d_mm × 1e-3`` to get
the total 3-D value. This is the same assumption FEMMT makes for
its 2-D EI mode.
"""

from __future__ import annotations

from pfc_inductor.fea.direct.geometry.base import (
    CoreGeometry,
    GeometryBuildResult,
    RegionTag,
)
from pfc_inductor.fea.direct.models import EICoreDims


class EIGeometry(CoreGeometry):
    """EI core 2-D planar geometry generator.

    Construction is purely declarative: stash the dimensions, then
    :meth:`build` runs all the Gmsh OCC calls in one pass.

    Parameters
    ----------
    dims:
        Explicit dimensions. Use :meth:`EICoreDims.from_core` when
        you only have aggregate ``Ae`` / ``Wa`` from the catalog.
    lgap_mm:
        Discrete air-gap length in the center leg. Zero = closed
        core (no air gap region emitted).
    bobbin_clearance_mm:
        Gap between the inner window edge and the start of the
        winding bundle (1 mm typical). Models the bobbin wall.
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
        """Populate ``gmsh.model`` with the EI cross-section.

        All Gmsh calls go through the OCC (OpenCASCADE) kernel —
        the boolean-fragment operations below need OCC; the
        built-in kernel would require manual surface stitching.
        """
        gmsh = gmsh_module
        d = self.dims

        # Convert mm → m for Gmsh (we'll use m for everything; the
        # solver expects SI units).
        SCALE = 1e-3
        cl_w = d.center_leg_w_mm * SCALE
        ww_w = d.window_w_mm * SCALE
        ww_h = d.window_h_mm * SCALE
        yoke = d.yoke_h_mm * SCALE
        outer = d.outer_leg_w_mm * SCALE
        clearance = self.bobbin_clearance_mm * SCALE
        gap = self.lgap_mm * SCALE

        total_w = d.total_w_mm * SCALE
        total_h = d.total_h_mm * SCALE

        gmsh.model.add(model_name)

        # ---- Step 1: outer rectangle of the full E ---------------
        # OCC.addRectangle returns the surface tag; we'll later
        # cut the two windows out of it via boolean difference.
        core_box = gmsh.model.occ.addRectangle(0.0, 0.0, 0.0, total_w, total_h)

        # ---- Step 2: the two windows -----------------------------
        # Window 1 (left): x ∈ [outer, outer+ww_w], y ∈ [yoke, yoke+ww_h]
        # Window 2 (right): x ∈ [outer+ww_w+cl_w, outer+2·ww_w+cl_w], y same
        win1 = gmsh.model.occ.addRectangle(outer, yoke, 0.0, ww_w, ww_h)
        win2 = gmsh.model.occ.addRectangle(outer + ww_w + cl_w, yoke, 0.0, ww_w, ww_h)

        # ---- Step 3: cut windows out of the core box -------------
        # ``cut`` returns ``(remaining_tags, removed_tags)``. We
        # only care about the first — the core with two holes.
        core_after_windows, _ = gmsh.model.occ.cut(
            [(2, core_box)],
            [(2, win1), (2, win2)],
            removeObject=True,
            removeTool=True,
        )
        core_tag = core_after_windows[0][1]

        # ---- Step 4: air gap (if any) ----------------------------
        # A thin horizontal slice through the center leg, located
        # at the center leg's mid-height. We cut this air rectangle
        # out of the core, then re-add it as its own surface so
        # the physics layer can apply ``μ_r = 1`` there.
        gap_surface_tag = None
        if gap > 0.0:
            gap_x0 = outer + ww_w
            gap_y0 = yoke + (ww_h - gap) / 2.0
            gap_rect = gmsh.model.occ.addRectangle(gap_x0, gap_y0, 0.0, cl_w, gap)
            # Cut the gap volume out of the core and keep the slice
            # as its own surface for the air-gap region.
            cut_result, _ = gmsh.model.occ.cut(
                [(2, core_tag)],
                [(2, gap_rect)],
                removeObject=True,
                removeTool=False,  # keep the slice — we want it back as AIR_GAP
            )
            core_tag = cut_result[0][1]
            gap_surface_tag = gap_rect

        # ---- Step 5: winding bundles in both windows -------------
        # Inset by the bobbin clearance so the winding doesn't
        # touch the core. The winding bundle is a single
        # homogenized rectangle — individual turn discretization
        # (which would require Litz handling) is Phase 2.
        coil_w = ww_w - 2 * clearance
        coil_h = ww_h - 2 * clearance
        coil_left = gmsh.model.occ.addRectangle(
            outer + clearance, yoke + clearance, 0.0, coil_w, coil_h
        )
        coil_right = gmsh.model.occ.addRectangle(
            outer + ww_w + cl_w + clearance,
            yoke + clearance,
            0.0,
            coil_w,
            coil_h,
        )

        # ---- Step 6: outer air box -------------------------------
        # 3× the core size, centered on it. The Dirichlet
        # ``A = 0`` BC sits on its perimeter, far enough from the
        # core that fringe-field cutoff doesn't perturb L by more
        # than ~0.5 %.
        AIR_FACTOR = 3.0
        air_w = total_w * AIR_FACTOR
        air_h = total_h * AIR_FACTOR
        air_x0 = total_w / 2.0 - air_w / 2.0
        air_y0 = total_h / 2.0 - air_h / 2.0
        air_box = gmsh.model.occ.addRectangle(air_x0, air_y0, 0.0, air_w, air_h)

        # Fragment with tag tracking. The ``outDimTagsMap`` tells us
        # which output tags each input mapped to — crucial for
        # robust region classification. Pre-v0.4.16-debug we tagged
        # by centroid which silently broke on concave shapes (the C-
        # shaped core's centroid falls inside its window-hole), and
        # the resulting mesh had NO physical group for ``Core`` so
        # the solver saw ``μ_r = μ₀`` everywhere → L independent of
        # the material — a 50× error against the analytical ideal.
        #
        # Input order is preserved in ``out_map``: index 0 is
        # ``core``, then air_box, coil_left, coil_right, and finally
        # gap (when present).
        fragments_in: list[tuple[int, int]] = [(2, core_tag)]
        fragments_in.append((2, air_box))
        fragments_in.append((2, coil_left))
        fragments_in.append((2, coil_right))
        idx_gap = -1
        if gap_surface_tag is not None:
            idx_gap = len(fragments_in)
            fragments_in.append((2, gap_surface_tag))

        _out_all, out_map = gmsh.model.occ.fragment(fragments_in, [])

        gmsh.model.occ.synchronize()

        # ---- Step 7: tag physical groups via fragment output map ─
        # Each entry of ``out_map`` corresponds to one input — the
        # list of dimtags it became after fragment. Most inputs map
        # 1:1 in our geometry, but a tool surface that lay across
        # multiple object surfaces can split (won't happen here, but
        # the code handles it gracefully).
        def _tags(out_entries):
            return [t for (d, t) in out_entries if d == 2]

        core_surfaces = _tags(out_map[0])
        # The air box minus the core / coils / gap = the surrounding
        # air. ``fragment`` already subtracted everything by
        # conformity, so out_map[1] gives just the air remainder.
        air_surfaces = _tags(out_map[1])
        coil_pos_surfaces = _tags(out_map[2])
        coil_neg_surfaces = _tags(out_map[3])
        gap_surfaces = _tags(out_map[idx_gap]) if idx_gap >= 0 else []

        # Emit physical groups. Empty groups are skipped so the
        # ``.pro`` doesn't reference dead tags.
        if core_surfaces:
            gmsh.model.addPhysicalGroup(2, core_surfaces, RegionTag.CORE, name="Core")
        if gap_surfaces:
            gmsh.model.addPhysicalGroup(2, gap_surfaces, RegionTag.AIR_GAP, name="AirGap")
        if air_surfaces:
            gmsh.model.addPhysicalGroup(2, air_surfaces, RegionTag.AIR_OUTER, name="Air")
        if coil_pos_surfaces:
            gmsh.model.addPhysicalGroup(2, coil_pos_surfaces, RegionTag.COIL_POS, name="Coil_pos")
        if coil_neg_surfaces:
            gmsh.model.addPhysicalGroup(2, coil_neg_surfaces, RegionTag.COIL_NEG, name="Coil_neg")

        # ---- Step 8: outer boundary tag --------------------------
        # Walk the boundary curves of the air box and tag them
        # together. The Dirichlet ``A = 0`` constraint in the
        # ``.pro`` file uses this group.
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
            # Pick only edges that lie on the air-box perimeter
            # (their centroid is outside the core's bounding box).
            cx, cy, *_ = gmsh.model.occ.getCenterOfMass(dim, tag)
            on_perimeter = (
                abs(cx - air_x0) < 1e-9
                or abs(cx - (air_x0 + air_w)) < 1e-9
                or abs(cy - air_y0) < 1e-9
                or abs(cy - (air_y0 + air_h)) < 1e-9
            )
            if on_perimeter:
                outer_curves.append(tag)
        if outer_curves:
            gmsh.model.addPhysicalGroup(
                1, outer_curves, RegionTag.OUTER_BOUNDARY, name="OuterBoundary"
            )

        # Final sync so the freshly-tagged groups land on disk
        # when the mesh is written out.
        gmsh.model.occ.synchronize()

        return GeometryBuildResult(model_name=model_name)


# ─── Convenience builder ──────────────────────────────────────────


def build_ei(
    gmsh_module,
    *,
    core: object,
    lgap_mm: float | None = None,
    model_name: str = "ei_inductor",
) -> GeometryBuildResult:
    """One-call EI builder for callers that don't want to manage dims.

    Back-derives ``EICoreDims`` from the catalog ``Core`` model
    (Phase 1 approximation — see :meth:`EICoreDims.from_core`).
    """
    dims = EICoreDims.from_core(core)
    effective_gap = float(lgap_mm if lgap_mm is not None else getattr(core, "lgap_mm", 0.0))
    geom = EIGeometry(dims=dims, lgap_mm=effective_gap)
    return geom.build(gmsh_module, model_name)
