"""Tier 0 — cheap geometric / saturation envelope filter.

Each candidate flows through a single function, `evaluate_candidate`,
that returns a `Tier0Result`. The filter is intentionally loose
(false positives are acceptable; false negatives are not) so designs
that the analytical engine could solve are never dropped.

The arithmetic is delegated to `optimize.feasibility.core_quick_check`,
which has been the project's O(1) viability heuristic since v2 and
already understands all three Phase-A topologies. Wrapping it in a
`Tier0Result` gives the orchestrator a uniform per-tier output type.
"""

from __future__ import annotations

from typing import Iterable, Iterator

from pfc_inductor.models import (
    Candidate,
    Core,
    Material,
    Tier0Result,
    Wire,
)
from pfc_inductor.models.cascade import FeasibilityEnvelope
from pfc_inductor.topology.protocol import ConverterModel


def evaluate_candidate(
    model: ConverterModel,
    candidate: Candidate,
    core: Core,
    material: Material,
    wire: Wire,
) -> Tier0Result:
    """Run the Tier-0 envelope check on a single candidate."""
    envelope = model.feasibility_envelope(core, material, wire)
    return Tier0Result(candidate=candidate, envelope=envelope)


def filter_candidates(
    model: ConverterModel,
    candidates: Iterable[Candidate],
    materials: dict[str, Material],
    cores: dict[str, Core],
    wires: dict[str, Wire],
) -> Iterator[Tier0Result]:
    """Yield a `Tier0Result` for every candidate, in input order.

    The orchestrator decides what to do with infeasible rows; this
    function never silently drops anything. Callers that want only
    the feasible subset can wrap the iterator with
    ``(r for r in filter_candidates(...) if r.envelope.feasible)``.

    The `materials` / `cores` / `wires` arguments are id-keyed lookup
    dicts, built once per run from the (typically static) database.
    Looking up by id avoids allocating strings on the hot path.
    """
    for candidate in candidates:
        material = materials.get(candidate.material_id)
        core = cores.get(candidate.core_id)
        wire = wires.get(candidate.wire_id)
        if material is None or core is None or wire is None:
            yield Tier0Result(
                candidate=candidate,
                envelope=FeasibilityEnvelope(
                    feasible=False,
                    reasons=["missing_db_entry"],
                ),
            )
            continue
        yield evaluate_candidate(model, candidate, core, material, wire)
