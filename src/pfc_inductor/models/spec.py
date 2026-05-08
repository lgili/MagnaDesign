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

Topology = Literal[
    "boost_ccm",
    "passive_choke",
    "line_reactor",
    "buck_ccm",
    "interleaved_boost_pfc",
    "flyback",
]


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

    Vout_V: float = Field(
        400.0, description="DC bus voltage. Ignored for passive choke / line reactor."
    )
    Pout_W: float = Field(800.0, description="Output power")
    eta: float = Field(
        0.97, ge=0.5, le=1.0, description="Assumed converter efficiency for current calc"
    )

    f_sw_kHz: float = Field(
        65.0, description="Switching frequency. Ignored for passive choke / line reactor."
    )
    ripple_pct: float = Field(
        30.0,
        ge=1.0,
        le=100.0,
        description="Peak-to-peak inductor current ripple, % of peak line current",
    )

    T_amb_C: float = Field(40.0, description="Ambient temperature for thermal calc")
    T_max_C: float = Field(125.0, description="Max allowable winding temp")

    Ku_max: float = Field(
        0.7, ge=0.05, le=0.7, description="Max window utilization (0.4 round, 0.2 litz)"
    )
    Bsat_margin: float = Field(
        0.20, ge=0.0, le=0.5, description="Saturation margin (20% means use Bsat*0.8 as limit)"
    )

    # --- line reactor only ---
    n_phases: int = Field(
        3,
        ge=1,
        le=3,
        description="1 or 3 — only used when topology == 'line_reactor'",
    )

    # --- interleaved boost PFC only ---
    # Number of parallel boost stages, PWM-shifted by 360°/N. Each
    # phase carries 1/N of the total input current; the engine sizes
    # one inductor (per ``per_phase_spec``) and the BOM lists it
    # ``×N`` times. 2-phase is the dominant choice (server PSUs,
    # 3–10 kW residential AC); 3-phase appears in EV chargers and
    # high-end industrial PSUs. The cancellation formulas only close
    # for the symmetric N-phase case so we restrict to 2 or 3.
    n_interleave: int = Field(
        2,
        ge=2,
        le=3,
        description=(
            "Number of parallel interleaved boost phases (2 or 3). "
            "Only used when topology == 'interleaved_boost_pfc'."
        ),
    )
    L_req_mH: float = Field(
        10.0,
        ge=0.05,
        le=1000.0,
        description=(
            "Target inductance for the reactor (mH). The legacy "
            "``pct_impedance`` kwarg auto-converts to this field via "
            "the model_validator below; very low %Z values (0.5 %) "
            "land near the 0.05 mH floor."
        ),
    )
    I_rated_Arms: float = Field(
        2.2,
        gt=0.0,
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

    # --- buck-CCM (DC-input topology) ---
    # ``Vin_dc_V`` is the nominal DC input voltage when the spec is a
    # DC-DC topology (currently ``buck_ccm``; future ``flyback`` /
    # ``psfb_output_choke`` will reuse the same field). When ``None``
    # the engine falls back to ``Vin_min_Vrms`` for backward
    # compatibility with legacy specs.
    Vin_dc_V: Optional[float] = Field(
        None,
        description=(
            "DC input voltage (volts). Used only for DC-input "
            "topologies (buck_ccm). For AC-input topologies leave "
            "as None — Vin_min/max/nom_Vrms drive the design."
        ),
    )
    Vin_dc_min_V: Optional[float] = Field(
        None,
        description="Lower bound of Vin_dc_V range (worst-case current).",
    )
    Vin_dc_max_V: Optional[float] = Field(
        None,
        description="Upper bound of Vin_dc_V range (worst-case ripple).",
    )

    # Buck-specific design knob: target ripple ratio ``ΔI_pp / Iout``.
    # 0.30 is the textbook optimum (Erickson §5.2). Lower values give
    # bigger inductors; higher values shrink L at the cost of larger
    # output capacitance. Ignored for non-buck topologies.
    ripple_ratio: Optional[float] = Field(
        None,
        ge=0.05,
        le=1.0,
        description=(
            "Target ΔI_pp / I_out for buck designs. 0.20–0.40 typical. "
            "When None, the legacy ``ripple_pct`` field is reused as "
            "a percent of I_out so old specs keep working."
        ),
    )

    # --- flyback (coupled-inductor isolated DC-DC) ---
    # Design-time operating mode. DCM is the textbook starting
    # point and works with every silicon controller; CCM gives
    # lower peak currents at the cost of a RHP zero in the
    # control loop. Ignored for non-flyback topologies.
    flyback_mode: Optional[Literal["dcm", "ccm"]] = Field(
        None,
        description=(
            "Flyback operating mode at design time. 'dcm' (default) "
            "stores energy fully each cycle; 'ccm' keeps non-zero "
            "primary current for lower peak stress. Ignored when "
            "topology != 'flyback'."
        ),
    )
    # Turns ratio Np/Ns. When None the engine picks the optimal
    # ratio that equalises FET drain stress and diode reverse
    # stress (V_drain_target ~ 600 V universal-input default).
    turns_ratio_n: Optional[float] = Field(
        None,
        gt=0.0,
        le=20.0,
        description=(
            "Primary-to-secondary turns ratio Np/Ns for flyback "
            "designs. None lets the engine pick an optimal value "
            "from the equal-stress design rule."
        ),
    )
    # Window-split factor for the primary winding (rest goes to
    # secondary). 0.45 is the textbook sandwich-winding default;
    # raising toward 0.55 favours the primary at the cost of
    # higher secondary fill.
    window_split_primary: float = Field(
        0.45,
        ge=0.30,
        le=0.65,
        description=(
            "Fraction of the bobbin window allocated to the primary "
            "winding in a flyback design. 0.45 is the textbook "
            "sandwich-winding default. Ignored for single-winding "
            "topologies."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _convert_legacy_pct_impedance(cls, data: object) -> object:
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
                    f"Vout_V={self.Vout_V} must exceed Vin_max_pk={self.Vin_max_Vrms * 1.41:.1f} for boost"
                )
        if self.topology == "line_reactor":
            if self.n_phases not in (1, 3):
                raise ValueError("line_reactor: n_phases must be 1 or 3")
        if self.topology == "interleaved_boost_pfc":
            # Same boost step-up rule per phase.
            if self.Vout_V <= self.Vin_max_Vrms * 1.41:
                raise ValueError(
                    f"interleaved_boost_pfc: Vout_V={self.Vout_V} must exceed "
                    f"Vin_max_pk={self.Vin_max_Vrms * 1.41:.1f} (each phase is "
                    "still a boost stage)."
                )
            if self.n_interleave not in (2, 3):
                raise ValueError(
                    "interleaved_boost_pfc: n_interleave must be 2 or 3 "
                    "(only the symmetric phase-shift case has closed-form "
                    "ripple cancellation)."
                )
        if self.topology == "buck_ccm":
            # Buck must step DOWN: Vout < Vin (with margin for duty
            # ratio < 0.99). Use ``Vin_dc_min_V`` if provided, else
            # ``Vin_dc_V``, else fall back to the legacy AC field so
            # specs migrated from boost-CCM tests don't fail loading.
            v_in = self.Vin_dc_min_V or self.Vin_dc_V or self.Vin_min_Vrms
            if v_in is None or v_in <= 0:
                raise ValueError("buck_ccm: Vin_dc_V (or Vin_dc_min_V) must be > 0")
            if self.Vout_V >= v_in * 0.99:
                raise ValueError(
                    f"buck_ccm: Vout_V={self.Vout_V} must be < "
                    f"Vin (got Vin={v_in}); buck is a step-down "
                    "converter — use boost_ccm if Vout > Vin."
                )
        if self.topology == "flyback":
            # Flyback is a buck-boost dressed in a coupled inductor
            # — Vout can be either above or below Vin. The only
            # hard requirements are Vin > 0 and Vout > 0; the
            # turns ratio handles whatever ratio the user picks.
            v_in = self.Vin_dc_min_V or self.Vin_dc_V or self.Vin_min_Vrms
            if v_in is None or v_in <= 0:
                raise ValueError("flyback: Vin_dc_V (or Vin_dc_min_V) must be > 0")
            if self.Vout_V <= 0:
                raise ValueError("flyback: Vout_V must be > 0")
            if self.flyback_mode is not None and self.flyback_mode not in ("dcm", "ccm"):
                raise ValueError(f"flyback_mode must be 'dcm' or 'ccm', got {self.flyback_mode!r}")
        return self

    @property
    def Vin_min_pk(self) -> float:
        return self.Vin_min_Vrms * (2**0.5)

    @property
    def Vin_max_pk(self) -> float:
        return self.Vin_max_Vrms * (2**0.5)

    @property
    def Vin_nom_pk(self) -> float:
        return self.Vin_nom_Vrms * (2**0.5)

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
