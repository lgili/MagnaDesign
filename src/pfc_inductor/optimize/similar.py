"""Similar-parts finder.

Given a target (Core, Material), search the database for alternatives whose
geometric and magnetic parameters are within configurable tolerances.

Two notions of "similar":

1. **Same shape, similar geometry** — replacement cores with comparable
   Ae, Wa, AL, μ_r, Bsat. These are first-order drop-in candidates.
2. **Same part number, alternate material** — the database often contains
   the same physical core wound with several material grades (e.g.
   TDK PQ 32/30 with N49, N87, N97). These appear naturally in the search
   and let the engineer compare loss/saturation tradeoffs without changing
   the mechanical footprint.

The distance metric is a weighted Euclidean over per-parameter % deltas
normalised by their tolerances; smaller is closer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pfc_inductor.data_loader import find_material
from pfc_inductor.models import Core, Material

_PARAM_KEYS = ("Ae", "Wa", "AL", "mu_r", "Bsat")


@dataclass
class SimilarityCriteria:
    """Tolerances in percent and filtering knobs.

    A candidate must satisfy every per-parameter tolerance to be "in
    tolerance"; results inside tolerance are returned ranked by composite
    distance, and out-of-tolerance candidates are dropped.
    """

    Ae_pct: float = 10.0
    Wa_pct: float = 15.0
    AL_pct: float = 20.0
    mu_r_pct: float = 20.0
    Bsat_pct: float = 15.0
    same_shape: bool = True
    same_vendor: bool = False
    exclude_self: bool = True
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "Ae": 1.5,
            "Wa": 1.0,
            "AL": 1.5,
            "mu_r": 1.0,
            "Bsat": 1.0,
        }
    )


@dataclass
class SimilarMatch:
    core: Core
    material: Material
    distance: float
    deltas_pct: dict[str, float]
    is_same_part_number: bool

    @property
    def is_cross_material(self) -> bool:
        """Same physical part number, different material variant."""
        return self.is_same_part_number


def _normalize_shape(s: str) -> str:
    """Bucket shape strings to coarse categories."""
    s = (s or "").lower().strip()
    if "tor" in s:
        return "toroid"
    if "etd" in s:
        return "etd"
    if s.startswith("pq") or "pq" in s:
        return "pq"
    if s.startswith("ee") or s.startswith("e") or "nee" in s or "ei" in s:
        return "e"
    return s or "unknown"


def _pct_delta(target: float, candidate: float) -> float:
    """Return (candidate - target) / target * 100. Zero target → +inf."""
    if abs(target) < 1e-12:
        return float("inf")
    return (candidate - target) / target * 100.0


def _compute_deltas(
    target_core: Core,
    target_material: Material,
    candidate_core: Core,
    candidate_material: Material,
) -> dict[str, float]:
    return {
        "Ae": _pct_delta(target_core.Ae_mm2, candidate_core.Ae_mm2),
        "Wa": _pct_delta(target_core.Wa_mm2, candidate_core.Wa_mm2),
        "AL": _pct_delta(target_core.AL_nH, candidate_core.AL_nH),
        "mu_r": _pct_delta(target_material.mu_initial, candidate_material.mu_initial),
        "Bsat": _pct_delta(target_material.Bsat_25C_T, candidate_material.Bsat_25C_T),
    }


def _within_tolerance(deltas: dict[str, float], crit: SimilarityCriteria) -> bool:
    tol = {
        "Ae": crit.Ae_pct,
        "Wa": crit.Wa_pct,
        "AL": crit.AL_pct,
        "mu_r": crit.mu_r_pct,
        "Bsat": crit.Bsat_pct,
    }
    for k in _PARAM_KEYS:
        if abs(deltas[k]) > tol[k]:
            return False
    return True


def _distance(deltas: dict[str, float], crit: SimilarityCriteria) -> float:
    """Weighted Euclidean over normalised deltas."""
    tol = {
        "Ae": crit.Ae_pct,
        "Wa": crit.Wa_pct,
        "AL": crit.AL_pct,
        "mu_r": crit.mu_r_pct,
        "Bsat": crit.Bsat_pct,
    }
    s = 0.0
    for k in _PARAM_KEYS:
        w = crit.weights.get(k, 1.0)
        if tol[k] <= 0:
            continue
        norm = deltas[k] / tol[k]
        s += w * (norm * norm)
    return s**0.5


def find_equivalents(
    target_core: Core,
    target_material: Material,
    cores: list[Core],
    materials: list[Material],
    criteria: Optional[SimilarityCriteria] = None,
) -> list[SimilarMatch]:
    """Return ranked list of alternatives matching the criteria."""
    crit = criteria or SimilarityCriteria()
    target_shape = _normalize_shape(target_core.shape)
    matches: list[SimilarMatch] = []

    for c in cores:
        if crit.exclude_self and c.id == target_core.id:
            continue
        if crit.same_shape and _normalize_shape(c.shape) != target_shape:
            continue
        if crit.same_vendor and c.vendor != target_core.vendor:
            continue
        try:
            m = find_material(materials, c.default_material_id)
        except KeyError:
            continue
        deltas = _compute_deltas(target_core, target_material, c, m)
        if not _within_tolerance(deltas, crit):
            continue
        d = _distance(deltas, crit)
        matches.append(
            SimilarMatch(
                core=c,
                material=m,
                distance=d,
                deltas_pct=deltas,
                is_same_part_number=(
                    c.vendor == target_core.vendor and c.part_number == target_core.part_number
                ),
            )
        )

    matches.sort(key=lambda x: (not x.is_same_part_number, x.distance))
    return matches
