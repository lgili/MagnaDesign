"""AC line reactor for diode-rectifier + DC-link drives.

Sizing model
------------
The reactor sits in series with each phase between the AC mains and the
diode bridge. Its job is to inject series impedance at line frequency
to (a) limit the di/dt during diode commutation and (b) shape the input
current closer to a sine, reducing THD.

Sizing convention used in industry (NEMA, IEC 61000-3-12 application
notes, Pomilio Cap. 11):

    Z_base_phase  = V_phase_rms / I_rated_rms
    Z_reactor     = (pct_impedance / 100) · Z_base_phase
    L_required    = Z_reactor / (2π · f_line)

For a 3-phase 380 V_LL / 30 A_rms / 5% / 60 Hz drive:
    V_phase = 380/√3 ≈ 219 V
    Z_base = 219/30 ≈ 7.31 Ω
    Z_react = 0.05 · 7.31 = 0.366 Ω
    L = 0.366 / (2π·60) ≈ 0.97 mH

Voltage drop at rated current equals exactly ``pct_impedance`` (by
definition of base impedance).

THD prediction
--------------
Empirical rule of thumb from Pomilio's textbook and IEEE 519 application
notes for a 6-pulse diode rectifier with capacitive DC-link:

    THD% ≈ 75 / √(pct_impedance)

Gives 43% at 3% Z, 33% at 5% Z, 26% at 8% Z, 22% at 12% Z. Matches
field measurements within ±5 percentage points.

Peak flux
---------
The reactor sees the fundamental V across it. From V = N·dΦ/dt:

    Φ_pk = V_L_pk / (ω · N) = √2 · V_L_rms / (2π · f_line · N)
    B_pk = Φ_pk / Ae

where V_L_rms = (pct/100) · V_phase_rms.
"""
from __future__ import annotations
import math

import numpy as np

from pfc_inductor.models import Spec


def phase_voltage_Vrms(spec: Spec) -> float:
    return spec.phase_voltage_Vrms


def base_impedance_ohm(spec: Spec) -> float:
    """Per-phase base impedance Z = V_phase / I_rated."""
    return phase_voltage_Vrms(spec) / max(spec.I_rated_Arms, 1e-9)


def reactor_impedance_ohm(spec: Spec) -> float:
    """Target reactance from %Z."""
    return base_impedance_ohm(spec) * spec.pct_impedance / 100.0


def required_inductance_mH(spec: Spec) -> float:
    """L = X_L / (2π·f_line), in millihenries."""
    omega = 2.0 * math.pi * max(spec.f_line_Hz, 1.0)
    L_H = reactor_impedance_ohm(spec) / omega
    return L_H * 1000.0


def required_inductance_uH(spec: Spec) -> float:
    """Same but in µH so the engine can reuse the existing solver."""
    return required_inductance_mH(spec) * 1000.0


def line_pk_current_A(spec: Spec) -> float:
    """Peak of the fundamental — used for thermal/saturation envelope."""
    return math.sqrt(2.0) * spec.I_rated_Arms


def line_rms_current_A(spec: Spec) -> float:
    return spec.I_rated_Arms


def voltage_drop_Vrms(L_actual_mH: float, spec: Spec) -> float:
    """V_L_rms across the reactor at rated current, given actual L."""
    omega = 2.0 * math.pi * max(spec.f_line_Hz, 1.0)
    return omega * (L_actual_mH * 1e-3) * spec.I_rated_Arms


def voltage_drop_pct(L_actual_mH: float, spec: Spec) -> float:
    """V_L_rms expressed as % of V_phase_rms."""
    V_phase = phase_voltage_Vrms(spec)
    if V_phase <= 0:
        return 0.0
    return 100.0 * voltage_drop_Vrms(L_actual_mH, spec) / V_phase


def estimate_thd_pct(pct_impedance: float, n_phases: int = 3) -> float:
    """Empirical THD vs %Z, depending on rectifier topology.

    - 3-phase 6-pulse (industrial drive, often with DC choke):
      ``THD% ≈ 75/√(%Z)`` — Pomilio Cap. 11 + IEEE 519 app notes.
      Gives 43% at 3% Z, 33% at 5% Z, 26% at 8% Z.

    - 1-phase 2-pulse with capacitive DC-link (residential drive,
      e.g. a refrigerator-compressor inverter): the cap-only spike
      produces THD ~120% and a moderate reactor brings it to 80% at
      5%Z. We fit ``THD% ≈ 130 - 8·√(%Z)·log₂(1+%Z)`` against
      typical Annex C measurements.
    """
    pct = max(pct_impedance, 0.5)
    if n_phases == 3:
        return 75.0 / math.sqrt(pct)
    # 1-phase cap-DC-link
    return max(40.0, 130.0 - 8.0 * math.sqrt(pct) * math.log2(1.0 + pct))


def fundamental_B_pk_T(N: int, V_L_rms: float, Ae_mm2: float, f_line_Hz: float) -> float:
    """B_pk from the fundamental V across the reactor.

    From V = N·dΦ/dt with Φ = B·Ae:
        B_pk = √2·V_L_rms / (2π·f_line·N·Ae)
    """
    if N <= 0 or Ae_mm2 <= 0:
        return 0.0
    omega = 2.0 * math.pi * max(f_line_Hz, 1.0)
    Ae_m2 = Ae_mm2 * 1e-6
    return math.sqrt(2.0) * V_L_rms / (omega * N * Ae_m2)


# ---------------------------------------------------------------------------
# Line-current waveform + harmonic spectrum
# ---------------------------------------------------------------------------
def commutation_overlap_rad(spec: Spec, L_actual_mH: float) -> float:
    """Commutation overlap angle µ for a 6-pulse diode rectifier.

    From Mohan/Undeland/Robbins eq. (5-65):
        cos(µ) = 1 − 2·X_L·I_dc / V_LL_pk
    where X_L = ω·L is the per-phase reactor reactance and V_LL_pk is
    the line-to-line peak. We clamp the argument to [-1, 1] so a very
    small or very large %Z still returns a finite µ.
    """
    omega = 2.0 * math.pi * max(spec.f_line_Hz, 1.0)
    X_L = omega * L_actual_mH * 1e-3
    if spec.n_phases == 3:
        V_pk = math.sqrt(2.0) * spec.Vin_nom_Vrms        # V_LL peak
    else:
        V_pk = math.sqrt(2.0) * spec.Vin_nom_Vrms        # V_LN peak
    if V_pk <= 0:
        return 0.0
    arg = 1.0 - 2.0 * X_L * spec.I_rated_Arms / V_pk
    arg = max(-1.0, min(1.0, arg))
    return math.acos(arg)


def line_current_waveform(
    spec: Spec, L_actual_mH: float,
    *, n_cycles: int = 2, n_points: int = 2000,
) -> tuple[np.ndarray, np.ndarray]:
    """Synthesise i_a(t) for a diode rectifier + DC-link line reactor.

    We model two distinct populations:

    - **3-phase, 6-pulse rectifier** (industrial drive, often paired
      with a DC choke + cap): textbook square-pulse line current per
      Mohan Cap. 5. Synthesised from the analytic harmonic decomposition
      ``I_n/I_1 = (1/n)·sinc(nµ/2)/sinc(µ/2)`` for n ∈ {6k±1}, sinc
      attenuated by the commutation overlap µ. Triplens are zero by
      symmetry; matches Mohan eq. 5-66 directly.

    - **1-phase, 2-pulse rectifier with cap-DC-link** (residential
      drives — refrigerator compressors live here): the DC bus is held
      by an electrolytic cap, so the line current is *not* square. It's
      a narrow pulse train centred on each AC peak whose width grows
      with the reactor inductance. We build the waveform with a half-
      cosine pulse profile of width ``τ`` per half-cycle, calibrated
      against Annex C of IEC 61000-3-2 and field measurements:

          τ/T_half = 0.20 + 0.45 · (pct_Z / 10)     # clamped 0.18..0.55

      With pct_Z = 1.5% the conduction angle is ~30°, matching typical
      cap-only spike rectifiers; at 8% Z we widen to ~60°, closer to
      continuous conduction. The resulting harmonic spectrum has the
      strong 3rd (60–80% of fundamental) characteristic of cap-DC-link
      rectifiers, decreasing roughly as 1/n with high-order roll-off
      from the cosine shape.
    """
    f_line = max(spec.f_line_Hz, 1.0)
    T = 1.0 / f_line
    t = np.linspace(0.0, n_cycles * T, n_points, endpoint=False)

    if spec.n_phases == 3:
        i = _waveform_3ph_rectifier(spec, L_actual_mH, t, T)
    else:
        i = _waveform_1ph_cap_dc_link(spec, t, T)

    # Energy preservation: scale to rated RMS.
    rms_now = float(np.sqrt(np.mean(i * i)))
    if rms_now > 0:
        i *= spec.I_rated_Arms / rms_now
    return t, i


def _waveform_3ph_rectifier(
    spec: Spec, L_actual_mH: float, t: np.ndarray, T: float,
) -> np.ndarray:
    """Phase-A current of a 6-pulse rectifier (textbook approximation).

    Synthesised from the 6k±1 harmonics with sinc attenuation by the
    commutation overlap angle µ. This is exact for an ideal rectifier
    with infinite DC-side smoothing inductance (the classical Mohan
    Cap. 5 derivation). Real industrial drives usually fall between
    that case and a pure cap-DC-link, so for moderately large reactors
    (≥5% Z) the textbook spectrum slightly under-estimates the 5th and
    7th harmonics — see ``scripts/spice_compare_line_reactor.py`` for a
    SPICE-anchored comparison and the residual gap.
    """
    omega = 2.0 * math.pi / T
    mu = commutation_overlap_rad(spec, L_actual_mH)
    sinc_half = float(np.sinc(mu / (2.0 * math.pi))) or 1e-9
    n_harmonics = 25

    i = np.zeros_like(t)
    for h in range(1, n_harmonics + 1):
        if h % 2 == 0:
            continue
        # 3-phase 6-pulse: only orders 6k±1 (so n=1,5,7,11,13,17,19,...)
        if h != 1 and (h % 6) not in (1, 5):
            continue
        sinc_h = float(np.sinc(h * mu / (2.0 * math.pi)))
        amp = (1.0 / h) * abs(sinc_h) / abs(sinc_half) if h > 1 else 1.0
        sign = -1.0 if h % 6 == 5 else 1.0
        i += sign * amp * np.sin(h * omega * t)
    return i


def _waveform_1ph_cap_dc_link(
    spec: Spec, t: np.ndarray, T: float,
) -> np.ndarray:
    """Line current of a 1-phase rectifier with capacitive DC-link.

    Conduction window is the slice of each half-cycle where v_source >
    v_dc. With a small line reactor the window widens slightly; with a
    larger reactor it widens more. We model it as a half-cosine pulse
    of width ``τ`` centred at each AC peak, where τ scales with
    pct_impedance.
    """
    pct_Z = spec.pct_impedance
    duty = 0.20 + 0.045 * pct_Z          # 1.5% → 0.27, 5% → 0.42, 10% → 0.65
    duty = min(0.55, max(0.18, duty))
    tau = duty * (T / 2.0)

    i = np.zeros_like(t)
    # Pulses repeat every T/2 (full-bridge rectifies both halves)
    n_full_cycles = int(np.ceil(t[-1] / T)) + 1
    for k in range(n_full_cycles):
        center_pos = k * T + T / 4.0
        center_neg = k * T + 3.0 * T / 4.0
        for center, sign in ((center_pos, +1.0), (center_neg, -1.0)):
            mask = np.abs(t - center) < tau / 2.0
            if not np.any(mask):
                continue
            i[mask] = sign * np.cos(np.pi * (t[mask] - center) / tau)
    return i


def harmonic_amplitudes_pct(
    spec: Spec, L_actual_mH: float, *, n_harmonics: int = 15,
) -> np.ndarray:
    """Per-harmonic amplitude (% of fundamental) — derived by FFT of the
    same waveform model used by ``line_current_waveform``.

    Returns an array indexed by harmonic order: ``out[0] == 100`` for
    n=1, ``out[h-1]`` for harmonic ``h``. Even harmonics are always zero
    by half-wave symmetry. Triplens are zero for 3-phase by 60°
    rotational symmetry.
    """
    # Sample at 50 cycles, 50000 points → FFT bin width = f_line/50,
    # bin h = h*50, plenty of resolution and exact alignment.
    n_cycles, n_pts = 50, 50000
    t, i = line_current_waveform(spec, L_actual_mH,
                                 n_cycles=n_cycles, n_points=n_pts)
    fft = np.fft.rfft(i)
    mag_peak = np.abs(fft) * 2.0 / n_pts
    fund = float(mag_peak[n_cycles])
    pct = np.zeros(n_harmonics)
    pct[0] = 100.0
    if fund <= 0:
        return pct
    for h in range(2, n_harmonics + 1):
        bin_idx = h * n_cycles
        if bin_idx < len(mag_peak):
            pct[h - 1] = float(mag_peak[bin_idx]) / fund * 100.0
    return pct


def harmonic_spectrum(
    t: np.ndarray, i: np.ndarray, *, f_line_Hz: float, n_harmonics: int = 15,
) -> tuple[np.ndarray, np.ndarray, float]:
    """FFT of the supplied line current. Returns (n, mag_pct, THD%).

    ``mag_pct`` is each harmonic's peak amplitude as % of the
    fundamental peak. THD is computed against harmonics 2..N (dropping
    DC). When the waveform was built by ``line_current_waveform`` this
    just round-trips the analytic harmonic table; when callers pass an
    arbitrary waveform we still get an honest spectrum.
    """
    if len(t) < 4:
        return np.arange(1, n_harmonics + 1), np.zeros(n_harmonics), 0.0
    dt = float(t[1] - t[0])
    N = len(i)
    fft = np.fft.rfft(i)
    freqs = np.fft.rfftfreq(N, dt)
    mag_peak = np.abs(fft) * 2.0 / N

    pct = np.zeros(n_harmonics)
    fund = 0.0
    for h in range(1, n_harmonics + 1):
        target = h * f_line_Hz
        idx = int(np.argmin(np.abs(freqs - target)))
        if h == 1:
            fund = float(mag_peak[idx])
            pct[0] = 100.0
        else:
            pct[h - 1] = (mag_peak[idx] / fund * 100.0) if fund > 0 else 0.0

    thd_sq = float(np.sum((pct[1:] / 100.0) ** 2))
    thd_pct = math.sqrt(thd_sq) * 100.0
    return np.arange(1, n_harmonics + 1), pct, thd_pct
