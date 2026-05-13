"""Magnetic-core data model.

The :class:`Core` Pydantic model holds the geometry + reference
inductance index for one core part as it appears in the curated
catalog. Two flavors of fields:

- **Geometry** (``Ae_mm2``, ``le_mm``, ``Ve_mm3``, ``Wa_mm2``,
  ``MLT_mm``, etc.) — the dimensions the engine reads to size
  windings and compute flux density.
- **Manufacturer index** (``AL_nH``) — inductance per N² at
  zero DC bias, with the manufacturer's default material. Powder
  cores additionally need the rolloff curve from
  :class:`Material` to derate ``AL`` at the operating H.

The catalog ships ~10 000 cores from Magnetics, TDK, Ferroxcube,
Thornton, Pulse, Coilcraft, Würth and Micrometals — see
:mod:`pfc_inductor.data_loader` for the JSON-on-disk schema.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Core(BaseModel):
    """Core part with geometry + reference inductance index.

    AL_nH is the manufacturer's inductance index (nH per N^2) measured at zero
    DC bias with the listed default_material_id. For powder cores, the
    effective AL is reduced by the rolloff curve at the operating H.
    """

    id: str
    vendor: str
    shape: str
    part_number: str
    default_material_id: str

    OD_mm: Optional[float] = None
    ID_mm: Optional[float] = None
    HT_mm: Optional[float] = None

    Ae_mm2: float
    le_mm: float
    Ve_mm3: float
    Wa_mm2: float
    MLT_mm: float

    AL_nH: float = Field(
        description="Inductance index nH/N^2 at zero DC bias with default material"
    )
    lgap_mm: float = 0.0
    cost_per_piece: Optional[float] = Field(
        default=None,
        description="Per-piece cost in the material's currency. Preferred "
        "over deriving from mass × material.cost_per_kg.",
    )
    mass_g: Optional[float] = Field(
        default=None,
        description="Core mass in grams. If absent, derived from Ve · rho.",
    )
    notes: str = ""


def stack_core(core: Core, n_stacks: int) -> Core:
    """Return a derived :class:`Core` representing ``n_stacks`` of ``core``
    physically assembled together (stacked toroids, paralleled EI halves,
    laminated EE sections).

    Scaling rules — the magnetic equivalent of N identical cores in
    parallel (cross-section adds, magnetic path stays the same):

    * ``Ae_mm2 *= n``     — cross-sections add.
    * ``Ve_mm3 *= n``     — volume scales linearly.
    * ``AL_nH *= n``      — inductance index is proportional to Ae.
    * ``Wa_mm2``          — unchanged (window per single core).
    * ``le_mm``           — unchanged (one magnetic loop, same length).
    * ``HT_mm *= n``      — physical stack is ``n×`` taller.
    * ``MLT_mm``          — grows by ``2·HT_mm·(n-1)``: every extra
      stacked layer adds two ``HT`` segments to the winding's perimeter.
      Exact for toroids (where ``MLT ≈ 2·HT + (OD-ID)``); a close
      approximation for EE/EI stacks. When ``HT_mm`` isn't known we
      fall back to ``MLT_mm *= n^(1/3)`` — the cube-root keeps the
      growth conservative on cores where the height field is empty.
    * ``mass_g *= n``     — n cores' worth of ferrite.
    * ``cost_per_piece *= n`` — represents the assembled magnetic
      structure's cost. BOM-side multiplication is therefore implicit
      in this single 'effective core' value.

    Returns the original ``core`` unchanged when ``n_stacks <= 1`` so
    callers can apply this blindly to a possibly-1 override value.
    """
    if n_stacks is None or n_stacks <= 1:
        return core
    n = int(n_stacks)
    new_ht = core.HT_mm * n if core.HT_mm is not None else None
    # MLT bump — exact for toroids, ≈ exact for EE/EI laminations.
    if core.HT_mm is not None:
        new_mlt = core.MLT_mm + 2.0 * core.HT_mm * (n - 1)
    else:
        new_mlt = core.MLT_mm * (n ** (1.0 / 3.0))
    new_mass = core.mass_g * n if core.mass_g is not None else None
    new_cost = core.cost_per_piece * n if core.cost_per_piece is not None else None
    return core.model_copy(
        update={
            "Ae_mm2": core.Ae_mm2 * n,
            "Ve_mm3": core.Ve_mm3 * n,
            "AL_nH": core.AL_nH * n,
            "HT_mm": new_ht,
            "MLT_mm": new_mlt,
            "mass_g": new_mass,
            "cost_per_piece": new_cost,
            "notes": (core.notes + f" [{n}× stacked]").strip(),
        }
    )
