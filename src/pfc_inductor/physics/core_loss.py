"""Core loss model.

Anchored Steinmetz baseline:
    Pv [mW/cm^3] = Pv_ref * (f/f_ref)^alpha * (B/B_ref)^beta

For PFC inductors the flux waveform has two superimposed components:
- LINE-FREQUENCY ENVELOPE (full-wave rectified at 2*f_line). Dropped for
  powder cores and ferrites at f_line << f_min_kHz — extrapolating Steinmetz
  outside its validated range gives garbage.
- HIGH-FREQUENCY RIPPLE at f_sw with PEAK-TO-PEAK amplitude that varies
  along the line cycle (max near vin = Vout/2 for boost CCM, ~zero at line
  zero crossings).

iGSE for the ripple term:
We sample ΔB_pp(t) along the line cycle and time-average <Pv(t)> with
Steinmetz applied LOCALLY at each phase. Because Pv ~ ΔB^β with β ≈ 2.0–2.7,
<ΔB(t)^β> >> <ΔB(t)>^β by a factor that can reach 1.5–2× for PFC waveforms.
A naïve Steinmetz with ΔB_avg under-predicts loss; iGSE corrects it without
needing any closed-form triangular wave constants.

Reference: J. Mühlethaler et al., "Improved core-loss calculation for
magnetic components employed in power electronic systems," IEEE TPE, 2012.
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np
from numpy.typing import ArrayLike

from pfc_inductor.models import Material


def steinmetz_volumetric_mWcm3(material: Material, f_kHz: float, B_pk_mT: float) -> float:
    """Pv [mW/cm^3] anchored at (f_ref, B_ref, Pv_ref).

    Hot scalar — called twice per ``core_loss_W_pfc`` invocation
    (line band + ripple-band fallback) and once per
    ``core_loss_W_sinusoidal``. The Numba kernel (when the
    ``[performance]`` extra is installed) runs the same math
    inline; the pure-Python branch below is the fallback.
    """
    s = material.steinmetz
    if f_kHz < s.f_min_kHz:
        return 0.0
    if _STEINMETZ_KERNEL is not None:
        return _STEINMETZ_KERNEL(
            float(f_kHz),
            float(B_pk_mT),
            float(s.Pv_ref_mWcm3),
            float(s.f_ref_kHz),
            float(s.B_ref_mT),
            float(s.alpha),
            float(s.beta),
        )
    f = max(f_kHz, 1e-3)
    B = max(B_pk_mT, 1e-6)
    return s.Pv_ref_mWcm3 * (f / s.f_ref_kHz) ** s.alpha * (B / s.B_ref_mT) ** s.beta


def core_loss_W_sinusoidal(
    material: Material,
    f_kHz: float,
    B_pk_T: float,
    Ve_mm3: float,
) -> float:
    """Total core loss in W given core volume and sinusoidal flux at f, B_pk."""
    Pv_mW_cm3 = steinmetz_volumetric_mWcm3(material, f_kHz, B_pk_T * 1000.0)
    Ve_cm3 = Ve_mm3 * 1e-3
    return Pv_mW_cm3 * Ve_cm3 * 1e-3


def _build_steinmetz_kernel() -> Optional[Callable[..., float]]:
    """Compile :func:`steinmetz_volumetric_mWcm3` with Numba if
    available. The kernel takes Pydantic-resolved coefficients
    as scalars so attribute access is paid once (in the wrapper)
    rather than per-call."""
    try:
        from numba import njit
    except ImportError:
        return None

    @njit(fastmath=True, cache=True, nogil=True)
    def _kernel(
        f_kHz: float,
        B_pk_mT: float,
        Pv_ref: float,
        f_ref_kHz: float,
        B_ref_mT: float,
        alpha: float,
        beta: float,
    ) -> float:
        f = f_kHz if f_kHz > 1e-3 else 1e-3
        B = B_pk_mT if B_pk_mT > 1e-6 else 1e-6
        return Pv_ref * (f / f_ref_kHz) ** alpha * (B / B_ref_mT) ** beta

    return _kernel


_STEINMETZ_KERNEL = _build_steinmetz_kernel()


def core_loss_W_pfc_ripple_iGSE(
    material: Material,
    f_sw_kHz: float,
    delta_B_pp_T_array: ArrayLike,
    Ve_mm3: float,
) -> float:
    """Time-averaged ripple loss over the line cycle (iGSE-style).

    delta_B_pp_T_array : ndarray of ΔB peak-to-peak [T] sampled over half line cycle.
    Local AC peak amplitude per switching cycle = ΔB_pp/2.
    Returns total ripple loss in Watts.

    Hot path — called 6× per ``engine.design()`` call (once per
    thermal-converge iteration). The Numba-accelerated kernel
    (:func:`_iGSE_kernel`) is used when the ``[performance]``
    extra is installed; otherwise the function falls back to
    the pure-numpy path. Both produce identical numbers.
    """
    s = material.steinmetz
    if f_sw_kHz < s.f_min_kHz:
        return 0.0
    f_factor = (f_sw_kHz / s.f_ref_kHz) ** s.alpha
    arr = np.asarray(delta_B_pp_T_array, dtype=float)

    if _NUMBA_KERNEL is not None:
        Pv_avg_mW_cm3 = float(
            _NUMBA_KERNEL(
                arr,
                s.Pv_ref_mWcm3,
                f_factor,
                s.B_ref_mT,
                s.beta,
            )
        )
    else:
        B_pk_mT = np.maximum(arr * 1000.0 / 2.0, 1e-6)
        Pv_per_t = s.Pv_ref_mWcm3 * f_factor * (B_pk_mT / s.B_ref_mT) ** s.beta
        Pv_avg_mW_cm3 = float(np.mean(Pv_per_t))

    Ve_cm3 = Ve_mm3 * 1e-3
    return Pv_avg_mW_cm3 * Ve_cm3 * 1e-3


# ─── Numba acceleration (opt-in via the ``[performance]`` extra) ───
#
# The pure-numpy path above pays ~5 µs of dispatch overhead per
# call (np.maximum, np.mean, ufunc broadcast). At 6 calls per
# engine.design() and 10 000 candidates per cascade run, that's
# ~300 ms wasted on numpy plumbing. A hand-written Numba kernel
# does the same math in a single tight loop with ~50× less
# overhead — see ``docs/PERFORMANCE.md`` for the benchmark.
#
# When the ``[performance]`` extra isn't installed, ``_NUMBA_KERNEL``
# stays None and we use the pure-numpy fallback. Same numbers,
# same accuracy — just slower.


def _build_numba_kernel() -> Optional[Callable[..., float]]:
    """Compile the iGSE-mean kernel with Numba if available.

    Returns the compiled function, or ``None`` when Numba isn't
    installed. Called once at module import; the result is
    cached in ``_NUMBA_KERNEL``. The ``Callable`` return type is
    deliberately loose — the kernel's exact signature is decided
    at compile time by Numba and we treat it as opaque from
    Python.
    """
    try:
        from numba import njit
    except ImportError:
        return None

    @njit(fastmath=True, cache=True, nogil=True)
    def _kernel(
        arr: np.ndarray, Pv_ref: float, f_factor: float, B_ref_mT: float, beta: float
    ) -> float:
        n = arr.shape[0]
        if n == 0:
            return 0.0
        s = 0.0
        coeff = Pv_ref * f_factor
        # Hand-rolled time-average: avoids np.maximum + np.mean
        # ufunc dispatch overhead that dominates for n ~ 200.
        for i in range(n):
            v = arr[i]
            if v < 0:
                v = -v
            B = v * 1000.0 / 2.0
            if B < 1e-6:
                B = 1e-6
            s += coeff * (B / B_ref_mT) ** beta
        return s / n

    return _kernel


_NUMBA_KERNEL = _build_numba_kernel()


def core_loss_W_pfc(
    material: Material,
    f_line_Hz: float,
    f_sw_kHz: float,
    B_pk_line_T: float,
    delta_B_ripple_avg_T: float,
    Ve_mm3: float,
    delta_B_pp_T_array: ArrayLike | None = None,
) -> tuple[float, float]:
    """Return (P_line_W, P_ripple_W).

    Line component: only counted if 2*f_line >= material.f_min_kHz.

    Ripple: if `delta_B_pp_T_array` is given (preferred), use iGSE — sample
    Pv(t) along the line cycle and time-average. Otherwise fall back to the
    naïve <ΔB>/2 Steinmetz call.
    """
    f_line_kHz = f_line_Hz * 1e-3
    P_line = core_loss_W_sinusoidal(material, 2 * f_line_kHz, B_pk_line_T, Ve_mm3)
    if delta_B_pp_T_array is not None:
        P_ripple = core_loss_W_pfc_ripple_iGSE(material, f_sw_kHz, delta_B_pp_T_array, Ve_mm3)
    else:
        B_pk_ripple_T = delta_B_ripple_avg_T / 2.0
        P_ripple = core_loss_W_sinusoidal(material, f_sw_kHz, B_pk_ripple_T, Ve_mm3)
    return P_line, P_ripple
