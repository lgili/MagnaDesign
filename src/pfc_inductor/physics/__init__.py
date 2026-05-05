"""Physics modules: rolloff, copper loss, core loss, thermal, cost."""

from pfc_inductor.physics.cost import (
    CostBreakdown, estimate as estimate_cost,
    wire_length_m, wire_mass_per_meter_g, core_mass_g, CU_DENSITY_KG_M3,
)

__all__ = [
    "CostBreakdown", "estimate_cost",
    "wire_length_m", "wire_mass_per_meter_g", "core_mass_g",
    "CU_DENSITY_KG_M3",
]
