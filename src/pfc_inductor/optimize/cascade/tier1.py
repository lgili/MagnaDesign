"""Tier 1 — analytical steady-state evaluation.

Wraps `design.engine.design` (the existing solver) behind the cascade
contract. The Tier 1 worker is intentionally thin: it delegates to
the topology model's `steady_state` and packages the result with
the cost estimate, ready for the run store.

`evaluate_design_safe` is the function that workers call in the
process pool. It catches every exception so a single bad candidate
never aborts a sweep — failures are recorded as a `notes` entry on
the candidate's row and the orchestrator moves on.
"""
from __future__ import annotations

from typing import Optional

from pfc_inductor.errors import DesignError
from pfc_inductor.models import (
    Candidate,
    Core,
    DesignResult,
    Material,
    Tier1Result,
    Wire,
)
from pfc_inductor.physics import estimate_cost
from pfc_inductor.topology.protocol import ConverterModel

# `design.engine._solve_N` caps at this turn count; designs that hit
# the cap are physically unbuildable and we drop them from the
# Tier 1 stream entirely (matching the existing `optimize/sweep.py`
# behaviour). Kept in sync with the engine.
_N_MAX = 500


def evaluate_candidate(
    model: ConverterModel,
    candidate: Candidate,
    core: Core,
    material: Material,
    wire: Wire,
) -> Optional[Tier1Result]:
    """Run the analytical engine for a single candidate.

    Returns `None` if the engine could not solve the design within
    its turn-count cap (i.e. `N_turns >= _N_MAX`). Such designs have
    catastrophically infeasible Ku/B/T and reporting them as
    "infeasible candidates" misleads the user — they are unsolved,
    not bad.
    """
    result = model.steady_state(core, material, wire)
    if result.N_turns >= _N_MAX:
        return None
    return Tier1Result(candidate=candidate, design=result)


def evaluate_candidate_safe(
    model: ConverterModel,
    candidate: Candidate,
    core: Core,
    material: Material,
    wire: Wire,
) -> tuple[Optional[Tier1Result], Optional[str]]:
    """Like `evaluate_candidate` but never raises.

    Returns `(result, error)`. On success, `error is None`. On
    failure, `result is None` and `error` carries a short
    description suitable for the run-store `notes` JSON.
    """
    try:
        result = evaluate_candidate(model, candidate, core, material, wire)
        return result, None
    except DesignError as exc:
        return None, f"design_error: {exc.user_message()}"
    except Exception as exc:
        return None, f"engine_error: {type(exc).__name__}: {exc}"


def cost_USD(
    result: DesignResult,
    core: Core,
    material: Material,
    wire: Wire,
) -> Optional[float]:
    """Convenience: extract the numeric BOM cost from `estimate_cost`.

    Returns `None` when the database lacks pricing for the chosen
    parts — matches the contract used by the existing sweep.
    """
    breakdown = estimate_cost(core, wire, material, result.N_turns)
    return breakdown.total_cost if breakdown is not None else None
