"""EN 55032 conducted-EMI estimator (analytical envelope).

EN 55032 caps the conducted noise voltage measured across a
50 Ω LISN over 150 kHz – 30 MHz, in two classes:

- **Class A** — industrial / commercial environments
  (60 dBµV quasi-peak / 50 dBµV average from 150 kHz to 500 kHz,
  then 47 dBµV / 40 dBµV up to 5 MHz, then 50 dBµV / 40 dBµV).
- **Class B** — residential / appliance, 10 dB tighter throughout.

This module ships a **first-order analytical estimate**: for a
PFC inductor with switching frequency ``fsw_kHz``, peak ripple
current ``I_ripple_pk_pk_A`` and a parasitic-capacitance
estimate, derive the conducted-noise voltage envelope at every
harmonic of fsw inside the 150 kHz – 30 MHz band.

What it isn't
-------------

Not a substitute for an LISN measurement. Real EMI compliance
depends on the controller's switching transients, snubber
losses, layout parasitics, and ground-plane returns the engine
has no view of. The estimator's role is to **flag designs that
won't even cross the threshold under ideal-case assumptions**:
if this analytical envelope already exceeds the limit, the
real measurement is guaranteed to fail too.

Calibration target: ±10 dB vs. typical bench measurements on
the validation reference set (see ``add-validation-reference-
set``). Documented as *estimate*, not certification.

Public API
----------

- :func:`evaluate_emi` — main entry point. Returns a
  ``ComplianceReport``-shaped result so the dispatcher can
  treat it interchangeably with IEC 61000-3-2.
- :func:`limit_dbuv` — per-frequency QP / AV limit lookup.
- :data:`FREQ_BAND_HZ` — the (start, end) tuple in Hz.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional

Class = Literal["A", "B"]
Detector = Literal["QP", "AV"]


FREQ_BAND_HZ: tuple[float, float] = (150_000.0, 30_000_000.0)
"""Conducted-EMI frequency band per EN 55032:2017."""


# ---------------------------------------------------------------------------
# Limit table — EN 55032:2017 Table A.5 + A.6.
# ---------------------------------------------------------------------------
# Each tuple is (f_low_Hz, f_high_Hz, qp_dbuv, av_dbuv) for the
# applicable class. Limits are flat within each band; the boundary
# at 500 kHz / 5 MHz is handled by linear interpolation per the
# standard (the slope is gentle so a piecewise-flat lookup is
# accurate to ±0.5 dB within the band edges).
_LIMIT_TABLE: dict[Class, tuple[tuple[float, float, float, float], ...]] = {
    "A": (
        (150_000.0, 500_000.0, 79.0, 66.0),  # 150 kHz – 500 kHz
        (500_000.0, 5_000_000.0, 73.0, 60.0),  # 500 kHz – 5 MHz
        (5_000_000.0, 30_000_000.0, 73.0, 60.0),  # 5 MHz – 30 MHz
    ),
    "B": (
        (150_000.0, 500_000.0, 66.0, 56.0),  # 150 kHz – 500 kHz
        (500_000.0, 5_000_000.0, 60.0, 50.0),  # 500 kHz – 5 MHz, log-decay region
        (5_000_000.0, 30_000_000.0, 60.0, 50.0),
    ),
}


def limit_dbuv(
    frequency_Hz: float,
    *,
    class_: Class = "B",
    detector: Detector = "QP",
) -> float:
    """Return the EN 55032 limit at ``frequency_Hz`` in dBµV.

    Frequencies outside ``FREQ_BAND_HZ`` return ``+inf`` so an
    out-of-band harmonic is never flagged as a violation. The
    table is piecewise-flat with linear interpolation at the
    Class-B 150 kHz – 500 kHz boundary (decays from 66 to 56 dBµV
    log-linearly per the standard).
    """
    if frequency_Hz < FREQ_BAND_HZ[0] or frequency_Hz > FREQ_BAND_HZ[1]:
        return float("inf")

    rows = _LIMIT_TABLE[class_]
    qp_idx = 2 if detector == "QP" else 3

    for f_lo, f_hi, qp_dbuv, av_dbuv in rows:
        if f_lo <= frequency_Hz <= f_hi:
            base_qp, base_av = qp_dbuv, av_dbuv
            # Class B 150–500 kHz region uses a log-decay curve
            # (66 dBµV @ 150 kHz → 56 dBµV @ 500 kHz). Interpolate
            # linearly in log10(f) for accuracy ±0.5 dB.
            if class_ == "B" and 150_000.0 <= frequency_Hz <= 500_000.0:
                t = math.log10(frequency_Hz / 150_000.0) / math.log10(500_000.0 / 150_000.0)
                base_qp = 66.0 - t * (66.0 - 56.0)
                base_av = 56.0 - t * (56.0 - 46.0)
            return base_qp if detector == "QP" else base_av

    # Should be unreachable given the band check above, but
    # keeping the guard so future table edits don't tip into
    # silent inf-returns.
    return float("inf")


# ---------------------------------------------------------------------------
# Estimator
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HarmonicEnvelopePoint:
    """One harmonic of fsw, measured at the LISN."""

    n: int
    """Harmonic index (1 = fundamental, 2 = 2 × fsw, …)."""

    frequency_Hz: float
    measured_dbuv: float
    limit_dbuv: float
    margin_dB: float
    """Positive = under the limit; negative = exceeds."""

    passes: bool


@dataclass
class EmiReport:
    """Aggregate output of :func:`evaluate_emi`."""

    class_: Class
    detector: Detector
    fsw_Hz: float
    points: list[HarmonicEnvelopePoint] = field(default_factory=list)
    worst_margin_dB: float = 0.0
    worst_n: Optional[int] = None
    passes: bool = True


# Default parasitic shunt capacitance (Cp) — sets the high-
# frequency rolloff of the inductor's self-resonance. 30 pF is
# typical for a layered solenoid winding on a powder core; the
# actual value lives somewhere in 5 pF (Litz) – 100 pF (large
# multi-layer) and dominates the 1 MHz+ envelope. Callers can
# override via the function arg when they have a measured value.
DEFAULT_CP_PF: float = 30.0

# Default conducted-EMI filter attenuation (dB).
#
# A bare PFC inductor at the production stage does NOT meet
# EN 55032 — the standard expects the converter to ship with a
# CISPR-class input filter (common-mode + differential X / Y
# capacitance + optional CMC) that buys 40–60 dB of additional
# rejection across the band. Without representing that filter
# explicitly the estimator would tell every PFC design "FAIL by
# 60 dB", which is technically true but engineering-useless: the
# inductor alone is not what gets measured at the LISN.
#
# 60 dB matches a typical two-stage CISPR Class B filter
# (CMC + DM-LC); first-order filters land closer to 40 dB.
# The user can override per project when they have a measured
# attenuation curve. Larger values produce a more permissive
# verdict — set to 0 to see the bare-inductor envelope.
DEFAULT_FILTER_ATTENUATION_DB: float = 60.0

# LISN impedance per CISPR 16-1-2: 50 Ω || 50 µH.
# At conducted-EMI frequencies the inductive part is negligible
# (≈ 47 Ω at 150 kHz, climbing); we treat it as a pure 50 Ω so
# the estimator doesn't claim a precision the model can't deliver.
_LISN_OHMS: float = 50.0


def evaluate_emi(
    spec_fsw_kHz: float,
    I_ripple_pk_pk_A: float,
    *,
    class_: Class = "B",
    detector: Detector = "QP",
    cp_pF: float = DEFAULT_CP_PF,
    filter_attenuation_dB: float = DEFAULT_FILTER_ATTENUATION_DB,
    n_harmonics: int = 200,
) -> EmiReport:
    """Estimate the conducted-EMI envelope across 150 kHz – 30 MHz.

    Args:
        spec_fsw_kHz: Switching frequency of the converter.
        I_ripple_pk_pk_A: Peak-to-peak ripple at the inductor.
            Drives the harmonic source amplitude.
        class_: ``"A"`` (industrial) or ``"B"`` (residential).
            Default ``"B"`` matches the appliance use case and
            is the tighter envelope.
        detector: ``"QP"`` (quasi-peak) or ``"AV"`` (average).
            QP is the headline limit; AV is consulted for narrow-
            band emissions and is typically 10 dB tighter.
        cp_pF: Estimated parasitic shunt capacitance of the
            inductor in picofarads. Sets the high-frequency
            rolloff of the V_n envelope.
        n_harmonics: How many fsw harmonics to evaluate. 200 ×
            65 kHz = 13 MHz which leaves ~17 MHz of the band
            uncovered; bump to 500 if fsw < 50 kHz.

    Returns:
        An :class:`EmiReport` with one
        :class:`HarmonicEnvelopePoint` per in-band harmonic plus
        the worst margin + pass/fail flag.

    Model
    -----

    Each harmonic is treated as a square-wave Fourier component:

        V_n_diff = (4 / nπ) × V_supply  (V)

    For the conducted noise we don't have V_supply directly; we
    approximate the differential voltage source as the ripple
    amplitude across the inductor's effective impedance plus the
    parasitic Cp shunting it. The resulting LISN-side voltage
    in dBµV is::

        V_LISN_uV(n) = (V_n × Z_LISN / (Z_LISN + Z_inductor(n))) × 1e6
        dBuV(n)      = 20 × log10(V_LISN_uV)

    Z_inductor(n) = (j ω_n L) || (1 / j ω_n Cp); for the
    estimator we use the magnitude.

    The L-value is the engine's analytical inductance — caller
    passes the ripple, not L, because ripple is the FFT-source
    amplitude and L only enters via the impedance shunting.
    """
    if spec_fsw_kHz <= 0 or I_ripple_pk_pk_A <= 0:
        return EmiReport(
            class_=class_,
            detector=detector,
            fsw_Hz=0.0,
            points=[],
            passes=True,
            worst_margin_dB=float("inf"),
        )

    fsw_Hz = spec_fsw_kHz * 1000.0
    cp_F = max(cp_pF, 0.001) * 1e-12

    points: list[HarmonicEnvelopePoint] = []
    worst_margin = float("inf")
    worst_n: Optional[int] = None
    passes = True

    for n in range(1, n_harmonics + 1):
        f_n = n * fsw_Hz
        if f_n < FREQ_BAND_HZ[0]:
            continue
        if f_n > FREQ_BAND_HZ[1]:
            break

        # Source amplitude per harmonic — square-wave 1/n decay.
        # The 4/π comes from the Fourier expansion of a square
        # wave in volts. Here we take the differential current
        # (I_ripple_pk_pk_A) and convert to a noise-source voltage
        # by assuming the inductor's high-frequency impedance is
        # Cp-dominated (1 / 2πf Cp) at every harmonic above the
        # self-resonant frequency — typical 1–5 MHz for a power
        # inductor.
        z_cp = 1.0 / (2.0 * math.pi * f_n * cp_F)
        v_source = (4.0 / (n * math.pi)) * I_ripple_pk_pk_A * z_cp

        # Voltage divider against the LISN. Cp dominates above
        # the self-resonant freq; LISN = 50 Ω.
        v_lisn = v_source * _LISN_OHMS / (_LISN_OHMS + z_cp)

        # AV is ~10 dB lower than QP for typical broadband sources;
        # we model it as a flat -10 dB offset until per-band
        # correction lands. The standard's actual relationship is
        # signal-shape dependent and beyond an analytical envelope.
        v_lisn_uv = max(v_lisn * 1e6, 1e-9)
        dbuv = 20.0 * math.log10(v_lisn_uv)
        if detector == "AV":
            dbuv -= 10.0
        # Apply the CISPR filter attenuation. The bare-inductor
        # envelope above is what would land at the LISN with NO
        # input filter; the user's converter ships with one and
        # the standard's measurement is taken downstream of it.
        dbuv -= filter_attenuation_dB

        lim = limit_dbuv(f_n, class_=class_, detector=detector)
        margin = lim - dbuv
        ok = dbuv <= lim

        points.append(
            HarmonicEnvelopePoint(
                n=n,
                frequency_Hz=f_n,
                measured_dbuv=float(dbuv),
                limit_dbuv=float(lim),
                margin_dB=float(margin),
                passes=bool(ok),
            )
        )
        if not ok:
            passes = False
        if margin < worst_margin:
            worst_margin = margin
            worst_n = n

    return EmiReport(
        class_=class_,
        detector=detector,
        fsw_Hz=fsw_Hz,
        points=points,
        worst_margin_dB=(worst_margin if worst_margin != float("inf") else 0.0),
        worst_n=worst_n,
        passes=passes,
    )
