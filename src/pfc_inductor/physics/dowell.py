"""AC resistance for round wire / Litz via Dowell-Ferreira approximations.

References:
- P.L. Dowell, "Effects of eddy currents in transformer windings", Proc. IEE, 1966.
- J.A. Ferreira, "Improved analytical modeling of conductive losses in
  magnetic components", IEEE Trans. PE, 1994 (round-wire form).

Skin depth in copper: delta = sqrt(rho / (pi * f * mu0)), with rho_cu(20C) = 1.724e-8 ohm.m.
"""

from __future__ import annotations

import math

MU_0 = 4 * math.pi * 1e-7
RHO_CU_20C = 1.724e-8  # ohm.m


def rho_cu(T_C: float) -> float:
    """Copper resistivity vs temperature (linear, alpha = 0.00393/K)."""
    return RHO_CU_20C * (1 + 0.00393 * (T_C - 20.0))


def skin_depth_m(f_Hz: float, T_C: float = 20.0) -> float:
    if f_Hz <= 0:
        return float("inf")
    return math.sqrt(rho_cu(T_C) / (math.pi * f_Hz * MU_0))


def Rac_over_Rdc_round(d_cu_m: float, f_Hz: float, layers: int = 1, T_C: float = 20.0) -> float:
    """AC resistance ratio for a single round conductor in a winding.

    Uses Ferreira's closed-form approximation extending Dowell to round wires.
    `layers` accounts for proximity in multi-layer windings (m in Dowell).
    For most PFC toroid windings on powder cores (single-layer-ish), use layers=1
    or the actual layer count derived from window geometry.
    """
    if f_Hz <= 0 or d_cu_m <= 0:
        return 1.0
    delta = skin_depth_m(f_Hz, T_C)
    # Dowell uses xi = (d/delta) * sqrt(pi/4) * sqrt(eta) where eta is porosity.
    # Use porosity = 0.9 default for round wire close-packed.
    eta = 0.9
    xi = (d_cu_m / delta) * math.sqrt(math.pi / 4.0) * math.sqrt(eta)

    sinh2x = math.sinh(2 * xi)
    sin2x = math.sin(2 * xi)
    cosh2x = math.cosh(2 * xi)
    cos2x = math.cos(2 * xi)

    den_skin = max(cosh2x - cos2x, 1e-30)
    den_prox = max(cosh2x + cos2x, 1e-30)

    F_R = xi * (sinh2x + sin2x) / den_skin
    G_R = xi * (sinh2x - sin2x) / den_prox

    m = max(layers, 1)
    Fr = F_R + (2.0 / 3.0) * (m * m - 1) * G_R
    return max(Fr, 1.0)


def Rac_over_Rdc_litz(
    d_strand_m: float,
    n_strands: int,
    f_Hz: float,
    layers_bundle: int = 1,
    T_C: float = 20.0,
) -> float:
    """AC/DC ratio for Litz: skin effect at strand level (per strand) plus
    proximity from external field on the bundle.

    Simplified model: each strand sees the same external H, no internal proximity
    (Litz is twisted to randomize position). Good for fsw < ~200 kHz.
    """
    if d_strand_m <= 0 or f_Hz <= 0:
        return 1.0
    delta = skin_depth_m(f_Hz, T_C)
    xi_s = (d_strand_m / delta) * math.sqrt(math.pi / 4.0)

    sinh2x = math.sinh(2 * xi_s)
    sin2x = math.sin(2 * xi_s)
    cosh2x = math.cosh(2 * xi_s)
    cos2x = math.cos(2 * xi_s)

    den_skin = max(cosh2x - cos2x, 1e-30)
    den_prox = max(cosh2x + cos2x, 1e-30)

    F_R = xi_s * (sinh2x + sin2x) / den_skin
    G_R = xi_s * (sinh2x - sin2x) / den_prox

    m = max(layers_bundle, 1)
    Fr = F_R + (2.0 / 3.0) * (m * m - 1) * G_R / max(n_strands, 1)
    return max(Fr, 1.0)
