"""Per-topology material-type policy.

Different inductor topologies operate at different frequency regimes,
so the magnetic material families that make engineering sense for one
are usually a poor fit for another. Running an optimizer (or even a
candidate browser) over the full 470-material catalogue when only a
handful of types apply to the chosen topology wastes wall time and
floods the result list with rows that any seasoned engineer would
discard at a glance.

The policy below maps each topology to the set of `Material.type`
values that are appropriate for it. It is deliberately conservative:
edge cases (e.g. a 400 Hz aerospace inductor that wants silicon-steel
in a switching application) are easy to add later by widening the
relevant set, and a future "show all" override can always escape the
filter when the engineer asks for it.

Engineering rationale
=====================

* **boost_ccm** — switching at 20–200 kHz. Powder cores (Magnetics
  Hi-Flux / MPP / Kool Mu, Micrometals, etc.), ferrites, and
  high-permeability soft-magnetics (nanocrystalline / amorphous) all
  carry kHz-rate flux at low core loss. Silicon-steel laminations
  are not used here — eddy currents in the lamination plane explode
  at switching frequency and the loss budget falls apart.

* **passive_choke** / **line_reactor** — line frequency 50/60 Hz.
  Silicon-steel laminations are the workhorse: cheap, high Bsat,
  low loss at 60 Hz. Nanocrystalline / amorphous strip works too
  (lower loss, higher cost). Ferrites are technically usable but
  almost never economic at line frequency. Powder cores have low
  μ (typ. 26–300) which would force impractical turn counts to
  reach the inductance line reactors need at 60 Hz, so they are
  excluded by default.
"""

from __future__ import annotations

from typing import Iterable

from pfc_inductor.models import Material
from pfc_inductor.models.material import MaterialType
from pfc_inductor.models.spec import Topology

# ----------------------------------------------------------------
# Policy table.
#
# Keys are the values of ``Topology`` from ``models.spec``; each
# value is the set of accepted ``Material.type`` values. Adding a
# new topology means listing it here — the resolver falls back to
# *no filter* when a topology is missing, so the orchestrator never
# strands the user with an empty material list because the policy
# table was forgotten.
# ----------------------------------------------------------------
_POLICY: dict[Topology, frozenset[MaterialType]] = {
    "boost_ccm": frozenset({"powder", "ferrite", "nanocrystalline", "amorphous"}),
    "passive_choke": frozenset({"silicon-steel", "amorphous", "nanocrystalline"}),
    "line_reactor": frozenset({"silicon-steel", "amorphous", "nanocrystalline"}),
    # Interleaved boost-PFC sees per-phase boost-CCM operation, so
    # the same material families apply: powder cores dominate the
    # 200 W – 3 kW per-phase band, with ferrite picking up at the
    # higher per-phase power for low-fsw designs.
    "interleaved_boost_pfc": frozenset({"powder", "ferrite", "nanocrystalline", "amorphous"}),
}


def material_types_for_topology(topology: Topology) -> frozenset[MaterialType]:
    """Return the ``Material.type`` values appropriate for ``topology``.

    Returns an empty frozenset when the topology is unknown — callers
    can use that as a sentinel to skip filtering (see
    :func:`materials_for_topology`).
    """
    return _POLICY.get(topology, frozenset())


def materials_for_topology(
    materials: Iterable[Material],
    topology: Topology,
) -> list[Material]:
    """Filter ``materials`` down to those appropriate for ``topology``.

    When the topology is unknown (i.e. not present in the policy
    table) the input list is returned unchanged. This is intentional:
    a missing policy entry is a programming oversight, not a user
    error, and silently dropping every material would surface the
    bug in a much more confusing place (an empty cascade run with
    "no candidates" messaging).
    """
    accepted = material_types_for_topology(topology)
    if not accepted:
        return list(materials)
    return [m for m in materials if m.type in accepted]
