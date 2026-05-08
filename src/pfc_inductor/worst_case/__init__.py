"""Worst-case + production-tolerance engine.

Wraps :func:`pfc_inductor.design.design` to evaluate a design across
a Design-of-Experiments grid (line × ambient × component-tolerance
× load) and report the worst-case violator per metric plus an
estimated yield via Monte-Carlo sampling.

Why it lives outside the engine
-------------------------------

``design()`` solves a single nominal operating point — that's the
right scope for it; multi-corner aggregation is a *consumer*-level
concern. Keeping the corner DOE here means:

- Every consumer (GUI worst-case tab, cascade Tier-1 envelope
  check, CLI ``magnadesign worst-case`` subcommand, datasheet's
  "production envelope" page) can opt in or out without paying
  for the corner sweep when it isn't needed.
- The nominal-design API stays stable — a `.pfc` file written by
  v0.5 still loads in v0.7 even if the tolerance schema evolves.

Public API
----------

- :class:`Tolerance`, :class:`ToleranceSet` — the input grammar.
- :func:`evaluate_corners` — deterministic DOE.
- :func:`simulate_yield` — Monte-Carlo, seedable for repro.
- :class:`WorstCaseSummary` — the aggregated output.
"""
from __future__ import annotations

from pfc_inductor.worst_case.engine import (
    CornerResult,
    WorstCaseConfig,
    WorstCaseSummary,
    evaluate_corners,
    sensitivity_table,
)
from pfc_inductor.worst_case.monte_carlo import (
    YieldReport,
    simulate_yield,
)
from pfc_inductor.worst_case.tolerances import (
    DEFAULT_TOLERANCES,
    Tolerance,
    ToleranceDistribution,
    ToleranceSet,
    load_tolerance_set,
)

__all__ = [
    "CornerResult",
    "DEFAULT_TOLERANCES",
    "Tolerance",
    "ToleranceDistribution",
    "ToleranceSet",
    "WorstCaseConfig",
    "WorstCaseSummary",
    "YieldReport",
    "evaluate_corners",
    "load_tolerance_set",
    "sensitivity_table",
    "simulate_yield",
]
