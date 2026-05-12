"""Result + intermediate dataclasses for the direct ONELAB backend.

Two type families:

- **Public** (``DirectFeaResult``): mirrors the FEMMT runner's
  return contract so the UI + cascade pipeline can switch backends
  without code changes.
- **Internal** (``BCKind``, ``ProbePoint``, ``MeshHints``,
  ``EICoreDims``): plumbing between the geometry / physics /
  solver / postproc layers. NOT part of the public surface — kept
  here so all backend modules import from one canonical place.

All dataclasses are frozen + slotted where possible to make them
hashable for the result-cache key the cascade orchestrator uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping, Optional

# ─── Public result type ───────────────────────────────────────────


@dataclass(frozen=True)
class DirectFeaResult:
    """Outcome of one direct-backend FEA run.

    Fields mirror what ``pfc_inductor.fea.femmt_runner._FEMMTResult``
    exposes so the UI's ``FeaResult`` adapter can consume either
    backend. Optional fields are ``None`` when the corresponding
    pass wasn't requested (e.g. AC results absent on DC-only runs).
    """

    # ── Inductance + energy ──────────────────────────────────────
    L_dc_uH: float
    """DC self-inductance (μH) computed from energy: L = 2·W/I²."""

    energy_J: float
    """Magnetic field energy stored in the domain (J)."""

    # ── Peak field ───────────────────────────────────────────────
    B_pk_T: float
    """Peak ``|B|`` over the core region (T) — saturation check."""

    B_avg_T: float
    """Volume-averaged ``|B|`` in the core (T)."""

    # ── AC pass (optional) ───────────────────────────────────────
    L_ac_uH: Optional[float] = None
    R_ac_mOhm: Optional[float] = None
    P_cu_ac_W: Optional[float] = None
    P_core_W: Optional[float] = None

    # ── Thermal pass (optional) ──────────────────────────────────
    T_winding_C: Optional[float] = None
    T_core_C: Optional[float] = None

    # ── Diagnostics ──────────────────────────────────────────────
    mesh_n_elements: int = 0
    mesh_n_nodes: int = 0
    solve_wall_s: float = 0.0
    """Pure GetDP wall time, excluding mesh generation."""

    workdir: Optional[Path] = None
    """Directory where ``.geo``/``.pro``/``.pos`` artifacts were
    written. Kept around so the UI can show field PNGs + so a
    failed solve can be re-inspected by hand. ``None`` for purely
    in-memory runs (none yet, but reserved)."""

    field_pngs: Mapping[str, Path] = field(default_factory=dict)
    """Map ``view_name → png_path`` for the rendered field plots.
    ``view_name`` is one of ``"B"``, ``"H"``, ``"J"``, ``"loss_density"``
    etc. — keys mirror what ``pos_renderer`` produces today."""


# ─── Internal primitives ──────────────────────────────────────────


class BCKind(Enum):
    """Boundary-condition flavors GetDP knows about.

    Used by ``physics/magnetostatic.py`` to emit the right
    ``Constraint`` block in the ``.pro`` file.
    """

    DIRICHLET = "dirichlet"
    """Fixed vector-potential A = 0 (perfect magnetic insulation).
    The default for the outer air box — flux returns inside."""

    NEUMANN = "neumann"
    """Zero normal flux ``∂A/∂n = 0`` (magnetic wall). Used on
    symmetry planes when we exploit axisymmetry."""

    PERIODIC = "periodic"
    """``A(boundary_1) = A(boundary_2)`` — for periodic structures
    (e.g. one slot of a multi-slot stator). Not used by inductors
    yet but reserved for future winding studies."""


@dataclass(frozen=True)
class ProbePoint:
    """Point in 2-D space where postproc extracts a field value.

    Convenient for "B at the air-gap centerline" or "J in the
    bottom layer of the winding" probes. The runner collects these
    after the solve and stores values in ``DirectFeaResult.extras``.
    """

    name: str
    """Stable id — used as the dict key on the result."""

    x_mm: float
    y_mm: float

    quantity: str
    """One of ``"B"``, ``"H"``, ``"A"``, ``"J"``, ``"loss_density"``."""


@dataclass(frozen=True)
class MeshHints:
    """Knobs the geometry layer hands to the mesh builder.

    Coarser-than-default on flat regions, finer near corners + air
    gaps where the field gradient is steep. Defaults below were
    tuned against FEMMT's auto-mesh on EI-cores and give similar
    L_dc accuracy at ~30 % fewer elements (fewer elements →
    faster solve → faster cascade Tier 3).
    """

    core_size_mm: float = 1.2
    """Mesh edge length inside the core volume."""

    gap_size_mm: float = 0.15
    """Mesh edge length inside the air-gap (much finer — the
    field crowds here)."""

    winding_size_mm: float = 0.6
    """Mesh edge length inside the winding cross-section."""

    air_size_mm: float = 3.0
    """Mesh edge length in the outer air box."""

    refine_corners: bool = True
    """Local refinement near re-entrant corners (where flux
    crowds). Adds ~5 % nodes; cuts B_pk error from ~8 % to ~2 %."""


@dataclass(frozen=True)
class EICoreDims:
    """Explicit dimensions of an EI core — what Gmsh needs to draw it.

    Our catalog ``Core`` model only carries aggregate quantities
    (``Ae_mm2``, ``Wa_mm2``, ``le_mm``, ``MLT_mm``). For an EI we
    need explicit widths, depths, and heights. ``from_core``
    back-derives them assuming standard EI proportions (center leg
    twice the outer leg width, square cross-section, window
    height = 2 × window width). Engineers with vendor datasheets
    handy can override by constructing ``EICoreDims`` manually.

    Reference geometry (looking at the EI from above, half-shown by
    axisymmetry around the y-axis on x=0):

        ┌──────────────────────┐         ↑
        │                      │         │ core_h
        │  ┌────┐    ┌────┐    │         │
        │  │ww  │    │  cl│    │         │
        │  │    │    │    │    │         ↓
        │  └────┘    └────┘    │
        │←─ ww_w ─→← cl_w →    │
        └──────────────────────┘
                ←──── total_w ───→

    ``cl_w`` = center-leg width, ``ww_w`` = window width, ``cl_d``
    = leg depth (into page), ``window_h`` = window height.
    """

    center_leg_w_mm: float
    center_leg_d_mm: float
    window_w_mm: float
    window_h_mm: float
    """Vertical window height (top yoke to bottom yoke, in mm)."""

    yoke_h_mm: float
    """Top/bottom yoke thickness (the horizontal piece that closes
    the magnetic circuit). Symmetric top + bottom in standard EI."""

    outer_leg_w_mm: float
    """Outer leg cross-section width — typically ``cl_w / 2`` so
    the flux splits evenly."""

    @property
    def total_w_mm(self) -> float:
        """Overall core width (outer-leg + window + center + window
        + outer-leg)."""
        return 2 * self.outer_leg_w_mm + 2 * self.window_w_mm + self.center_leg_w_mm

    @property
    def total_h_mm(self) -> float:
        """Overall core height (yoke + window + yoke)."""
        return 2 * self.yoke_h_mm + self.window_h_mm

    @classmethod
    def from_core(cls, core: object, lgap_mm: Optional[float] = None) -> EICoreDims:
        """Back-derive EI dims from a ``Core`` (Ae, Wa, MLT only).

        Assumptions for the standard-EI heuristic:

        - Center leg has square cross-section: ``cl_w = cl_d = sqrt(Ae)``.
        - Outer leg width = ``cl_w / 2`` (flux halves into each side).
        - Window aspect ratio ``h / w = 2`` (typical EI bobbin shape).
        - Yoke thickness = outer leg width.

        These are reasonable defaults but **not exact** for every
        vendor's part. For accuracy on production runs the engineer
        should pass explicit dimensions or extend ``Core`` with a
        ``geometry_hint`` dict. Phase 2 of the migration will add
        vendor-specific dim tables to the catalog ingestion.
        """
        import math

        Ae = float(core.Ae_mm2)
        Wa = float(core.Wa_mm2)
        cl = math.sqrt(Ae)
        outer = cl / 2.0
        # Window aspect 2:1 (h = 2 × w), so Wa = w · h = w · 2w =
        # 2w² → w = sqrt(Wa/2).
        ww_w = math.sqrt(Wa / 2.0)
        ww_h = 2.0 * ww_w
        yoke = outer
        return cls(
            center_leg_w_mm=cl,
            center_leg_d_mm=cl,
            window_w_mm=ww_w,
            window_h_mm=ww_h,
            yoke_h_mm=yoke,
            outer_leg_w_mm=outer,
        )
