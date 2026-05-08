"""DC bias permeability rolloff for powder cores.

Magnetics Inc publishes the relation
    mu_pct(H) = 1 / (a + b * H^c)
with H in Oersted (Oe), valid for each material/permeability grade.
This is reproduced here. Other vendors' rolloffs can be fitted to the same form.

Also provides anhysteretic B(H) — the static, single-valued B–H curve — by
integrating the small-signal permeability over H. Used for the operating-loop
visualization at the design point.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import ArrayLike

from pfc_inductor.models import Material

OE_PER_AM = 1.0 / 79.5774715459  # 1 A/m = this many Oe
MU_0 = 4.0 * math.pi * 1e-7  # T·m/A


def H_from_NI(N: int, I_A: float, le_mm: float, units: str = "Oe") -> float:
    """Magnetic field strength H = N*I/le.

    Parameters
    ----------
    N : turn count
    I_A : current (A)
    le_mm : magnetic path length (mm)
    units : 'Oe' or 'A/m'
    """
    le_m = le_mm * 1e-3
    H_am = N * I_A / le_m
    if units == "A/m":
        return H_am
    return H_am * OE_PER_AM


def mu_pct(material: Material, H_Oe: float) -> float:
    """Effective permeability fraction (1.0 = full nominal mu) at given DC bias H.

    Returns 1.0 for materials without rolloff data (ferrites/nano: gap dominates).
    """
    if material.rolloff is None:
        return 1.0
    a, b, c = material.rolloff.a, material.rolloff.b, material.rolloff.c
    H = max(H_Oe, 1e-6)
    val = 1.0 / (a + b * (H**c))
    return max(0.0, min(1.0, val))


def AL_effective_nH(AL_nominal_nH: float, mu_fraction: float) -> float:
    """Effective inductance index after rolloff."""
    return AL_nominal_nH * mu_fraction


def inductance_uH(N: int, AL_nH: float, mu_fraction: float = 1.0) -> float:
    """L [uH] = N^2 * AL [nH] * mu_fraction / 1000."""
    return (N * N * AL_nH * mu_fraction) * 1e-3


def B_dc_T(N: int, I_dc_A: float, AL_nH: float, Ae_mm2: float, mu_fraction: float = 1.0) -> float:
    """Peak DC flux density B = L*I / (N*Ae)."""
    L_H = inductance_uH(N, AL_nH, mu_fraction) * 1e-6
    Ae_m2 = Ae_mm2 * 1e-6
    if N == 0 or Ae_m2 == 0:
        return 0.0
    return L_H * I_dc_A / (N * Ae_m2)


def L_at_current_uH(
    material: Material,
    *,
    N: int,
    I_A: float,
    AL_nH: float,
    le_mm: float,
    Ae_mm2: float,
) -> float:
    """Differential inductance L(I) [µH] using the best available
    saturation model.

    Two paths:

    1. **Material with published rolloff curve** (powder cores like
       Magnetics 60 / 60-HighFlux / Kool-Mu, Mn-Zn ferrites with
       fitted μ%(H) tables). The vendor's per-grade rolloff
       polynomial gives μ%(H) directly:

           L = AL · N² · μ%(H_pk)

    2. **Material without rolloff data** (silicon-steel laminations,
       amorphous, nanocrystalline cores). Fall back to the
       analytical ``sech²`` differential-inductance model derived
       from a tanh saturation B(H):

           B_lin(I)   = L_lin · I / (N · A_e)        [linear extrap]
           L_diff(I)  = L_lin · sech²(B_lin / Bsat)

       with ``L_lin = AL · N²`` (zero-bias inductance, gap-set for
       silicon-steel). The model:

       - Reduces to ``L_lin`` when B_lin << Bsat (linear region).
       - Drops smoothly through the saturation knee.
       - Asymptotes to zero as B_lin >> Bsat. (In reality it would
         asymptote to the air-gap inductance; the model is a touch
         pessimistic deep in saturation but the cliff location is
         the visualisation's whole point and that is correct.)

    For very large arguments ``cosh`` overflows ``float``; we clamp
    the exponent so the curve flatlines at zero past 30·Bsat
    rather than raising.
    """
    if N <= 0 or AL_nH <= 0:
        return 0.0
    L_lin_uH = inductance_uH(N, AL_nH, 1.0)
    if material.rolloff is not None:
        H_Oe = H_from_NI(N, I_A, le_mm, units="Oe")
        return inductance_uH(N, AL_nH, mu_pct(material, H_Oe))
    # No rolloff — analytical sech² fallback.
    Bsat = max(material.Bsat_100C_T, 1e-6)
    Ae_m2 = max(Ae_mm2 * 1e-6, 1e-12)
    B_lin = (L_lin_uH * 1e-6) * I_A / (N * Ae_m2)
    arg = abs(B_lin) / Bsat
    if arg > 30.0:
        return 0.0
    sech2 = 1.0 / (math.cosh(arg) ** 2)
    return L_lin_uH * sech2


def mu_pct_array(material: Material, H_Oe_arr: ArrayLike) -> np.ndarray:
    """Vectorized version of `mu_pct` for an array of H values."""
    H = np.maximum(np.abs(np.asarray(H_Oe_arr, dtype=float)), 1e-6)
    if material.rolloff is None:
        return np.ones_like(H)
    a, b, c = material.rolloff.a, material.rolloff.b, material.rolloff.c
    val = 1.0 / (a + b * (H**c))
    return np.clip(val, 0.0, 1.0)


def B_anhysteretic_array_T(material: Material, H_Oe_arr: ArrayLike) -> np.ndarray:
    """Anhysteretic B(H) [T] for an array of H values [Oe], in either sign.

    Computes the cumulative integral
        B(H) = mu_0 · mu_initial · ∫_0^H mu_fraction(H') dH'
    and clamps to ±Bsat_100C · 1.05 to stay sane far past saturation.

    Internally builds a dense H grid from 0 to max(|H|) so the integral is
    well-defined regardless of how sparse or unsorted the input is, then
    interpolates back to the user's points.
    """
    H_in = np.asarray(H_Oe_arr, dtype=float)
    sign = np.sign(H_in)
    sign[sign == 0] = 1.0
    H_abs = np.abs(H_in)

    if material.rolloff is None:
        B = MU_0 * material.mu_initial * (H_abs / OE_PER_AM)
    else:
        H_max = float(H_abs.max()) if H_abs.size > 0 else 0.0
        if H_max <= 0:
            B = np.zeros_like(H_abs)
        else:
            n_dense = max(400, H_abs.size * 2)
            grid = np.unique(np.concatenate([np.linspace(0.0, H_max, n_dense), H_abs]))
            grid_Am = grid / OE_PER_AM
            mu_eff = material.mu_initial * mu_pct_array(material, grid)
            integrand = MU_0 * mu_eff
            B_grid = np.zeros_like(grid)
            if grid.size > 1:
                dH = np.diff(grid_Am)
                seg = 0.5 * (integrand[:-1] + integrand[1:]) * dH
                B_grid[1:] = np.cumsum(seg)
            B = np.interp(H_abs, grid, B_grid)

    Bsat_cap = material.Bsat_100C_T * 1.05
    B = np.minimum(B, Bsat_cap)
    return sign * B


def B_anhysteretic_T(material: Material, H_Oe: float) -> float:
    """Scalar wrapper for `B_anhysteretic_array_T`."""
    return float(B_anhysteretic_array_T(material, np.array([H_Oe]))[0])
