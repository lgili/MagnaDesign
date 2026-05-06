"""Physics modules: rolloff, copper loss, core loss, thermal, cost."""

from pfc_inductor.physics.cost import (
    CU_DENSITY_KG_M3,
    CostBreakdown,
    core_mass_g,
    wire_length_m,
    wire_mass_per_meter_g,
)
from pfc_inductor.physics.cost import (
    estimate as estimate_cost,
)

__all__ = [
    "CU_DENSITY_KG_M3",
    "CostBreakdown",
    "core_mass_g",
    "estimate_cost",
    "wire_length_m",
    "wire_mass_per_meter_g",
]
