"""Insulation system — class lookup + hi-pot calculator.

Per IEC 60085, every magnetic component is assigned a thermal
class that fixes the maximum continuous winding temperature:

- **Class A** (105 °C) — paper/cotton, basic kraft.
- **Class B** (130 °C) — Mylar / Mylar-Nomex laminate.
- **Class F** (155 °C) — Nomex 410 + polyester glass.
- **Class H** (180 °C) — Kapton / Nomex 411.

The chosen class drives:

- Tape between layers (Mylar / Nomex / Kapton thickness).
- Wire enamel grade (Class 200 / 220 magnet wire).
- Hi-pot test voltage (per IEC 61558: ``V_hipot = 2·V_work + 1000``).

The selector picks the lowest class whose limit comfortably
exceeds the engine's ``T_winding_C`` plus a 10 °C engineering
margin — bumping margin up trades cost vs. headroom.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Thermal-class identifiers per IEC 60085.
_ClassId = Literal["A", "B", "F", "H"]


@dataclass(frozen=True)
class InsulationClass:
    """One thermal class as catalogued in IEC 60085 + 61558."""

    id: _ClassId
    name: str
    """Human-readable name (``"Class B"`` etc.)."""

    T_max_C: float
    """Maximum continuous winding temperature (°C, IEC 60085)."""

    inter_layer_tape: str
    """Material name for the dielectric tape between layers."""

    inter_layer_tape_mm: float
    """Recommended tape thickness (mm)."""

    enamel_grade: str
    """Wire-enamel grade (``"Class 130"`` etc.)."""

    hipot_dwell_s: float
    """Hi-pot dwell time at the calculated voltage (s)."""


INSULATION_CLASSES: dict[str, InsulationClass] = {
    "A": InsulationClass(
        id="A", name="Class A", T_max_C=105.0,
        inter_layer_tape="Kraft paper",
        inter_layer_tape_mm=0.05,
        enamel_grade="Class 105",
        hipot_dwell_s=60.0,
    ),
    "B": InsulationClass(
        id="B", name="Class B", T_max_C=130.0,
        inter_layer_tape="Mylar polyester",
        inter_layer_tape_mm=0.05,
        enamel_grade="Class 130",
        hipot_dwell_s=60.0,
    ),
    "F": InsulationClass(
        id="F", name="Class F", T_max_C=155.0,
        inter_layer_tape="Nomex 410",
        inter_layer_tape_mm=0.07,
        enamel_grade="Class 155",
        hipot_dwell_s=60.0,
    ),
    "H": InsulationClass(
        id="H", name="Class H", T_max_C=180.0,
        inter_layer_tape="Kapton polyimide",
        inter_layer_tape_mm=0.10,
        enamel_grade="Class 180/200",
        hipot_dwell_s=60.0,
    ),
}


# Engineering margin between the engine's predicted winding temp
# and the class limit. 10 °C tracks the standard rule of thumb
# (Pulse / Würth design guides) — promotes the design out of any
# class where the winding sits within 10 °C of the limit.
_DEFAULT_MARGIN_C = 10.0


def pick_insulation_class(
    *,
    T_winding_C: float,
    margin_C: float = _DEFAULT_MARGIN_C,
) -> InsulationClass:
    """Return the lowest insulation class whose limit comfortably
    exceeds ``T_winding_C + margin_C``.

    Engineering bias: prefer the cheaper class when the headroom
    allows it — Class B tape costs ~30 % less than Class F.
    Always returns a class; ``T_winding > 180 °C`` falls back to
    Class H with an explicit caveat (the caller can layer their
    own warning on top).
    """
    if not isinstance(T_winding_C, (int, float)):
        T_winding_C = 0.0
    target = float(T_winding_C) + float(margin_C)
    for key in ("A", "B", "F", "H"):
        cls = INSULATION_CLASSES[key]
        if cls.T_max_C >= target:
            return cls
    # Above 180 °C — Class H is the highest the catalogue covers.
    return INSULATION_CLASSES["H"]


def hipot_voltage_V(V_work: float) -> float:
    """Hi-pot test voltage per IEC 61558 (``V_hipot = 2·V_work + 1000``).

    Floor at 1500 V to honour the standard's minimum acceptance
    voltage for low-V_work components.
    """
    if not isinstance(V_work, (int, float)) or V_work < 0:
        V_work = 0.0
    return max(1500.0, 2.0 * float(V_work) + 1000.0)
