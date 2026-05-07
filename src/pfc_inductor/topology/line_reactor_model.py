"""Line reactor (1Ø / 3Ø, diode-bridge front end) — Phase-A adapter."""
from __future__ import annotations

from pfc_inductor.design import design
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.models.cascade import FeasibilityEnvelope
from pfc_inductor.optimize.feasibility import core_quick_check


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
