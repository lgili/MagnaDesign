"""Tier 4 — swept-magnetostatic FEA validation.

Phase D Step 1 ships a multi-point magnetostatic sweep: it
re-runs the same `fea.runner.validate_design` call Tier 3 uses,
but at *N bias points* across the half-cycle (default 5 — the
fractions [0.2, 0.5, 0.7, 0.9, 1.0] of `I_pk_max`). The samples
produce a cycle-averaged FEA-corrected inductance and surface the
L_min..L_max spread driven by core geometry + rolloff
calibration. Saturation is flagged whenever any sample's `B_FEA`
exceeds the spec's saturation margin — Tier 4 is the strongest
sat guard in the cascade because it sees the actual flux
density the FEM solver predicts, not the linear `L · i / (N · Ae)`
approximation.

Step 2 will swap this for FEMMT's transient mode (`MagneticComponent.
simulate_transient`) when the per-candidate wall budget can absorb
5–60 minutes per design. The `Tier4Result` shape stays the same
across the swap; the orchestrator and UI don't change.

Per-candidate cost: ~N × (Tier 3 wall) ≈ 10–15 s on a typical
workstation. For top-K = 5 candidates that's ~1 minute total —
well below the per-tier budget the openspec design.md sets.
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
    Tier4Result,
    Wire,
)
from pfc_inductor.topology.protocol import ConverterModel

# Bias-point fractions of I_pk_max sampled across the half-cycle.
# Picked to cover the rolloff knee for typical powder cores: 0.2 is
# the lower line-cycle envelope, 0.7 covers the peak ripple, 1.0 is
# the worst-case design point. 5 points keeps the wall manageable.
DEFAULT_SWEEP_FRACTIONS: tuple[float, ...] = (0.2, 0.5, 0.7, 0.9, 1.0)


def evaluate_candidate(
    model: ConverterModel,
    candidate: Candidate,
    core: Core,
    material: Material,
    wire: Wire,
    *,
    tier1: Optional[Tier1Result] = None,
    tier3: Optional[Tier3Result] = None,
    sweep_fractions: tuple[float, ...] = DEFAULT_SWEEP_FRACTIONS,
    timeout_s: int = 300,
) -> Optional[Tier4Result]:
    """Run a swept-magnetostatic FEA on one candidate.

    Returns ``None`` when:

    - The analytical engine could not solve a starting design (no `N`
      to drive the simulator with).
    - The FEA backend has no support for the candidate's geometry,
      or no backend is installed (caller sees `None` plus a notes
      entry from the safe wrapper).

    Errors during the FEA solve propagate; `evaluate_candidate_safe`
    converts them into a notes string the orchestrator persists.
    """
    if tier1 is not None:
        design_result = tier1.design
    else:
        design_result = model.steady_state(core, material, wire)
    if design_result.N_turns <= 0:
        return None

    # Local import — `fea.runner` pulls heavy deps (FEMMT, gmsh) only
    # if the host has them installed. Same pattern Tier 3 uses.
    from pfc_inductor.fea.runner import validate_design

    I_pk = float(design_result.I_line_pk_A)
    if I_pk <= 0:
        return None

    fractions = tuple(sweep_fractions)
    if not fractions:
        return None

    sample_currents: list[float] = []
    sample_L: list[float] = []
    sample_B: list[float] = []

    backend_label = "unknown"
    t0 = time.perf_counter()
    for f in fractions:
        I_sample = max(I_pk * float(f), 1e-6)
        # Spin a copy of the engine result that points the FEA solver
        # at this bias point; everything else (N, Ae, gap…) stays the
        # same.
        sim_result = design_result.model_copy(update={
            "I_line_pk_A": I_sample,
            "I_pk_max_A": I_sample,
        })
        fea: FEAValidation = validate_design(
            model.spec, core, wire, material, sim_result,
            timeout_s=timeout_s,
        )
        sample_currents.append(I_sample)
        sample_L.append(fea.L_FEA_uH)
        sample_B.append(fea.B_pk_FEA_T)
        backend_label = _backend_label(fea.femm_binary)
    wall = time.perf_counter() - t0

    L_min = min(sample_L)
    L_max = max(sample_L)
    L_avg = sum(sample_L) / len(sample_L)
    B_pk = max(abs(b) for b in sample_B)

    # Saturation flag: any sampled B exceeds the configured margin.
    margin = float(model.spec.Bsat_margin)
    Bsat_25 = float(material.Bsat_25C_T)
    Bsat_100 = float(material.Bsat_100C_T)
    T_C = float(design_result.T_winding_C)
    if Bsat_100 > 0:
        T = max(25.0, min(100.0, T_C))
        Bsat_T = Bsat_25 + (Bsat_100 - Bsat_25) * (T - 25.0) / 75.0
    else:
        Bsat_T = Bsat_25
    sat_t4 = B_pk > Bsat_T * (1.0 - margin)

    # Cross-tier delta vs Tier 3 (single-point peak), if available.
    L_vs_t3: Optional[float] = None
    if tier3 is not None and tier3.L_FEA_uH > 0:
        L_vs_t3 = 100.0 * (L_avg - tier3.L_FEA_uH) / tier3.L_FEA_uH

    return Tier4Result(
        candidate=candidate,
        L_min_FEA_uH=float(L_min),
        L_max_FEA_uH=float(L_max),
        L_avg_FEA_uH=float(L_avg),
        B_pk_FEA_T=float(B_pk),
        saturation_t4=bool(sat_t4),
        sample_currents_A=sample_currents,
        sample_L_uH=sample_L,
        sample_B_T=sample_B,
        n_points_simulated=len(fractions),
        solve_time_s=wall,
        backend=backend_label,
        L_avg_relative_to_tier3_pct=L_vs_t3,
    )


def evaluate_candidate_safe(
    model: ConverterModel,
    candidate: Candidate,
    core: Core,
    material: Material,
    wire: Wire,
    *,
    tier1: Optional[Tier1Result] = None,
    tier3: Optional[Tier3Result] = None,
    sweep_fractions: tuple[float, ...] = DEFAULT_SWEEP_FRACTIONS,
    timeout_s: int = 300,
) -> tuple[Optional[Tier4Result], Optional[str]]:
    """Like `evaluate_candidate` but never raises.

    Reasons for `result is None`:

    - `tier4_unavailable: …`  — no FEA backend installed.
    - `tier4_solver_error: …` — solver crashed or timed out.
    - `tier4_engine_error: …` — analytical engine couldn't seed the
      sweep with a starting design.
    """
    try:
        return (
            evaluate_candidate(
                model, candidate, core, material, wire,
                tier1=tier1, tier3=tier3,
                sweep_fractions=sweep_fractions, timeout_s=timeout_s,
            ),
            None,
        )
    except FEMMNotAvailable as exc:
        return None, f"tier4_unavailable: {exc}"
    except FEMMSolveError as exc:
        return None, f"tier4_solver_error: {exc}"
    except DesignError as exc:
        return None, f"tier4_engine_error: {exc.user_message()}"
    except Exception as exc:
        return None, f"tier4_error: {type(exc).__name__}: {exc}"


def supports_tier4() -> bool:
    """Same backend probe Tier 3 uses — Tier 4 reuses Tier 3's solver."""
    try:
        from pfc_inductor.optimize.cascade.tier3 import supports_tier3
    except Exception:
        return False
    return bool(supports_tier3())


def _backend_label(femm_binary: str) -> str:
    s = (femm_binary or "").lower()
    if "femmt" in s or "onelab" in s or "getdp" in s:
        return "femmt"
    if "femm" in s or "xfemm" in s:
        return "femm"
    return "unknown"
