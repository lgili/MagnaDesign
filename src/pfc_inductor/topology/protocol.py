"""ConverterModel protocol — topology-agnostic adapter for the cascade.

Each topology implements this Protocol so the cascade orchestrator
never imports topology-specific code. The Phase-A subset covers
Tier 0 (feasibility envelope) and Tier 1 (analytical steady state).

Higher tiers extend the Protocol when they ship:

- Phase B (Tier 2 transient ODE) adds `state_derivatives`,
  `event_functions`, `loss_envelope`.
- Phase C/D (Tier 3/4 FEA) adds `fea_geometry_hints`.

A topology that has not yet implemented a higher-tier method may
either omit the method entirely (the orchestrator detects the
missing attribute via `hasattr`) or implement it to raise
`NotImplementedError`. The cascade surface a clear "topology does
not support tier N yet" message to the user in either case.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.models.cascade import FeasibilityEnvelope


@runtime_checkable
class ConverterModel(Protocol):
    """Topology-aware adapter that the cascade pipeline drives."""

    name: str
    spec: Spec

    # ─── Tier 0 ────────────────────────────────────────────────
    def feasibility_envelope(
        self, core: Core, material: Material, wire: Wire,
    ) -> FeasibilityEnvelope:
        """Cheap geometric / saturation envelope.

        Implementations must return in well under a millisecond and
        must never raise: any rejection becomes a reason code in
        the returned `FeasibilityEnvelope`.
        """
        ...

    # ─── Tier 1 ────────────────────────────────────────────────
    def steady_state(
        self, core: Core, material: Material, wire: Wire,
    ) -> DesignResult:
        """Closed-form steady-state operating point.

        Delegates to the existing analytical engine. May raise
        `DesignError` on hard failures (e.g. invalid material data);
        the orchestrator catches and records the error as a notes
        entry on the candidate.
        """
        ...
