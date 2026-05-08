"""Validation library — measurement loader + comparator tests.

Exercises the Phase-1 software half of the
``add-validation-reference-set`` change without requiring any
real bench data. Once Phase 2 lands the actual
``validation/<id>/`` directories, papermill-driven CI tests will
take over the integration coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add repo root to ``sys.path`` so the validation lib imports
# cleanly regardless of pytest's working directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from validation.lib import (
    compare,
    load_measurements,
    load_thresholds,
    render_summary,
)
from validation.lib.measure_loader import _to_float, _to_pct


# ---------------------------------------------------------------------------
# Float / pct parsing — defensive against bench-note quirks
# ---------------------------------------------------------------------------
def test_to_float_parses_si_suffixes() -> None:
    assert _to_float("510u", default=None) == pytest.approx(510e-6)
    assert _to_float("65k", default=None) == pytest.approx(65_000.0)
    assert _to_float("3.3m", default=None) == pytest.approx(0.0033)


def test_to_float_parses_scientific_and_plain() -> None:
    assert _to_float("4.7e-6", default=None) == pytest.approx(4.7e-6)
    assert _to_float("0.5", default=None) == pytest.approx(0.5)
    assert _to_float("", default=42.0) == 42.0


def test_to_pct_handles_pct_sign_and_fraction() -> None:
    # Explicit "%" form
    assert _to_pct("3%") == pytest.approx(3.0)
    assert _to_pct("3 %") == pytest.approx(3.0)
    # Bare integer ≥ 1 is interpreted as % (matches bench notes)
    assert _to_pct("5") == pytest.approx(5.0)
    # Fraction-form ≤ 1 is converted to %
    assert _to_pct("0.03") == pytest.approx(3.0)
    # Garbage falls back to 0
    assert _to_pct("not a number") == 0.0


# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------
def test_load_measurements_parses_canonical_csv(tmp_path: Path) -> None:
    """A clean CSV in the canonical schema parses with no
    warnings and every row makes it through."""
    csv_path = tmp_path / "m.csv"
    csv_path.write_text(
        "metric,condition,frequency_Hz,value,unit,instrument,uncertainty\n"
        "L,bias_0A,1000,510e-6,H,Keysight E4990,3%\n"
        "L,bias_4A,1000,420u,H,Keysight E4990,5%\n"
        "B_pk,operating_point,60,0.21,T,B-coil + integrator,8%\n"
        "T_winding,steady_25C,0,82,degC,FLIR,3%\n"
        "P_total,steady_25C,0,4.8,W,wattmeter,2%\n",
    )
    ms = load_measurements(csv_path)
    assert len(ms.all) == 5
    # SI suffix on the AWG14 row is honoured.
    assert ms.by_metric("L")[1].value == pytest.approx(420e-6)
    # Convenience accessor returns the first match.
    assert ms.first("B_pk").value == pytest.approx(0.21)


def test_load_measurements_skips_malformed_rows_with_warning(
    tmp_path: Path,
    capsys,
) -> None:
    """A malformed row is logged to stderr and skipped — the
    notebook still gets the surviving rows. CI catches missing
    measurements via the comparator's "no measurement" entry,
    not via the loader."""
    csv_path = tmp_path / "broken.csv"
    csv_path.write_text(
        "metric,condition,frequency_Hz,value,unit,instrument,uncertainty\n"
        ",bias_0A,1000,510e-6,H,Keysight,3%\n"  # missing metric
        "L,bias_4A,1000,420e-6,H,Keysight,5%\n"
        "B_pk,operating_point,60,not-a-number,T,B-coil,8%\n"  # bad value
    )
    ms = load_measurements(csv_path)
    captured = capsys.readouterr()
    assert "skipping" in captured.err
    # Only the AWG14 line survived.
    assert len(ms.all) == 1
    assert ms.all[0].metric == "L"


def test_load_thresholds_returns_flat_float_dict(tmp_path: Path) -> None:
    yaml_path = tmp_path / "t.yaml"
    yaml_path.write_text(
        "inductance_pct: 5.0\ntemperature_C: 10\nlabel: not-a-float-keep-out\n",
    )
    out = load_thresholds(yaml_path)
    assert out == {"inductance_pct": 5.0, "temperature_C": 10.0}


def test_load_thresholds_missing_file_returns_empty(tmp_path: Path) -> None:
    """A missing thresholds.yaml degrades to "all-pass" rather
    than crashing the notebook. Documented in measure_loader.py."""
    out = load_thresholds(tmp_path / "does-not-exist.yaml")
    assert out == {}


# ---------------------------------------------------------------------------
# Comparator
# ---------------------------------------------------------------------------
def test_compare_marks_within_threshold_as_pass(
    reference_design,
) -> None:
    """A measurement that matches the engine output exactly
    must always pass (delta = 0)."""
    from pfc_inductor.design import design
    from validation.lib.measure_loader import Measurement, MeasurementSet

    spec, core, wire, mat = reference_design
    result = design(spec, core, wire, mat)

    measurements = MeasurementSet(
        all=[
            # T_winding match
            Measurement(
                metric="T_winding",
                condition="d",
                frequency_Hz=0,
                value=result.T_winding_C,
                unit="degC",
            ),
            # P_total match
            Measurement(
                metric="P_total",
                condition="d",
                frequency_Hz=0,
                value=result.losses.P_total_W,
                unit="W",
            ),
            # B_pk match
            Measurement(
                metric="B_pk", condition="d", frequency_Hz=60, value=result.B_pk_T, unit="T"
            ),
            # L match — engine gives µH, bench gives H; the predicted
            # column rescales internally via the `* 1e-6` scale clause
            # in _METRIC_MAP.
            Measurement(
                metric="L",
                condition="d",
                frequency_Hz=1000,
                value=result.L_actual_uH * 1e-6,
                unit="H",
            ),
        ]
    )
    thresholds = {
        "inductance_pct": 5.0,
        "flux_density_pct": 8.0,
        "temperature_C": 10.0,
        "total_loss_pct": 15.0,
    }
    comparisons, summary = compare(result, measurements, thresholds)
    assert summary.all_passed, render_summary(comparisons, summary)


def test_compare_flags_out_of_threshold_as_fail(
    reference_design,
) -> None:
    """A measurement that differs by 50 % must fail any
    reasonable percentage threshold."""
    from pfc_inductor.design import design
    from validation.lib.measure_loader import Measurement, MeasurementSet

    spec, core, wire, mat = reference_design
    result = design(spec, core, wire, mat)

    # Halve the predicted total-loss to simulate a measurement
    # that disagrees badly with the engine.
    bad = Measurement(
        metric="P_total",
        condition="d",
        frequency_Hz=0,
        value=result.losses.P_total_W * 0.5,
        unit="W",
    )
    ms = MeasurementSet(all=[bad])
    _, summary = compare(result, ms, {"total_loss_pct": 5.0})
    assert not summary.all_passed
    assert len(summary.failures) == 1
    assert summary.failures[0].metric == "P_total"


def test_compare_handles_missing_measurement_with_skip_note(
    reference_design,
) -> None:
    """A threshold whose corresponding measurement isn't in the
    CSV produces a "no measurement" entry — surfaced to the
    notebook so the engineer sees gaps, not silent omissions."""
    from pfc_inductor.design import design
    from validation.lib.measure_loader import MeasurementSet

    spec, core, wire, mat = reference_design
    result = design(spec, core, wire, mat)

    comparisons, summary = compare(result, MeasurementSet(all=[]), {"inductance_pct": 5.0})
    assert len(comparisons) == 1
    assert comparisons[0].note == "no measurement"
    assert not summary.all_passed


def test_render_summary_reports_pass_or_fail_clearly(
    reference_design,
) -> None:
    """The terminal-friendly summary contains the verdict line
    CI keys on. No matter the locale or terminal width, the
    string ``verdict:`` followed by either ``PASS`` or ``FAIL``
    must always appear."""
    from pfc_inductor.design import design
    from validation.lib.measure_loader import Measurement, MeasurementSet

    spec, core, wire, mat = reference_design
    result = design(spec, core, wire, mat)
    ms = MeasurementSet(
        all=[
            Measurement(
                metric="T_winding",
                condition="d",
                frequency_Hz=0,
                value=result.T_winding_C * 5.0,
                unit="degC",
            ),
        ]
    )
    comparisons, summary = compare(result, ms, {"temperature_C": 1.0})
    text = render_summary(comparisons, summary, project_label="x")
    assert "verdict:" in text
    assert "FAIL" in text


# ---------------------------------------------------------------------------
# Shared fixture (catalogue + a feasible spec). Same shape as
# ``test_worst_case_engine.reference_design`` so the two suites
# share an engineering anchor.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def reference_design():
    from pfc_inductor.data_loader import (
        ensure_user_data,
        load_cores,
        load_materials,
        load_wires,
    )
    from pfc_inductor.models import Spec

    ensure_user_data()
    mats = load_materials()
    cores = load_cores()
    wires = load_wires()

    spec = Spec(
        topology="boost_ccm",
        Pout_W=600,
        Vin_min_Vrms=85,
        Vin_max_Vrms=265,
        Vout_V=400,
        f_sw_kHz=65,
        ripple_pct=20,
        T_amb_C=40,
    )
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    return spec, core, wire, mat
