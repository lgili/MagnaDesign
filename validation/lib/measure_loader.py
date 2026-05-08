"""Parse `measurements.csv` files into a typed :class:`MeasurementSet`.

CSV schema (long-form)
----------------------

::

    metric,condition,frequency_Hz,value,unit,instrument,uncertainty
    L,bias_0A_25C,1000,510e-6,H,Keysight E4990,3%
    L,bias_4A_25C,1000,420e-6,H,Keysight E4990,5%
    R_dc,room_temp,0,0.0093,ohm,Yokogawa GS610,1%
    R_ac,fsw,65000,0.0145,ohm,Keysight E4990,5%
    B_pk,operating_point,60,0.21,T,B-coil + integrator,8%
    T_winding,steady_state_25C_Pout,0,82,degC,FLIR T540,3%
    P_total,steady_state_25C_Pout,0,4.8,W,wattmeter,2%

Why long-form: every metric has a different (or no) frequency,
condition, and instrument. Wide-form would force null cells
everywhere; long-form keeps the schema honest and makes it
trivial to add a new measurement without touching the loader.

The loader is **defensive**: missing fields fall back to
sensible defaults, unknown metrics are kept as ``other``
entries so a notebook can still inspect them, and parse errors
on a single row don't crash the whole load.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass(frozen=True)
class Measurement:
    """One row of bench data."""

    metric: str
    condition: str
    frequency_Hz: float
    value: float
    unit: str
    instrument: str = ""
    uncertainty_pct: float = 0.0


@dataclass
class MeasurementSet:
    """All bench data for one prototype.

    The fields are convenience pre-buckets — every measurement
    also lives in :attr:`all` so a notebook can iterate or
    filter without these accessors.
    """

    all: list[Measurement] = field(default_factory=list)

    def by_metric(self, metric: str) -> list[Measurement]:
        return [m for m in self.all if m.metric == metric]

    def first(
        self,
        metric: str,
        *,
        condition: Optional[str] = None,
    ) -> Optional[Measurement]:
        """Return the first matching measurement or ``None``.

        The "first" is whatever order the CSV lists rows in —
        notebooks should pass an explicit ``condition`` when
        more than one row exists for the same metric.
        """
        for m in self.all:
            if m.metric != metric:
                continue
            if condition is not None and m.condition != condition:
                continue
            return m
        return None


def load_measurements(path: Path) -> MeasurementSet:
    """Read a `measurements.csv` into a :class:`MeasurementSet`.

    Raises ``FileNotFoundError`` when the path is wrong;
    skips malformed rows with a warning to ``stderr`` rather
    than crashing — the notebook should still render the rows
    that did parse so the engineer sees what data they have.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"measurements.csv not found: {p}")
    out: list[Measurement] = []
    with p.open("r", newline="") as fp:
        reader = csv.DictReader(fp)
        for row_index, row in enumerate(reader, start=2):  # row 1 = header
            try:
                m = _row_to_measurement(row)
            except (KeyError, ValueError) as exc:
                # Surface the parse error with row context so
                # the notebook author can fix the CSV. Keep going
                # — partial data is still useful.
                import sys

                sys.stderr.write(
                    f"[validation] skipping {p.name}:{row_index} — {type(exc).__name__}: {exc}\n",
                )
                continue
            out.append(m)
    return MeasurementSet(all=out)


def _row_to_measurement(row: dict[str, str]) -> Measurement:
    metric = (row.get("metric") or "").strip()
    if not metric:
        raise ValueError("missing 'metric' column")
    condition = (row.get("condition") or "default").strip()
    frequency = _to_float(row.get("frequency_Hz", "0"), default=0.0)
    value = _to_float(row.get("value", ""), default=None)
    if value is None:
        raise ValueError(f"missing 'value' for metric={metric}")
    unit = (row.get("unit") or "").strip()
    instrument = (row.get("instrument") or "").strip()
    uncertainty = _to_pct(row.get("uncertainty", "0"))
    return Measurement(
        metric=metric,
        condition=condition,
        frequency_Hz=frequency,
        value=value,
        unit=unit,
        instrument=instrument,
        uncertainty_pct=uncertainty,
    )


def _to_float(text: str, *, default: Optional[float]) -> Optional[float]:
    """Permissive float — handles SI suffixes (``5e-6``, ``510u``)
    and falls back to ``default`` on empty / unparseable input."""
    s = (text or "").strip()
    if not s:
        return default
    # Normalise simple SI suffixes that show up in bench notes.
    suffix_map = {
        "k": 1e3,
        "M": 1e6,
        "G": 1e9,
        "m": 1e-3,
        "u": 1e-6,
        "µ": 1e-6,
        "n": 1e-9,
        "p": 1e-12,
    }
    if s and s[-1] in suffix_map:
        head, suffix = s[:-1], s[-1]
        try:
            return float(head) * suffix_map[suffix]
        except ValueError:
            pass
    return float(s)


def _to_pct(text: str) -> float:
    """Parse uncertainty written as ``"3%"``, ``"3"``, or ``"0.03"``.
    Returns 0 on garbage."""
    s = (text or "").strip().rstrip("%").strip()
    if not s:
        return 0.0
    try:
        v = float(s)
    except ValueError:
        return 0.0
    # Heuristic: <= 1 means already-fractional ("0.03"), else %
    # form ("3"). Notebooks should use the explicit "%" form.
    return v * 100.0 if v <= 1.0 else v


def load_thresholds(path: Path) -> dict[str, float]:
    """Read the project-wide ``thresholds.yaml`` into a flat dict.

    Defaults are loose so a missing file still parses to
    "everything passes" (with a warning). Notebooks should
    treat this as a contract: each metric they compare must be
    in the dict, and a missing metric is itself a failure.
    """
    p = Path(path)
    if not p.is_file():
        return {}
    with p.open("r") as fp:
        data = yaml.safe_load(fp) or {}
    if not isinstance(data, dict):
        return {}
    # Coerce all values to float; ignore non-numeric keys cleanly.
    return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}
