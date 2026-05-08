"""UL 1411 — Class 2 / Class 3 magnetic-component limits.

UL 1411:2024 covers transformers and motor-supplies for use in
audio, radio, and television-type appliances. The MagnaDesign
catalogue includes line reactors and PFC chokes that ship into
US-region appliance products; for those a UL Class 2 / Class 3
classification ride along with the IEC compliance.

What this module covers
-----------------------

The two classifications most relevant to a PFC stage are:

- **Class 2** (Section 12) — power-limited circuits. Limits
  ``V_oc ≤ 30 Vrms`` (≤ 60 Vdc), ``I_sc ≤ 8 A``, ``V·A ≤ 100``.
  Applies to low-voltage rails downstream of the PFC stage; the
  *inductor* itself isn't usually Class 2 but the *secondary
  output* is.
- **Class 3** (Section 13) — high-voltage limited. ``V ≤ 100 Vrms
  / 150 Vdc``, ``V·A ≤ 100`` per circuit. Less common for PFC.

For the PFC stage itself UL 1411's relevant sections are:

- **Temperature rise limits** (§39.2). Class A insulation: 65 °C
  rise; Class B: 90 °C; Class F: 115 °C; Class H: 140 °C.
- **Hi-pot** (§40). Test voltage = 2 × V_working + 1000 V for
  60 s. Required for any winding above 30 V.
- **Insulation system** — must be UL-recognised per UL 1446.

This module ships an **analytical envelope check**: given the
engine's predicted thermal rise + the user's working voltage, it
verifies the design clears the standard's limits with margin.
Like EN 55032, it's a screening tool — final certification
needs the underwriter's lab.

Public API
----------

- :class:`UlClass1411` — A / B / F / H insulation enum.
- :func:`evaluate` — main entry. Returns an
  ``UlReport``-shaped result the dispatcher consumes.
- :func:`hipot_test_voltage` — ``2 × V_work + 1000 V`` per §40.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


InsulationClass = Literal["A", "B", "F", "H"]


# Per-class temperature-rise limits per UL 1411:2024 §39.2.
# Values are *rise above ambient*, not absolute temperatures.
_TEMP_RISE_LIMITS_C: dict[InsulationClass, float] = {
    "A": 65.0,    # 105 °C absolute - 40 °C ambient = 65 °C rise
    "B": 90.0,    # 130 °C abs
    "F": 115.0,   # 155 °C abs
    "H": 140.0,   # 180 °C abs
}


def temperature_rise_limit_C(insulation_class: InsulationClass) -> float:
    """Return the maximum allowed winding temperature *rise*
    above ambient for the given UL 1411 insulation class."""
    return _TEMP_RISE_LIMITS_C[insulation_class]


def hipot_test_voltage(working_voltage_Vrms: float) -> float:
    """UL 1411 §40 hi-pot test voltage.

    Formula: ``2 × V_working + 1000 V`` (60 s). Applies to any
    winding above 30 V; for windings below 30 V the test is
    typically waived but the calculator returns the same number
    so callers don't have to special-case.
    """
    return 2.0 * float(working_voltage_Vrms) + 1000.0


@dataclass
class UlReport:
    """Aggregate UL 1411 evaluation."""

    insulation_class: InsulationClass
    working_voltage_Vrms: float

    temperature_rise_C: float
    """Engine-predicted ΔT for the design."""

    temperature_rise_limit_C: float

    hipot_voltage_Vrms: float
    """``2 × V_work + 1000 V`` per §40."""

    margin_to_temperature_limit_C: float
    """Positive = under the limit; negative = over."""

    passes_temperature: bool
    passes_hipot_required: bool
    """True when V_working > 30 V → hi-pot is a release-gate
    requirement. The actual test is a fab/lab step; this flag
    just surfaces whether it's needed."""

    notes: list[str] = field(default_factory=list)


def evaluate(
    *,
    insulation_class: InsulationClass = "B",
    temperature_rise_C: float,
    working_voltage_Vrms: float,
    ambient_temperature_C: float = 40.0,
) -> UlReport:
    """Run the UL 1411 envelope check.

    Args:
        insulation_class: A / B / F / H per UL 1411:2024 §39.2.
            Default ``B`` matches the typical 130 °C-rated
            magnet wire used in appliance-grade PFC chokes.
        temperature_rise_C: ``DesignResult.T_rise_C`` — the
            engine's predicted winding rise above ambient at
            the worst-case operating point.
        working_voltage_Vrms: RMS voltage on the inductor's
            highest-stressed winding. For a single-winding
            choke this is the input AC RMS; for transformers
            it would be the primary V_rms.
        ambient_temperature_C: Reference ambient. UL 1411 tests
            at 25 °C ambient; the spec uses 40 °C by default.
            We accept either and adjust the rise limit
            accordingly (the rise envelope is independent of
            the ambient choice).

    Returns:
        :class:`UlReport` — pass/fail flags + the headline
        margins + the hi-pot test voltage the user's lab will
        need to apply.
    """
    rise_limit = temperature_rise_limit_C(insulation_class)
    margin = rise_limit - float(temperature_rise_C)
    passes_temp = float(temperature_rise_C) <= rise_limit
    hipot = hipot_test_voltage(working_voltage_Vrms)
    needs_hipot = float(working_voltage_Vrms) > 30.0

    notes: list[str] = [
        (
            f"Insulation class {insulation_class}: "
            f"max winding rise {rise_limit:.0f} °C above ambient "
            f"per UL 1411:2024 §39.2."
        ),
        (
            f"Hi-pot test voltage = 2·V_work + 1000 = "
            f"{hipot:.0f} Vrms for 60 s per §40."
        ),
    ]
    if not needs_hipot:
        notes.append(
            "Working voltage ≤ 30 V — hi-pot test typically "
            "waived per UL 1411:2024 §40.1, but the lab may "
            "still require an insulation-resistance check.",
        )
    if not passes_temp:
        notes.append(
            f"FAIL: temperature rise {temperature_rise_C:.0f} °C "
            f"exceeds the {insulation_class}-class limit "
            f"({rise_limit:.0f} °C). Step up to a higher "
            f"insulation class (A→B→F→H) or reduce losses."
        )
    notes.append(
        "Final UL 1411 certification requires submission to "
        "an underwriters' lab — this envelope check is a "
        "design-stage screening tool, not a substitute for "
        "the formal evaluation.",
    )

    return UlReport(
        insulation_class=insulation_class,
        working_voltage_Vrms=float(working_voltage_Vrms),
        temperature_rise_C=float(temperature_rise_C),
        temperature_rise_limit_C=rise_limit,
        hipot_voltage_Vrms=hipot,
        margin_to_temperature_limit_C=float(margin),
        passes_temperature=bool(passes_temp),
        passes_hipot_required=bool(needs_hipot),
        notes=notes,
    )
