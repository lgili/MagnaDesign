"""Validation library — predicted-vs-measured infrastructure.

Imported by every reference-design notebook to load the bench
data, run the same engine the GUI uses, and emit a PASS/FAIL
summary against the project-wide thresholds.

Public API
----------

- :class:`MeasurementSet` — typed container for one prototype's
  bench data (impedance sweep, B-coil capture, thermal map,
  line-cycle scope traces).
- :func:`load_measurements` — CSV → ``MeasurementSet``.
- :func:`load_thresholds` — YAML → flat dict.
- :class:`MetricComparison` — single predicted-vs-measured tuple.
- :func:`compare` — generate the full comparison list given a
  ``DesignResult`` and a ``MeasurementSet``.
- :func:`render_summary` — terminal-friendly table rendered by
  the notebook's last cell.
"""

from __future__ import annotations

from validation.lib.compare import (
    MetricComparison,
    PassFailSummary,
    compare,
    render_summary,
)
from validation.lib.measure_loader import (
    MeasurementSet,
    load_measurements,
    load_thresholds,
)

__all__ = [
    "MeasurementSet",
    "MetricComparison",
    "PassFailSummary",
    "compare",
    "load_measurements",
    "load_thresholds",
    "render_summary",
]
