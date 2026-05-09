"""Magnetic-material data model — saturation, rolloff, core-loss.

A :class:`Material` carries everything the engine needs to model
the magnetic behavior of a chosen core, regardless of geometry:

- **Saturation flux density** (``Bsat_25C_T`` / ``Bsat_100C_T``)
  with the temperature-derated value used as the design ceiling.
- **Initial permeability** (``mu_initial``) — bulk-µᵢ at zero
  DC bias; the design point uses :class:`RolloffParams` to
  derate as H grows.
- **Rolloff curve** (:class:`RolloffParams`) — power-law fit
  per material family (Kool Mu, MPP, High Flux, XFlux, …)
  calibrated against vendor µ-vs-H data.
- **Core-loss model** — :class:`SteinmetzParams` for the
  classic Pv = k·fᵅ·Bᵝ form, and the iGSE coefficients
  (Mühlethaler) for non-sinusoidal flux.
- **Density** (``rho_kg_m3``) for the BOM mass × $/kg cost.

The catalog ships ~470 materials from Magnetics, TDK, Ferroxcube,
Thornton, Magmattec and OpenMagnetics. See
:mod:`pfc_inductor.data_loader` for the JSON schema and
:mod:`pfc_inductor.physics.rolloff` for the rolloff math.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class SteinmetzParams(BaseModel):
    """Anchored Steinmetz: Pv = Pv_ref * (f/f_ref)^alpha * (B/B_ref)^beta.

    Anchoring at a (f_ref, B_ref, Pv_ref) datapoint avoids unit ambiguity
    and lets the user calibrate against any published datasheet point.
    """

    Pv_ref_mWcm3: float
    f_ref_kHz: float = 100.0
    B_ref_mT: float = 100.0
    alpha: float
    beta: float
    f_min_kHz: float = 1.0
    f_max_kHz: float = 500.0


class RolloffParams(BaseModel):
    """DC bias rolloff: mu_fraction = 1 / (a + b * H^c). H in Oe by default.

    Calibrate (a, b, c) so that at H=0, mu=1.0 (i.e. a small) and at H_50
    the value is 0.5. Matches Magnetics-style published curves.
    """

    a: float
    b: float
    c: float
    H_units: Literal["Oe", "A/m"] = "Oe"


MaterialType = Literal["powder", "ferrite", "nanocrystalline", "amorphous", "silicon-steel"]


class LossDatapoint(BaseModel):
    f_kHz: float
    B_T: float
    Pv_mWcm3: float


class Material(BaseModel):
    id: str
    vendor: str
    family: str
    name: str
    type: MaterialType
    mu_initial: float
    Bsat_25C_T: float
    Bsat_100C_T: float
    rho_kg_m3: float = Field(default=5000)
    steinmetz: SteinmetzParams
    rolloff: Optional[RolloffParams] = None
    loss_datapoints: list[LossDatapoint] = Field(default_factory=list)
    cost_per_kg: Optional[float] = Field(
        default=None,
        description="Bulk material price (USD/kg). If absent, core cost is "
        "still computable from Core.cost_per_piece.",
    )
    cost_currency: str = Field(default="USD")
    notes: str = ""
