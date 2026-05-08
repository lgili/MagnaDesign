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

    Hot path — called once per ``Rac_ohm`` call, which itself
    fires twice per thermal-converge iteration (~12× per
    ``engine.design()``). The Numba kernel below runs the
    transcendentals (sinh / cosh / sin / cos / sqrt) in compiled
    code; falls back to the pure-math path when Numba isn't
    installed.
    """
    if _ROUND_KERNEL is not None:
        return _ROUND_KERNEL(float(d_cu_m), float(f_Hz), int(layers), float(T_C))
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

    Numba-accelerated when the ``[performance]`` extra is
    installed; falls back to the pure-math path otherwise.
    """
    if _LITZ_KERNEL is not None:
        return _LITZ_KERNEL(
            float(d_strand_m),
            int(n_strands),
            float(f_Hz),
            int(layers_bundle),
            float(T_C),
        )
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


# ─── Numba kernels (opt-in via the ``[performance]`` extra) ───────
#
# Both Dowell ratios are pure scalar math (5 transcendentals + a
# handful of arithmetic ops). The pure-Python overhead is the
# function-call dispatch at 12× per ``engine.design()`` call —
# 6 thermal-converge iterations × 2 calls (DC + AC).
#
# Inlining ``rho_cu`` and ``skin_depth_m`` into the kernels means
# the entire Rac_ratio computation runs without a single Python
# call once the kernel is JIT-compiled.

_PI = math.pi
_RHO_CU_20C = 1.724e-8


def _build_round_kernel():
    """Compile :func:`Rac_over_Rdc_round` with Numba if available."""
    try:
        from numba import njit
    except ImportError:
        return None

    @njit(fastmath=True, cache=True)
    def _round(d_cu_m, f_Hz, layers, T_C):
        if f_Hz <= 0.0 or d_cu_m <= 0.0:
            return 1.0
        # Inline rho_cu(T) + skin_depth_m(f, T).
        rho = _RHO_CU_20C * (1.0 + 0.00393 * (T_C - 20.0))
        delta = (rho / (_PI * f_Hz * 4e-7 * _PI)) ** 0.5
        # Dowell xi with porosity = 0.9.
        xi = (d_cu_m / delta) * (_PI / 4.0) ** 0.5 * 0.9**0.5
        two_xi = 2.0 * xi
        # math.sinh / cosh / sin / cos all available in Numba.
        # ``math.sinh(2x) = (exp(2x) - exp(-2x)) / 2`` etc.; Numba
        # uses libm so the calls are native-fast already.
        sinh2x = math.sinh(two_xi)
        sin2x = math.sin(two_xi)
        cosh2x = math.cosh(two_xi)
        cos2x = math.cos(two_xi)

        den_skin = cosh2x - cos2x
        if den_skin < 1e-30:
            den_skin = 1e-30
        den_prox = cosh2x + cos2x
        if den_prox < 1e-30:
            den_prox = 1e-30

        F_R = xi * (sinh2x + sin2x) / den_skin
        G_R = xi * (sinh2x - sin2x) / den_prox

        m = layers if layers > 1 else 1
        Fr = F_R + (2.0 / 3.0) * (m * m - 1) * G_R
        if Fr < 1.0:
            return 1.0
        return Fr

    return _round


def _build_litz_kernel():
    """Compile :func:`Rac_over_Rdc_litz` with Numba if available."""
    try:
        from numba import njit
    except ImportError:
        return None

    @njit(fastmath=True, cache=True)
    def _litz(d_strand_m, n_strands, f_Hz, layers_bundle, T_C):
        if d_strand_m <= 0.0 or f_Hz <= 0.0:
            return 1.0
        rho = _RHO_CU_20C * (1.0 + 0.00393 * (T_C - 20.0))
        delta = (rho / (_PI * f_Hz * 4e-7 * _PI)) ** 0.5
        xi_s = (d_strand_m / delta) * (_PI / 4.0) ** 0.5
        two_xi = 2.0 * xi_s
        import math as _m

        sinh2x = _m.sinh(two_xi)
        sin2x = _m.sin(two_xi)
        cosh2x = _m.cosh(two_xi)
        cos2x = _m.cos(two_xi)

        den_skin = cosh2x - cos2x
        if den_skin < 1e-30:
            den_skin = 1e-30
        den_prox = cosh2x + cos2x
        if den_prox < 1e-30:
            den_prox = 1e-30

        F_R = xi_s * (sinh2x + sin2x) / den_skin
        G_R = xi_s * (sinh2x - sin2x) / den_prox

        m = layers_bundle if layers_bundle > 1 else 1
        n = n_strands if n_strands > 0 else 1
        Fr = F_R + (2.0 / 3.0) * (m * m - 1) * G_R / n
        if Fr < 1.0:
            return 1.0
        return Fr

    return _litz


_ROUND_KERNEL = _build_round_kernel()
_LITZ_KERNEL = _build_litz_kernel()
