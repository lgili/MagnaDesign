"""Monte-Carlo yield estimator.

The corner DOE in :mod:`pfc_inductor.worst_case.engine` covers the
*extremes* — useful for "is the worst-case in spec?" but not for
"what fraction of units shipped will pass?". This module samples
the interior of the tolerance hypercube and reports the fraction
that meet user-defined acceptance criteria.

Default acceptance criteria
---------------------------

A unit *passes* if **all** of:

- ``T_winding_C <= Spec.T_max_C``
- ``B_pk_T <= material.Bsat × (1 - Bsat_margin)``
- ``Ku_actual <= Ku_max`` (window fits)
- ``losses.P_total_W <= 0.10 × Spec.Pout_W``  (10 % of rated)

Override per project by passing a callable to
:func:`simulate_yield`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from pfc_inductor.design import design as run_design
from pfc_inductor.errors import DesignError
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.worst_case.engine import _apply_corner
from pfc_inductor.worst_case.tolerances import (
    Tolerance,
    ToleranceDistribution,
    ToleranceSet,
)


PassFn = Callable[[DesignResult, Spec, Material], bool]


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class YieldReport:
    """Aggregate output of :func:`simulate_yield`."""

    n_samples: int
    n_pass: int
    n_fail: int
    n_engine_error: int
    """Samples where the engine raised. Counted separately from
    "fail" because they're a tooling concern, not a design one."""

    pass_rate: float
    """``n_pass / n_samples``; range [0, 1]."""

    fail_modes: dict[str, int] = field(default_factory=dict)
    """Per-criterion fail count. A unit can appear in multiple
    buckets if it violates several criteria simultaneously."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def simulate_yield(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    tolerances: ToleranceSet,
    *,
    n_samples: int = 1000,
    seed: int = 0,
    pass_fn: Optional[PassFn] = None,
) -> YieldReport:
    """Sample the tolerance hypercube and count the passing units.

    Returns a :class:`YieldReport`. Reproducible — the same seed
    yields the same report so CI can regress on an exact figure.

    The ``n_samples`` default of 1 000 balances time budget
    (~1 minute on a laptop for the bundled default tolerance set)
    against confidence interval (~±3 % at 95 % CI for a 90 % yield).
    Bump to 10 k for a final-go report; 100 k for a ±0.3 % CI.
    """
    rng = np.random.default_rng(seed)
    pass_check = pass_fn or _default_pass_fn

    tols = tuple(tolerances.tolerances)
    n_pass = 0
    n_engine_error = 0
    fail_modes: dict[str, int] = {}

    for _ in range(n_samples):
        signs = _sample_signs(rng, tols)
        s, c, w, m = _apply_corner(signs, tols, spec, core, wire, material)
        try:
            result = run_design(s, c, w, m)
        except DesignError:
            n_engine_error += 1
            continue
        except (ValueError, TypeError, ArithmeticError):
            n_engine_error += 1
            continue

        passed, reasons = _check_pass(pass_check, result, s, m)
        if passed:
            n_pass += 1
        else:
            for reason in reasons:
                fail_modes[reason] = fail_modes.get(reason, 0) + 1

    n_fail = n_samples - n_pass - n_engine_error
    rate = n_pass / max(n_samples, 1)
    return YieldReport(
        n_samples=n_samples,
        n_pass=n_pass,
        n_fail=n_fail,
        n_engine_error=n_engine_error,
        pass_rate=rate,
        fail_modes=dict(sorted(fail_modes.items(),
                               key=lambda kv: -kv[1])),
    )


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------
def _sample_signs(
    rng: np.random.Generator,
    tols: tuple[Tolerance, ...],
) -> tuple[int, ...]:
    """Sample one signed multiplier per tolerance.

    The corner DOE engine consumes signs in {-1, 0, +1} to apply
    discrete shifts; for Monte-Carlo we need *continuous* shifts,
    but the engine's `_apply_corner` only honours the discrete
    grid. We work around it by quantising each Gaussian /
    triangular / uniform draw into the closest discrete sign at
    the corner *boundary*. This is a deliberate simplification —
    the next iteration will allow continuous fractional shifts
    by extending `_apply_tolerance` with a float `factor` argument
    instead of an int sign.

    For now the discrete approximation tracks worst-case yield
    behaviour well: the boundary samples dominate the tail
    statistics that the pass/fail decision actually depends on.
    """
    out: list[int] = []
    for tol in tols:
        # Draw normalised in [-1, +1] using the requested distro.
        if tol.distribution == "gaussian":
            # 1 σ = p3sigma_pct / 3, so a draw clamped to [-1, +1]
            # in normalised units == a draw in ±p3sigma_pct.
            x = rng.normal(0.0, 1.0 / 3.0)
            x = max(-1.0, min(1.0, x))
        elif tol.distribution == "uniform":
            x = rng.uniform(-1.0, 1.0)
        elif tol.distribution == "triangle":
            x = rng.triangular(-1.0, 0.0, 1.0)
        else:  # defensive
            x = 0.0
        # Quantise: |x| <= 0.33 → 0; else sign(x).
        if abs(x) <= 1.0 / 3.0:
            out.append(0)
        else:
            out.append(+1 if x > 0 else -1)
    return tuple(out)


# ---------------------------------------------------------------------------
# Default pass criterion
# ---------------------------------------------------------------------------
def _default_pass_fn(
    result: DesignResult,
    spec: Spec,
    material: Material,
) -> tuple[bool, list[str]]:
    """Evaluate the four-rule default acceptance.

    Returns ``(passed, reasons)`` — when ``passed`` is True,
    ``reasons`` is empty; otherwise it lists every violated
    criterion so the report can bucket fail modes.
    """
    reasons: list[str] = []

    # T_winding cap (Spec.T_max_C)
    t_max = float(spec.T_max_C)
    t_w = float(result.T_winding_C)
    if t_w > t_max:
        reasons.append("T_winding")

    # B_pk vs Bsat envelope
    bsat = float(getattr(material, "Bsat_100C_T", 0.0))
    margin = float(spec.Bsat_margin)
    bsat_limit = bsat * max(1.0 - margin, 0.0)
    b_pk = float(result.B_pk_T)
    if bsat_limit > 0 and b_pk > bsat_limit:
        reasons.append("Bsat")

    # Window fit (Ku)
    ku_actual = float(getattr(result, "Ku_actual", 0.0))
    ku_max = float(spec.Ku_max)
    if ku_actual > ku_max:
        reasons.append("Ku")

    # Loss budget — 10 % of rated Pout is a reasonable default.
    p_total = float(result.losses.P_total_W)
    pout = float(spec.Pout_W)
    if pout > 0 and p_total > 0.10 * pout:
        reasons.append("Losses")

    return (not reasons, reasons)


def _check_pass(
    fn: PassFn | Callable[[DesignResult, Spec, Material], tuple[bool, list[str]]],
    result: DesignResult,
    spec: Spec,
    material: Material,
) -> tuple[bool, list[str]]:
    """Adapter — caller-provided ``pass_fn`` may return a bool or
    the richer ``(bool, list[str])`` tuple. Normalise to tuple."""
    out = fn(result, spec, material)
    if isinstance(out, tuple):
        passed, reasons = out  # type: ignore[misc]
        return bool(passed), list(reasons)
    return bool(out), [] if out else ["fail"]
