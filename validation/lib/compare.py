"""Predicted-vs-measured comparator.

Given a :class:`DesignResult` from the engine and a
:class:`MeasurementSet` from the bench, produce one
:class:`MetricComparison` per metric the threshold file lists.
The notebook's last cell renders the list as a table and emits
the PASS/FAIL summary CI keys on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pfc_inductor.models import DesignResult

from validation.lib.measure_loader import MeasurementSet


# Map threshold-key → (metric_in_csv, predicted_lookup,
#                      kind: "pct" | "abs", short_label).
#
# ``predicted_lookup`` knows how to pull the value off a
# ``DesignResult`` — handles nested access (e.g. losses.P_cu_total_W)
# and unit conversion (T → mT) where the bench convention differs.
_METRIC_MAP: dict[str, tuple[str, str, str, str]] = {
    "inductance_pct":       ("L",         "L_actual_uH * 1e-6",          "pct", "L"),
    "flux_density_pct":     ("B_pk",      "B_pk_T",                      "pct", "B_pk"),
    "temperature_C":        ("T_winding", "T_winding_C",                 "abs", "T_winding"),
    "copper_loss_pct":      ("P_cu",      "losses.P_cu_total_W",          "pct", "P_cu"),
    "core_loss_pct":        ("P_core",    "losses.P_core_total_W",        "pct", "P_core"),
    "total_loss_pct":       ("P_total",   "losses.P_total_W",             "pct", "P_total"),
    "ac_resistance_pct":    ("R_ac",      "R_ac_ohm",                     "pct", "R_ac"),
}


@dataclass(frozen=True)
class MetricComparison:
    """One predicted-vs-measured row."""

    metric: str
    """Short label used in the report ("L", "B_pk", "T_winding")."""

    predicted: float
    measured: float
    unit: str

    threshold: float
    """Per-metric tolerance. Interpreted as a percentage band
    (``kind == "pct"``) or absolute delta (``kind == "abs"``)."""

    kind: str  # "pct" | "abs"
    delta: float
    """Signed difference: ``predicted - measured`` for ``abs``,
    ``(predicted - measured) / measured × 100`` for ``pct``."""

    passed: bool

    note: str = ""
    """Free-form note (e.g. "B-coil integrator drift suspected")."""


@dataclass(frozen=True)
class PassFailSummary:
    n_total: int
    n_passed: int
    failures: tuple[MetricComparison, ...]

    @property
    def all_passed(self) -> bool:
        return self.n_total > 0 and self.n_passed == self.n_total


def compare(
    result: DesignResult,
    measurements: MeasurementSet,
    thresholds: dict[str, float],
) -> tuple[list[MetricComparison], PassFailSummary]:
    """Run every threshold the project ships against the engine
    output + bench data. Skips metrics absent from either side
    (with a comparison entry tagged "skipped" so the notebook
    can flag missing data)."""
    comparisons: list[MetricComparison] = []
    failures: list[MetricComparison] = []

    for threshold_key, value in thresholds.items():
        spec = _METRIC_MAP.get(threshold_key)
        if spec is None:
            # Unknown threshold key — surface as a no-op entry so
            # the notebook doesn't silently drop it.
            comparisons.append(MetricComparison(
                metric=threshold_key, predicted=float("nan"),
                measured=float("nan"), unit="?",
                threshold=value, kind="pct",
                delta=float("nan"), passed=False,
                note="unknown threshold key",
            ))
            continue

        metric_in_csv, predicted_path, kind, label = spec
        bench = measurements.first(metric_in_csv)
        if bench is None:
            comparisons.append(MetricComparison(
                metric=label, predicted=float("nan"),
                measured=float("nan"), unit="—",
                threshold=value, kind=kind,
                delta=float("nan"), passed=False,
                note="no measurement",
            ))
            continue

        predicted = _eval_predicted(predicted_path, result)
        measured = float(bench.value)
        unit = bench.unit or "—"

        if kind == "pct":
            delta = (
                (predicted - measured) / measured * 100.0
                if measured != 0 else float("nan")
            )
            passed = abs(delta) <= value
        else:  # "abs"
            delta = predicted - measured
            passed = abs(delta) <= value

        cmp = MetricComparison(
            metric=label,
            predicted=predicted,
            measured=measured,
            unit=unit,
            threshold=value,
            kind=kind,
            delta=delta,
            passed=passed,
        )
        comparisons.append(cmp)
        if not passed:
            failures.append(cmp)

    summary = PassFailSummary(
        n_total=len(comparisons),
        n_passed=sum(1 for c in comparisons if c.passed),
        failures=tuple(failures),
    )
    return comparisons, summary


def _eval_predicted(path: str, result: DesignResult) -> float:
    """Evaluate a small DSL describing how to pull a number off
    the ``DesignResult``. Supported shapes:

    - ``"attr"`` — single attribute access.
    - ``"obj.attr"`` — one nested step (``losses.P_cu_total_W``).
    - ``"attr * 1e-6"`` — attribute scaled by a literal.

    Anything more complex would justify either extending the DSL
    or adding a callable column to ``_METRIC_MAP``; for now this
    covers every metric the threshold file ships with.
    """
    expr = path.strip()
    scale = 1.0
    if " * " in expr:
        attr_part, scale_part = expr.split(" * ", 1)
        scale = float(scale_part.strip())
        expr = attr_part.strip()
    if "." in expr:
        head, tail = expr.split(".", 1)
        obj = getattr(result, head, None)
        if obj is None:
            return float("nan")
        value = getattr(obj, tail, None)
    else:
        value = getattr(result, expr, None)
    if not isinstance(value, (int, float)):
        return float("nan")
    return float(value) * scale


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------
def render_summary(
    comparisons: list[MetricComparison],
    summary: PassFailSummary,
    *,
    project_label: str = "",
) -> str:
    """Format the comparison list as a fixed-width table the
    notebook's last cell can drop into a Markdown ``%%text``
    block. Designed to render readably in plain stdout too —
    handy for ``magnadesign validate`` once that subcommand
    lands."""
    lines: list[str] = []
    if project_label:
        lines.append(f"# {project_label} — predicted vs. measured")
        lines.append("")
    header = (
        f"{'metric':12s}  {'predicted':>12s}  {'measured':>12s}  "
        f"{'delta':>10s}  {'thresh':>8s}  result"
    )
    lines.append(header)
    lines.append("-" * len(header))

    for c in comparisons:
        if c.kind == "pct":
            delta_text = f"{c.delta:+.2f} %" if c.delta == c.delta else "n/a"
            thresh_text = f"±{c.threshold:.0f} %"
        else:
            delta_text = (
                f"{c.delta:+.2f} {c.unit}"
                if c.delta == c.delta else "n/a"
            )
            thresh_text = f"±{c.threshold:.0f} {c.unit}"

        if c.passed:
            mark = "✓ PASS"
        elif c.note:
            mark = f"⊘ SKIP ({c.note})"
        else:
            mark = "✗ FAIL"

        pred_text = (
            f"{c.predicted:.3g} {c.unit}"
            if c.predicted == c.predicted else "n/a"
        )
        meas_text = (
            f"{c.measured:.3g} {c.unit}"
            if c.measured == c.measured else "n/a"
        )
        lines.append(
            f"{c.metric:12s}  {pred_text:>12s}  {meas_text:>12s}  "
            f"{delta_text:>10s}  {thresh_text:>8s}  {mark}"
        )

    lines.append("")
    if summary.all_passed:
        lines.append(
            f"verdict: ✓ PASS  ({summary.n_passed} of "
            f"{summary.n_total} metrics)",
        )
    else:
        lines.append(
            f"verdict: ✗ FAIL  ({summary.n_passed} of "
            f"{summary.n_total} metrics, "
            f"{len(summary.failures)} regressions)",
        )
    return "\n".join(lines)
