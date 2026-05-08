"""Topology model registry — maps `Topology` literal → `ConverterModel`.

The cascade orchestrator and the UI topology picker both go through
this registry rather than hard-coding the three Phase-A topologies.
Adding a new topology means adding one entry here.
"""

from __future__ import annotations

from typing import Callable

from pfc_inductor.models import Spec
from pfc_inductor.models.spec import Topology
from pfc_inductor.topology.boost_ccm_model import BoostCCMModel
from pfc_inductor.topology.buck_ccm_model import BuckCCMModel
from pfc_inductor.topology.flyback_model import FlybackModel
from pfc_inductor.topology.interleaved_boost_pfc_model import (
    InterleavedBoostPFCModel,
)
from pfc_inductor.topology.line_reactor_model import LineReactorModel
from pfc_inductor.topology.passive_choke_model import PassiveChokeModel
from pfc_inductor.topology.protocol import ConverterModel

# A factory is a callable that turns a Spec into a `ConverterModel`.
# Using `Callable` rather than `type[ConverterModel]` lets us register
# both classes and plain functions, and keeps the type checker happy
# because the Protocol doesn't define `__init__`.
ModelFactory = Callable[[Spec], ConverterModel]

TOPOLOGY_MODELS: dict[Topology, ModelFactory] = {
    "boost_ccm": BoostCCMModel,
    "passive_choke": PassiveChokeModel,
    "line_reactor": LineReactorModel,
    "buck_ccm": BuckCCMModel,
    "flyback": FlybackModel,
    "interleaved_boost_pfc": InterleavedBoostPFCModel,
}


def registered_topologies() -> tuple[Topology, ...]:
    """All topology identifiers the system can drive."""
    return tuple(TOPOLOGY_MODELS.keys())


def model_for(spec: Spec) -> ConverterModel:
    """Instantiate the `ConverterModel` matching `spec.topology`."""
    factory = TOPOLOGY_MODELS.get(spec.topology)
    if factory is None:
        raise ValueError(
            f"No topology model registered for spec.topology={spec.topology!r}. "
            f"Registered: {registered_topologies()}",
        )
    return factory(spec)
