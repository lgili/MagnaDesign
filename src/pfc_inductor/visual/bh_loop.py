"""Operating-point B–H trajectory for the design.

Generates two curves on the B–H plane:
- A static (anhysteretic) reference curve, extended ~40% past the operating
  peak so the user sees how close the design is to saturation.
- The slow trajectory traced by the inductor flux over half a line cycle.
- An optional small-loop overlay representing the high-frequency ripple,
  located at the line phase where ripple peaks.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from pfc_inductor.models import Core, DesignResult, Material
from pfc_inductor.physics.rolloff import (
    OE_PER_AM,
    B_anhysteretic_array_T,
)


def compute_bh_trajectory(
    result: DesignResult,
    core: Core,
    material: Material,
    n_envelope: int = 200,
    n_ripple: int = 40,
    n_static: int = 300,
) -> dict:
    """Return arrays for the B–H plot.

    Keys:
      H_static_Oe, B_static_T : reference anhysteretic curve
      H_envelope_Oe, B_envelope_T : trajectory over half line cycle
      H_ripple_Oe, B_ripple_T : ripple range at peak ripple location (or None)
      H_pk_Oe, B_pk_T : peak operating values
      Bsat_T : material Bsat at hot temperature
    """
    N = max(result.N_turns, 1)
    le_m = max(core.le_mm * 1e-3, 1e-6)
    I_pk = result.I_line_pk_A

    # Slow envelope: iL_avg(t) = I_pk · |sin(ωt)| over half line cycle.
    phase = np.linspace(0.0, np.pi, n_envelope)
    iL_env = I_pk * np.sin(phase)
    H_env_Oe = (N * iL_env / le_m) * OE_PER_AM
    B_env_T = B_anhysteretic_array_T(material, H_env_Oe)

    # Static reference curve up to ~1.4× the peak (or a sensible floor for
    # tiny designs so the curve is visible).
    H_pk_Oe = float(H_env_Oe.max())
    H_max_static = max(H_pk_Oe * 1.4, 50.0)
    H_static = np.linspace(0.0, H_max_static, n_static)
    B_static = B_anhysteretic_array_T(material, H_static)

    # Ripple overlay: only render if appreciable HF ripple is present (boost
    # CCM) — passive choke has zero HF ripple.
    H_ripple_Oe = None
    B_ripple_T = None
    ripple_pp = result.I_ripple_pk_pk_A
    if ripple_pp > 0.01 * max(I_pk, 1e-6):
        # Place the ripple at the line phase where the ripple is largest. For
        # boost CCM with worst-case low line, that's typically near the line
        # peak (where vin · D · (1 − D) maximises). Use 0.7 · I_pk as a robust
        # generic placement (no need to refit topology).
        iL_center = 0.7 * I_pk
        iL_lo = max(iL_center - ripple_pp / 2, 0.0)
        iL_hi = iL_center + ripple_pp / 2
        H_lo = (N * iL_lo / le_m) * OE_PER_AM
        H_hi = (N * iL_hi / le_m) * OE_PER_AM
        H_ripple_Oe = np.linspace(H_lo, H_hi, n_ripple)
        B_ripple_T = B_anhysteretic_array_T(material, H_ripple_Oe)

    return {
        "H_static_Oe": H_static,
        "B_static_T": B_static,
        "H_envelope_Oe": H_env_Oe,
        "B_envelope_T": B_env_T,
        "H_ripple_Oe": H_ripple_Oe,
        "B_ripple_T": B_ripple_T,
        "H_pk_Oe": H_pk_Oe,
        "B_pk_T": float(B_env_T.max()),
        "Bsat_T": material.Bsat_100C_T,
    }
