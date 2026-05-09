"""Shared Vin accessors for DC-input topologies (buck, flyback, …).

Both buck-CCM and flyback specs may carry their input-voltage
information in *either* of two field families:

- Modern: ``Spec.Vin_dc_V`` (+ optional ``Vin_dc_min_V`` /
  ``Vin_dc_max_V`` for worst-case ripple / current envelopes).
- Legacy: ``Spec.Vin_min_Vrms`` / ``Vin_max_Vrms`` /
  ``Vin_nom_Vrms`` — these were the only Vin fields before the
  buck-CCM change introduced the DC fields. Specs serialised from
  v2 / v3 of the app still arrive with only the AC names set.

Every DC-input topology module needs the same fallback chain to
read the right voltage. Pre-extraction, ``buck_ccm.py`` and
``flyback.py`` each shipped a private copy; the two were 99 %
identical and drifted in sync only by accident. This module
centralises the helpers so future DC-input topologies (planned:
``psfb_output_choke``) inherit the same semantics for free.

Public API (``_``-prefixed at the module boundary because these
are infrastructure helpers, not engineering primitives):

- :func:`vin_min` — worst-case low input voltage; drives current.
- :func:`vin_max` — worst-case high input voltage; drives ripple
  / device-stress (FET drain, diode reverse).
- :func:`vin_nom` — nominal input voltage; used for waveform
  sampling and "what does the bench scope show" displays.

All three return ``0.0`` when no Vin source is set (rather than
raising), so callers can apply their own zero-guard with the
clearest local error message.
"""

from __future__ import annotations

from pfc_inductor.models import Spec


def vin_min(spec: Spec) -> float:
    """Worst-case low input voltage in volts.

    Resolution order (first non-zero wins):

    1. ``Spec.Vin_dc_min_V`` — explicit lower bound on a DC bus
       with worst-case ripple at low line.
    2. ``Spec.Vin_dc_V`` — single nominal DC voltage when the
       caller didn't bother carving min / max separately.
    3. ``Spec.Vin_min_Vrms`` — legacy AC field, treated as DC for
       back-compat with v2 / v3 spec serialisations.

    Returns ``0.0`` when none of the three is set; callers that
    need to fail loudly should wrap with their own zero-check.
    """
    return float(
        getattr(spec, "Vin_dc_min_V", None)
        or getattr(spec, "Vin_dc_V", None)
        or getattr(spec, "Vin_min_Vrms", 0.0)
        or 0.0
    )


def vin_max(spec: Spec) -> float:
    """Worst-case high input voltage in volts.

    Same fallback chain as :func:`vin_min` but rooted at
    ``Vin_dc_max_V``. Used by buck-CCM for the worst-case ripple
    point (largest ``1 − D``) and by flyback for the FET drain
    stress (``Vin_max + n·Vout + V_clamp``).
    """
    return float(
        getattr(spec, "Vin_dc_max_V", None)
        or getattr(spec, "Vin_dc_V", None)
        or getattr(spec, "Vin_max_Vrms", 0.0)
        or 0.0
    )


def vin_nom(spec: Spec) -> float:
    """Nominal input voltage in volts.

    Prefers the explicit ``Vin_dc_V`` field; falls back to
    :func:`vin_max` then :func:`vin_min` so a half-configured
    spec still yields a sensible "what would a bench scope
    show?" number for waveform plots.
    """
    return float(getattr(spec, "Vin_dc_V", None) or vin_max(spec) or vin_min(spec))
