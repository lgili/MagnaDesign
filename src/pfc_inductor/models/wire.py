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
