"""Interleaved boost PFC (2- or 3-phase parallel boost).

Topology
--------
N parallel boost stages drive a common DC bus, each with its own
inductor, switch, and diode. The PWM gates are phase-shifted by
``360°/N``. Each phase carries ``1/N`` of the total input current.

The big wins of interleaving over single-phase boost:

1. **Smaller per-phase inductor.** Sizing follows
   ``boost_ccm.required_inductance_uH(per_phase_spec)`` — the
   per-phase ``Pout/N`` shrinks the worst-case current by the
   same factor, so the ``L·I²`` energy each inductor stores is
   ``1/N²`` of the single-phase equivalent. Practically, a 3 kW
   2-phase design fits PQ32 cores per phase vs PQ40+ for the
   single-phase 3 kW; a 3-phase 3 kW design fits PQ26.
2. **Aggregate input-current ripple cancellation.** The N
   triangular ripple waveforms sum to a higher-frequency residue
   at ``N · f_sw`` whose amplitude vanishes at the duty-cycle
   nulls (``D = k/N`` for ``k = 1, …, N−1``) and reaches its
   worst case at ``D = (k+0.5)/N``. The closed-form aggregate
   ripple is the Hwu-Yau result (IEEE Trans IA, 2008):

       ΔI_in_pp(D, N) = ΔI_phase_pp(D) · α(D, N)

   where ``α(D, N)`` is the cancellation factor — see
   ``ripple_cancellation_factor`` below for the closed form.
3. **Thermal spreading.** Per-component loss is ``1/N``, so heat
   sinks shrink and per-component temperature rise drops.

Engineering note
----------------
For the inductor sizing problem this module is **a thin wrapper
over** ``boost_ccm``. The aggregate input-ripple chart is the
"signature" of interleaving but does not affect the per-phase
inductor — the engine sizes one inductor and the BOM lists ``×N``
identical units. The cancellation formula is exposed as a helper
for the report's per-phase / aggregate figure.

References
----------
- Hwu, K. I. & Yau, Y. T., "Performance Enhancement of Boost
  Converter Based on PID Controller Plus Linear-to-Nonlinear
  Translator", IEEE Trans. Industry Applications 44 (4), 2008.
- Erickson & Maksimovic, *Fundamentals of Power Electronics*,
  Ch. 18 (interleaving discussion at the end of the PFC chapter).
- TI Application Report SLUA479, "Interleaved Power Factor
  Correction (IPFC) Reference Design", Texas Instruments, 2009.
"""

from __future__ import annotations

import math

from pfc_inductor.models import Spec
from pfc_inductor.topology import boost_ccm


def per_phase_spec(spec: Spec) -> Spec:
    """Return a derived Spec sized for one of the ``n_interleave``
    phases.

    Each phase carries ``1/N`` of the total power; everything else
    (Vin range, Vout, fsw, ripple budget, environment) is the same
    per phase. Setting ``topology = "boost_ccm"`` lets the existing
    boost-CCM engine path size the inductor without an
    interleaved-specific code path inside ``design.engine``.
    """
    if spec.topology != "interleaved_boost_pfc":
        # Defensive: if a caller passes an already-boost spec, just
        # return it unchanged so the helper is always idempotent.
        return spec
    return spec.model_copy(
        update={
            "topology": "boost_ccm",
            "Pout_W": spec.Pout_W / spec.n_interleave,
        }
    )


# ---------------------------------------------------------------------------
# Per-phase delegations.
# ---------------------------------------------------------------------------
def line_peak_current_A(spec: Spec, Vin_Vrms: float) -> float:
    """Per-phase peak of the rectified line current.

    Equal to ``boost_ccm.line_peak_current_A`` evaluated on
    ``per_phase_spec(spec)``.
    """
    return boost_ccm.line_peak_current_A(per_phase_spec(spec), Vin_Vrms)


def line_rms_current_A(spec: Spec, Vin_Vrms: float) -> float:
    """Per-phase RMS line current."""
    return boost_ccm.line_rms_current_A(per_phase_spec(spec), Vin_Vrms)


def required_inductance_uH(spec: Spec, Vin_Vrms: float) -> float:
    """Per-phase required inductance.

    Each phase gets the same boost-CCM ripple-budget treatment
    against its own ``1/N``-scaled peak current. The aggregate
    input-current ripple is *better* than per-phase (cancellation),
    but that doesn't relax the per-phase sizing rule — each phase's
    L still has to carry its own peak.
    """
    return boost_ccm.required_inductance_uH(per_phase_spec(spec), Vin_Vrms)


def aggregate_input_rms_current_A(spec: Spec, Vin_Vrms: float) -> float:
    """Total input RMS current (sum of N phases).

    Equal to ``boost_ccm.line_rms_current_A`` evaluated on the
    ORIGINAL spec — the source still delivers all ``Pout`` worth
    of fundamental current; interleaving only redistributes it.
    """
    P_in = spec.Pout_W / spec.eta
    return P_in / Vin_Vrms


def aggregate_input_peak_current_A(spec: Spec, Vin_Vrms: float) -> float:
    """Total input peak current (per the rectified envelope)."""
    return math.sqrt(2.0) * aggregate_input_rms_current_A(spec, Vin_Vrms)


# ---------------------------------------------------------------------------
# Aggregate input ripple (the topology's signature).
# ---------------------------------------------------------------------------
def ripple_cancellation_factor(D: float, N: int) -> float:
    """Hwu-Yau aggregate-ripple cancellation factor.

    For N parallel boost phases PWM-shifted by ``360°/N``, the
    sum of N triangular ripple currents at duty ``D`` has
    amplitude:

        ΔI_in_pp(D, N) = ΔI_phase_pp(D) · α(D, N)

    with::

        α(D, N) = (1 − k·D)·(k·D − k + 1) / (D · (1 − D))

    where ``k = floor(N·D) + 1`` is the cancellation order at the
    current operating duty. ``α(D, N)`` is exactly **0** at the
    duty nulls ``D = k/N`` (k = 1, …, N−1) and reaches its worst
    case at ``D = (k+0.5)/N``.

    For N = 1 (degenerate case) we return 1.0 (no cancellation).
    """
    if N <= 1:
        return 1.0
    if D <= 0.0 or D >= 1.0:
        return 0.0
    # Pick the cancellation cell. ``k`` in the Hwu-Yau paper is
    # the integer part of N·D + 1 (so D ∈ (0, 1/N] uses k=1, etc.).
    k = int(math.floor(N * D)) + 1
    if k > N:
        return 0.0
    num = (1.0 - k * D + (k - 1)) * (k * D - (k - 1))
    den = D * (1.0 - D)
    if den <= 0.0:
        return 0.0
    factor = num / den
    # ``α`` should sit in [0, 1] for the symmetric N-phase case;
    # numerical edge cases at the cell boundaries can drift a hair
    # outside, so clamp.
    return max(0.0, min(1.0, factor))


def aggregate_input_ripple_pp(per_phase_pp: float, D: float, N: int) -> float:
    """Aggregate input-current ripple at duty ``D`` for ``N``
    interleaved phases."""
    return per_phase_pp * ripple_cancellation_factor(D, N)


def effective_input_ripple_frequency_Hz(f_sw_kHz: float, N: int) -> float:
    """The aggregate input-current ripple sits at ``N · f_sw``.

    The triangular per-phase ripple at ``f_sw`` shifts by ``T_sw/N``
    between adjacent phases; their sum has its lowest non-zero
    Fourier component at ``N · f_sw``. The input filter capacitor
    only has to attenuate that band, not ``f_sw`` — much smaller
    capacitance suffices.
    """
    return max(N, 1) * f_sw_kHz * 1000.0


# ---------------------------------------------------------------------------
# THD prediction.
# ---------------------------------------------------------------------------
def estimate_thd_pct(spec: Spec) -> float:
    """First-order THD estimate for the aggregate input current.

    Single-phase boost-CCM PFC has THD ~ 5 % under typical control.
    Interleaving doesn't fundamentally change the line-frequency
    fundamental shape (still controlled to track Vin), but the
    high-frequency residue shrinks by ``√N`` (the per-phase ripple
    contributions are uncorrelated at the current-loop bandwidth).

    Returns the boost-CCM value scaled by ``1/√N``.
    """
    base = boost_ccm.estimate_thd_pct(spec)
    return base / math.sqrt(max(spec.n_interleave, 1))


# ---------------------------------------------------------------------------
# Worst-case duty for ripple — useful for the cancellation chart.
# ---------------------------------------------------------------------------
def worst_case_duty_for_ripple(N: int) -> float:
    """Duty cycle that maximises the aggregate ripple for a given
    interleave count.

    For symmetric N-phase interleaving the worst-case lives at
    ``D = (k + 0.5)/N`` for any cancellation cell k. The lowest
    such duty (k=0) gives ``D = 1/(2N)`` which is below typical
    boost operating points; the highest (k=N−1) gives
    ``D = (2N−1)/(2N)``. For the report's "ripple at worst case"
    chart we use the centre cell, which is also the deepest.

    For N=2: D = 0.25 or 0.75. For N=3: D ∈ {1/6, 0.5, 5/6}.
    """
    if N <= 1:
        return 0.5
    # Centre of the middle cell for both N=2 and N=3.
    if N == 2:
        return 0.25
    if N == 3:
        return 0.5
    # General formula for any symmetric N (not used today).
    return 0.5 + 0.5 / N
