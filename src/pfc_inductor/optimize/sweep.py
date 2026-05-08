"""Sweep optimizer for PFC inductor design.

Two modes:
- sweep_cores(spec, material, wires, cores) — fixed material, vary cores and wires.
- sweep_full(spec, materials, cores, wires) — vary everything (slower; intended
  for "find me the best design overall" runs).

Returns SweepResult objects sorted by user-chosen score (default: P_total).
Computes Pareto front across (volume, total loss) for visualization.

Performance
-----------

The per-candidate ``engine.design()`` call runs at
~17 000 cand/s on a single core thanks to the Numba kernel
stack (see ``docs/PERFORMANCE.md``). For typical UI sweeps
(500-2 500 candidates) a sequential pass finishes in 30-150 ms,
so the OptimizerDialog stays responsive without process-pool
parallelism overhead.

For very large sweeps (≥ 50 000 candidates) use the cascade
orchestrator instead — it already parallelises Tier 1 across a
process pool and persists results to SQLite for resume.

Threading was investigated and **does not help** here: even
though the Numba kernels are decorated with ``nogil=True``,
the surrounding ``engine.design()`` body is GIL-bound (Pydantic
validation, dict lookups, attribute access on Spec / Core /
Wire / Material), so a ``ThreadPoolExecutor`` over candidates
produces no measurable speedup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from pfc_inductor.data_loader import find_material
from pfc_inductor.design import design
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.physics import CostBreakdown, estimate_cost


@dataclass
class SweepResult:
    core: Core
    wire: Wire
    material: Material
    result: DesignResult
    _cost_cache: Optional[CostBreakdown] = None

    @property
    def volume_cm3(self) -> float:
        return self.core.Ve_mm3 / 1000.0

    @property
    def feasible(self) -> bool:
        return self.result.is_feasible()

    @property
    def P_total_W(self) -> float:
        return self.result.losses.P_total_W

    @property
    def T_winding_C(self) -> float:
        return self.result.T_winding_C

    @property
    def n_warnings(self) -> int:
        return len(self.result.warnings)

    @property
    def cost(self) -> Optional[CostBreakdown]:
        if self._cost_cache is None:
            self._cost_cache = estimate_cost(
                self.core,
                self.wire,
                self.material,
                self.result.N_turns,
            )
        return self._cost_cache

    @property
    def total_cost(self) -> Optional[float]:
        c = self.cost
        return c.total_cost if c is not None else None


def _safe_design(spec: Spec, core: Core, wire: Wire, material: Material) -> Optional[DesignResult]:
    try:
        return design(spec, core, wire, material)
    except Exception:
        return None


# ``_solve_N`` in ``design.engine`` caps at this many turns. When the
# engine returns N == _N_MAX it means it couldn't satisfy L_required
# even at the cap — the resulting design has Ku > 100 % and T > 200 °C
# and shouldn't even be presented as "infeasible" in the table; it's
# unsolved. We drop those rows entirely so they don't crowd the UI.
_N_MAX = 500


def _is_solvable(r: DesignResult) -> bool:
    """Drop designs where the engine hit ``N_max`` (couldn't reach L)."""
    return r.N_turns < _N_MAX


def sweep(
    spec: Spec,
    cores: Iterable[Core],
    wires: Iterable[Wire],
    materials: list[Material],
    *,
    material_id: Optional[str] = None,
    only_compatible_cores: bool = True,
    only_round_wires: bool = True,
    feasible_only: bool = False,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> list[SweepResult]:
    """Sweep across cores × wires (with optional fixed material).

    If `material_id` is given, only that material is considered.
    `only_compatible_cores=True` filters to cores whose default_material_id
    matches the candidate material.

    Sequential by design. The Numba kernel stack pushes
    ``engine.design()`` to ~17 000 cand/s on a single core, so a
    typical 2 500-candidate sweep finishes in 150 ms — fast
    enough that adding a process pool's 500 ms-per-worker spawn
    cost would be a net regression. Threads don't help either:
    ``engine.design()`` is GIL-bound outside the Numba kernels
    (Pydantic + dict lookups). For very large sweeps (≥ 50 000
    candidates) use the cascade orchestrator instead — it
    parallelises Tier 1 across a process pool by design.
    """
    cores_list = list(cores)
    wires_list = [w for w in wires if not only_round_wires or w.type == "round"]
    if material_id:
        mats = [find_material(materials, material_id)]
    else:
        mats = list(materials)

    results: list[SweepResult] = []
    total = sum(
        len([c for c in cores_list if not only_compatible_cores or c.default_material_id == m.id])
        for m in mats
    ) * len(wires_list)
    done = 0

    for material in mats:
        candidate_cores = [
            c
            for c in cores_list
            if not only_compatible_cores or c.default_material_id == material.id
        ]
        for core in candidate_cores:
            for wire in wires_list:
                r = _safe_design(spec, core, wire, material)
                done += 1
                if r is None:
                    continue
                # Drop unsolved designs (engine couldn't fit L
                # within N_max). They always look catastrophically
                # infeasible (B huge, Ku >> 100 %); reporting them
                # as "infeasible candidates" misleads the user.
                if not _is_solvable(r):
                    continue
                sr = SweepResult(core, wire, material, r)
                if feasible_only and not sr.feasible:
                    continue
                results.append(sr)
                if progress_cb is not None and done % 50 == 0:
                    progress_cb(done, total)
    if progress_cb is not None:
        progress_cb(done, total)
    return results


def pareto_front(results: list[SweepResult]) -> list[SweepResult]:
    """Non-dominated set across (volume_cm3, P_total_W). Lower-is-better on both axes.

    Only considers feasible results (infeasible designs aren't worth comparing).
    """
    feas = [r for r in results if r.feasible]
    pareto: list[SweepResult] = []
    for i, ri in enumerate(feas):
        dominated = False
        for j, rj in enumerate(feas):
            if i == j:
                continue
            if (
                rj.volume_cm3 <= ri.volume_cm3
                and rj.P_total_W <= ri.P_total_W
                and (rj.volume_cm3 < ri.volume_cm3 or rj.P_total_W < ri.P_total_W)
            ):
                dominated = True
                break
        if not dominated:
            pareto.append(ri)
    pareto.sort(key=lambda r: r.volume_cm3)
    return pareto


def rank(
    results: list[SweepResult],
    *,
    by: str = "loss",
    feasible_first: bool = True,
) -> list[SweepResult]:
    """Sort sweep results.

    by:
      'loss'   — lowest P_total_W first
      'volume' — smallest volume first
      'temp'   — lowest T_winding_C first
      'score'  — composite (normalized loss+volume, lower is better)
    """
    if by == "loss":
        key = lambda r: r.P_total_W
    elif by == "volume":
        key = lambda r: r.volume_cm3
    elif by == "temp":
        key = lambda r: r.T_winding_C
    elif by == "cost":
        # Designs without cost go to the end.
        def _cost_key(r: SweepResult) -> tuple[bool, float]:
            c = r.total_cost
            return (c is None, c if c is not None else float("inf"))

        key = _cost_key
    elif by == "score":
        if not results:
            return []
        max_loss = max(r.P_total_W for r in results) or 1.0
        max_vol = max(r.volume_cm3 for r in results) or 1.0
        key = lambda r: (r.P_total_W / max_loss) * 0.6 + (r.volume_cm3 / max_vol) * 0.4
    elif by == "score_with_cost":
        if not results:
            return []
        max_loss = max(r.P_total_W for r in results) or 1.0
        max_vol = max(r.volume_cm3 for r in results) or 1.0
        costs = [r.total_cost for r in results if r.total_cost is not None]
        max_cost = max(costs) if costs else 1.0

        def _composite(r: SweepResult) -> float:
            c = r.total_cost if r.total_cost is not None else max_cost
            return (
                0.4 * (r.P_total_W / max_loss)
                + 0.3 * (r.volume_cm3 / max_vol)
                + 0.3 * (c / max_cost)
            )

        key = _composite
    else:
        raise ValueError(f"Unknown ranking criterion: {by}")
    sorted_res = sorted(results, key=key)
    if feasible_first:
        sorted_res.sort(key=lambda r: (not r.feasible, key(r)))
    return sorted_res
