"""Acoustic-noise prediction for compressor-inverter PFC inductors.

Compressor-inverter PFC stages run with switching frequencies in
the 4–25 kHz range — squarely inside the audible band. The
inductor radiates acoustic noise via two mechanisms:

1. **Magnetostriction** — the core's dimensional change with B
   (∝ λ_s) excites mechanical vibration at fsw and 2·fsw.
2. **Winding Lorentz force** — alternating current in adjacent
   layers pushes/pulls them at fsw.

For appliance use cases (fridges, dishwashers, AC) audible
inductor whine at idle is a direct customer-complaint vector;
quality teams reject otherwise-working designs that hum.

This module ships an analytical estimator that takes engine
outputs (B_pk, ripple, fsw, geometry) plus material data
(λ_s if present, fall-back default per material type) and
returns an A-weighted SPL at 1 m + the dominant mechanism +
the headroom against a customer-grade threshold.

Calibration target: ±3 dB(A) against bench-mic measurements
on the validation reference set (``add-validation-reference-
set``). Documented as estimate; final acceptance needs an
anechoic-chamber measurement.

Public API
----------

- :class:`NoiseEstimate` — the result.
- :func:`estimate_noise` — entry point: ``(spec, core, wire,
  material, design_result) → NoiseEstimate``.
- :func:`magnetostrictive_lambda_s_ppm` — material-side helper
  with sensible defaults when the catalogue entry doesn't
  carry an explicit λ_s value.
"""

from __future__ import annotations

from pfc_inductor.acoustic.model import (
    NoiseEstimate,
    estimate_noise,
    magnetostrictive_lambda_s_ppm,
)

__all__ = [
    "NoiseEstimate",
    "estimate_noise",
    "magnetostrictive_lambda_s_ppm",
]
