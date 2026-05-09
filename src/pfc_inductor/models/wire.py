"""Wire data model — round, Litz, and foil constructions.

A :class:`Wire` carries the conductor metrics the engine uses
for window-fill, copper loss, and AC-loss (Dowell):

- **Geometry** — ``d_cu_mm`` (bare copper diameter), ``d_iso_mm``
  (over-insulation), ``A_cu_mm2`` (copper cross-section).
- **Construction** — ``type`` (``"round"`` / ``"litz"`` / ``"foil"``)
  and the Litz-specific extras (``n_strands``, ``d_strand_mm``,
  ``awg_strand``, ``d_bundle_mm``).
- **Cost / mass** — ``cost_per_meter`` and ``mass_per_meter_g``
  for the BOM.

The catalog ships 1 433 round wires from AWG40 → AWG0 plus a
curated Litz set (0.05 mm → 0.30 mm strands, 7 → 4 050 strands).
See :mod:`pfc_inductor.optimize.litz` for the Sullivan-criterion
optimizer that picks Litz constructions on demand and
:mod:`pfc_inductor.physics.dowell` for the AC-loss model.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

WireType = Literal["round", "litz", "foil"]


class Wire(BaseModel):
    id: str
    type: WireType
    awg: Optional[int] = None
    d_cu_mm: Optional[float] = None
    d_iso_mm: Optional[float] = None
    A_cu_mm2: float

    awg_strand: Optional[int] = None
    d_strand_mm: Optional[float] = None
    n_strands: Optional[int] = None
    d_bundle_mm: Optional[float] = None

    cost_per_meter: Optional[float] = None
    mass_per_meter_g: Optional[float] = None

    notes: str = ""

    def outer_diameter_mm(self) -> float:
        if self.type == "litz" and self.d_bundle_mm is not None:
            return self.d_bundle_mm
        if self.d_iso_mm is not None:
            return self.d_iso_mm
        if self.d_cu_mm is not None:
            return self.d_cu_mm
        raise ValueError(f"Wire {self.id} has no diameter info")
