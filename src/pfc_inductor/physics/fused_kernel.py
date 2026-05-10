"""Fused thermal-converge + total-loss Numba kernel.

The previous per-leaf Numba kernels (``iGSE``, ``Steinmetz``,
``Dowell``, ``_solve_N``) speed up individual hot calls but
each one still pays a Python→Numba dispatch boundary
crossing per call. The thermal solver iterates 6× per
``engine.design()``, calling 5 leaf functions per iteration —
that's 30 boundary crossings.

This module collapses all of that into a single kernel:

    thermal_converge_fused(  # 25 scalar args + 1 array
        T_amb, A_surface, T_init,
        N, MLT_mm, A_cu_mm2,
        fsw_Hz_skin, layers,
        wire_kind, d_cu_m, d_strand_m, n_strands,
        I_dc_line, I_rip_rms,
        f_line_Hz, fsw_kHz_loss,
        B_pk_for_loss, delta_B_avg, delta_B_pp_array, Ve_mm3,
        Pv_ref, alpha, beta, B_ref_mT, f_ref_kHz, f_min_kHz,
    ) -> (T_final, P_total, P_cu_dc, P_cu_ac, P_line, P_ripple, converged)

The kernel inlines:

- ``rho_cu(T)`` (linear temp coefficient)
- ``cp.Rdc_ohm`` (geometry × resistivity)
- ``dowell.Rac_over_Rdc_round`` / ``…_litz`` (5 transcendentals)
- ``cl.steinmetz_volumetric_mWcm3`` (line band)
- ``cl.core_loss_W_pfc_ripple_iGSE`` (time-average over ΔB array)
- ``thermal.converge_temperature`` (iterative T solver)

The same 6 thermal iterations now run in compiled native code
without ever returning to Python — the dispatch boundary cost
(~2-5 µs per crossing) drops to zero.

When Numba isn't installed (``[performance]`` extra absent),
``_FUSED_KERNEL`` is ``None`` and the caller (``engine.design``)
falls back to the per-leaf path. Same numerical answer, just
slower.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

import numpy as np

# Constants used by the fused kernel — kept module-level so
# Numba can reference them as compile-time constants.
_RHO_CU_20C = 1.724e-8
_PI = math.pi

# Wire-kind constants matched against ``wire.type`` strings in the
# caller. Numba kernel uses the integer encoding so we don't have
# to ship strings into JIT-compiled code.
WIRE_ROUND = 0
WIRE_LITZ = 1
WIRE_OTHER = 2  # foil, unsupported — Fr falls back to 1.0


def _build_fused_kernel() -> Optional[Callable[..., tuple]]:
    """Compile the thermal-converge + total-loss fused kernel
    with Numba if available.

    Returns the JIT-compiled function or ``None`` when Numba
    isn't installed. The ``Callable`` return type is loose —
    the kernel signature is large (20+ scalars) and opaque to
    Python; the caller passes a fixed argument bundle.
    """
    try:
        from numba import njit
    except ImportError:
        return None

    @njit(fastmath=True, cache=True, nogil=True)
    def _kernel(
        # Thermal solver setup
        T_amb_C: float,
        A_surface_m2: float,
        T_init_C: float,
        max_iter: int,
        tol_K: float,
        relax_factor: float,
        T_hard_max_C: float,
        h_conv: float,
        # Cu loss geometry
        N: int,
        MLT_mm: float,
        A_cu_mm2: float,
        # Rac inputs
        fsw_Hz_skin: float,
        layers: int,
        wire_kind: int,
        d_cu_m: float,
        d_strand_m: float,
        n_strands: int,
        # Currents
        I_dc_line: float,
        I_rip_rms: float,
        # Core loss line band
        f_line_Hz: float,
        # Core loss ripple band
        fsw_kHz_loss: float,
        # Flux densities
        B_pk_for_loss_T: float,
        delta_B_avg_T: float,
        delta_B_pp_T_array: np.ndarray,
        # Core volume
        Ve_mm3: float,
        # Steinmetz coefficients (Pv_ref @ f_ref, B_ref)
        Pv_ref: float,
        alpha: float,
        beta: float,
        B_ref_mT: float,
        f_ref_kHz: float,
        f_min_kHz: float,
    ) -> tuple:
        # Pre-compute factors that don't depend on temperature.
        L_wire_m = N * MLT_mm * 1e-3
        A_cu_m2 = A_cu_mm2 * 1e-6
        Ve_cm3 = Ve_mm3 * 1e-3

        # ── Steinmetz line-band: 2 * f_line_Hz ──
        f_line_kHz_2 = 2.0 * f_line_Hz * 1e-3
        if f_line_kHz_2 < f_min_kHz:
            P_line_W = 0.0
        else:
            f_line = f_line_kHz_2 if f_line_kHz_2 > 1e-3 else 1e-3
            B_line_mT = B_pk_for_loss_T * 1000.0
            if B_line_mT < 1e-6:
                B_line_mT = 1e-6
            Pv_line = Pv_ref * (f_line / f_ref_kHz) ** alpha * (B_line_mT / B_ref_mT) ** beta
            P_line_W = Pv_line * Ve_cm3 * 1e-3

        # ── iGSE ripple band ── (independent of T)
        if fsw_kHz_loss < f_min_kHz:
            P_ripple_W = 0.0
        else:
            f_factor = (fsw_kHz_loss / f_ref_kHz) ** alpha
            n_arr = delta_B_pp_T_array.shape[0]
            if n_arr == 0:
                # Fallback: naive Steinmetz on delta_B_avg / 2.
                B_rip_mT = (delta_B_avg_T / 2.0) * 1000.0
                if B_rip_mT < 1e-6:
                    B_rip_mT = 1e-6
                Pv_avg = Pv_ref * f_factor * (B_rip_mT / B_ref_mT) ** beta
            else:
                s = 0.0
                coeff = Pv_ref * f_factor
                for i in range(n_arr):
                    v = delta_B_pp_T_array[i]
                    if v < 0:
                        v = -v
                    B_local_mT = v * 1000.0 / 2.0
                    if B_local_mT < 1e-6:
                        B_local_mT = 1e-6
                    s += coeff * (B_local_mT / B_ref_mT) ** beta
                Pv_avg = s / n_arr
            P_ripple_W = Pv_avg * Ve_cm3 * 1e-3

        # ── Thermal converge loop ──
        T = T_init_C
        converged = False
        P_total = 0.0
        P_cu_dc = 0.0
        P_cu_ac = 0.0
        for _ in range(max_iter):
            T_eval = T if T < T_hard_max_C else T_hard_max_C

            # Rdc(T)
            rho = _RHO_CU_20C * (1.0 + 0.00393 * (T_eval - 20.0))
            if A_cu_m2 <= 0:
                Rdc = 1e30  # mock infinity — propagates as huge loss
            else:
                Rdc = rho * L_wire_m / A_cu_m2

            # Rac(T) via Dowell
            if fsw_Hz_skin <= 0:
                Fr = 1.0
            elif wire_kind == WIRE_ROUND and d_cu_m > 0:
                # Inline ``rho_cu`` + ``skin_depth_m`` + Dowell-Ferreira round
                rho_cu = _RHO_CU_20C * (1.0 + 0.00393 * (T_eval - 20.0))
                delta = (rho_cu / (_PI * fsw_Hz_skin * 4e-7 * _PI)) ** 0.5
                xi = (d_cu_m / delta) * (_PI / 4.0) ** 0.5 * 0.9**0.5
                two_xi = 2.0 * xi
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
                m_lay = layers if layers > 1 else 1
                Fr = F_R + (2.0 / 3.0) * (m_lay * m_lay - 1) * G_R
                if Fr < 1.0:
                    Fr = 1.0
            elif wire_kind == WIRE_LITZ and d_strand_m > 0 and n_strands > 0:
                rho_cu = _RHO_CU_20C * (1.0 + 0.00393 * (T_eval - 20.0))
                delta = (rho_cu / (_PI * fsw_Hz_skin * 4e-7 * _PI)) ** 0.5
                xi_s = (d_strand_m / delta) * (_PI / 4.0) ** 0.5
                two_xi = 2.0 * xi_s
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
                F_R = xi_s * (sinh2x + sin2x) / den_skin
                G_R = xi_s * (sinh2x - sin2x) / den_prox
                m_lay = layers if layers > 1 else 1
                Fr = F_R + (2.0 / 3.0) * (m_lay * m_lay - 1) * G_R / n_strands
                if Fr < 1.0:
                    Fr = 1.0
            else:
                Fr = 1.0
            Rac = Rdc * Fr

            P_cu_dc = I_dc_line * I_dc_line * Rdc
            P_cu_ac = I_rip_rms * I_rip_rms * Rac
            P_total = P_cu_dc + P_cu_ac + P_line_W + P_ripple_W

            # Thermal balance: T_new = T_amb + P / (h * A).
            if A_surface_m2 <= 0:
                dT = 0.0
            else:
                dT = P_total / (h_conv * A_surface_m2)
            T_new = T_amb_C + dT
            if T_new > T_hard_max_C:
                T_new = T_hard_max_C
            if abs(T_new - T) < tol_K:
                T = T_new
                converged = True
                break
            T = T + relax_factor * (T_new - T)
            if T > T_hard_max_C:
                T = T_hard_max_C

        return (T, P_total, P_cu_dc, P_cu_ac, P_line_W, P_ripple_W, converged)

    return _kernel


_FUSED_KERNEL = _build_fused_kernel()


# ─── Public Python wrapper ───────────────────────────────────────


def fused_converge(
    *,
    spec_T_amb_C: float,
    spec_f_line_Hz: float,
    A_surface_m2: float,
    T_init_C: float,
    N: int,
    MLT_mm: float,
    A_cu_mm2: float,
    fsw_Hz_skin: float,
    fsw_kHz_loss: float,
    layers: int,
    wire_kind: int,
    d_cu_m: float,
    d_strand_m: float,
    n_strands: int,
    I_dc_line: float,
    I_rip_rms: float,
    B_pk_for_loss_T: float,
    delta_B_avg_T: float,
    delta_B_pp_T_array: np.ndarray | None,
    Ve_mm3: float,
    Pv_ref: float,
    alpha: float,
    beta: float,
    B_ref_mT: float,
    f_ref_kHz: float,
    f_min_kHz: float,
    h_conv: float = 12.0,
    max_iter: int = 30,
    tol_K: float = 0.5,
    relax: float = 0.5,
    T_hard_max_C: float = 300.0,
) -> tuple[float, float, float, float, float, float, bool] | None:
    """Run the fused thermal-converge + total-loss kernel.

    Returns ``(T_final, P_total, P_cu_dc, P_cu_ac,
    P_core_line, P_core_ripple, converged)`` — the same tuple
    the caller would assemble by running ``converge_temperature``
    and the final-breakdown block of ``engine.design`` separately.

    Returns ``None`` when the kernel isn't loaded (caller falls
    back to the per-leaf path).
    """
    if _FUSED_KERNEL is None:
        return None
    if delta_B_pp_T_array is None:
        delta_B_pp_T_array = np.zeros(0, dtype=np.float64)
    arr = np.ascontiguousarray(delta_B_pp_T_array, dtype=np.float64)
    return _FUSED_KERNEL(
        float(spec_T_amb_C),
        float(A_surface_m2),
        float(T_init_C),
        int(max_iter),
        float(tol_K),
        float(relax),
        float(T_hard_max_C),
        float(h_conv),
        int(N),
        float(MLT_mm),
        float(A_cu_mm2),
        float(fsw_Hz_skin),
        int(layers),
        int(wire_kind),
        float(d_cu_m),
        float(d_strand_m),
        int(n_strands),
        float(I_dc_line),
        float(I_rip_rms),
        float(spec_f_line_Hz),
        float(fsw_kHz_loss),
        float(B_pk_for_loss_T),
        float(delta_B_avg_T),
        arr,
        float(Ve_mm3),
        float(Pv_ref),
        float(alpha),
        float(beta),
        float(B_ref_mT),
        float(f_ref_kHz),
        float(f_min_kHz),
    )
