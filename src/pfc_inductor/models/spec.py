from __future__ import annotations
import math
from typing import Literal
from pydantic import BaseModel, Field, model_validator

Topology = Literal["boost_ccm", "passive_choke", "line_reactor"]


class Spec(BaseModel):
    """Design spec for a PFC inductor or AC line reactor."""

    topology: Topology = "boost_ccm"

    Vin_min_Vrms: float = Field(85.0, description="Lower input AC RMS (universal mains)")
    Vin_max_Vrms: float = Field(265.0, description="Upper input AC RMS")
    Vin_nom_Vrms: float = Field(
        230.0,
        description=(
            "Nominal AC RMS for steady-state operating point. For "
            "line_reactor with n_phases=3, this is the line-to-line "
            "voltage; for n_phases=1, line-to-neutral."
        ),
    )
    f_line_Hz: float = Field(50.0, description="Line frequency (50 or 60 Hz)")

    Vout_V: float = Field(400.0, description="DC bus voltage. Ignored for passive choke / line reactor.")
    Pout_W: float = Field(800.0, description="Output power")
    eta: float = Field(0.97, ge=0.5, le=1.0, description="Assumed converter efficiency for current calc")

    f_sw_kHz: float = Field(65.0, description="Switching frequency. Ignored for passive choke / line reactor.")
    ripple_pct: float = Field(30.0, ge=1.0, le=100.0,
                              description="Peak-to-peak inductor current ripple, % of peak line current")

    T_amb_C: float = Field(40.0, description="Ambient temperature for thermal calc")
    T_max_C: float = Field(100.0, description="Max allowable winding temp")

    Ku_max: float = Field(0.4, ge=0.05, le=0.7, description="Max window utilization (0.4 round, 0.2 litz)")
    Bsat_margin: float = Field(0.20, ge=0.0, le=0.5,
                               description="Saturation margin (20% means use Bsat*0.8 as limit)")

    # --- line reactor only ---
    n_phases: int = Field(
        3, ge=1, le=3,
        description="1 or 3 — only used when topology == 'line_reactor'",
    )
    pct_impedance: float = Field(
        5.0, ge=0.5, le=20.0,
        description=(
            "Target % of base line impedance for the reactor. "
            "Typical: 3 (light filtering) / 5 (standard) / 8 (heavy)."
        ),
    )
    I_rated_Arms: float = Field(
        30.0, gt=0.0,
        description="Rated continuous RMS current at the reactor (line side).",
    )

    @model_validator(mode="after")
    def _check_voltages(self) -> "Spec":
        if self.topology == "boost_ccm":
            if self.Vout_V <= self.Vin_max_Vrms * 1.41:
                raise ValueError(
                    f"Vout_V={self.Vout_V} must exceed Vin_max_pk={self.Vin_max_Vrms*1.41:.1f} for boost"
                )
        if self.topology == "line_reactor":
            if self.n_phases not in (1, 3):
                raise ValueError("line_reactor: n_phases must be 1 or 3")
        return self

    @property
    def Vin_min_pk(self) -> float:
        return self.Vin_min_Vrms * (2 ** 0.5)

    @property
    def Vin_max_pk(self) -> float:
        return self.Vin_max_Vrms * (2 ** 0.5)

    @property
    def Vin_nom_pk(self) -> float:
        return self.Vin_nom_Vrms * (2 ** 0.5)

    @property
    def phase_voltage_Vrms(self) -> float:
        """Per-phase RMS voltage.

        For 3-phase line reactors ``Vin_nom_Vrms`` is interpreted as the
        line-to-line voltage and the per-phase value is V_LL/√3. For
        single-phase (or other topologies), it's already the per-phase
        value.
        """
        if self.topology == "line_reactor" and self.n_phases == 3:
            return self.Vin_nom_Vrms / math.sqrt(3.0)
        return self.Vin_nom_Vrms
