"""IEC 61000-3-2 Class D harmonic-emission limits.

Class D applies to single-phase equipment ≤ 16 A per phase whose input
current waveform falls inside the special envelope (PCs, TVs, lighting,
diode-rectifier+cap drives — the population this app's reactors target).

Per-harmonic limit:

    limit_n = min(Factor_n[mA/W] · Pi[W] / 1000, abs_limit_n[A])

Factors and absolute limits come from Table 3 (n = 3, 5, 7, 9, 11) plus
the n = 13..39 (odd) extension. The numerator of the extension differs
between editions:

- Edition 4.0 / 5.0 (≤ 2018): 3.85 / n
- Edition 5.0 (post-2018):    3.65 / n

The single-source authority on these numbers is the OpenMagnetics-style
spreadsheet in ``../extrator_harmonicos/src/logic/iec.py``; this module
mirrors those formulas.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Iterable, Literal, Optional


Edition = Literal["4.0", "5.0"]


# ---------------------------------------------------------------------------
# Table 3 — fixed factors and absolute limits for n in {3, 5, 7, 9, 11}
# ---------------------------------------------------------------------------
LIMIT_FACTORS_FIXED_MA_W: Dict[int, float] = {
    3: 3.4, 5: 1.9, 7: 1.0, 9: 0.5, 11: 0.35,
}
ABS_LIMITS_FIXED_A: Dict[int, float] = {
    3: 2.30, 5: 1.14, 7: 0.77, 9: 0.40, 11: 0.33,
}

# Default reference voltage and power factor used by the IEC test setup.
# The standard specifies 230 V (Vr) and pf_normalized = 0.78.
DEFAULT_PF_NORMALIZED = 0.78
DEFAULT_VR = 230.0
DEFAULT_EDITION: Edition = "4.0"

# Class D applies to odd harmonics 3..39.
ODD_HARMONICS: list[int] = list(range(3, 40, 2))


def factor_per_watt_ma(n: int, edition: Edition = DEFAULT_EDITION) -> float:
    """mA/W factor for harmonic ``n``.

    For n ∈ {3, 5, 7, 9, 11} the value is fixed. For higher odd
    harmonics the factor decays as ``num/n`` where the numerator
    differs by edition (3.85 in 4.0, 3.65 in 5.0).
    """
    if n in LIMIT_FACTORS_FIXED_MA_W:
        return LIMIT_FACTORS_FIXED_MA_W[n]
    numerator = 3.65 if str(edition) == "5.0" else 3.85
    return numerator / n


def absolute_limit_a(n: int) -> float:
    """Absolute current limit (A) for harmonic ``n``."""
    if n in ABS_LIMITS_FIXED_A:
        return ABS_LIMITS_FIXED_A[n]
    return 0.15 * 15 / n   # 2.25 / n


def class_d_limits(
    Pi_W: float, edition: Edition = DEFAULT_EDITION,
    *, harmonics: Optional[Iterable[int]] = None,
) -> Dict[int, float]:
    """Per-harmonic Class D limit (A) for the supplied input power.

    ``Pi_W`` is the rated input active power. ``harmonics`` defaults to
    odd 3..39.
    """
    orders = list(harmonics) if harmonics is not None else ODD_HARMONICS
    out: Dict[int, float] = {}
    for n in orders:
        relative = (factor_per_watt_ma(n, edition) / 1000.0) * float(Pi_W)
        out[n] = min(relative, absolute_limit_a(n))
    return out


# ---------------------------------------------------------------------------
# Compliance evaluation
# ---------------------------------------------------------------------------
@dataclass
class HarmonicCheck:
    n: int
    measured_A: float
    limit_A: float
    margin_pct: float        # (limit - measured) / limit · 100; negative = over
    passes: bool


@dataclass
class ComplianceReport:
    Pi_W: float
    edition: Edition
    checks: list[HarmonicCheck] = field(default_factory=list)
    limiting_harmonic: Optional[int] = None
    margin_min_pct: float = 0.0    # smallest margin across all harmonics
    passes: bool = True

    def by_order(self) -> Dict[int, HarmonicCheck]:
        return {c.n: c for c in self.checks}


def evaluate_compliance(
    harmonics_A: Dict[int, float],
    Pi_W: float,
    edition: Edition = DEFAULT_EDITION,
) -> ComplianceReport:
    """Compare each measured harmonic against its Class D limit.

    ``harmonics_A`` maps harmonic order → RMS current in amperes. Only
    odd harmonics in ``ODD_HARMONICS`` are evaluated; the rest are
    ignored.
    """
    limits = class_d_limits(Pi_W, edition)
    checks: list[HarmonicCheck] = []
    margin_min = float("inf")
    limiting_n: Optional[int] = None
    passes = True
    for n in ODD_HARMONICS:
        meas = harmonics_A.get(n)
        if meas is None:
            continue
        lim = limits.get(n)
        if lim is None or lim <= 0:
            continue
        margin = (lim - meas) / lim * 100.0
        chk = HarmonicCheck(
            n=n, measured_A=float(meas), limit_A=float(lim),
            margin_pct=margin, passes=meas <= lim,
        )
        checks.append(chk)
        if not chk.passes:
            passes = False
        if margin < margin_min:
            margin_min = margin
            limiting_n = n
    return ComplianceReport(
        Pi_W=float(Pi_W), edition=edition,
        checks=checks,
        limiting_harmonic=limiting_n,
        margin_min_pct=margin_min if margin_min != float("inf") else 0.0,
        passes=passes,
    )
