"""Interleaved boost-PFC ConverterModel adapter.

Wraps the per-phase delegation so the cascade orchestrator,
feasibility prefilter, and Tier-2 transient simulator drive
through a single object. The ``ConverterModel`` Protocol is
fulfilled by routing every method through ``BoostCCMModel`` after
swapping the spec for ``per_phase_spec(spec)`` — the same
shortcut the analytic engine takes.

Each method runs against *one* of the N parallel phases. The
report layer multiplies the BOM and the aggregate-power KPIs by
``spec.n_interleave`` after the engine returns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.models.cascade import FeasibilityEnvelope
from pfc_inductor.topology.boost_ccm_model import BoostCCMModel
from pfc_inductor.topology.interleaved_boost_pfc import per_phase_spec

if TYPE_CHECKING:
    from pfc_inductor.simulate.nonlinear_inductor import NonlinearInductor


class InterleavedBoostPFCModel:
    """``ConverterModel`` adapter for N-phase interleaved boost PFC.

    Internally a thin wrapper around ``BoostCCMModel`` evaluated
    on the per-phase spec. The adapter owns the original spec
    (so callers see ``self.spec.topology == "interleaved_boost_pfc"``)
    but delegates every Protocol method to a private boost model
    built on the per-phase spec.
    """

    name: str = "interleaved_boost_pfc"

    def __init__(self, spec: Spec) -> None:
        if spec.topology != "interleaved_boost_pfc":
            raise ValueError(
                "InterleavedBoostPFCModel requires "
                "spec.topology == 'interleaved_boost_pfc', got "
                f"{spec.topology!r}",
            )
        self.spec = spec
        self._per_phase_spec = per_phase_spec(spec)
        # Reuse the existing boost adapter — every method behaves
        # identically once the spec is swapped, including the
        # transient ODE.
        self._boost = BoostCCMModel(self._per_phase_spec)

    # ─── Phase-A: feasibility + steady-state ────────────────────
    def feasibility_envelope(
        self,
        core: Core,
        material: Material,
        wire: Wire,
    ) -> FeasibilityEnvelope:
        # Per-phase feasibility: each of the N inductors carries
        # 1/N of the total current, so the per-phase boost check
        # *is* the right answer. Aggregate-power infeasibility
        # (e.g. core too small at total Pout) doesn't apply since
        # we're sizing one of N units.
        return self._boost.feasibility_envelope(core, material, wire)

    def steady_state(
        self,
        core: Core,
        material: Material,
        wire: Wire,
    ) -> DesignResult:
        # Route through the engine's interleaved branch directly
        # — it both runs the boost-CCM design and stamps the
        # ``× N units`` badge on ``result.notes`` in one call.
        from pfc_inductor.design import design as _design

        return _design(self.spec, core, wire, material)

    # ─── Phase-B: Tier 2 state-space ────────────────────────────
    # The interleaved transient is N copies of the boost ODE with
    # phase-shifted PWM carriers. For Tier-2 purposes (per-phase
    # inductor sizing) we simulate *one* phase — the carrier
    # offset doesn't change the per-phase L·di/dt loading, only
    # the aggregate input current. Aggregate views live in the
    # report's cancellation chart, not in the simulator.
    def initial_state(self) -> np.ndarray:
        return self._boost.initial_state()

    def state_derivatives(
        self,
        t: float,
        x: np.ndarray,
        inductor: NonlinearInductor,
    ) -> np.ndarray:
        return self._boost.state_derivatives(t, x, inductor)
