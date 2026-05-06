"""Subset of the OpenMagnetics MAS schema as pydantic v2 models.

Captures the fields we need for material / core / wire description plus
loss methods and rolloff (via `x-pfc-inductor` extension namespace).
Does not aim for full MAS coverage — that's a future evolution.

References:
- https://github.com/OpenMagnetics/MAS
- https://openmagnetics.com (schema docs)

Convention: every model uses `model_config = ConfigDict(populate_by_name=True)`
so we can write JSON with the MAS canonical names and read it via
PEP-8-friendly Python attribute names.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Material building blocks
# ---------------------------------------------------------------------------
class MasPermeability(BaseModel):
    """`magnetic.material.permeability` — initial relative permeability.

    MAS expresses permeability with several entries (initial, vs frequency,
    etc.). For our PFC use we keep the canonical initial value plus optional
    extensions.
    """
    model_config = ConfigDict(populate_by_name=True)

    initial_value: float = Field(alias="initialValue")


class MasSaturation(BaseModel):
    """One row of `magnetic.material.saturation` — Bsat at a temperature."""
    model_config = ConfigDict(populate_by_name=True)

    temperature_C: float = Field(alias="temperature")
    magnetic_flux_density_T: float = Field(alias="magneticFluxDensity")


class MasSteinmetzCoeffs(BaseModel):
    """Coefficients for the anchored Steinmetz law."""
    model_config = ConfigDict(populate_by_name=True)

    k: float
    alpha: float
    beta: float


class MasCoreLoss(BaseModel):
    """`magnetic.material.coreLossesMethods[]` entry."""
    model_config = ConfigDict(populate_by_name=True)

    method: Literal["steinmetz", "iGSE", "table"]
    coefficients: Optional[MasSteinmetzCoeffs] = None
    reference_frequency_Hz: Optional[float] = Field(
        default=None, alias="referenceFrequency",
    )
    reference_flux_density_T: Optional[float] = Field(
        default=None, alias="referenceFluxDensity",
    )


class MasMaterial(BaseModel):
    """Subset of `magnetic.material` for our use.

    Custom fields (id, calibrated rolloff, cost, raw loss measurements) live
    under the `x-pfc-inductor` namespace so MAS validators don't choke on
    unknown fields.
    """
    model_config = ConfigDict(populate_by_name=True)

    name: str
    manufacturer: str
    family: str = ""
    type: str = "powder"   # MAS uses lowercase; we mirror

    permeability: MasPermeability
    saturation: list[MasSaturation] = Field(default_factory=list)
    core_losses_methods: list[MasCoreLoss] = Field(
        default_factory=list, alias="coreLossesMethods",
    )
    density_kg_m3: Optional[float] = Field(default=None, alias="density")

    notes: str = ""
    x_pfc_inductor: dict[str, Any] = Field(
        default_factory=dict, alias="x-pfc-inductor",
    )


# ---------------------------------------------------------------------------
# Core building blocks
# ---------------------------------------------------------------------------
class MasCoreShape(BaseModel):
    """`magnetic.core.shape` — name + family (e.g. "T-25-15-10" / "Toroid")."""
    model_config = ConfigDict(populate_by_name=True)

    name: str
    family: str = ""   # toroid, e, etd, pq, ...


class MasCoreDimensions(BaseModel):
    """Effective dimensions of the core in millimetres / cubic millimetres.

    MAS keeps these under `magnetic.core.functionalDescription[].coreFunctionalDescription`
    in the spec, but for our pragmatic interop we flatten them.
    """
    model_config = ConfigDict(populate_by_name=True)

    Ae_mm2: float = Field(alias="effectiveArea")
    le_mm: float = Field(alias="effectiveMagneticPathLength")
    Ve_mm3: float = Field(alias="effectiveVolume")
    Wa_mm2: float = Field(alias="windingWindowArea", default=0.0)
    MLT_mm: float = Field(alias="meanLengthTurn", default=0.0)
    OD_mm: Optional[float] = Field(default=None, alias="outerDiameter")
    ID_mm: Optional[float] = Field(default=None, alias="innerDiameter")
    HT_mm: Optional[float] = Field(default=None, alias="height")


class MasCore(BaseModel):
    """`magnetic.core` subset."""
    model_config = ConfigDict(populate_by_name=True)

    name: str             # part number
    manufacturer: str
    shape: MasCoreShape
    dimensions: MasCoreDimensions
    material_name: str = Field(alias="materialName")
    inductance_factor_nH: float = Field(alias="inductanceFactor")
    gap_length_mm: float = Field(default=0.0, alias="gapLength")
    notes: str = ""
    x_pfc_inductor: dict[str, Any] = Field(
        default_factory=dict, alias="x-pfc-inductor",
    )


# ---------------------------------------------------------------------------
# Wire building blocks
# ---------------------------------------------------------------------------
class MasWire(BaseModel):
    """Subset of `magnetic.coil.functionalDescription[].wire`."""
    model_config = ConfigDict(populate_by_name=True)

    name: str
    type: Literal["round", "litz", "foil"] = "round"
    awg: Optional[int] = None
    conducting_diameter_mm: Optional[float] = Field(
        default=None, alias="conductingDiameter",
    )
    insulated_diameter_mm: Optional[float] = Field(
        default=None, alias="outerDiameter",
    )
    conducting_area_mm2: float = Field(alias="conductingArea")
    # Litz extras
    strand_awg: Optional[int] = Field(default=None, alias="strandAwg")
    strand_diameter_mm: Optional[float] = Field(
        default=None, alias="strandDiameter",
    )
    number_strands: Optional[int] = Field(default=None, alias="numberStrands")
    bundle_diameter_mm: Optional[float] = Field(
        default=None, alias="bundleDiameter",
    )
    # Cost (custom)
    cost_per_meter: Optional[float] = Field(default=None, alias="costPerMeter")
    mass_per_meter_g: Optional[float] = Field(
        default=None, alias="massPerMeter",
    )

    notes: str = ""
    x_pfc_inductor: dict[str, Any] = Field(
        default_factory=dict, alias="x-pfc-inductor",
    )
