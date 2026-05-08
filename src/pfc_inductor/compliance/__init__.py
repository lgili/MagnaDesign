"""Compliance dispatcher — connects the engine to regulatory checks.

The :mod:`pfc_inductor.standards` package owns the per-standard
formulas (Class D limit tables, conducted-EMI envelopes, hi-pot
thresholds). This package wires those checks into the design
pipeline:

- For a given ``Spec / DesignResult``, decide which standards
  apply (line-frequency / topology / region).
- Extract the inputs each standard needs (harmonic amplitudes,
  fsw spectrum, hot-spot temperature).
- Aggregate the per-standard results into a single
  :class:`ComplianceBundle` the UI / CLI / PDF writer can render
  uniformly.

Today the bundle covers IEC 61000-3-2 Class D for the line
reactor and passive choke topologies; EN 55032 conducted-EMI is
stubbed and lights up on the next phase. Any standard that lands
later (UL 1411, IEC 60335-1) plugs into the dispatcher without
re-touching every consumer.

Public API
----------

- :class:`ComplianceBundle` — the aggregated output.
- :class:`StandardResult` — one report per applicable standard.
- :func:`evaluate` — driver function (engine → bundle).
- :func:`applicable_standards` — predicate used by the UI to
  light up which checks the current spec triggers.
"""
from __future__ import annotations

from pfc_inductor.compliance.dispatcher import (
    ComplianceBundle,
    ConclusionLabel,
    StandardResult,
    applicable_standards,
    evaluate,
)

__all__ = [
    "ComplianceBundle",
    "ConclusionLabel",
    "StandardResult",
    "applicable_standards",
    "evaluate",
]
