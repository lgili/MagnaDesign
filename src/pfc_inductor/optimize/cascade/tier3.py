"""Tier 3 — magnetostatic FEA validation.

Wraps `fea.runner.validate_design` (the same dispatcher the GUI's
*Validate (FEA)* dialog uses) and packages the result into the
cascade-shaped `Tier3Result`. Used by the orchestrator on the
top-K Tier-2 survivors to give the engineer a numerical
second-source on `L_actual_uH` and `B_pk_T` from a 2-D FEM solve.

Phase C ships:

- boost-CCM topology, all curated core shapes (toroid via FEMM
  axisymmetric when present, EE/ETD/PQ via FEMMT), passive choke
  / line reactor reuse the same FEA dispatcher.
- A *disagreement flag* — when the FEA L or B differs from the
  analytical Tier-1 result by more than `disagree_pct` (default
  15 %), the row gets `disagrees_with_tier1 = True` so the UI
  can badge it.

The orchestrator runs Tier 3 sequentially because FEMMT spawns
ONELAB with shared temp directories — concurrent runs collide.
Per-candidate wall is 5–30 s on a typical workstation, so a
`tier3_top_k` of 10–50 is the practical sweet spot.
"""
from __future__ import annotations

import time
from typing import Optional

from pfc_inductor.errors import DesignError
from pfc_inductor.fea.models import (
    FEAValidation,
    FEMMNotAvailable,
    FEMMSolveError,
)
from pfc_inductor.models import (
    Candidate,
    Core,
    Material,
    Tier1Result,
    Tier3Result,
    Wire,
)
from pfc_inductor.topology.protocol import ConverterModel


def evaluate_candidate(
    model: ConverterModel,
    candidate: Candidate,
    core: Core,
    material: Material,
    wire: Wire,
    *,
    tier1: Optional[Tier1Result] = None,
    timeout_s: int = 300,
    disagree_pct: float = 15.0,
) -> Optional[Tier3Result]:
    """Run a magnetostatic FEA on one candidate.

    Returns ``None`` when:

    - The analytical engine could not solve a starting design (no `N`
      to feed the FEA).
    - The FEA backend has no support for the core's geometry or is
      not installed (callers see this as `None` plus a notes entry
      from the safe wrapper).

    Errors during the FEA solve propagate; `evaluate_candidate_safe`
    converts them into a notes string.
    """
    # Tier 3 needs the engine's solved design as the analytical
    # reference and to know how many turns / what current to drive
    # the FEA simulation with. If the caller ran Tier 1 already we
    # reuse it; otherwise we spin the engine here.
    if tier1 is not None:
        design_result = tier1.design
    else:
        design_result = model.steady_state(core, material, wire)
    if design_result.N_turns <= 0:
        return None

    # Local import — `fea.runner` pulls in heavy deps (FEMMT, gmsh)
    # only if the host actually has them installed. Importing inside
    # the function keeps `optimize.cascade.tier3` cheap on systems
    # without FEMMT and lets the safe wrapper convert ImportError
    # into a clean notes entry.
    from pfc_inductor.fea.runner import validate_design

    t0 = time.perf_counter()
    fea: FEAValidation = validate_design(
        model.spec, core, wire, material, design_result,
        timeout_s=timeout_s,
    )
    wall = time.perf_counter() - t0

    disagrees = bool(
        abs(fea.L_pct_error) > disagree_pct
        or abs(fea.B_pct_error) > disagree_pct,
    )

    return Tier3Result(
        candidate=candidate,
        L_FEA_uH=fea.L_FEA_uH,
        B_pk_FEA_T=fea.B_pk_FEA_T,
        L_relative_error_pct=fea.L_pct_error,
        B_relative_error_pct=fea.B_pct_error,
        solve_time_s=wall,
        backend=_backend_label(fea.femm_binary),
        confidence=fea.confidence,
        disagrees_with_tier1=disagrees,
    )


def evaluate_candidate_safe(
    model: ConverterModel,
    candidate: Candidate,
    core: Core,
    material: Material,
    wire: Wire,
    *,
    tier1: Optional[Tier1Result] = None,
    timeout_s: int = 300,
    disagree_pct: float = 15.0,
) -> tuple[Optional[Tier3Result], Optional[str]]:
    """Like `evaluate_candidate` but never raises.

    Returns `(result, error)`. Common reasons for `result is None`:

    - `tier3_unavailable: <reason>` — FEMMT / FEMM not installed,
      or shape unsupported.
    - `tier3_solver_error: <reason>` — solver crashed or timed out.
    - `tier3_engine_error: <reason>` — the analytical engine could
      not produce a starting design.
    """
    try:
        return (
            evaluate_candidate(
                model, candidate, core, material, wire,
                tier1=tier1, timeout_s=timeout_s,
                disagree_pct=disagree_pct,
            ),
            None,
        )
    except FEMMNotAvailable as exc:
        return None, f"tier3_unavailable: {exc}"
    except FEMMSolveError as exc:
        return None, f"tier3_solver_error: {exc}"
    except DesignError as exc:
        return None, f"tier3_engine_error: {exc.user_message()}"
    except Exception as exc:
        return None, f"tier3_error: {type(exc).__name__}: {exc}"


def supports_tier3() -> bool:
    """Runtime check: is at least one FEA backend installed and
    configured? The orchestrator uses this to skip Tier 3 silently
    when neither FEMMT nor FEMM/xfemm is reachable, instead of
    flooding the run store with `tier3_unavailable` notes."""
    try:
        from pfc_inductor.fea.probe import (
            is_femm_available,
            is_femmt_onelab_configured,
        )
    except Exception:
        return False
    return bool(is_femmt_onelab_configured()) or bool(is_femm_available())


def _backend_label(femm_binary: str) -> str:
    """Translate the FEAValidation's `femm_binary` field into the
    cascade's terse backend label (`"femmt"` / `"femm"` / `"unknown"`)
    so the run store and CLI don't carry full paths."""
    s = (femm_binary or "").lower()
    if "femmt" in s or "onelab" in s or "getdp" in s:
        return "femmt"
    if "femm" in s or "xfemm" in s:
        return "femm"
    return "unknown"
