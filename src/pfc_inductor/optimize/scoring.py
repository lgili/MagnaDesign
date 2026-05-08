"""Heuristic 0–100 scoring of materials / cores / wires for the
Core selection card's ranked-table view.

Scoring functions are deliberately *cheap* — they do not call
``design()``. Each takes the current ``Spec`` plus the candidate and
returns a float in ``[0, 100]``. The Core table sorts by this
score and uses :class:`ScorePill <pfc_inductor.ui.widgets.ScorePill>`
to colour-grade rows.

The scores are not absolute "how good is this part?" metrics — they
are *relative ranking signals* tuned for the dashboard UX. A core with
score 85 is more likely to lead to a feasible design than a core with
score 40, but both may still need engine validation. The numbers
reflect heuristic factors only:

- **Materials:** Bsat, μᵢ, vendor curation, suitability for the
  active topology (line-reactor wants high-saturation alloys; HF PFC
  wants powder cores).
- **Cores:** ``core_quick_check`` verdict, volume efficiency, AL/Ae
  proportionality, vendor curation.
- **Wires:** current-density match, type bonus (round vs litz at HF),
  cost-per-metre availability.
"""
from __future__ import annotations

import math
from typing import Iterable

from pfc_inductor.models import Core, Material, Spec, Wire
from pfc_inductor.optimize.feasibility import (
    core_quick_check,
    peak_current_A,
    required_L_uH,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _vendor_bonus(vendor: str) -> float:
    """Tiny preference for in-tree curated vendors that we have
    cost data for."""
    curated = {
        "magnetics", "magmattec", "micrometals", "csc",
        "thornton", "dongxing", "tdk", "ferroxcube",
    }
    return 4.0 if vendor.lower().strip() in curated else 0.0


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def score_material(spec: Spec, material: Material) -> float:
    """Score a material for the chosen topology + frequency band.

    Heuristic axes:

    - **Bsat**: ≥ 0.5 T → +25; < 0.3 T → +10 (small ferrites still
      score, but lower). Saturation determines the inductor's I·N
      ceiling.
    - **μᵢ band**: each topology has a "happy zone" for μᵢ (line
      reactor likes 1.5k–10k; HF PFC likes 26–125; passive choke
      sits in between). Award up to +35 for being inside the band.
    - **Loss density at fsw**: lower Pv_ref → +25 maximum (only when
      the reference frequency is in band).
    - **Vendor / curation**: +5 max.
    """
    score = 0.0

    # 1. Saturation
    if material.Bsat_25C_T >= 0.5:
        score += 25.0
    elif material.Bsat_25C_T >= 0.3:
        score += 18.0
    else:
        score += 10.0

    # 2. μᵢ band per topology
    mu = material.mu_initial
    band_score = _mu_band_score(spec.topology, mu)
    score += band_score  # 0..35

    # 3. Loss density. Steinmetz Pv_ref @ (f_ref, B_ref). Lower is
    #    better. We only credit when the material *has* a Steinmetz
    #    table; otherwise neutral.
    if material.steinmetz is not None:
        Pv_ref = material.steinmetz.Pv_ref_mWcm3
        if Pv_ref > 0:
            # 80 mW/cm³ → +25; 800 mW/cm³ → 0; log scale.
            score += _clamp(25.0 * (1.0 - math.log10(max(Pv_ref, 1.0)) / 3.0),
                            0.0, 25.0)

    # 4. Vendor curation + cost-data availability
    score += _vendor_bonus(material.vendor)
    if material.cost_per_kg is not None:
        score += 6.0

    # Topology mismatch penalty — line reactor on a high-μ ferrite
    # designed for HF PFC is suboptimal; we already covered this via
    # the band score, but cap a hard floor.
    return _clamp(score, 0.0, 100.0)


def _mu_band_score(topology: str, mu: float) -> float:
    """Map μᵢ to a [0, 35] score depending on topology preference."""
    if topology == "line_reactor":
        # Wants high-permeability soft magnetic steels / nanocrystalline.
        if 5_000 <= mu <= 30_000:
            return 35.0
        if 2_000 <= mu < 5_000:
            return 25.0
        if 1_000 <= mu < 2_000:
            return 15.0
        return 5.0
    if topology == "boost_ccm":
        # Wants powder cores in the 26–125 μ range, or low-μ ferrite.
        if 26 <= mu <= 125:
            return 35.0
        if 14 <= mu < 26 or 125 < mu <= 200:
            return 25.0
        if mu < 14:
            return 12.0
        return 8.0
    # passive_choke — somewhere in between; broad acceptance.
    if 60 <= mu <= 1_000:
        return 32.0
    if 26 <= mu < 60 or 1_000 < mu <= 5_000:
        return 22.0
    return 10.0


# ---------------------------------------------------------------------------
# Cores
# ---------------------------------------------------------------------------

def score_core(
    spec: Spec, core: Core, material: Material, wire: Wire,
) -> float:
    """Score a core given the full design context.

    Axes:

    - **Feasibility verdict** (``core_quick_check``): ok=70, the rest
      get a 0–35 partial credit so they still rank above truly broken
      candidates.
    - **Volume efficiency**: cores whose Ve is within a 1×–3× window
      of the ideal volume score full marks; very oversized or
      undersized lose proportionally.
    - **AL_nH presence**: a core without an AL value can't be
      scored properly — falls back to a small floor.
    - **Vendor / curation**: +5 max.
    """
    verdict = core_quick_check(spec, core, material, wire)
    if verdict == "ok":
        score = 70.0
    elif verdict == "window_overflow":
        # Could be feasible with a thinner wire — partial credit.
        score = 35.0
    elif verdict == "saturates":
        # Could be feasible with a wider gap or different material.
        score = 25.0
    else:  # too_small_L
        score = 8.0

    # Volume efficiency (Ve relative to "ideal").
    L_req_uH = max(required_L_uH(spec), 1e-9)
    I_pk = peak_current_A(spec)
    # Stored energy ≈ ½ L I² (J). Empirically a packing factor
    # relating volume (mm³) to stored energy gives a sanity-check
    # band: Ve [mm³] / E [µJ] in [200, 2000] is reasonable.
    E_uJ = 0.5 * L_req_uH * 1e-6 * (I_pk ** 2) * 1e6  # µJ
    if E_uJ > 0 and core.Ve_mm3 > 0:
        ratio = core.Ve_mm3 / E_uJ
        if 200 <= ratio <= 1500:
            score += 20.0
        elif 100 <= ratio < 200 or 1500 < ratio <= 3000:
            score += 12.0
        else:
            score += 4.0

    if core.AL_nH > 0:
        score += 4.0
    score += _vendor_bonus(core.vendor)

    # Cost-data availability (small bonus — proxy for "we can get this").
    if core.cost_per_piece is not None:
        score += 4.0

    return _clamp(score, 0.0, 100.0)


# ---------------------------------------------------------------------------
# Wires
# ---------------------------------------------------------------------------

# Target current density (A/mm²). Engineering rules of thumb:
# - 3 A/mm² for inductors with passive cooling
# - 4–5 A/mm² for forced-air or PCB-mounted designs
# - 8 A/mm² for short-duty chokes
_J_TARGET = 4.0


def score_wire(
    spec: Spec, core: Core, wire: Wire, material: Material,
) -> float:
    """Score a wire for the operating current and switching frequency.

    Axes:

    - **Current density**: how close the wire's effective area gives
      a J close to ``_J_TARGET``. Up to +50.
    - **Type match**: at high frequency Litz beats round (skin).
      Round wire scores +20 at low f, Litz scores +30 at f_sw ≥ 50 kHz.
    - **Cost-per-metre availability**: +5 max.
    - **Vendor curation**: +5 max.
    """
    score = 0.0

    # Current density
    I_rms = peak_current_A(spec) / math.sqrt(2.0)
    if I_rms > 0 and wire.A_cu_mm2 > 0:
        J_actual = I_rms / wire.A_cu_mm2
        # Penalty grows quickly as J deviates from target.
        delta = abs(J_actual - _J_TARGET) / _J_TARGET
        score += _clamp(50.0 * (1.0 - min(delta, 1.0)), 0.0, 50.0)

    # Type-vs-frequency
    f_sw_kHz = (spec.f_sw_kHz if spec.topology == "boost_ccm"
                else spec.f_line_Hz / 1000.0)
    f_sw_Hz = f_sw_kHz * 1000.0
    if f_sw_Hz >= 50_000:
        # High frequency — Litz wins.
        if wire.type == "litz":
            score += 30.0
        elif wire.type == "round":
            score += 12.0
        else:
            score += 8.0
    else:
        if wire.type == "round":
            score += 25.0
        elif wire.type == "foil":
            score += 22.0
        else:
            # Litz is overkill at line frequency — small penalty
            # (still works, just costs more).
            score += 14.0

    # Window plausibility — the wire is more useful when its outer
    # diameter is < ~ 30 % of the core's window.
    try:
        d_o = wire.outer_diameter_mm()
        wa = max(core.Wa_mm2, 1e-9)
        # Rough single-layer turns budget; if too few, penalise.
        budget = math.sqrt(wa) / max(d_o, 0.05)
        if budget >= 12:
            score += 10.0
        elif budget >= 6:
            score += 5.0
    except (ValueError, ZeroDivisionError):
        pass

    if wire.cost_per_meter is not None:
        score += 5.0

    return _clamp(score, 0.0, 100.0)


# ---------------------------------------------------------------------------
# Bulk helpers
# ---------------------------------------------------------------------------

def rank_materials(
    spec: Spec, materials: Iterable[Material],
) -> list[tuple[Material, float]]:
    return sorted(
        ((m, score_material(spec, m)) for m in materials),
        key=lambda mm: mm[1], reverse=True,
    )


def rank_cores(
    spec: Spec, cores: Iterable[Core], material: Material, wire: Wire,
) -> list[tuple[Core, float]]:
    return sorted(
        ((c, score_core(spec, c, material, wire)) for c in cores),
        key=lambda cc: cc[1], reverse=True,
    )


def rank_wires(
    spec: Spec, core: Core, wires: Iterable[Wire], material: Material,
) -> list[tuple[Wire, float]]:
    return sorted(
        ((w, score_wire(spec, core, w, material)) for w in wires),
        key=lambda ww: ww[1], reverse=True,
    )
