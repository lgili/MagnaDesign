"""DTOs for the cascade optimizer pipeline.

The cascade evaluates each candidate through up to four tiers
(feasibility, analytical, transient simulation, FEA) and stores
per-tier metrics in a run-scoped SQLite database. The DTOs in this
module are the in-memory representation that flows between tiers
and the persistence layer.

Phase A defines the Tier 0–1 shapes only. Tier 2/3/4 result types
land with their respective phases under the same naming pattern.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from pfc_inductor.models.result import DesignResult


class Candidate(BaseModel):
    """A single (core, material, wire) point in the search space.

    `N` and `gap_mm` are optional. When `None`, the steady-state
    solver inside the engine picks them: today's engine solves N
    from the topology's L_required and uses the core's intrinsic
    `lgap_mm`. Future phases may sweep over explicit N / gap pairs.
    """

    core_id: str
    material_id: str
    wire_id: str
    N: Optional[int] = None
    gap_mm: Optional[float] = None

    def key(self) -> str:
        """Stable identifier for the candidate within a run.

        Used as the primary lookup when the orchestrator needs to
        de-duplicate or resume — two Candidates with the same key
        describe the same evaluation.
        """
        n = "_" if self.N is None else str(self.N)
        g = "_" if self.gap_mm is None else f"{self.gap_mm:.4f}"
        return f"{self.core_id}|{self.material_id}|{self.wire_id}|{n}|{g}"


class FeasibilityEnvelope(BaseModel):
    """Tier 0 verdict for a candidate.

    `reasons` is empty on a `feasible=True` envelope; otherwise it
    holds one or more rejection codes (e.g. ``"too_small_L"``,
    ``"window_overflow"``, ``"saturates"``) suitable for both UI
    rendering and the run-store `notes` column.
    """

    feasible: bool
    reasons: list[str] = Field(default_factory=list)


class Tier0Result(BaseModel):
    """Outcome of the Tier 0 feasibility filter for one candidate."""

    candidate: Candidate
    envelope: FeasibilityEnvelope


class Tier1Result(BaseModel):
    """Outcome of the Tier 1 analytical evaluation for one candidate.

    `design` is the full `DesignResult` from the engine, kept so the
    UI can hydrate the candidate into the standard design view
    without recomputing. The orchestrator extracts the columns it
    persists from this object.
    """

    candidate: Candidate
    design: DesignResult

    @property
    def feasible(self) -> bool:
        return self.design.is_feasible()

    @property
    def total_loss_W(self) -> float:
        return self.design.losses.P_total_W

    @property
    def temp_C(self) -> float:
        return self.design.T_winding_C

    @property
    def n_warnings(self) -> int:
        return len(self.design.warnings)


class Tier3Result(BaseModel):
    """Outcome of the Tier 3 magnetostatic FEA validation for one candidate.

    Fields mirror :class:`pfc_inductor.fea.models.FEAValidation` plus a
    `disagrees_with_tier1` flag that the orchestrator uses to surface
    rows where the FEA number differs from the analytical engine by
    more than the design.md threshold (default 15 %).

    Phase C ships boost-CCM toroid + EE/ETD/PQ via FEMMT; topologies
    or shapes the FEA backend cannot handle yield ``None`` from
    `evaluate_candidate` (no Tier3Result is written), and the
    orchestrator records the reason in `notes`.
    """

    candidate: Candidate

    L_FEA_uH: float
    B_pk_FEA_T: float
    L_relative_error_pct: float
    B_relative_error_pct: float

    solve_time_s: float
    backend: str
    confidence: str
    disagrees_with_tier1: bool


class Tier2Result(BaseModel):
    """Outcome of the Tier 2 transient ODE simulation for one candidate.

    Carries the post-processed metrics — the full waveform stays in
    the integrator and is not persisted to keep the run store narrow.
    Phase B Step 1 covers boost-CCM only; topologies without a
    state-space implementation never produce a Tier2Result.

    Cross-tier comparison fields (`L_relative_error_pct`,
    `B_relative_error_pct`) are populated when the orchestrator has a
    Tier-1 result for the same candidate to compare against.
    """

    candidate: Candidate

    # Steady-state metrics from the simulated last cycle.
    i_pk_A: float
    i_rms_A: float
    B_pk_T: float
    L_min_uH: float        # smallest L over the cycle (at peak bias)
    L_avg_uH: float        # cycle-averaged L

    # Saturation flag — true if any sample of the simulated cycle
    # exceeded the configured Bsat margin.
    saturation_t2: bool

    # Convergence + cost metadata.
    converged: bool
    n_line_cycles_simulated: int
    sim_wall_time_s: float

    # Optional cross-tier deltas (None when no Tier-1 reference).
    L_relative_error_pct: Optional[float] = None
    B_relative_error_pct: Optional[float] = None
    i_pk_relative_error_pct: Optional[float] = None
