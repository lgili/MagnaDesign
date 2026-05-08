"""Cascade optimizer — multi-tier brute-force inductor design search.

Phase A ships:

- `RunStore`            — SQLite-backed persistence (this module's `store`).
- `Tier 0 / Tier 1`     — feasibility filter and analytical evaluator.
- `CascadeOrchestrator` — process-pool runner with cancellation and resume.

Phase B/C/D add Tier 2 (transient ODE), Tier 3 (batched FEA) and
Tier 4 (transient FEA). The public API surface in this package is
intentionally narrow — most callers go through the orchestrator.
"""

from pfc_inductor.optimize.cascade.orchestrator import (
    CascadeConfig,
    CascadeOrchestrator,
    ProgressCallback,
    TierProgress,
)
from pfc_inductor.optimize.cascade.store import (
    CandidateRow,
    RunRecord,
    RunStatus,
    RunStore,
)

__all__ = [
    "CandidateRow",
    "CascadeConfig",
    "CascadeOrchestrator",
    "ProgressCallback",
    "RunRecord",
    "RunStatus",
    "RunStore",
    "TierProgress",
]
