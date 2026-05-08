"""Power-factor estimation as a function of inductance.

Both the passive line choke and the AC line reactor improve the input
power factor (PF) of a capacitor-input diode-rectifier load by
"stiffening" the source: a series choke widens the conduction angle
of the rectifier, which lowers the line-current THD and pushes the
PF closer to unity. The relationship between L and PF is well
documented (Pomilio, Erickson) and we use the same fits the
``datasheet.py`` / engine layer already does, exposed here as
``pf_at_L(spec, L_uH)`` so plot helpers (PDF + live chart) can
sweep L without re-implementing the formulae.

Boost-PFC (``boost_ccm``) is intentionally excluded — the active
control loop forces PF ≈ 1 regardless of L, so a PF vs L plot is
uninformative.

References
----------
- Pomilio, *Eletrônica de Potência*, Cap. 11 (line reactor) and
  Cap. 13 (passive PFC).
- Erickson & Maksimovic, *Fundamentals of Power Electronics*,
  Ch. 18 (passive PFC).
- IEC 61000-3-12 Tabel 4 (industrial harmonic limits) — for the
  THD / PF cross-validation.
"""

from __future__ import annotations

import math

from pfc_inductor.models import Spec

# Industry-standard constants.
_PF_BASELINE_NO_CHOKE = 0.55  # capacitor-input rectifier baseline
_PF_ASYMPTOTIC = 0.95  # passive choke practical ceiling
# Displacement PF for a 6-pulse rectifier with line reactor (small
# commutation-notch loss; nearly unity).
_DPF_LINE_REACTOR = 0.99


def pf_at_L(spec: Spec, L_uH: float) -> float:
    """Return the estimated input power factor for the given choke /
    reactor inductance, in the topology the spec describes.

    Returns ``1.0`` for ``boost_ccm`` (active control sets PF ≈ 1).
    Returns ``_PF_BASELINE_NO_CHOKE`` for ``L_uH <= 0`` so the
    sweep's left endpoint plots cleanly.
    """
    if L_uH <= 0:
        return _PF_BASELINE_NO_CHOKE
    if spec.topology == "passive_choke":
        return _pf_passive_choke(spec, L_uH)
    if spec.topology == "line_reactor":
        return _pf_line_reactor(spec, L_uH)
    if spec.topology == "boost_ccm":
        return 1.0
    return 1.0


def thd_at_L(spec: Spec, L_uH: float) -> float:
    """Return the estimated line-current THD [%] for the given L.

    Same Pomilio fit the engine uses (``75 / √%Z``); returns 100 %
    for ``L = 0`` (capacitor-input rectifier without any choke).
    """
    if L_uH <= 0:
        return 100.0
    if spec.topology == "boost_ccm":
        return 5.0  # active PFC; sub-5 % typical
    omega = 2.0 * math.pi * max(spec.f_line_Hz, 1.0)
    L_H = L_uH * 1e-6
    if spec.topology == "line_reactor":
        Vphase = spec.phase_voltage_Vrms
        Z_base = Vphase / max(spec.I_rated_Arms, 1e-9)
        pct_Z = 100.0 * omega * L_H / max(Z_base, 1e-9)
    else:  # passive_choke
        Vin = spec.Vin_nom_Vrms
        Vbus = 0.9 * math.sqrt(2.0) * Vin
        I_dc = spec.Pout_W / max(spec.eta * Vbus, 1.0)
        V_drop = omega * L_H * I_dc
        pct_Z = max(0.1, 100.0 * V_drop / max(Vin, 1e-6))
    pct_Z = max(0.1, pct_Z)
    return min(100.0, 75.0 / math.sqrt(pct_Z))


def apparent_power_VA(spec: Spec, L_uH: float) -> float:
    """Apparent power S = P_active / PF that the source must deliver
    to satisfy the spec's load with this choke L.

    Higher PF → less apparent power → smaller transformer / breaker
    sizing. Useful as a secondary y-axis when plotting PF vs L
    because it answers the bottom-line question for the user:
    *what does this PF cost me at the source?*
    """
    P_active = spec.Pout_W / max(spec.eta, 0.5)  # input active power
    pf = pf_at_L(spec, L_uH)
    return P_active / max(pf, 0.05)


def active_power_at_inst_current_W(
    spec: Spec, L_uH: float, I_pk_inst_A: float,
) -> float:
    """Active input power that the source delivers when the inductor
    carries an instantaneous peak current ``I_pk_inst_A`` and the
    effective inductance at that operating point is ``L_uH``.

    Used by the "Power vs inductance" parametric chart. As the
    inductor saturates (L drops past the operating point) the input
    PF degrades, so even though the current keeps rising, the
    real power tapers off — exactly the failure mode the engineer
    wants to see.

    Per-topology mapping from ``I_pk_inst`` to source-side RMS:

    - **boost_ccm / passive_choke**: peak inductor current is the
      peak of the rectified line current, so ``I_rms = I_pk / √2``;
      single-phase, ``P = V_in · I_rms · PF``.
    - **line_reactor**: peak phase current = ``√2 · I_rated``, so
      ``I_rms_per_phase = I_pk / √2``. For 3-phase loads multiply
      by 3 phases (or equivalently use ``√3 · V_LL``).
    """
    if I_pk_inst_A <= 0:
        return 0.0
    pf = pf_at_L(spec, L_uH)
    I_rms = I_pk_inst_A / math.sqrt(2.0)
    if spec.topology == "line_reactor":
        Vphase = spec.phase_voltage_Vrms
        n = max(spec.n_phases, 1)
        return n * Vphase * I_rms * pf
    # Single-phase topologies (boost_ccm, passive_choke).
    return spec.Vin_nom_Vrms * I_rms * pf


# ---------------------------------------------------------------------------
# Per-topology fits.
# ---------------------------------------------------------------------------
def _pf_passive_choke(spec: Spec, L_uH: float) -> float:
    """Passive single-phase choke, capacitor-input rectifier.

    Empirical saturation curve (Erickson Ch. 18 / Pomilio Cap. 13):

        PF(L) = pf₀ + (pf_∞ − pf₀) · (1 − exp(−x))

    where ``x`` is the choke's reactance normalised by a "natural"
    impedance scale ``0.4 · V_pk / I_pk_load``. The constant 0.4
    encodes how far past the natural impedance the rectifier needs
    to be pushed to widen the conduction angle materially.
    """
    omega = 2.0 * math.pi * max(spec.f_line_Hz, 1.0)
    L_H = L_uH * 1e-6
    Vin_rms = spec.Vin_nom_Vrms
    eta = max(spec.eta, 0.5)
    # Baseline RMS load current (assumes pf₀ at first iteration —
    # the engine uses the same starting point in ``_passive_choke_extras``).
    I_load_rms = spec.Pout_W / max(eta * Vin_rms * _PF_BASELINE_NO_CHOKE, 1e-6)
    Vpk = math.sqrt(2.0) * Vin_rms
    Ipk_load = math.sqrt(2.0) * I_load_rms
    z_react = omega * L_H
    natural_Z = max(0.4 * Vpk / max(Ipk_load, 1e-6), 1e-6)
    x = z_react / natural_Z
    pf = _PF_BASELINE_NO_CHOKE + (_PF_ASYMPTOTIC - _PF_BASELINE_NO_CHOKE) * (1.0 - math.exp(-x))
    return max(_PF_BASELINE_NO_CHOKE, min(_PF_ASYMPTOTIC, pf))


def _pf_line_reactor(spec: Spec, L_uH: float) -> float:
    """3-φ (or 1-φ) AC line reactor.

    PF_total = DPF / √(1 + (THD)²). The displacement factor DPF
    starts at ~0.99 with any reactor in place (commutation notch
    losses nearly unity); harmonic distortion is the dominant
    PF-killer and follows the Pomilio fit ``THD% ≈ 75 / √(%Z)``.
    """
    omega = 2.0 * math.pi * max(spec.f_line_Hz, 1.0)
    L_H = L_uH * 1e-6
    Vphase = spec.phase_voltage_Vrms
    Z_base = Vphase / max(spec.I_rated_Arms, 1e-9)
    pct_Z = 100.0 * omega * L_H / max(Z_base, 1e-9)
    pct_Z = max(0.1, pct_Z)
    THD_frac = 0.75 / math.sqrt(pct_Z)  # 75/√%Z, in fraction
    pf_total = _DPF_LINE_REACTOR / math.sqrt(1.0 + THD_frac**2)
    return max(_PF_BASELINE_NO_CHOKE, min(0.99, pf_total))
