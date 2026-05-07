"""Transient ODE simulation for cascade Tier 2.

Phase B ships:

- `NonlinearInductor` — `L(i, T)` time-varying inductance computed
  from the same rolloff curves the analytical engine uses, so Tier
  1 and Tier 2 stay aligned by construction.
- `simulate_to_steady_state` — generic ODE driver that integrates
  any `ConverterModel` whose `state_derivatives` is implemented,
  returns a `Waveform` ready for Tier-2 post-processing.
- `Waveform` — sampled trajectory plus convenience metrics
  (`i_pk_A`, `B_pk_T`, `i_rms_A`).

The package is intentionally topology-agnostic. Each topology owns
its own state-space (the differential equations + switching events)
in its `*_model.py` adapter.
"""
from pfc_inductor.simulate.integrator import (
    SimulationConfig,
    simulate_to_steady_state,
    simulate_transient,
)
from pfc_inductor.simulate.nonlinear_inductor import NonlinearInductor
from pfc_inductor.simulate.waveform import Waveform

__all__ = [
    "NonlinearInductor",
    "SimulationConfig",
    "Waveform",
    "simulate_to_steady_state",
    "simulate_transient",
]
