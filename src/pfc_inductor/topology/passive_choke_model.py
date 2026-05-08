"""Passive line-frequency choke — Phase-A adapter + Phase-B state-space."""

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


class PassiveChokeModel:
    """`ConverterModel` adapter for the passive line-frequency choke."""

    name: str = "passive_choke"

    def __init__(self, spec: Spec) -> None:
        if spec.topology != "passive_choke":
            raise ValueError(
                f"PassiveChokeModel requires spec.topology == 'passive_choke', "
                f"got {spec.topology!r}",
            )
        self.spec = spec
        self._omega_line = 2.0 * math.pi * float(spec.f_line_Hz)
        self._V_in_pk = math.sqrt(2.0) * float(spec.Vin_min_Vrms)

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

    # ─── Phase-B Tier 2 — state-space ─────────────────────────────
    #
    # Passive choke is a single-state AC inductor with no PWM and
    # no controller. The Tier 2 simulator dispatches passive
    # topologies to the imposed-trajectory path (Step 1) — its
    # answer is already exact for these. The state-space hooks
    # exist so the topology satisfies `Tier2ConverterModel`, and so
    # a future Step-3 transient analysis (e.g. inrush study with
    # explicit source impedance) has a plant to integrate.

    def initial_state(self) -> np.ndarray:
        return np.array([0.0], dtype=float)

    def state_derivatives(
        self,
        t: float,
        x: np.ndarray,
        inductor: NonlinearInductor,
    ) -> np.ndarray:
        """`L(i) · di/dt = v_in(t) − i · R_load`.

        We model an AC source with a load resistance chosen so the
        steady-state RMS current matches `I_rated_Arms` (when set)
        — otherwise the open-loop LC integrator has no dissipation
        and runs away. For typical passive-choke specs without a
        rated current we substitute the boost-style I_pk derived
        from `Pout_W` / `Vin_min_Vrms`.
        """
        i_L = float(x[0])
        v_in = self._V_in_pk * math.sin(self._omega_line * t)
        # Equivalent series resistance for a sinusoidal-imposed-current
        # operating point: V_in_pk / (R_eq) = I_pk → R_eq = V_in_pk / I_pk.
        I_rated = float(self.spec.I_rated_Arms)
        I_pk_des = math.sqrt(2.0) * max(I_rated, 1e-3)
        R_eq = self._V_in_pk / max(I_pk_des, 1e-6)
        v_L = v_in - R_eq * i_L
        L = inductor.L_H(i_L)
        if L <= 1e-15:
            return np.array([0.0])
        return np.array([v_L / L])
