"""Tier 2 — transient ODE evaluation.

Drives a topology's `state_derivatives` ODE through
`simulate_to_steady_state`, post-processes the captured waveform
into design metrics, and packages the answer as a `Tier2Result`.

Phase B Step 1 ships the boost-CCM path. Topologies that do not
yet implement `Tier2ConverterModel` are detected and skipped — the
caller (orchestrator) gets `None` and a reason string.

The Tier-2 saturation flag promotes from "advisory" to a
candidate-killer: any candidate whose simulated `B(t)` exceeds the
spec's `Bsat · (1 - margin)` envelope at any sample is dropped from
the next-tier ranking regardless of its analytical loss.
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np

from pfc_inductor.models import (
    Candidate,
    Core,
    Material,
    Tier1Result,
    Tier2Result,
    Wire,
)
from pfc_inductor.simulate import (
    NonlinearInductor,
    SimulationConfig,
    simulate_to_steady_state,
)
from pfc_inductor.topology.protocol import ConverterModel, Tier2ConverterModel


def supports_tier2(model: ConverterModel) -> bool:
    """Runtime check: does this topology implement the Tier-2 protocol?"""
    return isinstance(model, Tier2ConverterModel)


def evaluate_candidate(
    model: ConverterModel,
    candidate: Candidate,
    core: Core,
    material: Material,
    wire: Wire,
    *,
    tier1: Optional[Tier1Result] = None,
    config: Optional[SimulationConfig] = None,
    bsat_margin: Optional[float] = None,
) -> Optional[Tier2Result]:
    """Run the transient simulator on one candidate.

    Returns ``None`` when:
    - the topology does not implement `state_derivatives` (Tier 2 N/A)
    - the analytical engine could not solve a starting design (no `N`
      to drive the simulator with — Tier 2 needs the same N)

    Errors during integration propagate as exceptions; the orchestrator
    is responsible for catching them and writing a `notes` entry.
    """
    if not supports_tier2(model):
        return None

    # We need the engine's N to know what inductor to simulate. If the
    # caller already ran Tier 1, reuse its design; otherwise run the
    # engine here.
    if tier1 is not None:
        design_result = tier1.design
    else:
        design_result = model.steady_state(core, material, wire)
    N = design_result.N_turns
    if N <= 0:
        return None

    inductor = NonlinearInductor.from_design_point(
        core=core,
        material=material,
        N=N,
        T_C=design_result.T_winding_C,
    )

    # solve_ivp call wall-clocked separately so the orchestrator
    # can budget per-tier time without timing the housekeeping.
    t0 = time.perf_counter()
    waveform = simulate_to_steady_state(
        model,
        inductor,
        config=config,
    )
    sim_wall = time.perf_counter() - t0

    # Use only the last simulated line cycle for steady-state metrics.
    last = waveform.last_cycle()
    i_pk = last.i_pk_A
    i_rms = last.i_rms_A
    B_pk = last.B_pk_T

    # Sample L(i) along the cycle to derive min and average inductance —
    # the analytical engine reports a single `L_actual_uH` from the peak
    # bias, so showing the spread is exactly the kind of thing Tier 2
    # exists to surface.
    L_arr = inductor.L_H_array(last.i_L_A) * 1e6  # µH
    if L_arr.size > 0:
        L_min_uH = float(np.min(L_arr))
        L_avg_uH = float(np.mean(L_arr))
    else:
        L_min_uH = 0.0
        L_avg_uH = 0.0

    # Saturation flag — uses the anhysteretic curve at the peak
    # current so deep-saturation cases (where `L · i / (N · Ae)`
    # collapses) are correctly flagged.
    margin = bsat_margin
    if margin is None:
        margin = float(model.spec.Bsat_margin)
    saturated = inductor.is_saturated_at_current(i_pk, margin=margin)

    # Cross-tier deltas vs the analytical numbers (when available).
    L_err: Optional[float] = None
    B_err: Optional[float] = None
    i_err: Optional[float] = None
    if design_result.L_actual_uH > 0:
        L_err = 100.0 * (L_avg_uH - design_result.L_actual_uH) / design_result.L_actual_uH
    if design_result.B_pk_T > 0:
        B_err = 100.0 * (B_pk - design_result.B_pk_T) / design_result.B_pk_T
    if design_result.I_pk_max_A > 0:
        i_err = 100.0 * (i_pk - design_result.I_pk_max_A) / design_result.I_pk_max_A

    return Tier2Result(
        candidate=candidate,
        i_pk_A=i_pk,
        i_rms_A=i_rms,
        B_pk_T=B_pk,
        L_min_uH=L_min_uH,
        L_avg_uH=L_avg_uH,
        saturation_t2=saturated,
        converged=waveform.cycle_stats.converged,
        n_line_cycles_simulated=waveform.n_line_cycles,
        sim_wall_time_s=sim_wall,
        L_relative_error_pct=L_err,
        B_relative_error_pct=B_err,
        i_pk_relative_error_pct=i_err,
    )


def evaluate_candidate_safe(
    model: ConverterModel,
    candidate: Candidate,
    core: Core,
    material: Material,
    wire: Wire,
    *,
    tier1: Optional[Tier1Result] = None,
    config: Optional[SimulationConfig] = None,
    bsat_margin: Optional[float] = None,
) -> tuple[Optional[Tier2Result], Optional[str]]:
    """Like `evaluate_candidate` but never raises.

    Returns `(result, error)`. On success, `error is None`. The
    orchestrator records `error` as a `notes` entry on the
    candidate's row.
    """
    try:
        return (
            evaluate_candidate(
                model,
                candidate,
                core,
                material,
                wire,
                tier1=tier1,
                config=config,
                bsat_margin=bsat_margin,
            ),
            None,
        )
    except NotImplementedError as exc:
        return None, f"tier2_unavailable: {exc}"
    except Exception as exc:
        return None, f"tier2_error: {type(exc).__name__}: {exc}"
