from __future__ import annotations

import hashlib
import json
import math
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# Direct import — ``modulation`` imports nothing from spec.py, so
# this is acyclic. Required at runtime so Pydantic v2 can resolve
# the ``Optional[FswModulation]`` field annotation when validating
# a Spec from JSON.
from pfc_inductor.models.modulation import FswModulation

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
    T_max_C: float = Field(125.0, description="Max allowable winding temp")

    Ku_max: float = Field(0.7, ge=0.05, le=0.7, description="Max window utilization (0.4 round, 0.2 litz)")
    Bsat_margin: float = Field(0.20, ge=0.0, le=0.5,
                               description="Saturation margin (20% means use Bsat*0.8 as limit)")

    # --- line reactor only ---
    n_phases: int = Field(
        3, ge=1, le=3,
        description="1 or 3 — only used when topology == 'line_reactor'",
    )
    L_req_mH: float = Field(
        10.0, ge=0.05, le=1000.0,
        description=(
            "Target inductance for the reactor (mH). The legacy "
            "``pct_impedance`` kwarg auto-converts to this field via "
            "the model_validator below; very low %Z values (0.5 %) "
            "land near the 0.05 mH floor."
        ),
    )
    I_rated_Arms: float = Field(
        2.2, gt=0.0,
        description="Rated continuous RMS current at the reactor (line side).",
    )

    # --- Variable-frequency-drive (VFD) modulation envelope ---
    # When a compressor inverter dithers fsw across a band — typical
    # 4–25 kHz on appliance compressors — the engine must evaluate
    # the design at multiple fsw points to surface the worst-case
    # corner across the band, not just at a single nominal point.
    # Default ``None`` keeps every existing `.pfc` round-trip-safe
    # and routes through the single-point engine path. See
    # :mod:`pfc_inductor.models.modulation` for the field details.
    fsw_modulation: Optional[FswModulation] = Field(
        None,
        description=(
            "Optional VFD switching-frequency band. When set, the "
            "engine evaluates the design at every ``fsw_modulation."
            "fsw_points_kHz()`` point and aggregates the worst-case "
            "envelope. ``None`` (default) preserves single-point "
            "behaviour."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _convert_legacy_pct_impedance(cls, data):
        """Back-compat shim: callers (and tests) that still pass
        ``pct_impedance=X`` get it auto-converted to the equivalent
        ``L_req_mH`` from base impedance and rated current. The
        legacy kwarg is consumed so it doesn't trip Pydantic's
        ``extra='forbid'`` mode.
        """
        if not isinstance(data, dict):
            return data
        pct_z = data.pop("pct_impedance", None)
        if pct_z is None:
            return data
        # Don't override an explicit L_req_mH.
        if "L_req_mH" in data:
            return data
        v_nom = float(data.get("Vin_nom_Vrms", 230.0))
        n_phases = int(data.get("n_phases", 3))
        v_phase = v_nom / math.sqrt(3.0) if n_phases == 3 else v_nom
        i_rated = float(data.get("I_rated_Arms", 2.2))
        f_line = float(data.get("f_line_Hz", 50.0))
        z_base = v_phase / max(i_rated, 1e-9)
        z_react = float(pct_z) / 100.0 * z_base
        l_req_h = z_react / (2.0 * math.pi * max(f_line, 1.0))
        data["L_req_mH"] = l_req_h * 1000.0
        return data

    @model_validator(mode="after")
    def _check_voltages(self) -> Spec:
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

    @property
    def pct_impedance(self) -> float:
        """Derived %Z at rated current from ``L_req_mH``.

        Kept as a read-only computed property for back-compat with
        callers (e.g. ``topology.line_reactor.reactor_impedance_ohm``)
        and tests written before the v3.x migration to a direct
        ``L_req_mH`` field. New code should compute this on demand or
        use the topology helpers.
        """
        if self.topology != "line_reactor":
            return 0.0
        omega = 2.0 * math.pi * max(self.f_line_Hz, 1.0)
        z_react = omega * (self.L_req_mH * 1e-3)
        z_base = self.phase_voltage_Vrms / max(self.I_rated_Arms, 1e-9)
        if z_base <= 0:
            return 0.0
        return 100.0 * z_react / z_base

    def canonical_hash(self) -> str:
        """SHA-256 over the canonical JSON of every spec field.

        Used by the cascade `RunStore` to detect that a resumed run
        is being attempted against a different spec than the one it
        was started with — guarantees reproducibility.
        """
        payload = self.model_dump(mode="json", exclude_none=False)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
