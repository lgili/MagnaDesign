"""DC and AC copper loss for an inductor winding."""
from __future__ import annotations
import math

from pfc_inductor.models import Wire
from pfc_inductor.physics.dowell import (
    rho_cu, Rac_over_Rdc_round, Rac_over_Rdc_litz,
)


def length_total_m(N: int, MLT_mm: float) -> float:
    return N * MLT_mm * 1e-3


def Rdc_ohm(N: int, MLT_mm: float, A_cu_mm2: float, T_C: float) -> float:
    L_m = length_total_m(N, MLT_mm)
    A_m2 = A_cu_mm2 * 1e-6
    if A_m2 <= 0:
        return float("inf")
    return rho_cu(T_C) * L_m / A_m2


def Rac_ohm(
    wire: Wire,
    f_Hz: float,
    Rdc_value_ohm: float,
    layers: int = 1,
    T_C: float = 20.0,
) -> float:
    """AC resistance of the winding at frequency f."""
    if wire.type == "litz" and wire.d_strand_mm and wire.n_strands:
        Fr = Rac_over_Rdc_litz(
            wire.d_strand_mm * 1e-3, wire.n_strands, f_Hz, layers, T_C
        )
    elif wire.type == "round" and wire.d_cu_mm:
        Fr = Rac_over_Rdc_round(wire.d_cu_mm * 1e-3, f_Hz, layers, T_C)
    else:
        Fr = 1.0
    return Rdc_value_ohm * Fr


def estimate_layers(N: int, wire: Wire, Wa_mm2: float) -> int:
    """Estimate number of layers given turn count, wire diameter, and window area.

    For a toroid, this is rough (single-layer-equivalent often). For bobbin
    cores (ETD/EE), layers = ceil(N * d_iso / window_height).
    """
    d = wire.outer_diameter_mm()
    if d <= 0 or Wa_mm2 <= 0:
        return 1
    # Approximate window as square; layers = N*d / sqrt(Wa)
    window_side_mm = math.sqrt(Wa_mm2)
    if window_side_mm <= 0:
        return 1
    layers = max(1, int(math.ceil(N * d / window_side_mm)))
    return layers


def window_utilization(N: int, wire: Wire, Wa_mm2: float) -> float:
    """Ku = N * A_iso / Wa. Uses outer (insulated) diameter."""
    d_iso_mm = wire.outer_diameter_mm()
    A_iso_mm2 = math.pi * (d_iso_mm ** 2) / 4.0
    return (N * A_iso_mm2) / max(Wa_mm2, 1e-9)


def loss_dc_W(I_dc_rms_A: float, Rdc_ohm_val: float) -> float:
    return I_dc_rms_A * I_dc_rms_A * Rdc_ohm_val


def loss_ac_W(I_ac_rms_A: float, Rac_ohm_val: float) -> float:
    return I_ac_rms_A * I_ac_rms_A * Rac_ohm_val
