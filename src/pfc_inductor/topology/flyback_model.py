"""Flyback converter model — `ConverterModel` adapter.

Wraps :mod:`pfc_inductor.topology.flyback` (math) and
:func:`pfc_inductor.design.engine.design` (analytical solver) behind
the ``ConverterModel`` Protocol so the cascade orchestrator's
Tier 0/1/2 paths work for flyback the same way they work for buck.

Compared to single-winding topologies, flyback's ``state_derivatives``
is more interesting: there are TWO conduction phases per
switching cycle (ON: primary ramps up; OFF/demag: secondary ramps
down). The state vector is ``[i_p, i_s]`` and the integrator
flips between them based on the PWM carrier.

For Tier 0 / Tier 1, the analytical engine handles both the
primary and secondary winding sizing — this adapter just
delegates to ``design()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from pfc_inductor.design import design
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.models.cascade import FeasibilityEnvelope
from pfc_inductor.optimize.feasibility import core_quick_check
from pfc_inductor.topology import flyback

if TYPE_CHECKING:
    from pfc_inductor.simulate.nonlinear_inductor import NonlinearInductor


class FlybackModel:
    """``ConverterModel`` adapter for flyback (DCM + CCM)."""

    name: str = "flyback"

    def __init__(self, spec: Spec) -> None:
        if spec.topology != "flyback":
            raise ValueError(
                f"FlybackModel requires spec.topology == 'flyback', got {spec.topology!r}",
            )
        self.spec = spec
        # Cached scalars for the hot ODE path.
        self._V_in = flyback._vin_nom(spec)
        self._V_in_min = flyback._vin_min(spec)
        self._V_out = float(spec.Vout_V)
        self._f_sw_Hz = float(spec.f_sw_kHz) * 1000.0
        self._n = flyback.optimal_turns_ratio(spec)
        self._mode = flyback._flyback_mode(spec)
        # Duty cycle at the design (low-line) operating point.
        if self._mode == "ccm":
            self._duty = flyback.ccm_duty_cycle(
                spec,
                self._n,
                Vin=self._V_in_min,
            )
        else:
            # Need Lp for DCM duty; we can't compute it here without
            # the core. The ODE path falls back to a fixed D=0.45
            # boundary if Tier 2 ever invokes it on a flyback spec
            # without going through Tier 1 first. In practice the
            # cascade always runs Tier 1 (the analytical pass) before
            # Tier 2, so this fallback rarely fires.
            self._duty = 0.45

    # ─── Tier-0 / Tier-1 ─────────────────────────────────────────

    def feasibility_envelope(
        self,
        core: Core,
        material: Material,
        wire: Wire,
    ) -> FeasibilityEnvelope:
        """Tier-0 envelope: the cheap single-winding feasibility
        check applied to the primary side. Full two-winding window
        check happens in Tier 1 inside ``design()``.

        Engineers reading this might wonder why we don't validate
        the secondary here too — the answer is that Tier 0 is the
        "is this combination even worth the engine call" filter,
        and 99 % of unfeasible flyback designs fail the primary
        side first (window overflow on Np or saturation at the
        primary's peak). The secondary check happens in Tier 1
        once we've actually picked Np / Ns; we don't have those
        numbers in Tier 0.
        """
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

    # ─── Tier-2: state-space transient simulation ────────────────

    def initial_state(self) -> np.ndarray:
        """Start at zero — flyback's natural cold-start condition.

        DCM steady-state is reached within ``~3·Lp/R_eq`` seconds;
        for typical ``Lp = 100 µH`` and ``R_eq = 1 Ω`` (small flyback)
        that's 300 µs, well below any meaningful Tier-2 simulation
        window. Starting from zero is also physically faithful to
        the real cold-start transient an engineer might want to
        observe.

        State layout: ``x[0] = i_p`` (primary current),
        ``x[1] = i_s`` (secondary current).
        """
        return np.array([0.0, 0.0], dtype=float)

    def state_derivatives(
        self,
        t: float,
        x: np.ndarray,
        inductor: NonlinearInductor,
    ) -> np.ndarray:
        """Flyback two-state ODE: ``Lp · dip/dt = v_Lp`` and
        ``Ls · dis/dt = v_Ls`` with the conduction-phase logic.

        DCM has three phases; CCM has two. The carrier-vs-duty
        comparator picks the active phase per integration step.

        Phase 1 (ON, ``carrier < D``):
            primary: ``v_Lp = Vin``  ⇒  ip ramps up
            secondary: ``v_Ls = -Vout``  ⇒  is is forced to 0
                (in DCM and CCM, the secondary diode is reverse-
                biased during the primary's conduction window)

        Phase 2 (DEMAG, ``D ≤ carrier < D + D2``):
            primary: ``v_Lp = -n · Vout``  ⇒  ip ramps down to 0
                (DCM) or to the minimum (CCM)
            secondary: ``v_Ls = Vout``  ⇒  is ramps down

        Phase 3 (IDLE, ``carrier ≥ D + D2``, DCM only):
            both windings see no voltage; currents stay at 0.

        ``inductor.L_H`` returns the *primary* inductance at the
        current operating point. The secondary's inductance is
        ``Ls = Lp / n²``. The same NonlinearInductor object is
        used for both windings — the saturation curve is shared
        because they share the core.
        """
        i_p = float(x[0])
        # ``i_s`` (secondary current state) is bound by the integrator
        # via ``x[1]`` but the derivatives below are written purely
        # in terms of ``v_Ls / Ls`` — the secondary current evolves
        # without needing its current value, so we don't unpack it.
        # Keeping the state-vector layout 2-D here so the ODE
        # solver allocates the right shape; the secondary current
        # is observable via the integrator's own history.

        # Carrier in [0, 1) at f_sw.
        carrier = (t * self._f_sw_Hz) % 1.0

        # Demag duty — varies with the operating point in DCM.
        # Use a static estimate (the design-time value) so the ODE
        # doesn't re-derive it every step. CCM has D + D2 = 1.
        if self._mode == "ccm":
            D2 = 1.0 - self._duty
        else:
            # DCM: D2 = D · Vin / (n · Vout). Using design-time Vin.
            if self._n > 0 and self._V_out > 0:
                D2 = self._duty * self._V_in_min / (self._n * self._V_out)
            else:
                D2 = 0.0

        Lp = inductor.L_H(i_p)
        if Lp <= 0.0:
            return np.array([0.0, 0.0])
        Ls = Lp / max(self._n * self._n, 1e-9)

        if carrier < self._duty:
            # ON phase
            v_Lp = self._V_in
            v_Ls = -self._V_out  # diode reverse-biased; is held at 0
            dip = v_Lp / Lp
            dis = 0.0  # forced; the diode blocks reverse current
        elif carrier < self._duty + D2:
            # DEMAG phase
            v_Lp = -self._n * self._V_out  # reflected
            v_Ls = self._V_out
            dip = v_Lp / Lp
            dis = v_Ls / Ls
        else:
            # IDLE (DCM only)
            dip = 0.0
            dis = 0.0

        return np.array([dip, dis])
