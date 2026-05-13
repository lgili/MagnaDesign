"""Saturation roll-off for the direct FEA backend.

Thin wrapper around :mod:`pfc_inductor.physics.rolloff` (the
established analytical engine module) so the direct backend can
apply the same μ_eff(H) curves without duplicating the canonical
fit logic.

Two main entry points:

- :func:`compute_mu_eff_dc_bias` — closed-form ``μ_eff`` for a
  given operating point. Used by the toroidal solver to apply the
  catalog rolloff before computing L.

- :func:`solve_self_consistent_mu` — iterate ``μ_eff ↔ H`` until
  converged. For ``H_avg = N·I/le`` (the aggregate model) this is
  a single pass because H doesn't depend on μ. The interface
  exists because Phase 3.1 will introduce spatial μ(B) where the
  loop is non-trivial.

Why a wrapper rather than direct import? The direct backend may
evolve formulations that need B-dependent μ (per-element μ(B) in
the axi solver), which has a different signature from the
analytical-engine's lookup. Encapsulating here keeps the
backend's calling convention stable as those features land.
"""

from __future__ import annotations

import math
from typing import Optional

from pfc_inductor.physics import rolloff as _rolloff


def complex_mu_r_at(material: object, frequency_Hz: float) -> Optional[tuple[float, float]]:
    """Interpolate the material's ``complex_mu_r`` table at frequency.

    Returns ``(mu_prime, mu_double_prime)`` for the requested
    frequency, interpolated linearly in log-f space. Returns
    ``None`` when the material has no ``complex_mu_r`` table —
    callers should fall back to scalar ``mu_initial``.

    Phase 2.1 of the FEA replacement: lets the AC harmonic /
    Dowell paths model frequency-dependent core inductance and
    loss without needing a separate complex-μ FEM template.
    """
    import math as _m

    table = getattr(material, "complex_mu_r", None)
    if not table or frequency_Hz <= 0:
        return None

    pts = sorted((float(f), float(mp), float(mpp)) for f, mp, mpp in table)
    if len(pts) == 0:
        return None
    if len(pts) == 1 or frequency_Hz <= pts[0][0]:
        return pts[0][1], pts[0][2]
    if frequency_Hz >= pts[-1][0]:
        return pts[-1][1], pts[-1][2]

    from itertools import pairwise

    log_f = _m.log10(frequency_Hz)
    for (f_lo, mp_lo, mpp_lo), (f_hi, mp_hi, mpp_hi) in pairwise(pts):
        if f_lo <= frequency_Hz <= f_hi:
            t = (log_f - _m.log10(f_lo)) / (_m.log10(f_hi) - _m.log10(f_lo))
            return (
                mp_lo + t * (mp_hi - mp_lo),
                mpp_lo + t * (mpp_hi - mpp_lo),
            )
    return None


def compute_mu_eff_dc_bias(
    *,
    material: object,
    n_turns: int,
    current_A: float,
    le_m: float,
    fallback_mu_r: Optional[float] = None,
) -> tuple[float, float]:
    """Compute ``μ_r_eff`` under the DC bias of an operating point.

    Returns
    -------
    (mu_r_eff, mu_fraction)
        Where ``mu_r_eff = μ_initial · mu_fraction``. The fraction
        is in (0, 1] — 1.0 at zero bias, drops as the core nears
        saturation.

    Falls back to ``μ_initial`` (or ``fallback_mu_r`` if provided)
    when the material has no ``rolloff`` block (typical for solid
    ferrites — they handle saturation via a discrete air gap or a
    soft-knee tanh model elsewhere).
    """
    mu_r_init = float(
        getattr(material, "mu_r", None)
        or getattr(material, "mu_r_initial", None)
        or getattr(material, "mu_initial", None)
        or fallback_mu_r
        or 1.0
    )

    rolloff_block = getattr(material, "rolloff", None)
    if rolloff_block is None:
        return mu_r_init, 1.0

    # H in Oersted (the canonical unit Magnetics uses).
    H_Am = abs(n_turns * current_A) / max(le_m, 1e-9)
    H_Oe = H_Am * _rolloff.OE_PER_AM
    mu_fraction = _rolloff.mu_pct(material, H_Oe)  # type: ignore[arg-type]
    return mu_r_init * mu_fraction, mu_fraction


def solve_self_consistent_mu(
    *,
    material: object,
    n_turns: int,
    current_A: float,
    le_m: float,
    mu_r_initial: Optional[float] = None,
    max_iter: int = 1,
) -> tuple[float, int]:
    """Self-consistent ``μ_eff`` solve.

    For the aggregate-circuit model where ``H = N·I/le`` is
    independent of ``μ`` (the iron path length le is geometry,
    not material), a single pass converges by construction. The
    loop wrapper is here so Phase 3.1 (spatial μ(B) iteration in
    the axi solver) can drop in without changing the call sites.
    """
    fallback = mu_r_initial if mu_r_initial is not None else 1.0
    mu_eff, _frac = compute_mu_eff_dc_bias(
        material=material,
        n_turns=n_turns,
        current_A=current_A,
        le_m=le_m,
        fallback_mu_r=fallback,
    )
    return mu_eff, 1  # one pass — H_avg model converges trivially


def ferrite_saturation_factor(
    *,
    B_T: float,
    B_sat_T: float,
    knee_sharpness: float = 5.0,
) -> float:
    """Soft saturation knee for solid ferrites with no rolloff data.

    Polynomial knee model::

        μ_eff/μ_i = 1 / (1 + (B/B_sat)^N)

    with ``N ≈ 4–6`` for MnZn ferrites. At ``B = 0.7·B_sat`` this
    gives μ_eff ≈ 0.84·μ_i; at ``B = B_sat`` it gives 0.5·μ_i; at
    ``B = 1.2·B_sat`` it drops to ~0.2·μ_i. Reasonable agreement
    with vendor "% of initial permeability" charts.

    For PFC design the analytical engine flags ``B > 0.8·B_sat``
    as a violation, so the knee region matters more for spotting
    near-saturation operation than for accurate L modelling deep
    in saturation (where the operating point is invalid anyway).
    """
    if B_sat_T <= 0:
        return 1.0
    ratio = abs(B_T) / B_sat_T
    return 1.0 / (1.0 + ratio**knee_sharpness)


def _to_Oe(H_Am: float) -> float:
    """Convert A/m → Oe (utility, mirrors rolloff.OE_PER_AM).

    Kept locally as a utility for tests that want to verify the
    conversion path without importing the rolloff module.
    """
    return H_Am / 79.57747154594767


# Silence unused-warning for math (kept available for future
# Brillouin/Langevin curve extensions).
_ = math.pi


__all__ = [
    "complex_mu_r_at",
    "compute_mu_eff_dc_bias",
    "ferrite_saturation_factor",
    "solve_self_consistent_mu",
]
