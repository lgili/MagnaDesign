"""Compliance standards for harmonic emissions.

Currently shipped: IEC 61000-3-2 Class D (single-phase equipment ≤ 16 A
per phase). Class A and Class C will live alongside when needed.

Public API:
    from pfc_inductor.standards import iec61000_3_2 as iec
    limits_A = iec.class_d_limits(Pi_W=400)
    pf_check = iec.evaluate_compliance(harmonics_A, Pi_W=400)
"""
from pfc_inductor.standards import iec61000_3_2

__all__ = ["iec61000_3_2"]
