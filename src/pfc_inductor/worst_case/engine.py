"""Corner-DOE engine — sweep ``design()`` over a tolerance grid.

Given a nominal ``(Spec, Core, Wire, Material)`` tuple plus a
:class:`ToleranceSet`, evaluate the engine at every combination of
``±p3sigma`` extremes and report the worst-case violator per
metric.

How tolerances are applied
--------------------------

Each tolerance maps to a *specific deformation* of the input
tuple:

- ``Vin_Vrms``   → ``Spec.Vin_min_Vrms`` / ``Vin_nom_Vrms`` shifted.
- ``T_amb_C``    → ``Spec.T_amb_C`` shifted (absolute, not %).
- ``Pout_pct``   → ``Spec.Pout_W`` scaled.
- ``AL_pct``     → ``Core.AL_nH`` scaled.
- ``Bsat_pct``   → ``Material.Bsat_25C_T`` and ``Bsat_100C_T``
                  scaled (lot-to-lot tracks together).
- ``mu_r_pct``   → ``Material.mu_initial`` scaled.
- ``wire_dia_pct`` → ``Wire.d_cu_mm`` scaled.

The deformations are pure functions returning fresh objects — no
in-place mutation, no side effects on the caller's catalogue.

Why ±3σ corners only
--------------------

For an N-tolerance set, the full DOE grid is 3^N points (each
tolerance at -1, 0, +1). We evaluate ALL 3^N combinations only
when N ≤ 4 (81 points = ~30 s on a modern CPU). For N > 4 we
sample the **fractional factorial** (the 2^N edges of the
hypercube plus the centre, plus the per-axis ±extreme) — that's
the corner set most engineers care about. Monte-Carlo in
``monte_carlo.simulate_yield`` handles the dense interior.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Optional

from pfc_inductor.design import design as run_design
from pfc_inductor.errors import DesignError
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.worst_case.tolerances import (
    Tolerance,
    ToleranceKind,
    ToleranceSet,
)


# ---------------------------------------------------------------------------
# Config + result dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WorstCaseConfig:
    """Knobs that control how the corner DOE behaves.

    Defaults are chosen so the typical 7-tolerance set (the
    bundled ``DEFAULT_TOLERANCES``) runs in under 10 s on a
    laptop. Tighten / widen as the project demands.
    """

    full_factorial_max_n: int = 4
    """Below this number of tolerances, evaluate every 3^N corner.
    Above it, fall back to the per-axis fractional sample."""

    metrics_to_track: tuple[str, ...] = (
        "T_winding_C",
        "B_pk_T",
        "P_total_W",
        "T_rise_C",
    )
    """DesignResult fields to aggregate per corner. Each appears
    in :class:`WorstCaseSummary` with its worst-case corner."""


@dataclass(frozen=True)
class CornerResult:
    """A single point on the DOE grid."""

    label: str
    """Human-readable corner name, e.g. ``"AL=-1, Bsat=+1"``."""

    deltas: dict[str, float]
    """Per-tolerance signed delta applied (-1, 0, +1)."""

    spec: Spec
    core: Core
    wire: Wire
    material: Material

    result: Optional[DesignResult] = None
    """``None`` when the engine raised — the corner is then
    flagged as ``failure`` in :attr:`failure_reason`."""

    failure_reason: Optional[str] = None


@dataclass(frozen=True)
class WorstCaseSummary:
    """Aggregated DOE output."""

    n_corners_evaluated: int
    n_corners_failed: int
    """Failed = engine raised. Distinct from "feasibility violation"
    which is a normal numeric outcome."""

    nominal: Optional[CornerResult]
    corners: tuple[CornerResult, ...]
    worst_per_metric: dict[str, CornerResult] = field(default_factory=dict)
    """Per-metric corner that produced the highest value (worst
    for ΔT, B_pk, P_total — these are all "lower is better")."""


# ---------------------------------------------------------------------------
# Tolerance application
# ---------------------------------------------------------------------------
def _apply_tolerance(
    sign: int,
    tolerance: Tolerance,
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
) -> tuple[Spec, Core, Wire, Material]:
    """Return fresh ``(spec, core, wire, material)`` deformed by
    one tolerance × one sign.

    ``sign`` is -1, 0, or +1. Sign 0 returns the inputs unchanged
    (the nominal axis position). The function is pure: the
    catalogue objects passed in are untouched.
    """
    if sign == 0 or tolerance.p3sigma_pct == 0:
        return spec, core, wire, material

    pct = tolerance.p3sigma_pct
    factor_pct = 1.0 + sign * pct / 100.0
    kind: ToleranceKind = tolerance.kind

    if kind == "Vin_Vrms":
        # Absolute Vrms swing on the design point. We deform
        # ``Vin_min_Vrms`` (the engine's worst-case input) so the
        # corner test exercises both rails.
        delta = sign * pct
        new_spec = spec.model_copy(
            update={
                "Vin_min_Vrms": max(spec.Vin_min_Vrms + delta, 1.0),
                "Vin_nom_Vrms": max(spec.Vin_nom_Vrms + delta, 1.0),
            }
        )
        return new_spec, core, wire, material

    if kind == "T_amb_C":
        # Absolute °C — pct field is interpreted as °C swing,
        # not percent. Documented in tolerances.py.
        delta = sign * pct
        new_spec = spec.model_copy(
            update={
                "T_amb_C": spec.T_amb_C + delta,
            }
        )
        return new_spec, core, wire, material

    if kind == "Pout_pct":
        new_spec = spec.model_copy(
            update={
                "Pout_W": max(spec.Pout_W * factor_pct, 1.0),
            }
        )
        return new_spec, core, wire, material

    if kind == "AL_pct":
        new_core = core.model_copy(
            update={
                "AL_nH": max(core.AL_nH * factor_pct, 1e-3),
            }
        )
        return spec, new_core, wire, material

    if kind == "Bsat_pct":
        update: dict[str, float] = {}
        for fld in ("Bsat_25C_T", "Bsat_100C_T"):
            current = getattr(material, fld, None)
            if current is not None:
                update[fld] = max(current * factor_pct, 0.01)
        new_mat = material.model_copy(update=update) if update else material
        return spec, core, wire, new_mat

    if kind == "mu_r_pct":
        new_mat = material.model_copy(
            update={
                "mu_initial": max(material.mu_initial * factor_pct, 1.0),
            }
        )
        return spec, core, wire, new_mat

    if kind == "wire_dia_pct":
        d = getattr(wire, "d_cu_mm", None)
        if d is None:
            return spec, core, wire, material
        new_wire = wire.model_copy(
            update={
                "d_cu_mm": max(d * factor_pct, 1e-4),
            }
        )
        return spec, core, new_wire, material

    # Unknown kind — silently no-op rather than crashing the DOE.
    return spec, core, wire, material


def _apply_corner(
    signs: tuple[int, ...],
    tolerances: tuple[Tolerance, ...],
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
) -> tuple[Spec, Core, Wire, Material]:
    """Apply every tolerance × its sign in sequence."""
    s, c, w, m = spec, core, wire, material
    for sign, tol in zip(signs, tolerances, strict=True):
        s, c, w, m = _apply_tolerance(sign, tol, s, c, w, m)
    return s, c, w, m


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def evaluate_corners(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    tolerances: ToleranceSet,
    *,
    config: Optional[WorstCaseConfig] = None,
) -> WorstCaseSummary:
    """Run ``design()`` over the corner DOE.

    Returns a :class:`WorstCaseSummary` with per-metric worst-case
    corners. Engine failures (DesignError) are absorbed into a
    ``failure_reason`` field on the corner; the summary's
    ``n_corners_failed`` lets the caller know how many points
    couldn't be evaluated.
    """
    cfg = config or WorstCaseConfig()
    tols = tuple(tolerances.tolerances)

    if not tols:
        # No tolerances — degenerate to a single nominal evaluation.
        nominal = _evaluate_one(
            (),
            tols,
            spec,
            core,
            wire,
            material,
            label="nominal",
        )
        worst = {m: nominal for m in cfg.metrics_to_track} if nominal.result else {}
        return WorstCaseSummary(
            n_corners_evaluated=1,
            n_corners_failed=0 if nominal.result else 1,
            nominal=nominal,
            corners=(nominal,),
            worst_per_metric=worst,
        )

    # Pick corner-enumeration strategy based on N.
    n = len(tols)
    if n <= cfg.full_factorial_max_n:
        sign_grid = list(itertools.product([-1, 0, +1], repeat=n))
    else:
        # Fractional factorial: 2^N hypercube edges + centre +
        # per-axis ± extremes. Keeps the count under control for
        # N = 7 (128 + 1 + 14 = 143 corners ≈ 30 s on a laptop).
        edges = list(itertools.product([-1, +1], repeat=n))
        centre = (0,) * n
        per_axis: list[tuple[int, ...]] = []
        for i in range(n):
            for s in (-1, +1):
                row = [0] * n
                row[i] = s
                per_axis.append(tuple(row))
        sign_grid = [centre, *edges, *per_axis]

    corners: list[CornerResult] = []
    nominal: Optional[CornerResult] = None
    for signs in sign_grid:
        label = _label_for(signs, tols)
        cr = _evaluate_one(signs, tols, spec, core, wire, material, label=label)
        corners.append(cr)
        if all(s == 0 for s in signs):
            nominal = cr

    # Aggregate: per metric, find the corner that drove it highest.
    # Engine failures are excluded so a failed corner doesn't claim
    # the worst slot. Falls back to None if every corner failed —
    # the caller checks `n_corners_failed` for that pathology.
    worst: dict[str, CornerResult] = {}
    for metric in cfg.metrics_to_track:
        candidate: Optional[CornerResult] = None
        candidate_value: float = float("-inf")
        for cr in corners:
            if cr.result is None:
                continue
            v = _read_metric(cr.result, metric)
            if v is None:
                continue
            if v > candidate_value:
                candidate_value = v
                candidate = cr
        if candidate is not None:
            worst[metric] = candidate

    return WorstCaseSummary(
        n_corners_evaluated=len(corners),
        n_corners_failed=sum(1 for c in corners if c.result is None),
        nominal=nominal,
        corners=tuple(corners),
        worst_per_metric=worst,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _evaluate_one(
    signs: tuple[int, ...],
    tols: tuple[Tolerance, ...],
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    *,
    label: str,
) -> CornerResult:
    s, c, w, m = _apply_corner(signs, tols, spec, core, wire, material)
    deltas = _delta_dict(signs, tols)
    try:
        result = run_design(s, c, w, m)
    except DesignError as exc:
        return CornerResult(
            label=label,
            deltas=deltas,
            spec=s,
            core=c,
            wire=w,
            material=m,
            result=None,
            failure_reason=str(exc),
        )
    except (ValueError, TypeError, ArithmeticError) as exc:
        # Unexpected non-DesignError — record but don't propagate.
        # A corner that crashes is still useful information.
        return CornerResult(
            label=label,
            deltas=deltas,
            spec=s,
            core=c,
            wire=w,
            material=m,
            result=None,
            failure_reason=f"{type(exc).__name__}: {exc}",
        )
    return CornerResult(
        label=label,
        deltas=deltas,
        spec=s,
        core=c,
        wire=w,
        material=m,
        result=result,
        failure_reason=None,
    )


def _label_for(signs: tuple[int, ...], tols: tuple[Tolerance, ...]) -> str:
    if all(s == 0 for s in signs):
        return "nominal"
    parts = []
    for sign, tol in zip(signs, tols, strict=True):
        if sign == 0:
            continue
        parts.append(f"{tol.name.split()[0]}={sign:+d}")
    return ", ".join(parts) if parts else "nominal"


def _delta_dict(
    signs: tuple[int, ...],
    tols: tuple[Tolerance, ...],
) -> dict[str, float]:
    return {tol.name: float(sign) for sign, tol in zip(signs, tols, strict=True)}


def sensitivity_table(
    summary: WorstCaseSummary,
) -> dict[str, list[tuple[str, float]]]:
    """Per-metric ranked sensitivity table.

    For each tracked metric, computes ``∂metric / ∂tolerance`` by
    finite differences across the corner DOE and returns the
    tolerances ranked by absolute impact (largest first).

    The "impact" is the metric range a single tolerance can swing
    holding the others at zero — i.e. ``max(metric@+1) -
    min(metric@-1)`` across corners where only the named tolerance
    differs from nominal. With a fractional-factorial DOE this
    isn't a perfect partial-derivative; it's a screening
    sensitivity that surfaces the dominant contributors so the
    engineer knows which tolerance to tighten when a design fails.

    Returns ``{metric_key: [(tolerance_name, impact), …]}`` with
    each list pre-sorted descending by impact.
    """
    if not summary.corners or not summary.worst_per_metric:
        return {}

    # Group corners by which tolerances are at non-zero positions.
    # For the per-axis "+1" and "-1" rows in the fractional DOE,
    # exactly one tolerance is non-zero; we pair those with the
    # nominal centre to estimate per-tolerance swing.
    nominal = summary.nominal
    if nominal is None or nominal.result is None:
        return {}

    tolerance_names: set[str] = set()
    for cr in summary.corners:
        for name, sign in cr.deltas.items():
            if sign != 0:
                tolerance_names.add(name)

    out: dict[str, list[tuple[str, float]]] = {}
    metric_keys = list(summary.worst_per_metric.keys())

    for metric in metric_keys:
        nominal_value = _read_metric(nominal.result, metric)
        if nominal_value is None:
            continue
        per_tolerance_impact: list[tuple[str, float]] = []
        for tol_name in tolerance_names:
            # Find the +1 and -1 corners for this tolerance with
            # all other tolerances at 0 (the per-axis rows of the
            # fractional DOE). When the DOE is full-factorial 3^N
            # we get a perfect partial; for fractional we use
            # any corner where this tolerance is the only signed
            # axis.
            plus_value: Optional[float] = None
            minus_value: Optional[float] = None
            for cr in summary.corners:
                if cr.result is None:
                    continue
                non_zero = [(n, s) for n, s in cr.deltas.items() if s != 0]
                if len(non_zero) != 1:
                    continue
                axis_name, axis_sign = non_zero[0]
                if axis_name != tol_name:
                    continue
                v = _read_metric(cr.result, metric)
                if v is None:
                    continue
                if axis_sign > 0:
                    plus_value = v
                elif axis_sign < 0:
                    minus_value = v
            if plus_value is None and minus_value is None:
                continue
            # Impact = max(|plus - nominal|, |minus - nominal|).
            # For a missing branch we use the available one only.
            impact_plus = abs(plus_value - nominal_value) if plus_value is not None else 0.0
            impact_minus = abs(minus_value - nominal_value) if minus_value is not None else 0.0
            impact = max(impact_plus, impact_minus)
            if impact > 0:
                per_tolerance_impact.append((tol_name, impact))
        per_tolerance_impact.sort(key=lambda kv: -kv[1])
        out[metric] = per_tolerance_impact
    return out


def _read_metric(result: DesignResult, metric: str) -> Optional[float]:
    """Pull a numeric metric off a DesignResult. Returns None for
    unknown metrics or non-finite values so the worst-case picker
    skips them cleanly."""
    import math

    if "." in metric:
        # Nested attr like "losses.P_total_W" — walk the chain.
        obj: object = result
        for part in metric.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        value = obj
    else:
        # Top-level convenience — also peek into ``losses`` for
        # the common P_total_W shorthand.
        value = getattr(result, metric, None)
        if value is None and hasattr(result, "losses"):
            value = getattr(result.losses, metric, None)
    if not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)
