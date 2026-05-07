"""Line reactor (1Ø / 3Ø, diode-bridge front end) — Phase-A adapter
+ Phase-B state-space."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from pfc_inductor.design import design
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.models.cascade import FeasibilityEnvelope
from pfc_inductor.optimize.feasibility import core_quick_check

if TYPE_CHECKING:
    from pfc_inductor.simulate.nonlinear_inductor import NonlinearInductor


class LineReactorModel:
    """`ConverterModel` adapter for the line reactor."""

    name: str = "line_reactor"

    def __init__(self, spec: Spec) -> None:
        if spec.topology != "line_reactor":
            raise ValueError(
                f"LineReactorModel requires spec.topology == 'line_reactor', "
                f"got {spec.topology!r}",
            )
        self.spec = spec
        self._omega_line = 2.0 * math.pi * float(spec.f_line_Hz)
        # `phase_voltage_Vrms` already handles 1φ vs 3φ (V_LL/√3 for 3φ).
        self._V_phase_pk = math.sqrt(2.0) * float(spec.phase_voltage_Vrms)

    def feasibility_envelope(
        self, core: Core, material: Material, wire: Wire,
    ) -> FeasibilityEnvelope:
        verdict = core_quick_check(self.spec, core, material, wire)
        if verdict == "ok":
            return FeasibilityEnvelope(feasible=True)
        return FeasibilityEnvelope(feasible=False, reasons=[verdict])

    def steady_state(
        self, core: Core, material: Material, wire: Wire,
    ) -> DesignResult:
        return design(self.spec, core, wire, material)

    # ─── Phase-B Tier 2 — state-space ─────────────────────────────
    #
    # Line reactor in the diode-bridge + DC-link configuration: the
    # inductor sees an AC source on one side and a clamped DC voltage
    # on the other, with current shaped by the diode commutation.
    # The Tier 2 simulator dispatches passive topologies to the
    # imposed-trajectory path (Step 1), which reuses the existing
    # `topology.line_reactor.line_current_waveform` generator —
    # that already encodes the diode-bridge waveform for both 1φ
    # and 3φ cases.
    #
    # The state-space hook here is a simplified "lossy AC inductor"
    # form provided for protocol compatibility and for any future
    # transient study.

    def initial_state(self) -> np.ndarray:
        return np.array([0.0], dtype=float)

    def state_derivatives(
        self,
        t: float,
        x: np.ndarray,
        inductor: NonlinearInductor,
    ) -> np.ndarray:
        """`L(i) · di/dt = v_phase(t) − i · Z_base` where Z_base
        is the spec's per-phase base impedance.

        This is intentionally simplified — the diode-bridge
        commutation logic that determines the actual current shape
        in steady state lives in
        ``topology.line_reactor.line_current_waveform`` and is
        invoked by the imposed-trajectory simulator.
        """
        i_L = float(x[0])
        v_phase = self._V_phase_pk * math.sin(self._omega_line * t)
        Z_base = float(self.spec.phase_voltage_Vrms) / max(
            float(self.spec.I_rated_Arms), 1e-6,
        )
        v_L = v_phase - Z_base * i_L
        L = inductor.L_H(i_L)
        if L <= 1e-15:
            return np.array([0.0])
        return np.array([v_L / L])
