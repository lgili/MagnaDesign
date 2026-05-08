"""MAS (Magnetic Agnostic Structure) — interop with OpenMagnetics.

This module is the bridge between our internal `Material` / `Core` / `Wire`
classes and the PSMA-incubated MAS schema. The internal API stays
unchanged; persistence and import paths can opt-in to MAS by going
through these adapters.

Public:
    pfc_inductor.models.mas.types       — subset of MAS as pydantic v2
    pfc_inductor.models.mas.adapters    — material/core/wire ↔ MAS
"""

from pfc_inductor.models.mas.adapters import (
    core_from_mas,
    core_to_mas,
    material_from_mas,
    material_to_mas,
    wire_from_mas,
    wire_to_mas,
)
from pfc_inductor.models.mas.types import (
    MasCore,
    MasCoreDimensions,
    MasCoreLoss,
    MasCoreShape,
    MasMaterial,
    MasPermeability,
    MasSaturation,
    MasSteinmetzCoeffs,
    MasWire,
)

__all__ = [
    "MasCore",
    "MasCoreDimensions",
    "MasCoreLoss",
    "MasCoreShape",
    "MasMaterial",
    "MasPermeability",
    "MasSaturation",
    "MasSteinmetzCoeffs",
    "MasWire",
    "core_from_mas",
    "core_to_mas",
    "material_from_mas",
    "material_to_mas",
    "wire_from_mas",
    "wire_to_mas",
]
