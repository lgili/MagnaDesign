"""Dowell-style analytical AC resistance for round-wire windings.

Phase 2.8 — bridges the gap between DC resistance (trivial) and
full AC harmonic FEM (Phase 2.2 stranded model, still under
calibration). For PFC inductors at 50–300 kHz with AWG18-24 wire
in 1-5 layers, Dowell's closed-form is accurate to ±15 % vs full
FEM and ±10 % vs measurement.

The formula
===========

Dowell (1966) for an m-layer winding of round conductors:

    F_R = ξ · [ Re_1(ξ) + (2/3)·(m² - 1)·Re_2(ξ) ]

where:

::

    Re_1(ξ) = (sinh(2ξ) + sin(2ξ)) / (cosh(2ξ) - cos(2ξ))
    Re_2(ξ) = (sinh(ξ)  - sin(ξ))  / (cosh(ξ)  + cos(ξ))

and ``ξ = h_eff / δ`` with:

- ``h_eff = π/4 · d_cu · η`` — porosity-corrected effective
  conductor thickness (the "equivalent foil" Dowell uses to map
  round wires onto his layered-foil derivation)
- ``δ = sqrt(2/(ω·μ_0·σ))`` — copper skin depth
- ``η = d_cu / pitch`` — packing density along the winding axis
- ``m`` — number of layers in the bobbin

For ``m = 1`` (single-layer), the proximity term vanishes and we're
left with the skin-effect-only ``F_R = ξ · Re_1(ξ)`` ≥ 1.

Inputs are deliberately simple — N, wire diameter, layer count.
The cascade Tier 3 (or any caller) gets ``F_R(f)`` cheaply and
multiplies by ``R_dc`` to get the AC resistance.

When this is *not* the right model
==================================

- Litz wire — see ``litz_homogenized.py`` (Phase 2.3, pending)
- Foil winding — see foil module (Phase 2.4, pending)
- Wire bundles where the inter-strand field varies along the
  axis (very tall bobbins): use the AC harmonic FEM instead.

Dowell assumes the field penetrates each conductor in 1-D
parallel to the winding axis. That's a great approximation for
typical wound inductors; breaks down for ironless or
"non-rectangular" coil layouts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class DowellOutputs:
    """Result of a Dowell AC-resistance evaluation."""

    F_R: float
    """AC-to-DC resistance ratio (``R_ac / R_dc``). ``≥ 1.0``."""

    R_ac_mOhm: float
    """Total AC winding resistance at the given frequency (mΩ)."""

    R_dc_mOhm: float
    """DC resistance for context (mΩ)."""

    skin_depth_mm: float
    """Skin depth at the operating frequency (mm)."""

    xi: float
    """Dowell's nondimensional parameter ξ = h_eff/δ."""

    n_layers: int
    """Number of winding layers used in the formula."""


def skin_depth_m(
    *,
    frequency_Hz: float,
    conductivity_Spm: float = 5.96e7,
    mu_r: float = 1.0,
) -> float:
    """Classical skin depth for a conductor at the given frequency.

    Default σ = 5.96e7 S/m (annealed Cu @ 20 °C). For aluminium
    pass σ = 3.5e7. The non-magnetic μ_r=1 default applies to all
    standard winding conductors.
    """
    mu0 = 4 * math.pi * 1e-7
    omega = 2 * math.pi * frequency_Hz
    return math.sqrt(2.0 / (omega * conductivity_Spm * (mu0 * mu_r)))


def dowell_fr(
    *,
    wire_diameter_m: float,
    n_layers: int,
    frequency_Hz: float,
    porosity_eta: float = 0.83,
    conductivity_Spm: float = 5.96e7,
) -> tuple[float, float]:
    """Dowell's ``F_R`` ratio for a round-wire winding.

    Parameters
    ----------
    wire_diameter_m:
        Copper-conductor diameter in metres (exclude enamel).
    n_layers:
        Number of layers in the winding (``m`` in Dowell's paper).
        For toroid: count the winding layers around the bobbin;
        for bobbin-wound: count the rows.
    frequency_Hz:
        Excitation frequency.
    porosity_eta:
        Packing density along the winding axis. ``= d_cu / pitch``.
        For tightly-wound enamel wire: ~ 0.83-0.90. For Litz or
        loose winding: lower.
    conductivity_Spm:
        Copper conductivity (S/m). 5.96e7 at 20 °C. Drops with T
        (~0.4%/K) — the cascade passes a temperature-corrected value.

    Returns
    -------
    (F_R, xi)
        F_R ≥ 1 (skin + proximity factor), and ξ for diagnostics.
    """
    if wire_diameter_m <= 0:
        raise ValueError(f"wire_diameter_m must be positive (got {wire_diameter_m})")
    if frequency_Hz <= 0:
        raise ValueError(f"frequency_Hz must be positive (got {frequency_Hz})")
    if n_layers < 1:
        raise ValueError(f"n_layers must be ≥ 1 (got {n_layers})")
    if not (0 < porosity_eta <= 1.0):
        raise ValueError(f"porosity_eta must be in (0, 1] (got {porosity_eta})")

    delta = skin_depth_m(frequency_Hz=frequency_Hz, conductivity_Spm=conductivity_Spm)
    h_eff = (math.pi / 4.0) * wire_diameter_m * porosity_eta
    xi = h_eff / delta

    # Guard against numerical overflow at very high frequencies
    # (ξ > ~30 means F_R is essentially ξ; cosh/sinh saturate).
    if xi > 30.0:
        return xi, xi
    if xi < 1e-4:
        # Low-frequency limit: F_R → 1.
        return 1.0, xi

    sh2 = math.sinh(2.0 * xi)
    si2 = math.sin(2.0 * xi)
    ch2 = math.cosh(2.0 * xi)
    co2 = math.cos(2.0 * xi)
    sh1 = math.sinh(xi)
    si1 = math.sin(xi)
    ch1 = math.cosh(xi)
    co1 = math.cos(xi)

    re_skin = (sh2 + si2) / (ch2 - co2)
    re_prox = (sh1 - si1) / (ch1 + co1)
    F_R = xi * (re_skin + (2.0 / 3.0) * (n_layers**2 - 1) * re_prox)
    return F_R, xi


def evaluate_ac_resistance(
    *,
    n_turns: int,
    wire_diameter_m: float,
    n_layers: int,
    mlt_mm: float,
    frequency_Hz: float,
    T_winding_C: float = 25.0,
    porosity_eta: float = 0.83,
) -> DowellOutputs:
    """One-shot evaluator: ``(R_dc, F_R, R_ac, skin_depth, ξ)``.

    For PFC inductors at switching frequency.
    """
    # Copper resistivity at temperature (ρ_20 = 1.68e-8 Ω·m)
    rho_20 = 1.68e-8
    alpha = 3.93e-3
    rho_T = rho_20 * (1 + alpha * (T_winding_C - 20))
    sigma_T = 1.0 / rho_T

    # DC resistance
    wire_area_m2 = math.pi * (wire_diameter_m**2) / 4.0
    wire_length_m = float(n_turns) * float(mlt_mm) * 1e-3
    R_dc_Ohm = rho_T * wire_length_m / wire_area_m2

    F_R, xi = dowell_fr(
        wire_diameter_m=wire_diameter_m,
        n_layers=n_layers,
        frequency_Hz=frequency_Hz,
        porosity_eta=porosity_eta,
        conductivity_Spm=sigma_T,
    )
    R_ac_Ohm = R_dc_Ohm * F_R
    delta_m = skin_depth_m(frequency_Hz=frequency_Hz, conductivity_Spm=sigma_T)

    return DowellOutputs(
        F_R=F_R,
        R_ac_mOhm=R_ac_Ohm * 1e3,
        R_dc_mOhm=R_dc_Ohm * 1e3,
        skin_depth_mm=delta_m * 1e3,
        xi=xi,
        n_layers=n_layers,
    )


def dowell_fr_litz(
    *,
    strand_diameter_m: float,
    n_strands: int,
    n_layers: int,
    frequency_Hz: float,
    porosity_eta: float = 0.65,
    conductivity_Spm: float = 5.96e7,
) -> tuple[float, float]:
    """Dowell's F_R extended for Litz wire (Albach / Tourkhani).

    For a Litz bundle with ``n_strands`` of individually-insulated
    strands of diameter ``d_strand``, the formula generalises:

    ::

        ξ_strand = (π/4) · d_strand · η_strand / δ
        F_R = ξ_strand · [Re_1 + (2/3)·(n_strands² · n_layers² - 1)·Re_2]

    The key insight: each strand sees the proximity field from
    EVERY other strand in the bundle, not just same-layer strands.
    For ``n_strands × n_layers`` total "equivalent layers" the
    proximity term grows as the square of that product.

    Critical condition for good Litz performance:
    ``d_strand < δ × √2`` (strand diameter less than skin depth);
    otherwise the strand itself shows skin effect and Litz buys
    little over solid wire.

    Returns
    -------
    (F_R, xi_strand)
    """
    if strand_diameter_m <= 0:
        raise ValueError("strand_diameter_m must be positive")
    if n_strands < 1:
        raise ValueError("n_strands must be ≥ 1")
    if n_layers < 1:
        raise ValueError("n_layers must be ≥ 1")

    delta = skin_depth_m(frequency_Hz=frequency_Hz, conductivity_Spm=conductivity_Spm)
    h_eff = (math.pi / 4.0) * strand_diameter_m * porosity_eta
    xi = h_eff / delta

    if xi > 30.0:
        return xi, xi
    if xi < 1e-4:
        return 1.0, xi

    sh2 = math.sinh(2.0 * xi)
    si2 = math.sin(2.0 * xi)
    ch2 = math.cosh(2.0 * xi)
    co2 = math.cos(2.0 * xi)
    sh1 = math.sinh(xi)
    si1 = math.sin(xi)
    ch1 = math.cosh(xi)
    co1 = math.cos(xi)

    re_skin = (sh2 + si2) / (ch2 - co2)
    re_prox = (sh1 - si1) / (ch1 + co1)
    # Effective layer count: each strand sees all other strands' fields
    n_eff_layers = n_strands * n_layers
    F_R = xi * (re_skin + (2.0 / 3.0) * (n_eff_layers**2 - 1) * re_prox)
    return F_R, xi


def dowell_fr_foil(
    *,
    foil_thickness_m: float,
    n_turns: int,
    frequency_Hz: float,
    conductivity_Spm: float = 5.96e7,
) -> tuple[float, float]:
    """Ferreira's F_R for foil-wound transformers / inductors.

    For a foil winding of ``n_turns`` layers, each layer of
    thickness ``h``, the Ferreira approximation:

    ::

        Δ = h / δ                       (foil-thickness / skin-depth)
        F_R = Δ · [(sinh(2Δ) + sin(2Δ))/(cosh(2Δ) - cos(2Δ))
                 + (2/3)·(m² - 1)·(sinh(Δ) - sin(Δ))/(cosh(Δ) + cos(Δ))]

    Same hyperbolic kernels as Dowell's round-wire form; the only
    difference is the porosity factor is 1.0 (foil fills the layer
    width entirely) and ``h_eff = h`` directly.

    Foil windings are common in switching transformers where
    high-current secondaries benefit from low DC resistance.
    """
    if foil_thickness_m <= 0:
        raise ValueError("foil_thickness_m must be positive")
    if n_turns < 1:
        raise ValueError("n_turns must be ≥ 1")

    delta = skin_depth_m(frequency_Hz=frequency_Hz, conductivity_Spm=conductivity_Spm)
    xi = foil_thickness_m / delta

    if xi > 30.0:
        return xi, xi
    if xi < 1e-4:
        return 1.0, xi

    sh2 = math.sinh(2.0 * xi)
    si2 = math.sin(2.0 * xi)
    ch2 = math.cosh(2.0 * xi)
    co2 = math.cos(2.0 * xi)
    sh1 = math.sinh(xi)
    si1 = math.sin(xi)
    ch1 = math.cosh(xi)
    co1 = math.cos(xi)

    re_skin = (sh2 + si2) / (ch2 - co2)
    re_prox = (sh1 - si1) / (ch1 + co1)
    F_R = xi * (re_skin + (2.0 / 3.0) * (n_turns**2 - 1) * re_prox)
    return F_R, xi


__all__ = [
    "DowellOutputs",
    "dowell_fr",
    "dowell_fr_foil",
    "dowell_fr_litz",
    "evaluate_ac_resistance",
    "skin_depth_m",
]
