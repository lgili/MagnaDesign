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
