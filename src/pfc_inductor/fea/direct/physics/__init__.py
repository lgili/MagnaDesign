"""GetDP ``.pro`` file generators — one module per problem class.

A ``.pro`` file is the GetDP equivalent of a Sentaurus / COMSOL
study setup: it declares (in order) the function space, the
constraints (BCs + sources), the formulation (the weak form),
the resolution (what to solve and how), and the postoperation
(what quantities to extract).

The module layout follows that order:

- ``magnetostatic`` — DC magnetic problem, plus L extraction via
  energy method. Phase 1 of the FEMMT migration.
- ``ac_harmonic`` (TODO) — frequency-domain AC for skin / proximity
  losses. Reuses the magnetostatic geometry + groups; just swaps
  the formulation block.
- ``thermal`` (TODO) — steady-state heat with loss densities from
  the AC pass as source terms. One-way coupling for now.
"""

from __future__ import annotations

__all__ = [
    "MagnetostaticAxiTemplate",
    "MagnetostaticTemplate",
]


def __getattr__(name: str):
    if name == "MagnetostaticTemplate":
        from pfc_inductor.fea.direct.physics.magnetostatic import (
            MagnetostaticTemplate,
        )

        return MagnetostaticTemplate
    if name == "MagnetostaticAxiTemplate":
        from pfc_inductor.fea.direct.physics.magnetostatic_axi import (
            MagnetostaticAxiTemplate,
        )

        return MagnetostaticAxiTemplate
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
