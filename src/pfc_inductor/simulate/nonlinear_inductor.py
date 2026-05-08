"""Time-varying L(i, T) for transient simulation.

`NonlinearInductor` wraps a (core, material, N) tuple and exposes
the instantaneous inductance and flux density at any current. It
delegates to `physics.rolloff` so Tier 1 (analytical) and Tier 2
(transient) share exactly the same calibrated permeability curves
— there is no second implementation of the rolloff math to drift.

Usage::

    inductor = NonlinearInductor(core, material, N=45, T_C=80.0)
    L_H = inductor.L_H(i_A=14.0)        # instantaneous inductance, henries
    B_T = inductor.B_T(i_A=14.0)        # instantaneous flux density, tesla
    H_Oe = inductor.H_Oe(i_A=14.0)      # magnetic field, oersted

The temperature parameter is reserved for future Phase-B work that
folds in copper resistivity changes; for now it is recorded but
does not modify the rolloff lookup (the rolloff fit was made at
fixed material temperature).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from pfc_inductor.models import Core, Material
from pfc_inductor.physics import rolloff as rf


@dataclass
class NonlinearInductor:
    """`L(i, T)` for one (core, material, N) point in the search space."""

    core: Core
    material: Material
    N: int
    T_C: float = 25.0
    # Cached quantities that don't depend on i_L — recomputed if any
    # of (core, material, N) changes via `model_copy`-style usage.
    _AL_nH: float = field(init=False, repr=False)
    _le_mm: float = field(init=False, repr=False)
    _Ae_m2: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Pull immutable geometry once so the per-step hot path doesn't
        # reach into the Pydantic `Core` object on every integration step.
        self._AL_nH = float(self.core.AL_nH)
        self._le_mm = float(self.core.le_mm)
        self._Ae_m2 = float(self.core.Ae_mm2) * 1e-6

    # ─── Scalar accessors (per integration step) ────────────────

    def H_Oe(self, i_A: float) -> float:
        """Magnetic field strength at instantaneous current `i_A`."""
        return rf.H_from_NI(self.N, abs(i_A), self._le_mm, units="Oe")

    def mu_pct(self, i_A: float) -> float:
        """Effective permeability fraction at instantaneous current."""
        return rf.mu_pct(self.material, self.H_Oe(i_A))

    def L_uH(self, i_A: float) -> float:
        """Instantaneous inductance in microhenries."""
        return rf.inductance_uH(self.N, self._AL_nH, self.mu_pct(i_A))

    def L_H(self, i_A: float) -> float:
        """Instantaneous inductance in henries — the form the ODE wants."""
        return self.L_uH(i_A) * 1e-6

    def B_T(self, i_A: float) -> float:
        """Instantaneous flux density at current `i_A`.

        Uses the line-envelope identity `B = L · i / (N · Ae)`. For
        deeper non-linear analyses (full B–H trajectory with
        hysteresis) Phase B is intentionally agnostic — that lives
        in `physics/rolloff.B_anhysteretic_T` and is exposed via
        `B_anhysteretic_T()` below.
        """
        if self.N <= 0 or self._Ae_m2 <= 0:
            return 0.0
        return self.L_H(i_A) * i_A / (self.N * self._Ae_m2)

    def B_anhysteretic_T(self, i_A: float) -> float:
        """Anhysteretic B(H) at this current — uses the integrated curve.

        Slower than `B_T` (a quadrature is performed inside
        `physics.rolloff.B_anhysteretic_T`) so prefer `B_T` on hot
        paths; this is the right call when sampling a B–H operating
        loop at a handful of points.
        """
        return rf.B_anhysteretic_T(self.material, self.H_Oe(i_A))

    # ─── Vectorised accessors (for waveform post-processing) ────

    def L_H_array(self, i_A: np.ndarray) -> np.ndarray:
        """Vectorised `L_H` over an array of currents."""
        H_Oe = rf.H_from_NI(self.N, 1.0, self._le_mm, units="Oe") * np.abs(i_A)
        mu = rf.mu_pct_array(self.material, H_Oe)
        return rf.inductance_uH(self.N, self._AL_nH, 1.0) * mu * 1e-6

    def B_T_array(self, i_A: np.ndarray) -> np.ndarray:
        """Vectorised `B_T` over an array of currents."""
        if self.N <= 0 or self._Ae_m2 <= 0:
            return np.zeros_like(i_A)
        L_H = self.L_H_array(i_A)
        return L_H * i_A / (self.N * self._Ae_m2)

    # ─── Saturation helpers ────────────────────────────────────

    def Bsat_T(self) -> float:
        """Saturation flux density at the configured temperature.

        Linear interpolation between the 25 °C and 100 °C anchor
        points the material data carries.
        """
        Bsat_25 = self.material.Bsat_25C_T
        Bsat_100 = self.material.Bsat_100C_T
        if Bsat_100 <= 0:
            return Bsat_25
        # Clamp to the anchor range — extrapolation beyond is risky.
        T = max(25.0, min(100.0, self.T_C))
        return Bsat_25 + (Bsat_100 - Bsat_25) * (T - 25.0) / 75.0

    def saturation_margin_pct(
        self,
        B_pk: float,
        *,
        margin: float = 0.20,
    ) -> float:
        """How close (as %) `B_pk` is to the configured saturation limit.

        Returns 0 % at exactly the limit, positive when below, negative
        when above. Pre-computed `B_pk` is taken at face value — for
        the linear `B = L · i / (N · Ae)` value, prefer
        `is_saturated_at_current` which uses the anhysteretic curve
        and correctly identifies deep saturation.
        """
        limit = self.Bsat_T() * (1.0 - margin)
        if limit <= 0:
            return 0.0
        return 100.0 * (limit - abs(B_pk)) / limit

    def is_saturated(
        self,
        B_pk: float,
        *,
        margin: float = 0.20,
    ) -> bool:
        """True iff `|B_pk|` exceeds `Bsat·(1 − margin)` for a *given* `B_pk`.

        Note: in deep saturation, the linear `B = L·i/(N·Ae)` value
        UNDERSTATES the true flux density (because `L` already
        collapsed via rolloff). Callers that want the physical
        verdict at peak current should use
        :meth:`is_saturated_at_current` instead.
        """
        return abs(B_pk) > self.Bsat_T() * (1.0 - margin)

    def is_saturated_at_current(
        self,
        i_A: float,
        *,
        margin: float = 0.20,
    ) -> bool:
        """True iff the **anhysteretic** B at `i_A` exceeds the margin.

        Uses `physics.rolloff.B_anhysteretic_T`, which integrates
        `μ_0 · μ_r(H)` along the H trajectory and clamps at Bsat.
        That's the right primitive for saturation detection: in
        the deep-saturation regime, the linear `L · i / (N · Ae)`
        formula collapses (because L → 0), masking saturation; the
        anhysteretic curve correctly reports a near-Bsat value.
        """
        return abs(self.B_anhysteretic_T(i_A)) > self.Bsat_T() * (1.0 - margin)

    # ─── Construction sugar ────────────────────────────────────

    @classmethod
    def from_design_point(
        cls,
        core: Core,
        material: Material,
        N: int,
        T_C: Optional[float] = None,
    ) -> NonlinearInductor:
        """Construct from the same fields the engine returns in `DesignResult`."""
        return cls(core=core, material=material, N=N, T_C=T_C if T_C is not None else 25.0)
