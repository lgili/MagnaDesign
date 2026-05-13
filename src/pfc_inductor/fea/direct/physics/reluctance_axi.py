"""Analytical reluctance solver for axisymmetric ferrite/powder cores.

Why an analytical solver here when we already have a FEM-based one?
==================================================================

The axisymmetric FEM (``magnetostatic_axi``) ships a known-broken
calibration envelope for EE/EI/PQ ferrite cores: the round-leg
approximation + the Form1P-with-BF_PerpendicularEdge basis combine
to give an L that is *insensitive to both the air-gap and the
material μ_r* on real benchmark cases. The bug is structural — it
won't be fixed without replacing the formulation, which is a
Phase 4.2 (3-D mode) milestone.

Meanwhile, the **textbook reluctance model** is fast, well-known,
and lands within ~15 % of FEMMT on every shape we test. For PFC
inductor design, where the analytical engine already drives the
design at the 5 % level, an FEA validator at ±15 % is plenty.

The formula
===========

For an EE/EI/PQ ferrite core with a discrete gap in the center leg:

::

    R_iron = le / (μ_r · μ_0 · Ae)
    R_gap  = lgap / (μ_0 · Ae · k_fringe)
    L      = N² / (R_iron + R_gap)
    B_pk   = N · I / [(R_iron + R_gap) · Ae]

where ``k_fringe`` is the fringing factor that accounts for the
flux spreading out around the gap (the effective gap area exceeds
``Ae``). Empirical Phase 2 calibration on PQ ferrites:

::

    k_fringe = 1 + 2·sqrt(lgap / w_centerleg)

This is the **Roters / McLyman approximation**, valid for
``lgap / w_centerleg`` in the 0.01 to 0.3 range. Below it
saturates at 1.0; above it the formula loses accuracy and we
clamp at 3.0.

What we don't try
=================

- Saturation roll-off: applied separately via the powder-core
  rolloff helper (Phase 2.5b).
- AC effects (skin, proximity): the AC harmonic template stays;
  this is DC-only.
- Stray flux outside the magnetic circuit: ignored. For high-μ
  ferrite + sane geometry, stray is < 1 % of the iron path flux.
- Fringing in the absence of a gap: closed-circuit ferrites get
  the bare ``L = μ·N²·Ae/le`` (no gap correction).

Better than FEMMT
=================

This module runs in microseconds and works on every shape in our
catalog (EE/EI/PQ/ETD/RM/EP/EFD/EQ/UI/UR/EC/PT). FEMMT supports
only EE/PQ/Single — for the rest it returns ``Core shape 'generic'
not yet supported``. We get coverage and speed; the FEMMT
calibration gap is "structurally limited by axi round-leg".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ReluctanceInputs:
    """Inputs for the analytical reluctance solver."""

    Ae_mm2: float
    """Effective cross-section area of the magnetic path (mm²)."""

    le_mm: float
    """Mean magnetic path length (mm). Catalog ``le_mm`` value."""

    center_leg_w_mm: float
    """Width of the center leg (mm). Used for the fringing factor.
    For PQ / ETD this is the round-leg diameter; for true EE this is
    the rectangular center-leg width."""

    mu_r_core: float
    """Relative permeability of the core."""

    n_turns: int

    current_A: float = 1.0
    """DC current — sets the absolute B scale."""

    lgap_mm: float = 0.0
    """Discrete air-gap length in the center leg (mm).
    Zero for closed-core ferrites (gapless) or powder cores
    (distributed gap handled via the saturation module)."""

    fringing_model: str = "roters"
    """Which fringing model to use: ``"roters"`` (default), ``"none"``
    (k_fringe=1), or ``"flat"`` (k_fringe=1.15, simple empirical
    constant that fits the Phase 2.0 PQ benchmark median)."""


@dataclass(frozen=True)
class ReluctanceOutputs:
    """Same shape contract as ``ToroidalOutputs`` for runner parity."""

    L_uH: float
    B_pk_T: float
    B_avg_T: float
    energy_J: float
    R_iron_per_turn: float
    """Iron path reluctance (A·t/Wb). Diagnostic."""
    R_gap_per_turn: float
    """Air-gap reluctance (A·t/Wb). Diagnostic."""
    k_fringe: float
    """Fringing-factor used (≥ 1.0)."""
    method: str = "analytical_reluctance"


def fringing_factor_roters(lgap_mm: float, w_center_leg_mm: float) -> float:
    """Roters / McLyman fringing factor.

    ``k = 1 + 2·sqrt(lgap / w_center_leg)``

    Clamped to ``[1.0, 3.0]``. The cap at 3.0 prevents runaway when
    ``lgap`` is very large compared to the center leg width (in
    which case the simple closed-form breaks down and a full FEM
    or 3D model is the right answer).
    """
    if lgap_mm <= 0.0 or w_center_leg_mm <= 0.0:
        return 1.0
    k = 1.0 + 2.0 * math.sqrt(lgap_mm / w_center_leg_mm)
    return max(1.0, min(k, 3.0))


def solve_reluctance(inputs: ReluctanceInputs) -> ReluctanceOutputs:
    """Solve the magnetic circuit reluctance for a gapped/closed core."""
    if inputs.Ae_mm2 <= 0 or inputs.le_mm <= 0:
        raise ValueError(f"Ae and le must be positive (got Ae={inputs.Ae_mm2}, le={inputs.le_mm})")
    if inputs.mu_r_core < 1:
        raise ValueError(f"mu_r_core must be ≥ 1 (got {inputs.mu_r_core})")

    mu0 = 4 * math.pi * 1e-7
    Ae = inputs.Ae_mm2 * 1e-6
    le = inputs.le_mm * 1e-3
    lgap = max(inputs.lgap_mm, 0.0) * 1e-3
    N = int(inputs.n_turns)
    I = float(inputs.current_A)

    # Fringing factor
    if inputs.fringing_model == "none":
        k_fringe = 1.0
    elif inputs.fringing_model == "flat":
        k_fringe = 1.15 if lgap > 0 else 1.0
    else:  # roters
        k_fringe = fringing_factor_roters(inputs.lgap_mm, inputs.center_leg_w_mm)

    # Reluctances
    R_iron = le / (inputs.mu_r_core * mu0 * Ae)
    R_gap = lgap / (mu0 * Ae * k_fringe) if lgap > 0 else 0.0
    R_total = R_iron + R_gap

    if R_total <= 0:
        L = 0.0
    else:
        L = (N**2) / R_total

    # Flux and B
    if R_total > 0:
        flux_Wb = N * I / R_total
        B_pk = flux_Wb / Ae
    else:
        flux_Wb = 0.0
        B_pk = 0.0
    # Average B over the circuit: for a closed circuit B ~ uniform
    # across Ae (assuming uniform cross-section). For a gapped
    # circuit, B_iron ≈ B_gap ≈ B_pk. So B_avg ≈ B_pk for these
    # 1-D-reluctance models.
    B_avg = B_pk

    W = 0.5 * L * (I**2)

    return ReluctanceOutputs(
        L_uH=L * 1e6,
        B_pk_T=abs(B_pk),
        B_avg_T=abs(B_avg),
        energy_J=W,
        R_iron_per_turn=R_iron,
        R_gap_per_turn=R_gap,
        k_fringe=k_fringe,
    )


def _mu_r_from_catalog_AL(core: object, fallback_mu_r: float) -> float:
    """Back-derive μ_r from the catalog's experimental AL_nH value.

    For a closed core (no gap), the inductance per turn² is
    ``AL_nH × 1e-3 = μ_r · μ_0 · Ae / le`` (in H). Solving for μ_r:

        μ_r = AL_nH · 1e-3 · le / (μ_0 · Ae)

    AL is **experimentally measured by the manufacturer** at low
    signal, so it captures the actual operating-condition μ_initial.
    The catalog material's ``mu_initial`` field can be conservative
    (e.g. Ferroxcube 3C90 catalog lists ~1416 here, but the
    datasheet μ_i at 25 °C is 2300 — and AL implies 2300).

    Using AL-derived μ_r makes closed-core L match the catalog
    exactly. For gapped cores we still use this μ_r in the iron
    reluctance term; the gap reluctance dominates anyway when
    lgap > 0.1 mm so the iron μ_r matters less.

    Returns ``fallback_mu_r`` when AL isn't populated or yields a
    nonsensical value (negative, zero, or > 1e6).
    """
    AL = getattr(core, "AL_nH", None)
    Ae = getattr(core, "Ae_mm2", None)
    le = getattr(core, "le_mm", None)
    if AL is None or Ae is None or le is None:
        return fallback_mu_r
    AL = float(AL or 0)
    Ae = float(Ae or 0)
    le = float(le or 0)
    if AL <= 0 or Ae <= 0 or le <= 0:
        return fallback_mu_r
    # AL is for the AS-SHIPPED core, including any catalog gap. Cores
    # shipped pre-gapped (catalog lgap_mm > 0) have AL that ALREADY
    # accounts for the gap. We back-derive μ_r assuming the AL was
    # measured on the closed equivalent — only valid for ungapped
    # catalog entries.
    catalog_gap = float(getattr(core, "lgap_mm", 0.0) or 0.0)
    if catalog_gap > 0:
        return fallback_mu_r
    mu0 = 4 * math.pi * 1e-7
    L_per_turn_H = AL * 1e-9
    mu_r_implied = L_per_turn_H * (le * 1e-3) / (mu0 * Ae * 1e-6)
    if mu_r_implied <= 0 or mu_r_implied > 1_000_000:
        return fallback_mu_r
    return mu_r_implied


def solve_reluctance_from_core(
    *,
    core: object,
    material: object,
    n_turns: int,
    current_A: float = 1.0,
    gap_mm: Optional[float] = None,
    apply_dc_bias_rolloff: bool = True,
    fringing_model: str = "roters",
    use_catalog_AL: bool = True,
) -> ReluctanceOutputs:
    """Adapter from catalog Core+Material to ``ReluctanceOutputs``.

    Mirrors the toroidal solver's calling convention.

    Parameters
    ----------
    use_catalog_AL:
        When ``True`` (default), back-derive ``μ_r`` from the catalog's
        ``AL_nH`` value (experimentally measured) so closed-core L
        matches manufacturer data exactly. When ``False``, use the
        material's ``mu_initial`` directly — useful for what-if
        studies where the user wants to model a non-catalog material.
    """
    # Fast path: when the catalog ships an ``AL_nH`` value AND the
    # caller hasn't overridden the gap, just use the manufacturer-
    # measured AL × N². This matches the analytical engine's
    # ``inductance_uH(N, AL, mu_pct)`` exactly and is the right answer
    # for any catalog core (closed or gapped) at the operating
    # condition the manufacturer measured. The reluctance model is a
    # fallback for catalog entries without AL or when the user wants
    # a non-catalog gap.
    AL_catalog = getattr(core, "AL_nH", None)
    user_overrode_gap = gap_mm is not None
    if use_catalog_AL and AL_catalog and float(AL_catalog) > 0 and not user_overrode_gap:
        mu_pct = 1.0
        if apply_dc_bias_rolloff and getattr(material, "rolloff", None) is not None:
            from pfc_inductor.fea.direct.physics.saturation import compute_mu_eff_dc_bias

            le_m = float(getattr(core, "le_mm", 0.0) or 0.0) * 1e-3
            if le_m > 0:
                _mu_eff, mu_pct = compute_mu_eff_dc_bias(
                    material=material,
                    n_turns=int(n_turns),
                    current_A=float(current_A),
                    le_m=le_m,
                    fallback_mu_r=1.0,
                )

        Ae_m2 = float(getattr(core, "Ae_mm2", 0.0) or 0.0) * 1e-6
        L_H = float(AL_catalog) * 1e-9 * (int(n_turns) ** 2) * mu_pct
        # B_pk = L·I / (N·Ae) — same expression the analytical
        # engine uses (energy + flux balance).
        if int(n_turns) > 0 and Ae_m2 > 0:
            B_pk = L_H * float(current_A) / (int(n_turns) * Ae_m2)
        else:
            B_pk = 0.0

        return ReluctanceOutputs(
            L_uH=L_H * 1e6,
            B_pk_T=abs(B_pk),
            B_avg_T=abs(B_pk),
            energy_J=0.5 * L_H * (float(current_A) ** 2),
            R_iron_per_turn=0.0,
            R_gap_per_turn=0.0,
            k_fringe=1.0,
            method="catalog_AL",
        )

    Ae = float(getattr(core, "Ae_mm2", 0.0) or 0.0)
    le = float(getattr(core, "le_mm", 0.0) or 0.0)
    if Ae <= 0 or le <= 0:
        raise ValueError(
            f"Core {getattr(core, 'id', '?')} missing Ae/le — "
            f"can't run analytical reluctance solver"
        )

    # Center-leg width: from FEMMT db lookup if possible, else
    # fall back to sqrt(Ae) (square approximation).
    from pfc_inductor.fea.direct.models import EICoreDims

    try:
        dims = EICoreDims.from_core(core)
        cl_w_mm = dims.center_leg_w_mm
    except Exception:
        cl_w_mm = math.sqrt(Ae)

    mu_r_initial = float(
        getattr(material, "mu_r", None)
        or getattr(material, "mu_r_initial", None)
        or getattr(material, "mu_initial", None)
        or 1.0
    )

    # Calibrate μ_r against catalog AL when available.
    if use_catalog_AL:
        mu_r_initial = _mu_r_from_catalog_AL(core, mu_r_initial)

    mu_r = mu_r_initial
    if apply_dc_bias_rolloff and getattr(material, "rolloff", None) is not None:
        # Powder cores: Magnetics-style μ(H) rolloff.
        from pfc_inductor.fea.direct.physics.saturation import compute_mu_eff_dc_bias

        _mu_unused, mu_pct = compute_mu_eff_dc_bias(
            material=material,
            n_turns=int(n_turns),
            current_A=float(current_A),
            le_m=le * 1e-3,
            fallback_mu_r=mu_r_initial,
        )
        mu_r = mu_r_initial * mu_pct
    elif apply_dc_bias_rolloff:
        # Ferrite (no rolloff curve, has Bsat): apply the tanh
        # soft-knee saturation factor ONLY for closed-core operation
        # (no gap). Gapped cores rely on the gap to keep B in the
        # linear region and don't need the knee. Phase 3.1 acceptance
        # focuses on B vs I up to 1.3·Bsat, which only happens on
        # closed cores or severe over-current cases.
        catalog_lgap = float(getattr(core, "lgap_mm", 0.0) or 0.0)
        effective_lgap = float(gap_mm) if gap_mm is not None else catalog_lgap
        Bsat = float(
            getattr(material, "Bsat_100C_T", None) or getattr(material, "Bsat_25C_T", None) or 0.0
        )
        if effective_lgap == 0 and Bsat > 0:
            from pfc_inductor.fea.direct.physics.saturation import (
                ferrite_saturation_factor,
            )

            mu0 = 4 * math.pi * 1e-7
            # Closed-circuit B estimate (no gap → μ_initial dominates)
            B_estimate = mu_r_initial * mu0 * int(n_turns) * float(current_A) / (le * 1e-3)
            knee_factor = ferrite_saturation_factor(
                B_T=B_estimate, B_sat_T=Bsat, knee_sharpness=5.0
            )
            mu_r = mu_r_initial * knee_factor

    # Effective gap: explicit override → catalog lgap_mm → 0
    if gap_mm is not None:
        lgap = float(gap_mm)
    else:
        lgap = float(getattr(core, "lgap_mm", 0.0) or 0.0)

    return solve_reluctance(
        ReluctanceInputs(
            Ae_mm2=Ae,
            le_mm=le,
            center_leg_w_mm=cl_w_mm,
            mu_r_core=mu_r,
            n_turns=int(n_turns),
            current_A=float(current_A),
            lgap_mm=lgap,
            fringing_model=fringing_model,
        )
    )


__all__ = [
    "ReluctanceInputs",
    "ReluctanceOutputs",
    "fringing_factor_roters",
    "solve_reluctance",
    "solve_reluctance_from_core",
]
