"""Engine wrapper that evaluates a design across an fsw band.

Single entry point: :func:`eval_band`. Iterates the band's fsw
points, calls :func:`pfc_inductor.design.design` per point with a
spec deformed only on ``f_sw_kHz``, and aggregates the per-point
results via :func:`pfc_inductor.models.banded_result.aggregate_band`.

Engine failures are absorbed per-point — a fsw value that pushes
the design into a corner where the engine raises is recorded as a
``BandPoint`` with ``failure_reason`` set, and the band keeps
going. The aggregator then drops failed points from the worst-case
search but counts them in ``flagged_points`` so a downstream
report can flag them.

Performance note
----------------

For the bundled 5-point default band, an end-to-end ``eval_band``
call is ~5× one ``design()`` invocation (the engine takes a few
ms at the operating point on a modern laptop). The cascade
optimizer + UI worst-case tab call this in worker threads, so the
GUI stays responsive even on a 20-point band.
"""

from __future__ import annotations

from typing import Optional

from pfc_inductor.errors import DesignError
from pfc_inductor.models import Core, Material, Spec, Wire
from pfc_inductor.models.banded_result import (
    BandedDesignResult,
    BandPoint,
    DesignOrBanded,
    aggregate_band,
)


def eval_band(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    *,
    Vin_design_Vrms: Optional[float] = None,
) -> BandedDesignResult:
    """Evaluate the design at every fsw point in the band.

    Raises ``ValueError`` when ``spec.fsw_modulation`` is None —
    callers should use :func:`design_or_band` to dispatch on
    spec shape automatically.
    """
    band = spec.fsw_modulation
    if band is None:
        raise ValueError(
            "eval_band requires spec.fsw_modulation to be set. "
            "Use design_or_band(spec, …) for the dispatch path "
            "that handles the single-point case as well.",
        )

    # Lazy import — keeps the model layer free of design-engine
    # imports for cleaner test boundaries.
    from pfc_inductor.design import design as run_design

    results: list[BandPoint] = []
    for fsw_kHz in band.fsw_points_kHz():
        point_spec = spec.model_copy(update={"f_sw_kHz": float(fsw_kHz)})
        try:
            result = run_design(
                point_spec,
                core,
                wire,
                material,
                Vin_design_Vrms=Vin_design_Vrms,
            )
            results.append(
                BandPoint(
                    fsw_kHz=float(fsw_kHz),
                    result=result,
                )
            )
        except DesignError as exc:
            results.append(
                BandPoint(
                    fsw_kHz=float(fsw_kHz),
                    result=None,
                    failure_reason=str(exc),
                )
            )
        except (ValueError, TypeError, ArithmeticError) as exc:
            # Engine raised something unexpected — record it but
            # don't propagate, the band stays a complete record.
            results.append(
                BandPoint(
                    fsw_kHz=float(fsw_kHz),
                    result=None,
                    failure_reason=f"{type(exc).__name__}: {exc}",
                )
            )

    return aggregate_band(
        spec,
        results,
        edge_weighted=band.is_edge_weighted(),
    )


def eval_load_band(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    *,
    Vin_design_Vrms: Optional[float] = None,
) -> BandedDesignResult:
    """Evaluate the design at every Pout point in the load band.

    Mirror of :func:`eval_band` for the ``LoadModulation`` path:
    iterates ``spec.load_modulation.pout_points_W()``, deforms
    each point's spec by overriding ``Pout_W``, calls
    :func:`pfc_inductor.design.design`, and aggregates via
    :func:`aggregate_band`. Returns the same
    :class:`BandedDesignResult` shape so every consumer (Analysis
    band chart, datasheet, optimizer scorer) handles fsw and load
    bands identically.

    Raises ``ValueError`` when ``spec.load_modulation`` is None —
    callers should use :func:`design_or_band` to dispatch
    automatically.
    """
    band = spec.load_modulation
    if band is None:
        raise ValueError(
            "eval_load_band requires spec.load_modulation to be set. "
            "Use design_or_band(spec, …) for the dispatch path "
            "that handles the single-point case as well.",
        )

    from pfc_inductor.design import design as run_design

    results: list[BandPoint] = []
    for pout_W in band.pout_points_W():
        point_spec = spec.model_copy(update={"Pout_W": float(pout_W)})
        try:
            result = run_design(
                point_spec,
                core,
                wire,
                material,
                Vin_design_Vrms=Vin_design_Vrms,
            )
            results.append(BandPoint(pout_W=float(pout_W), result=result))
        except DesignError as exc:
            results.append(
                BandPoint(
                    pout_W=float(pout_W),
                    result=None,
                    failure_reason=str(exc),
                )
            )
        except (ValueError, TypeError, ArithmeticError) as exc:
            results.append(
                BandPoint(
                    pout_W=float(pout_W),
                    result=None,
                    failure_reason=f"{type(exc).__name__}: {exc}",
                )
            )

    return aggregate_band(
        spec,
        results,
        edge_weighted=band.is_edge_weighted(),
    )


def design_or_band(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    *,
    Vin_design_Vrms: Optional[float] = None,
) -> DesignOrBanded:
    """Dispatcher — single-point or banded depending on the spec.

    Three paths:

    1. ``spec.fsw_modulation`` set → :func:`eval_band` (fsw sweep).
    2. ``spec.load_modulation`` set → :func:`eval_load_band` (Pout sweep).
    3. Neither set → :func:`design` (single-point legacy path).

    The two modulation fields are mutually exclusive (enforced by
    Spec validator) so the dispatch order is unambiguous.
    """
    from pfc_inductor.design import design as run_design

    if spec.fsw_modulation is not None:
        return eval_band(
            spec,
            core,
            wire,
            material,
            Vin_design_Vrms=Vin_design_Vrms,
        )
    if spec.load_modulation is not None:
        return eval_load_band(
            spec,
            core,
            wire,
            material,
            Vin_design_Vrms=Vin_design_Vrms,
        )
    return run_design(
        spec,
        core,
        wire,
        material,
        Vin_design_Vrms=Vin_design_Vrms,
    )
