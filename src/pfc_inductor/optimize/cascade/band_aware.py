"""Band-aware re-ranking of a completed cascade run.

When a Spec carries an ``fsw_modulation`` band, ranking the
cascade's top-N by nominal-fsw loss can mislead — a candidate
that's optimal at 65 kHz nominal may saturate at the band edges.
This module post-processes a completed run: it re-evaluates
each candidate row across the user's band and substitutes the
**worst-case** loss / temp / Bpk for the per-row stored values.

Why post-process instead of touching the Tier-1 hot path
--------------------------------------------------------

The cascade's Tier-1 worker runs in a process pool with one
``ConverterModel`` per worker bound at startup; making it
band-aware would require re-pickling the model + the band
config per candidate. The post-process path takes the same
``(spec, core, wire, material)`` tuple and runs through
:func:`pfc_inductor.modulation.eval_band` in-thread — slower
per candidate but acceptable for the top-N (default 25) the
user actually inspects.

Public API
----------

- :func:`band_aware_rerank` — takes a list of
  :class:`CandidateRow` + the engine catalogues + a banded spec,
  returns a fresh list with worst-case fields substituted in.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Optional

from pfc_inductor.errors import DesignError
from pfc_inductor.models import Core, Material, Spec, Wire
from pfc_inductor.models.banded_result import BandedDesignResult
from pfc_inductor.modulation import eval_band
from pfc_inductor.optimize.cascade.store import CandidateRow


@dataclass(frozen=True)
class _BandRerankResult:
    """One candidate's banded re-evaluation outcome."""

    row: CandidateRow
    """Original ``CandidateRow`` with worst-case fields substituted
    into ``loss_t1_W`` / ``temp_t1_C``. Other fields are preserved
    verbatim."""

    worst_fsw_kHz_loss: Optional[float]
    """fsw at which the worst-case loss was found."""

    worst_fsw_kHz_temp: Optional[float]
    """fsw at which the worst-case temperature was found."""

    flagged: bool
    """True when at least one band point's engine raised."""


def band_aware_rerank(
    rows: list[CandidateRow],
    spec: Spec,
    cores_by_id: dict[str, Core],
    wires_by_id: dict[str, Wire],
    materials_by_id: dict[str, Material],
) -> list[CandidateRow]:
    """Re-rank ``rows`` by band-worst-case loss.

    For each row, look up the (core, material, wire) triple in
    the catalogue dicts, run :func:`eval_band` over the spec's
    band, and substitute:

    - ``loss_t1_W`` ← worst across the band
    - ``temp_t1_C`` ← worst across the band

    Returns a list sorted ascending by the new ``loss_t1_W``
    (lower is better) so the caller can hand it straight to
    the UI / CLI without an extra ``sorted()`` step.

    Rows whose lookup fails (catalogue churned between the run
    and now) are returned **unchanged** — the original Tier-1
    nominal value is more honest than guessing zero.
    """
    if spec.fsw_modulation is None:
        return list(rows)

    out: list[CandidateRow] = []
    for row in rows:
        core = cores_by_id.get(row.core_id)
        material = materials_by_id.get(row.material_id)
        wire = wires_by_id.get(row.wire_id)
        if core is None or material is None or wire is None:
            out.append(row)
            continue
        try:
            banded = eval_band(spec, core, wire, material)
        except DesignError:
            out.append(row)
            continue
        except (ValueError, TypeError, ArithmeticError):
            out.append(row)
            continue
        worst_loss = _worst_metric(banded, "P_total_W")
        worst_temp = _worst_metric(banded, "T_winding_C")
        new_row = replace(
            row,
            loss_t1_W=(worst_loss if worst_loss is not None
                       else row.loss_t1_W),
            temp_t1_C=(worst_temp if worst_temp is not None
                       else row.temp_t1_C),
        )
        out.append(new_row)

    # Stable sort by worst-case loss; rows missing loss go to
    # the end (treat as +inf for ordering).
    def _sort_key(row: CandidateRow) -> float:
        v = row.loss_t1_W
        if v is None:
            return float("inf")
        if not math.isfinite(v):
            return float("inf")
        return float(v)

    out.sort(key=_sort_key)
    return out


def _worst_metric(
    banded: BandedDesignResult,
    metric: str,
) -> Optional[float]:
    """Pull the worst-case value of ``metric`` from a
    :class:`BandedDesignResult`.

    The aggregator already populated ``worst_per_metric`` with
    the corner whose metric is highest — this just unwraps the
    numeric value (or returns None when the metric isn't
    tracked / every band point failed)."""
    cr = banded.worst_per_metric.get(metric)
    if cr is None or cr.result is None:
        return None
    if "." in metric:
        # Defensive — current call sites only pass top-level
        # attrs but the helper is generic.
        obj: object = cr.result
        for part in metric.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        if isinstance(obj, (int, float)) and math.isfinite(float(obj)):
            return float(obj)
        return None
    value = getattr(cr.result, metric, None)
    if value is None and hasattr(cr.result, "losses"):
        value = getattr(cr.result.losses, metric, None)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None
