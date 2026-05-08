"""Metric definitions and per-metric "better/worse" semantics for diff colouring.

The leftmost column is the reference. Every other column's metric value is
classified relative to it: "better" if the change is in the favourable
direction, "worse" otherwise, "neutral" if equal or if the metric carries
no preference (e.g. raw line current — that's a function of spec, not a
design choice).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pfc_inductor.compare.slot import CompareSlot

DiffKind = Literal["better", "worse", "neutral"]


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    unit: str
    fmt: str
    direction: Literal["lower", "higher", "neutral"]

    def value_of(self, slot: CompareSlot) -> float:
        r = slot.result
        # Direct attributes, with a few derived ones.
        if hasattr(r, self.key):
            return float(getattr(r, self.key))
        if hasattr(r.losses, self.key):
            return float(getattr(r.losses, self.key))
        if self.key == "Volume_cm3":
            return slot.core.Ve_mm3 / 1000.0
        if self.key == "Window_use_pct":
            return r.Ku_actual * 100.0
        raise KeyError(f"Unknown metric: {self.key}")

    def format(self, slot: CompareSlot) -> str:
        return self.fmt.format(self.value_of(slot))


METRICS: list[MetricDef] = [
    MetricDef("L_actual_uH",       "L actual",           "µH",    "{:.0f}", "neutral"),
    MetricDef("N_turns",           "Turns N",            "",      "{:.0f}", "lower"),
    MetricDef("mu_pct_at_peak",    "μ% at peak",         "",      "{:.2f}", "higher"),
    MetricDef("Volume_cm3",        "Volume",             "cm³",   "{:.1f}", "lower"),
    MetricDef("I_line_pk_A",       "I line peak",        "A",     "{:.2f}", "neutral"),
    MetricDef("I_line_rms_A",      "I line RMS",         "A",     "{:.2f}", "neutral"),
    MetricDef("I_ripple_pk_pk_A",  "Ripple max pp",      "A",     "{:.2f}", "lower"),
    MetricDef("I_pk_max_A",        "I peak total",       "A",     "{:.2f}", "lower"),
    MetricDef("H_dc_peak_Oe",      "H peak DC",          "Oe",    "{:.0f}", "lower"),
    MetricDef("B_pk_T",            "B peak",             "T",     "{:.3f}", "lower"),
    MetricDef("sat_margin_pct",    "Bsat margin",        "%",     "{:.0f}", "higher"),
    MetricDef("R_dc_ohm",          "Rdc",                "Ω",     "{:.4f}", "lower"),
    MetricDef("R_ac_ohm",          "Rac @ fsw",          "Ω",     "{:.4f}", "lower"),
    MetricDef("P_cu_dc_W",         "P Cu DC",            "W",     "{:.2f}", "lower"),
    MetricDef("P_cu_ac_W",         "P Cu AC",            "W",     "{:.3f}", "lower"),
    MetricDef("P_core_line_W",     "P core (line)",      "W",     "{:.3f}", "lower"),
    MetricDef("P_core_ripple_W",   "P core (ripple)",    "W",     "{:.3f}", "lower"),
    MetricDef("P_total_W",         "P total",            "W",     "{:.2f}", "lower"),
    MetricDef("T_rise_C",          "ΔT",                 "K",     "{:.0f}", "lower"),
    MetricDef("T_winding_C",       "T winding",          "°C",    "{:.0f}", "lower"),
    MetricDef("Window_use_pct",    "Window util. Ku",    "%",     "{:.1f}", "lower"),
]


# Lookup tables for quick categorize() use.
_DIRECTION_BY_KEY = {m.key: m.direction for m in METRICS}


def categorize(metric_key: str, leftmost: float, this: float,
               rel_eps: float = 1e-3) -> DiffKind:
    """Classify `this` vs `leftmost` according to metric semantics."""
    if abs(this - leftmost) <= max(abs(leftmost), 1.0) * rel_eps:
        return "neutral"
    direction = _DIRECTION_BY_KEY.get(metric_key, "neutral")
    if direction == "lower":
        return "better" if this < leftmost else "worse"
    if direction == "higher":
        return "better" if this > leftmost else "worse"
    return "neutral"
