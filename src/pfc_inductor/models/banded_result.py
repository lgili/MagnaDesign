"""Banded design result — engine output for a VFD-modulated spec.

When a :class:`Spec` carries an ``fsw_modulation`` band, the
engine evaluates the design at every fsw point in the band and
aggregates the per-point results. This module owns the typed
container that holds all the per-point evaluations plus the
worst-case envelope a downstream consumer (UI, optimizer,
compliance, datasheet) reads.

Two design notes
----------------

1. **No engine breakage.** Today's ``design()`` returns a
   ``DesignResult``. The engine wrapper that lights up the band
   path returns either a ``DesignResult`` (single point) or a
   ``BandedDesignResult`` (band). Consumers that need the
   single-point flat surface call :meth:`BandedDesignResult.unwrap`
   to get the worst-case ``DesignResult`` back; everything else
   handles both shapes via :func:`unwrap_for_kpi` at the
   call site.

2. **Worst-case is per-metric.** The thermal worst case (highest
   ΔT) and the magnetic worst case (highest B_pk) usually live at
   different fsw points — high fsw drives losses, low fsw drives
   B_pk because of the larger volt-second area per cycle. The
   container exposes ``worst_per_metric`` so callers can bucket
   the failures correctly instead of conflating them into a
   single "worst point".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Union

from pfc_inductor.models.result import DesignResult
from pfc_inductor.models.spec import Spec


@dataclass(frozen=True)
class BandPoint:
    """One evaluation at a specific fsw within the band."""

    fsw_kHz: float
    """The switching frequency for this evaluation."""

    result: Optional[DesignResult]
    """The full design result. ``None`` when the engine raised at
    this point — the failure is recorded in :attr:`failure_reason`
    so the band stays a complete record."""

    failure_reason: Optional[str] = None


@dataclass
class BandedDesignResult:
    """Engine output for a banded (VFD-modulated) spec.

    Has the same role as ``DesignResult`` for the single-point
    path: every consumer (UI cards, datasheet, optimizer
    scorer) reads from this. The :meth:`unwrap` shim returns the
    worst-case ``DesignResult`` for callers that don't care
    about the band detail and just want the conservative
    answer.
    """

    spec: Spec
    band: tuple[BandPoint, ...]
    nominal: Optional[DesignResult]
    """Result at the band's centre point. ``None`` if the centre
    eval failed; the worst-case envelope is then derived from
    whichever non-failed points landed."""

    worst_per_metric: dict[str, BandPoint] = field(default_factory=dict)
    """Per-metric worst-case point. Keys today: ``T_winding_C``,
    ``B_pk_T``, ``P_total_W``, ``T_rise_C``."""

    flagged_points: tuple[BandPoint, ...] = field(default_factory=tuple)
    """Subset of ``band`` whose engine raised. Empty when every
    evaluation succeeded — the canonical "happy" case."""

    @property
    def all_succeeded(self) -> bool:
        return not self.flagged_points

    @property
    def fsw_count(self) -> int:
        return len(self.band)

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------
    def worst(self, metric: str) -> Optional[BandPoint]:
        """Return the band point whose ``metric`` is highest. Used
        for "this design fails ΔT at fsw=8 kHz" reporting."""
        return self.worst_per_metric.get(metric)

    def unwrap(self) -> Optional[DesignResult]:
        """Return the most-conservative ``DesignResult`` across
        the band — the one whose ``T_winding_C`` is highest. The
        thermal corner is the single best summary because it
        captures both copper and core loss + ambient effects.

        Used by surfaces that expect the legacy single-point
        shape (today's KPI strip, the legacy report writer).
        """
        bp = self.worst_per_metric.get("T_winding_C")
        if bp is None or bp.result is None:
            # Fall back to the first successful point.
            for cand in self.band:
                if cand.result is not None:
                    return cand.result
            return None
        return bp.result


# ---------------------------------------------------------------------------
# Aggregation helper — used by the engine wrapper to populate
# ``worst_per_metric`` and ``flagged_points`` from the raw band.
# ---------------------------------------------------------------------------
def aggregate_band(
    spec: Spec,
    band: list[BandPoint],
    *,
    metrics: tuple[str, ...] = (
        "T_winding_C",
        "B_pk_T",
        "P_total_W",
        "T_rise_C",
    ),
    edge_weighted: bool = False,
) -> BandedDesignResult:
    """Build a ``BandedDesignResult`` from a list of evaluated
    band points.

    ``edge_weighted=True`` (used for the ``triangular_dither``
    profile) restricts the worst-case search to the band's
    extremes (first + last point) — the dither spends most of
    its time near the edges, so the engine reports the *edge*
    worst case rather than a centre-point quirk.
    """
    if not band:
        return BandedDesignResult(
            spec=spec,
            band=(),
            nominal=None,
            worst_per_metric={},
            flagged_points=(),
        )

    flagged = tuple(p for p in band if p.result is None)
    nominal = _pick_nominal(band)

    # Restrict the worst-case search per the edge-weighted hint.
    candidates = (band[0], band[-1]) if edge_weighted and len(band) >= 2 else tuple(band)

    worst: dict[str, BandPoint] = {}
    for metric in metrics:
        best_point: Optional[BandPoint] = None
        best_value: float = float("-inf")
        for bp in candidates:
            if bp.result is None:
                continue
            value = _read_metric(bp.result, metric)
            if value is None:
                continue
            if value > best_value:
                best_value = value
                best_point = bp
        if best_point is not None:
            worst[metric] = best_point

    return BandedDesignResult(
        spec=spec,
        band=tuple(band),
        nominal=nominal.result if nominal is not None else None,
        worst_per_metric=worst,
        flagged_points=flagged,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pick_nominal(band: list[BandPoint]) -> Optional[BandPoint]:
    """Return the band's centre point if it succeeded, else
    ``None`` (caller falls back to "any successful point")."""
    if not band:
        return None
    mid_idx = len(band) // 2
    candidate = band[mid_idx]
    if candidate.result is not None:
        return candidate
    # Centre failed — try the geometric centre of the
    # frequency band instead of the index midpoint, since the
    # band may be uneven.
    target_fsw = sum(p.fsw_kHz for p in band) / len(band)
    closest = min(
        (p for p in band if p.result is not None),
        key=lambda p: abs(p.fsw_kHz - target_fsw),
        default=None,
    )
    return closest


def _read_metric(result: DesignResult, metric: str) -> Optional[float]:
    v = getattr(result, metric, None)
    if v is None and hasattr(result, "losses"):
        v = getattr(result.losses, metric, None)
    if not isinstance(v, (int, float)):
        return None
    if not math.isfinite(v):
        return None
    return float(v)


# ---------------------------------------------------------------------------
# Public type alias for callers that handle both shapes
# ---------------------------------------------------------------------------
DesignOrBanded = Union[DesignResult, BandedDesignResult]


def unwrap_for_kpi(result: DesignOrBanded) -> Optional[DesignResult]:
    """Centralised "give me a flat DesignResult" shim.

    Surfaces that don't yet understand banded results call this
    to get the most-conservative single-point answer. The
    optimizer's ranking + the legacy datasheet writer take this
    path; consumers that DO understand banded (worst-case tab,
    Analysis tab band plots) read the band directly.
    """
    if isinstance(result, BandedDesignResult):
        return result.unwrap()
    return result
