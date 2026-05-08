"""Circuit-simulator export — emit a saturable-inductor model
for downstream simulators (LTspice, PSIM, OpenModelica).

The app's nominal output is an L value plus a calibrated
rolloff curve. Re-typing those numbers into a circuit
simulator drops the rolloff fidelity on the floor — the user's
LTspice run sees a constant-L inductor where production sees
a saturable one. This module closes the loop by emitting a
ready-to-import sub-circuit / fragment / package per simulator
that carries the same L(I) curve the engine used.

Public API
----------

- :func:`L_vs_I_table` — vendor-agnostic ``[(I, L), …]``
  table sweeping current 0..I_max and applying the rolloff.
- :func:`flux_vs_current` — ``[(I, λ_Wb), …]`` (some
  simulators want flux instead of inductance).
- :func:`to_ltspice_subcircuit` — LTspice ``.subckt`` with a
  ``B``-source for the nonlinear flux + a series resistor.
- :func:`to_psim_fragment` — PSIM "Saturable Inductor"
  flux-current pair list.
- :func:`to_modelica` — Modelica package using
  ``Modelica.Magnetic.FluxTubes`` primitives.

Each emitter returns a ``str`` so the caller (CLI / UI / direct
script) decides where to write it.
"""

from __future__ import annotations

from pfc_inductor.export.curves import (
    L_vs_I_table,
    flux_vs_current,
)
from pfc_inductor.export.ltspice import to_ltspice_subcircuit
from pfc_inductor.export.modelica import to_modelica
from pfc_inductor.export.psim import to_psim_fragment

__all__ = [
    "L_vs_I_table",
    "flux_vs_current",
    "to_ltspice_subcircuit",
    "to_modelica",
    "to_psim_fragment",
]
