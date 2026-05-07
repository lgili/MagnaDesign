"""Boost-CCM converter model — Phase-A adapter.

Wraps `boost_ccm.py` (math) and `design.engine.design` (analytical
solver) behind the `ConverterModel` Protocol so the cascade
orchestrator can drive every topology through a single interface.
"""
from __future__ import annotations

from pfc_inductor.design import design
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.models.cascade import FeasibilityEnvelope
from pfc_inductor.optimize.feasibility import core_quick_check


class BoostCCMModel:
    """`ConverterModel` adapter for active boost PFC in CCM."""

    name: str = "boost_ccm"

    def __init__(self, spec: Spec) -> None:
        if spec.topology != "boost_ccm":
            raise ValueError(
                f"BoostCCMModel requires spec.topology == 'boost_ccm', "
                f"got {spec.topology!r}",
            )
        self.spec = spec

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
