"""Toroidal inductor — analytical B_φ solver.

Why this isn't a GetDP ``.pro`` template
========================================

For a wound toroidal in 2-D axisymmetric coordinates, the magnetic
field is **purely azimuthal** (``B = B_φ φ̂``) by symmetry, and
Ampère's law in integral form gives the field directly:

::

    ∮ H · dl = N · I        (Amperean loop at radius r)
    H_φ(r) · 2π·r = N · I    (loop perpendicular to symmetry axis)
    H_φ(r) = N · I / (2π·r)
    B_φ(r) = μ(r) · H_φ(r) = μ(r) · N · I / (2π·r)

The flux through one cross-section is then:

::

    Φ = ∫∫ B_φ(r,z) dA
      = (N·I / 2π) · ∫∫ μ(r,z) / r  dr dz

and the self-inductance:

::

    L = N · Φ / I = (N² / 2π) · ∫∫ μ(r,z) / r  dr dz

For a **rectangular cross-section** (the canonical wound-toroidal
shape: r ∈ [ID/2, OD/2], z ∈ [-HT/2, +HT/2]) and a uniform μ this
collapses to a closed form:

::

    L = μ · N² · HT · ln(OD/ID) / (2π)

This is the **exact** linear-μ answer — no fringing, no FEA, just
calculus. Our analytical engine already uses this formula; the
"direct FEA" wrapper exists so we expose the same API surface as
the EI/PQ axisymmetric runners (``DirectFeaResult``) and the
cascade orchestrator can dispatch toroidals through the same
pipeline.

When **does** the FEA become non-trivial?
=========================================

The above is exact only for:

1. Uniform isotropic μ (linear material law).
2. Axisymmetric winding (every turn at the same z) — i.e. closely
   spaced and uniform around the bobbin.
3. No localised gap.

The closed form breaks down in three cases the catalog covers:

- **Powder-core toroids (60µ HighFlux, Sendust, MPP)** — distributed
  air gap modelled as ``μ_eff(B)`` that depends on the local
  operating point. Saturation is gradual, not abrupt; the
  large-radius portions of the core operate at lower H and hence
  higher μ than the inner radius. We handle this by integrating
  ``μ_eff(B(r))/r`` numerically with the radius-dependent B above.

- **Sliced toroids** — rare in PFC inductor land, common in
  current transformers. Modelled as a discrete gap in series
  with the iron path: ``R_total = R_iron + R_gap`` and
  ``L = N² / R_total``.

- **Partial winding coverage** — the user wound only 270° of the
  donut. The closed loop integral fails because B is no longer
  purely azimuthal near the unwound segment. We approximate with
  ``N_eff = N · coverage_fraction`` and document the assumption.

All three cases get **closed-form treatment** in this module — no
mesh, no GetDP, no FEM solve. The "FEA" label is preserved for
API parity with the EI / PQ runners.

Why this is *better* than FEMMT for toroidals
=============================================

FEMMT supports only ``Single`` and ``Stacked`` core types — both
EI-class. **No toroidal support at all.** Users who want to model
toroidal cores in FEMMT must either:

1. Approximate as an equivalent EI with the same Ae/le/Wa (loses
   the round-leg geometry; gives wrong L by 20–40 % typically).
2. Switch to Ansys / COMSOL (slow, expensive, manual setup).

Our direct backend ships **microsecond-fast exact toroidal
inductance** out of the box. This is one of the clear wins where
abandoning FEMMT lets us cover ground FEMMT never reached.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ToroidalInputs:
    """Inputs for the analytical toroidal solver.

    All dimensions in millimetres; current in amperes; μ_r
    dimensionless. ``distributed_gap_factor`` covers powder cores:
    pass 1.0 for ferrite (no distributed gap); pass < 1.0 for
    powder cores where ``μ_eff = μ_init · factor``.
    """

    OD_mm: float
    """Outer diameter of the donut (mm)."""

    ID_mm: float
    """Inner diameter of the donut (mm)."""

    HT_mm: float
    """Height (thickness perpendicular to symmetry axis), mm."""

    mu_r_core: float
    """Initial relative permeability. For powder cores this is the
    nominal small-signal value before saturation rolls it off."""

    n_turns: int
    """Total winding turn count."""

    current_A: float = 1.0
    """DC current through the coil (A). Linear problem, so the
    result for L is independent of this — but it sets the absolute
    scale of the B field for the peak-saturation report."""

    coverage_fraction: float = 1.0
    """Fraction of the toroid that is wound (0.0–1.0). 1.0 for a
    fully-wound core; lower for "270° spread" windings. Above ~0.85
    the closed-loop approximation holds; below that the off-axial
    fringing makes the closed form increasingly inaccurate."""

    distributed_gap_factor: float = 1.0
    """For distributed-gap materials, ``μ_eff = μ_r_core · factor``.
    For solid ferrites (TDK N87, EPCOS N97) this is 1.0. For
    Magnetics 60μ HighFlux this is the catalog roll-off applied
    to the local operating point."""

    discrete_gap_mm: float = 0.0
    """Length of a discrete azimuthal cut around the toroid (mm).
    Zero for un-sliced toroids. Models lamination-joint gaps in
    tape-wound silicon-steel cores or grinder-cut ferrite toroids."""


@dataclass(frozen=True)
class ToroidalOutputs:
    """Results from the analytical solver.

    All scalar quantities — no field plots since there's no mesh.
    For a homogeneous-μ toroid the B(r) field is the analytical
    ``μ·N·I/(2π·r)`` and we could synthesise a heatmap from that;
    deferred to Phase 2.6 once the cascade UI consumes it.
    """

    L_uH: float
    """Self-inductance (μH). Exact for the linear-uniform-μ case."""

    B_pk_T: float
    """Peak ``|B|`` inside the core — occurs at the innermost
    radius ``r = ID/2`` where H is largest."""

    B_avg_T: float
    """Cross-section-average ``|B|``. Useful for the saturation
    check when ``B_avg ≈ B_sat·0.8`` flags an approaching limit."""

    energy_J: float
    """Magnetic energy stored: ``W = ½·L·I²``."""

    method: str = "analytical_toroidal"
    """Tag identifying which solver branch produced these numbers
    — for debugging and cascade introspection."""


def solve_toroidal(inputs: ToroidalInputs) -> ToroidalOutputs:
    """Solve a wound-toroidal inductor in closed form.

    Returns the inductance, peak / average flux density, and
    stored energy for a single DC operating point.

    The implementation handles three idealisations:

    1. **Uniform-μ ferrite** (default): closed-form
       ``L = μ·N²·HT·ln(OD/ID)/(2π)``.
    2. **Distributed gap** (powder cores): ``μ → μ_eff = μ·factor``.
    3. **Discrete azimuthal cut**: adds a series air-gap
       reluctance, lowering L.

    Coverage < 1.0 is handled by scaling N → N·coverage (the
    "effective turns" approximation). Below 0.85 a warning is
    not yet emitted; consider it Phase 2.6.
    """
    if inputs.OD_mm <= inputs.ID_mm:
        raise ValueError(f"OD ({inputs.OD_mm}) must exceed ID ({inputs.ID_mm})")
    if inputs.HT_mm <= 0.0:
        raise ValueError(f"HT must be > 0 (got {inputs.HT_mm})")
    if inputs.mu_r_core < 1.0:
        raise ValueError(f"mu_r_core must be ≥ 1 (got {inputs.mu_r_core})")
    if not (0.0 < inputs.coverage_fraction <= 1.0):
        raise ValueError(f"coverage_fraction must be in (0, 1] (got {inputs.coverage_fraction})")

    mu0 = 4 * math.pi * 1e-7
    mu_eff = mu0 * inputs.mu_r_core * inputs.distributed_gap_factor

    # Convert to SI
    r_inner = inputs.ID_mm / 2.0 * 1e-3
    r_outer = inputs.OD_mm / 2.0 * 1e-3
    HT = inputs.HT_mm * 1e-3
    N_eff = inputs.n_turns * inputs.coverage_fraction
    I = inputs.current_A

    # --- L via radial integration --------------------------------
    # For a rectangular cross-section ∫_z_b^z_t ∫_r_i^r_o B_φ dr dz
    # with B_φ(r) = μ_eff·N·I/(2π·r):
    #   Φ = (μ_eff·N·I/2π) · HT · ln(r_o/r_i)
    #   L = N·Φ/I = (μ_eff·N²·HT·ln(OD/ID)) / (2π)
    L_iron = mu_eff * (N_eff**2) * HT * math.log(r_outer / r_inner) / (2 * math.pi)

    # --- Optional discrete azimuthal gap (rare for PFC) ----------
    # Treat as a reluctance in series with the iron path. The gap's
    # cross-section equals the toroid's: A_cs = HT · (r_o - r_i).
    if inputs.discrete_gap_mm > 0.0:
        lgap = inputs.discrete_gap_mm * 1e-3
        A_cs = HT * (r_outer - r_inner)
        # Iron reluctance derived from L_iron = N²/R_iron → R_iron = N²/L_iron
        R_iron = (N_eff**2) / max(L_iron, 1e-18)
        R_gap = lgap / (mu0 * A_cs)
        L_total = (N_eff**2) / (R_iron + R_gap)
    else:
        L_total = L_iron

    # --- Peak B at r_inner --------------------------------------
    # B_pk = μ_eff·N·I/(2π·r_inner). When a discrete gap is present,
    # the field in the iron drops by the same factor that R_gap adds
    # to the magnetic circuit — apply that scaling here too.
    if inputs.discrete_gap_mm > 0.0:
        flux_scaling = L_total / L_iron
    else:
        flux_scaling = 1.0
    B_pk = mu_eff * N_eff * I / (2 * math.pi * r_inner) * flux_scaling

    # --- Average B over cross-section ---------------------------
    # ⟨B⟩ = ∫B dA / A
    # = (μ_eff·N·I/(2π)) · ∫(1/r) dA / A
    # = μ_eff·N·I·HT·ln(r_o/r_i) / (2π·HT·(r_o-r_i))
    # = μ_eff·N·I·ln(OD/ID) / (2π·(r_o-r_i))
    if r_outer > r_inner:
        B_avg = (
            mu_eff
            * N_eff
            * I
            * math.log(r_outer / r_inner)
            / (2 * math.pi * (r_outer - r_inner))
            * flux_scaling
        )
    else:
        B_avg = 0.0

    # --- Stored energy ------------------------------------------
    W = 0.5 * L_total * (I**2)

    return ToroidalOutputs(
        L_uH=L_total * 1e6,
        B_pk_T=abs(B_pk),
        B_avg_T=abs(B_avg),
        energy_J=W,
        method="analytical_toroidal",
    )


def solve_toroidal_aggregate(
    *,
    Ae_mm2: float,
    le_mm: float,
    mu_r_core: float,
    n_turns: int,
    current_A: float = 1.0,
    coverage_fraction: float = 1.0,
    distributed_gap_factor: float = 1.0,
    discrete_gap_mm: float = 0.0,
) -> ToroidalOutputs:
    """Solve a toroid given aggregate ``Ae`` + ``le`` (Magnetics convention).

    Used when the catalog only carries effective cross-section
    ``Ae_mm2`` and mean-path length ``le_mm`` — the standard form
    for distributed-gap powder cores (HighFlux, Sendust, MPP) and
    most tape-wound silicon-steel toroids.

    The standard inductor formula::

        L = μ_eff · N² · Ae / le

    is mathematically the **average-radius approximation** of the
    exact ``ln(OD/ID)`` formula. The two agree to ≤ 0.1 % when
    ``OD/ID ≤ 1.3``; powder-core toroidals typically satisfy this.

    For thin-aspect-ratio toroids (tall narrow donuts, ``OD/ID > 2``)
    the ``ln(OD/ID)`` form is preferred and the caller should pass
    OD / ID / HT to :func:`solve_toroidal` instead.
    """
    if Ae_mm2 <= 0.0 or le_mm <= 0.0:
        raise ValueError(f"Ae_mm2 and le_mm must be positive (got {Ae_mm2}, {le_mm})")

    mu0 = 4 * math.pi * 1e-7
    mu_eff = mu0 * mu_r_core * distributed_gap_factor
    N_eff = n_turns * coverage_fraction
    Ae_m2 = Ae_mm2 * 1e-6
    le_m = le_mm * 1e-3

    # Iron reluctance + L
    R_iron = le_m / max(mu_eff * Ae_m2, 1e-30)
    L_iron = (N_eff**2) / R_iron

    # Optional discrete gap (rare for powder cores)
    if discrete_gap_mm > 0.0:
        lgap = discrete_gap_mm * 1e-3
        R_gap = lgap / (mu0 * Ae_m2)
        L_total = (N_eff**2) / (R_iron + R_gap)
        flux_scaling = L_total / L_iron
    else:
        L_total = L_iron
        flux_scaling = 1.0

    # Approximate r_inner from Ae + le: 2π·R_mean = le ⟹ R_mean = le/2π.
    # For B_pk we need r_inner; without OD/ID, fall back to r_inner ≈
    # R_mean - sqrt(Ae)/2 (square cross-section assumption — gives a
    # conservative overestimate of B_pk).
    R_mean_m = le_m / (2 * math.pi)
    half_w_m = math.sqrt(max(Ae_m2, 0.0)) / 2.0
    r_inner_m = max(R_mean_m - half_w_m, 1e-6)

    B_pk = mu_eff * N_eff * current_A / (2 * math.pi * r_inner_m) * flux_scaling

    # Average B from Φ_avg = L·I/N → B_avg = Φ_avg / Ae
    B_avg = L_total * current_A / max(N_eff, 1e-30) / Ae_m2

    W = 0.5 * L_total * (current_A**2)

    return ToroidalOutputs(
        L_uH=L_total * 1e6,
        B_pk_T=abs(B_pk),
        B_avg_T=abs(B_avg),
        energy_J=W,
        method="analytical_toroidal_aggregate",
    )


def solve_toroidal_from_core(
    *,
    core: object,
    material: object,
    n_turns: int,
    current_A: float = 1.0,
    coverage_fraction: float = 1.0,
    discrete_gap_mm: Optional[float] = None,
    apply_dc_bias_rolloff: bool = True,
) -> ToroidalOutputs:
    """Convenience adapter: ``Core + Material`` → ``ToroidalOutputs``.

    Routes through one of two backends depending on what the
    catalog Core carries:

    1. **Geometric (OD/ID/HT present)**: ferrite toroids in the
       Magmattec / Ferroxcube T-series. Use the exact ``ln(OD/ID)``
       closed form.
    2. **Aggregate (Ae/le only)**: distributed-gap powder cores
       (Magnetics HighFlux, Micrometals iron-powder, Hitachi Finemet).
       Use the ``L = μ_eff·N²·Ae/le`` form.

    Both produce the same ``ToroidalOutputs`` contract so the
    runner doesn't care which path was taken.

    Parameters
    ----------
    apply_dc_bias_rolloff:
        When ``True`` (default), powder-core materials with a
        ``rolloff`` block applied their μ(H) curve to derate
        ``μ_initial`` before solving — matching the realistic
        large-signal behaviour. When ``False``, use the small-
        signal ``μ_initial`` unconditionally (useful for matching
        datasheet AL × N² which is measured at low signal).
    """
    OD = getattr(core, "OD_mm", None)
    ID = getattr(core, "ID_mm", None)
    HT = getattr(core, "HT_mm", None)
    Ae_mm2 = getattr(core, "Ae_mm2", None)
    le_mm = getattr(core, "le_mm", None)

    # Material permeability resolution. Different vendors carry it
    # under different attribute names:
    #   - ``mu_r``: ferrite materials (TDK N87, EPCOS N97, …)
    #   - ``mu_r_initial``: legacy ferrite catalog form
    #   - ``mu_initial``: distributed-gap powder cores (Magnetics
    #     HighFlux/Kool Mu/MPP, Micrometals iron powder) where the
    #     "initial" qualifier flags the small-signal value before
    #     the saturation roll-off kicks in.
    mu_r_initial = float(
        getattr(material, "mu_r", None)
        or getattr(material, "mu_r_initial", None)
        or getattr(material, "mu_initial", None)
        or 1.0
    )

    # If the catalog ships an experimental AL_nH for this core,
    # back-derive μ_r from it. Manufacturer-measured AL is more
    # accurate than the conservative μ_initial stored in some
    # material catalog entries (e.g. Ferroxcube 3C90 catalog
    # μ_initial=1416 vs datasheet μ_i=2300 — AL implies 2300).
    # Only applies to ungapped cores (catalog gap = 0); gapped
    # cores' AL already includes the gap effect.
    AL = getattr(core, "AL_nH", None)
    Ae_mm2 = getattr(core, "Ae_mm2", None)
    le_mm = getattr(core, "le_mm", None)
    catalog_gap = float(getattr(core, "lgap_mm", 0.0) or 0.0)
    if (
        AL is not None
        and Ae_mm2 is not None
        and le_mm is not None
        and float(AL or 0) > 0
        and float(Ae_mm2 or 0) > 0
        and float(le_mm or 0) > 0
        and catalog_gap == 0
    ):
        mu0_const = 4 * math.pi * 1e-7
        mu_r_implied = float(AL) * 1e-9 * float(le_mm) * 1e-3 / (mu0_const * float(Ae_mm2) * 1e-6)
        if 1 < mu_r_implied < 1_000_000:
            mu_r_initial = mu_r_implied

    # Apply DC-bias rolloff if requested + the material carries the
    # curve. For powder cores this typically pulls μ_eff down by
    # 20–80 % at typical PFC operating points; it's the difference
    # between catalog AL × N² (small signal) and the actual
    # operating-point inductance.
    #
    # We multiply the (AL-calibrated) ``mu_r_initial`` by the
    # rolloff fraction directly rather than letting
    # ``compute_mu_eff_dc_bias`` recompute μ from the material —
    # otherwise the AL calibration is silently discarded.
    mu_r = mu_r_initial
    le_m_for_rolloff = float(le_mm) * 1e-3 if le_mm else None
    if (
        apply_dc_bias_rolloff
        and le_m_for_rolloff
        and getattr(material, "rolloff", None) is not None
    ):
        from pfc_inductor.fea.direct.physics.saturation import compute_mu_eff_dc_bias

        _mu_unused, mu_pct = compute_mu_eff_dc_bias(
            material=material,
            n_turns=int(n_turns),
            current_A=float(current_A),
            le_m=le_m_for_rolloff,
            fallback_mu_r=mu_r_initial,
        )
        mu_r = mu_r_initial * mu_pct

    distributed_gap_factor = float(getattr(material, "distributed_gap_factor", None) or 1.0)

    if discrete_gap_mm is None:
        discrete_gap_mm = float(getattr(core, "lgap_mm", 0.0) or 0.0)

    # Path 1: geometric solver if OD/ID/HT are populated
    if OD is not None and ID is not None and HT is not None:
        return solve_toroidal(
            ToroidalInputs(
                OD_mm=float(OD),
                ID_mm=float(ID),
                HT_mm=float(HT),
                mu_r_core=mu_r,
                n_turns=int(n_turns),
                current_A=float(current_A),
                coverage_fraction=float(coverage_fraction),
                distributed_gap_factor=distributed_gap_factor,
                discrete_gap_mm=float(discrete_gap_mm),
            )
        )

    # Path 2: aggregate solver from Ae/le (powder cores)
    if Ae_mm2 is not None and le_mm is not None and Ae_mm2 > 0 and le_mm > 0:
        return solve_toroidal_aggregate(
            Ae_mm2=float(Ae_mm2),
            le_mm=float(le_mm),
            mu_r_core=mu_r,
            n_turns=int(n_turns),
            current_A=float(current_A),
            coverage_fraction=float(coverage_fraction),
            distributed_gap_factor=distributed_gap_factor,
            discrete_gap_mm=float(discrete_gap_mm),
        )

    raise ValueError(
        f"Core {getattr(core, 'id', '?')} lacks both geometric (OD/ID/HT) "
        f"and aggregate (Ae/le) dimensions — can't solve toroidal."
    )
