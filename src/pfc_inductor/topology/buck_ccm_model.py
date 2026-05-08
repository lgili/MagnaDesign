"""Buck-CCM converter model — `ConverterModel` adapter.

Wraps :mod:`pfc_inductor.topology.buck_ccm` (math) and
:func:`pfc_inductor.design.engine.design` (analytical solver) behind
the ``ConverterModel`` Protocol so the cascade orchestrator's
Tier 0/1/2 paths work for buck-CCM the same way they work for boost.

Buck has no AC line envelope, so ``state_derivatives`` is the
simplest of all the topology adapters: a one-state ODE on ``i_L``
with ``v_L = Vin − Vout`` during the switch's ON phase and
``v_L = −Vout`` during OFF. The PWM carrier is a sawtooth at
``f_sw``.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from pfc_inductor.design import design
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.models.cascade import FeasibilityEnvelope
from pfc_inductor.optimize.feasibility import core_quick_check
from pfc_inductor.topology import buck_ccm

if TYPE_CHECKING:
    from pfc_inductor.simulate.nonlinear_inductor import NonlinearInductor


class BuckCCMModel:
    """``ConverterModel`` adapter for synchronous DC-DC buck in CCM."""

    name: str = "buck_ccm"

    def __init__(self, spec: Spec) -> None:
        if spec.topology != "buck_ccm":
            raise ValueError(
                f"BuckCCMModel requires spec.topology == 'buck_ccm', "
                f"got {spec.topology!r}",
            )
        self.spec = spec
        # Cached scalars used inside the hot ODE path.
        self._V_in = buck_ccm._vin_nom(spec)
        self._V_out = float(spec.Vout_V)
        self._f_sw_Hz = float(spec.f_sw_kHz) * 1000.0
        # CCM volt-seconds duty: D = Vout / (Vin · η). Cached so the
        # ODE doesn't recompute it every step.
        eta = float(getattr(spec, "eta", 0.97) or 0.97)
        if self._V_in > 0:
            self._duty = min(self._V_out / (self._V_in * max(eta, 0.5)), 0.99)
        else:
            self._duty = 0.0

    # ─── Tier-0 / Tier-1 ─────────────────────────────────────────

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

    # ─── Tier-2: state-space transient simulation ────────────────

    def initial_state(self) -> np.ndarray:
        """Start near steady state — a buck reaches its DC operating
        point in a handful of switching periods, but starting from
        zero adds an unnecessary transient. Use ``Iout`` as the
        initial guess; the integrator settles instantly.
        """
        return np.array([buck_ccm.output_current_A(self.spec)], dtype=float)

    def state_derivatives(
        self,
        t: float,
        x: np.ndarray,
        inductor: "NonlinearInductor",
    ) -> np.ndarray:
        """Buck-CCM inductor: ``L · di/dt = v_L``.

        Switch ON  (carrier < D):  v_L = Vin − Vout
        Switch OFF (carrier ≥ D):  v_L = −Vout

        State layout (``x``):
            ``x[0] = i_L`` (A) — inductor current
        """
        i_L = float(x[0])

        # Sawtooth PWM carrier in [0, 1) at the switching frequency.
        carrier = (t * self._f_sw_Hz) % 1.0
        if carrier < self._duty:
            v_L = self._V_in - self._V_out
        else:
            v_L = -self._V_out

        L = inductor.L_H(i_L)
        if L <= 0.0:
            return np.array([0.0])
        return np.array([v_L / L])
