"""ConverterModel protocol — topology-agnostic adapter for the cascade.

Each topology implements this Protocol so the cascade orchestrator
never imports topology-specific code. The Phase-A subset covers
Tier 0 (feasibility envelope) and Tier 1 (analytical steady state).

Higher tiers extend the Protocol when they ship:

- Phase B (Tier 2 transient ODE) adds `state_derivatives`,
  `initial_state`, optional `event_functions`, `loss_envelope`.
- Phase C/D (Tier 3/4 FEA) adds `fea_geometry_hints`.

A topology that has not yet implemented a higher-tier method may
either omit the method entirely (the orchestrator detects the
missing attribute via `hasattr`) or implement it to raise
`NotImplementedError`. The cascade surfaces a clear "topology does
not support tier N yet" message to the user in either case.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.models.cascade import FeasibilityEnvelope

if TYPE_CHECKING:
    from pfc_inductor.simulate.nonlinear_inductor import NonlinearInductor


@runtime_checkable
class ConverterModel(Protocol):
    """Topology-aware adapter that the cascade pipeline drives."""

    name: str
    spec: Spec

    # ─── Tier 0 ────────────────────────────────────────────────
    def feasibility_envelope(
        self,
        core: Core,
        material: Material,
        wire: Wire,
    ) -> FeasibilityEnvelope:
        """Cheap geometric / saturation envelope.

        Implementations must return in well under a millisecond and
        must never raise: any rejection becomes a reason code in
        the returned `FeasibilityEnvelope`.
        """
        ...

    # ─── Tier 1 ────────────────────────────────────────────────
    def steady_state(
        self,
        core: Core,
        material: Material,
        wire: Wire,
    ) -> DesignResult:
        """Closed-form steady-state operating point.

        Delegates to the existing analytical engine. May raise
        `DesignError` on hard failures (e.g. invalid material data);
        the orchestrator catches and records the error as a notes
        entry on the candidate.
        """
        ...


@runtime_checkable
class Tier2ConverterModel(ConverterModel, Protocol):
    """ConverterModel that also drives the transient simulator (Tier 2).

    Topologies that implement this Protocol expose the right-hand
    side of the inductor's state-space ODE plus an initial state.
    The cascade orchestrator runtime-checks against this protocol
    via ``isinstance`` to decide whether to schedule Tier 2.
    """

    def state_derivatives(
        self,
        t: float,
        x: np.ndarray,
        inductor: NonlinearInductor,
    ) -> np.ndarray:
        """Compute `dx/dt` at time `t` and state `x`.

        The state vector layout is topology-defined; by convention
        `x[0]` is the inductor current so the integrator can sample
        it without knowing the rest of the state. Implementations
        must be pure (no I/O, no globals) so they pickle cleanly
        through the worker pool.
        """
        ...

    def initial_state(self) -> np.ndarray:
        """Return the state vector at `t=0`.

        The cascade integrates from rest by default (zero current).
        Topologies that need to start from a non-trivial DC bias
        (e.g. line reactor with a pre-charged DC link) override
        this hook.
        """
        ...
