"""Candidate generators for the cascade optimizer.

A generator yields `Candidate(core, material, wire, N=None, gap_mm=None)`
tuples lazily — no full materialisation in memory. The cascade
orchestrator pipes the stream through Tier 0 and downstream tiers.

Phase A ships a single Cartesian generator over a fixed material/
core/wire selection. Future phases may add stratified or
random-restart generators for very large search spaces.
"""
from __future__ import annotations

from typing import Iterable, Iterator

from pfc_inductor.models import Candidate, Core, Material, Wire


def cartesian(
    materials: Iterable[Material],
    cores: Iterable[Core],
    wires: Iterable[Wire],
    *,
    only_compatible_cores: bool = True,
    only_round_wires: bool = True,
) -> Iterator[Candidate]:
    """Yield `Candidate(core, material, wire)` for every combination.

    Constraints (mirroring `optimize/sweep.py::sweep` defaults):

    - When `only_compatible_cores` is True, a core is paired only
      with its `default_material_id` material — pairing every core
      with every material multiplies the search space ~50× while
      most pairings are physically nonsensical (a Kool Mu core with
      a ferrite material does not match the AL or rolloff curve).
    - When `only_round_wires` is True, Litz wires are excluded; the
      Litz optimizer is the right tool for those, not the cascade
      sweep.

    The order is `(material, core, wire)` so workers see batches of
    same-material candidates back-to-back — friendlier to caches in
    the analytical evaluator.
    """
    materials_list = list(materials)
    cores_list = list(cores)
    wires_list = [w for w in wires if not only_round_wires or w.type == "round"]

    for material in materials_list:
        if only_compatible_cores:
            candidate_cores = [
                c for c in cores_list if c.default_material_id == material.id
            ]
        else:
            candidate_cores = cores_list
        for core in candidate_cores:
            for wire in wires_list:
                yield Candidate(
                    core_id=core.id,
                    material_id=material.id,
                    wire_id=wire.id,
                )


def cartesian_count(
    materials: Iterable[Material],
    cores: Iterable[Core],
    wires: Iterable[Wire],
    *,
    only_compatible_cores: bool = True,
    only_round_wires: bool = True,
) -> int:
    """Count what `cartesian()` would yield — for progress bars.

    Identical filters to `cartesian()`. O(M·C·W) once, but the dataset
    is small (~50 mat × 1000 cores × ~13 round wires) so the count
    runs in a few milliseconds.
    """
    materials_list = list(materials)
    cores_list = list(cores)
    wires_list = [w for w in wires if not only_round_wires or w.type == "round"]
    n_wires = len(wires_list)

    total = 0
    for material in materials_list:
        if only_compatible_cores:
            n_cores = sum(
                1 for c in cores_list if c.default_material_id == material.id
            )
        else:
            n_cores = len(cores_list)
        total += n_cores * n_wires
    return total
