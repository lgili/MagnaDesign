"""Acceptance Test Plan (ATP) — vendor-runnable per-unit tests.

Every magnetic component leaves a vendor with an ATP attached:
the rows the supplier's QC bench uses to either accept or
reject each finished unit. The ATP is the contract between
designer and supplier — without it, an RFQ comes back with
"please specify acceptance criteria".

Each row carries:

- **Test name** — engineer-readable label.
- **Condition** — input stimulus (frequency, bias, voltage).
- **Expected** — nominal value the engine predicted.
- **Tolerance** — ± band the unit must hit.
- **Instrument** — generic instrument class (LCR, hi-pot tester,
  ohmmeter, megger). Specific make/model is the vendor's choice.

The list below covers the standard six rows for an inductor.
Compliance-grade designs add hi-pot dwell + IR @ HV (handled
inline because every class needs them).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pfc_inductor.manufacturing.insulation_stack import (
    hipot_voltage_V,
    pick_insulation_class,
)
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire


@dataclass(frozen=True)
class AcceptanceTest:
    """One acceptance-test row in the FAT plan."""

    name: str
    """Test name (``"Inductance"`` / ``"DC resistance"``…)."""

    condition: str
    """Stimulus the bench applies (``"100 kHz, 0 A bias"``)."""

    expected: str
    """Nominal value the unit must read (engine-predicted)."""

    tolerance: str
    """Acceptance band (``"±10 %"`` or ``"max 0.45 Ω"``)."""

    instrument: str
    """Generic instrument class (``"LCR meter"`` / ``"Hi-pot tester"``)."""


def build_acceptance_tests(
    *,
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
) -> list[AcceptanceTest]:
    """Return the standard six-row ATP for an inductor design.

    Tolerances follow the conservative Pulse / Würth guideline
    set: ±10 % on inductance (loose enough to absorb AL spread
    without a calibrated standard), ±15 % on resistance (wire
    diameter + temperature compensation), ±10 % on Bsat-bias
    inductance. Override per-row by hand-editing the returned
    list when the customer's spec demands tighter bands.
    """
    L_uH = max(result.L_actual_uH, 0.0)
    R_ohm = _winding_resistance_ohm(wire, result)
    work_voltage = _working_voltage_V(spec)
    insulation = pick_insulation_class(T_winding_C=result.T_winding_C)
    hipot_V = hipot_voltage_V(work_voltage)

    rows: list[AcceptanceTest] = []

    # 1. Inductance — small-signal at 100 kHz, no bias.
    rows.append(AcceptanceTest(
        name="Inductance",
        condition="100 kHz, 0 A DC bias, 0.5 V AC",
        expected=f"{L_uH:.1f} µH",
        tolerance="±10 %",
        instrument="LCR meter (HP 4284A or equivalent)",
    ))

    # 2. Inductance under DC bias — drops with rolloff. The
    # engine reports peak as ``I_pk_max_A`` (boost / line-reactor)
    # or — for buck — falls back to the rms estimate. Use any
    # finite peak field we can find.
    i_pk = (
        getattr(result, "I_pk_max_A", None)
        or getattr(result, "I_line_pk_A", None)
        or getattr(result, "I_pk_A", None)
        or 0.0
    )
    if i_pk and L_uH > 0:
        bias = round(0.7 * float(i_pk), 2)
        # Approximate the biased L: at 70 % of I_pk, the rolloff
        # has typically dropped to 70-90 % of the no-bias value
        # for the materials we ship. Use the engine's L_actual
        # as a stand-in for the small-signal-at-bias number; the
        # vendor's LCR will report the real figure and the ±20 %
        # tolerance absorbs the discrepancy.
        rows.append(AcceptanceTest(
            name="Inductance @ DC bias",
            condition=f"100 kHz, {bias:.2f} A DC bias",
            expected=f"≥ {L_uH * 0.7:.1f} µH",
            tolerance="±20 % (rolloff envelope)",
            instrument="LCR meter with DC-bias accessory",
        ))

    # 3. DC resistance.
    rows.append(AcceptanceTest(
        name="DC resistance",
        condition="20 °C ambient, 4-wire Kelvin",
        expected=f"{R_ohm * 1000.0:.1f} mΩ"
                 if R_ohm < 1.0 else f"{R_ohm:.3f} Ω",
        tolerance="±15 %",
        instrument="Micro-ohmmeter (4-wire, ≥ 100 mA test)",
    ))

    # 4. Hi-pot — production safety check.
    rows.append(AcceptanceTest(
        name="Hi-pot",
        condition=(
            f"{hipot_V:.0f} V AC, "
            f"{insulation.hipot_dwell_s:.0f} s dwell, "
            f"winding ↔ core"
        ),
        expected="No breakdown, no flashover",
        tolerance=f"Leakage < 1 mA ({insulation.name})",
        instrument="Hi-pot tester (5 kV AC range)",
    ))

    # 5. Insulation resistance.
    rows.append(AcceptanceTest(
        name="Insulation resistance",
        condition="500 V DC, winding ↔ core",
        expected="≥ 100 MΩ",
        tolerance="No upper limit",
        instrument="Megger (insulation tester)",
    ))

    # 6. Visual + dimensional.
    rows.append(AcceptanceTest(
        name="Visual + dimensional",
        condition="Per drawing tolerances",
        expected="No varnish runs, no chipped core, "
                 "lead positions within ±0.5 mm",
        tolerance="MIL-STD-883 method 2009.10",
        instrument="Caliper, 10× loupe",
    ))

    return rows


def _winding_resistance_ohm(wire: Wire, result: DesignResult) -> float:
    """Pull the winding resistance off the engine's result if
    present, fall back to the engine's ``losses.R_dc_ohm`` field
    when present. Returns 0.0 only when both paths fail — the
    ATP row degrades gracefully to ``"0 mΩ"`` instead of crashing.
    """
    candidate = getattr(result, "R_dc_ohm", None)
    if isinstance(candidate, (int, float)) and candidate > 0:
        return float(candidate)
    losses = getattr(result, "losses", None)
    if losses is not None:
        candidate = getattr(losses, "R_dc_ohm", None)
        if isinstance(candidate, (int, float)) and candidate > 0:
            return float(candidate)
    return 0.0


def _working_voltage_V(spec: Spec) -> float:
    """Resolve a "working voltage" for the hi-pot calculator.

    The standard is silent on which V to plug in for an inductor
    that sits across an AC line vs. a buck switch node; we use:

    - DC-DC topologies: the bus voltage (Vin_dc_V or Vout_V).
    - AC-input topologies: the peak-of-Vin_max (worst-case
      mains envelope).
    """
    topology = (spec.topology or "").lower()
    if topology == "buck_ccm":
        return float(getattr(spec, "Vin_dc_V", None) or
                     getattr(spec, "Vin_dc_max_V", None) or
                     getattr(spec, "Vin_nom_Vrms", None) or
                     0.0)
    # AC topologies — peak of Vin_max.
    vmax = float(getattr(spec, "Vin_max_Vrms", None) or 0.0)
    if vmax > 0:
        return vmax * (2 ** 0.5)
    return float(getattr(spec, "Vin_nom_Vrms", None) or 0.0) * (2 ** 0.5)
