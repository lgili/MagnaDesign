"""Boost-CCM converter model — Phase-A adapter + Phase-B state-space.

Wraps `boost_ccm.py` (math) and `design.engine.design` (analytical
solver) behind the `ConverterModel` Protocol, and adds the Phase-B
``Tier2ConverterModel`` hooks for the transient simulator: the PFC
cycle-averaged inductor differential equation with PWM-resolved
switch state.
"""

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


class BoostCCMModel:
    """`ConverterModel` adapter for active boost PFC in CCM."""

    name: str = "boost_ccm"

    def __init__(self, spec: Spec) -> None:
        if spec.topology != "boost_ccm":
            raise ValueError(
                f"BoostCCMModel requires spec.topology == 'boost_ccm', got {spec.topology!r}",
            )
        self.spec = spec
        # Cached scalars used inside the hot ODE path.
        self._omega_line = 2.0 * math.pi * float(spec.f_line_Hz)
        self._V_in_pk = math.sqrt(2.0) * float(spec.Vin_min_Vrms)
        self._V_out = float(spec.Vout_V)
        self._f_sw_Hz = float(spec.f_sw_kHz) * 1000.0

    def feasibility_envelope(
        self,
        core: Core,
        material: Material,
        wire: Wire,
    ) -> FeasibilityEnvelope:
        verdict = core_quick_check(self.spec, core, material, wire)
        if verdict == "ok":
            return FeasibilityEnvelope(feasible=True)
        return FeasibilityEnvelope(feasible=False, reasons=[verdict])

    def steady_state(
        self,
        core: Core,
        material: Material,
        wire: Wire,
    ) -> DesignResult:
        return design(self.spec, core, wire, material)

    # ─── Phase-B: Tier 2 state-space ─────────────────────────────

    def initial_state(self) -> np.ndarray:
        """Start from rest. The transient integrator drives the line
        envelope up over the first cycle and converges within a
        handful of cycles for boost CCM."""
        return np.array([0.0], dtype=float)

    def state_derivatives(
        self,
        t: float,
        x: np.ndarray,
        inductor: NonlinearInductor,
    ) -> np.ndarray:
        """Boost-CCM PFC inductor: `L(i) · di/dt = v_in − s · V_out`.

        Steady-state CCM control imposes the duty cycle
        `d(t) = 1 − v_in(t) / V_out` so that the time-averaged
        inductor voltage is zero across each switching period; the
        switch state `s ∈ {0, 1}` is recovered from a sawtooth carrier
        synchronised to the spec's switching frequency.

        Diode bridge rectification gives `v_in(t) = √2 · V_in_RMS ·
        |sin(ω_line · t)|`. Worst-case sizing uses ``Vin_min_Vrms``,
        matching the analytical engine.

        State layout (`x`):
            x[0] = i_L (A)        — inductor current
        """
        i_L = float(x[0])

        # Line envelope (rectified sinusoid).
        v_in = self._V_in_pk * abs(math.sin(self._omega_line * t))

        # PWM duty for steady-state CCM regulation.
        if self._V_out > 0:
            duty = 1.0 - v_in / self._V_out
        else:
            duty = 0.0
        if duty < 0.0:
            duty = 0.0
        elif duty > 1.0:
            duty = 1.0

        # Sawtooth carrier in [0, 1) at the switching frequency.
        carrier = (t * self._f_sw_Hz) % 1.0
        # Switch closed (s=0) when carrier < duty: V_out shorted out
        # of the inductor loop; else the inductor sees v_in − V_out.
        if carrier < duty:
            v_L = v_in
        else:
            v_L = v_in - self._V_out

        L = inductor.L_H(i_L)
        if L <= 0.0:
            return np.array([0.0])
        return np.array([v_L / L])
