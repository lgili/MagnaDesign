"""Bill-of-materials cost estimation for an inductor design.

Returns a `CostBreakdown` (core $ + wire $ + total $) when the database
entries carry the necessary fields, or `None` otherwise. The caller is
responsible for hiding the cost UI when this is None.

Auto-derivations:
- Core cost defaults to `Core.cost_per_piece`. If that's missing but the
  material has `cost_per_kg`, we use the core mass (provided or derived
  from `Ve · rho_kg_m3`) × material price.
- Wire mass per metre is derived from `A_cu_mm2 · rho_Cu` if not provided.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from pfc_inductor.models import Core, Material, Wire

CU_DENSITY_KG_M3 = 8960.0  # copper


class CostBreakdown(BaseModel):
    core_cost: float
    wire_cost: float
    total_cost: float
    currency: str
    wire_length_m: float
    wire_mass_g: float
    core_mass_g: float


def wire_length_m(N_turns: int, MLT_mm: float) -> float:
    return max(N_turns, 0) * MLT_mm * 1e-3


def wire_mass_per_meter_g(wire: Wire) -> float:
    if wire.mass_per_meter_g is not None:
        return wire.mass_per_meter_g
    if wire.A_cu_mm2 <= 0:
        return 0.0
    A_m2 = wire.A_cu_mm2 * 1e-6
    return A_m2 * 1.0 * CU_DENSITY_KG_M3 * 1000.0  # m³/m × kg/m³ × g/kg


def core_mass_g(core: Core, material: Material) -> float:
    if core.mass_g is not None:
        return core.mass_g
    return core.Ve_mm3 * 1e-9 * material.rho_kg_m3 * 1000.0


def estimate(
    core: Core,
    wire: Wire,
    material: Material,
    N_turns: int,
) -> Optional[CostBreakdown]:
    """Compute the BOM cost. Returns None if neither core nor wire price
    paths are available."""
    length_m = wire_length_m(N_turns, core.MLT_mm)
    cu_mass_g = wire_mass_per_meter_g(wire) * length_m
    cm_g = core_mass_g(core, material)

    wire_cost: Optional[float] = None
    if wire.cost_per_meter is not None:
        wire_cost = length_m * wire.cost_per_meter

    core_cost: Optional[float] = None
    if core.cost_per_piece is not None:
        core_cost = core.cost_per_piece
    elif material.cost_per_kg is not None:
        core_cost = (cm_g / 1000.0) * material.cost_per_kg

    if wire_cost is None and core_cost is None:
        return None

    return CostBreakdown(
        core_cost=float(core_cost or 0.0),
        wire_cost=float(wire_cost or 0.0),
        total_cost=float((core_cost or 0.0) + (wire_cost or 0.0)),
        currency=material.cost_currency or "USD",
        wire_length_m=length_m,
        wire_mass_g=cu_mass_g,
        core_mass_g=cm_g,
    )
