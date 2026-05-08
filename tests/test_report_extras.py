"""Datasheet extras — modulation envelope + worst-case sections.

Exercises ``pfc_inductor.report.extras`` which produces the
opt-in PDF datasheet pages that close VFD-modulation Phase 7
and worst-case Phase 6. The tests assert the *shape* of the
flowable list (PageBreak presence, table row counts) rather
than the exact PDF byte stream — those layout details belong
to ReportLab. We just need to know:

- Empty input → empty list (host's ``story.extend`` stays
  branch-free).
- Valid input → at least one PageBreak + heading + chart +
  table.
- The yield-rate colour bands flip the right way relative to
  the 95 % / 90 % thresholds.
"""

from __future__ import annotations

import math

import pytest
from reportlab.platypus import Image, PageBreak, Paragraph, Table


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def reference_inputs():
    """Catalogue + spec used as the canonical specimen."""
    from pfc_inductor.data_loader import (
        ensure_user_data,
        load_cores,
        load_materials,
        load_wires,
    )
    from pfc_inductor.models import FswModulation, Spec

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
    spec_b = spec.model_copy(
        update={
            "fsw_modulation": FswModulation(
                fsw_min_kHz=8,
                fsw_max_kHz=20,
                n_eval_points=4,
            ),
        }
    )
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    return spec, spec_b, core, wire, mat


@pytest.fixture(scope="module")
def banded_result(reference_inputs):
    """A real ``BandedDesignResult`` from the live engine — the
    factories are designed to consume engine output, so the
    canonical happy-path is the engine's own answer."""
    from pfc_inductor.modulation import eval_band

    _, spec_b, core, wire, mat = reference_inputs
    return eval_band(spec_b, core, wire, mat)


@pytest.fixture(scope="module")
def worst_case_summary(reference_inputs):
    """A small ``WorstCaseSummary`` from a 2-tolerance DOE
    (3^2 = 9 corners, ~3 s) so the test stays brisk."""
    from pfc_inductor.worst_case import (
        Tolerance,
        ToleranceSet,
        WorstCaseConfig,
        evaluate_corners,
    )

    spec, _spec_b, core, wire, mat = reference_inputs
    tols = ToleranceSet(
        name="extras-test",
        tolerances=[
            Tolerance(name="AL ±5", kind="AL_pct", p3sigma_pct=5.0),
            Tolerance(name="Bsat ±5", kind="Bsat_pct", p3sigma_pct=5.0),
        ],
    )
    return evaluate_corners(
        spec,
        core,
        wire,
        mat,
        tols,
        config=WorstCaseConfig(full_factorial_max_n=4),
    )


# ---------------------------------------------------------------------------
# Modulation envelope page
# ---------------------------------------------------------------------------
def test_modulation_envelope_empty_band_returns_empty_list() -> None:
    """No band points → empty flowable list. The host's
    ``story.extend`` must stay branch-free."""
    from pfc_inductor.models import Spec
    from pfc_inductor.models.banded_result import BandedDesignResult
    from pfc_inductor.report.extras import modulation_envelope_flowables

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
    banded = BandedDesignResult(
        spec=spec,
        band=(),
        nominal=None,
        worst_per_metric={},
        flagged_points=(),
    )
    assert modulation_envelope_flowables(banded) == []


def test_modulation_envelope_all_failed_returns_empty_list() -> None:
    """Every band point failed → still empty. The chart would
    have nothing to plot, the worst-case table nothing to show
    — better to skip the page than to ship a blank one."""
    from pfc_inductor.models import Spec
    from pfc_inductor.models.banded_result import (
        BandedDesignResult,
        BandPoint,
    )
    from pfc_inductor.report.extras import modulation_envelope_flowables

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
    failing = (
        BandPoint(fsw_kHz=4.0, result=None, failure_reason="x"),
        BandPoint(fsw_kHz=20.0, result=None, failure_reason="y"),
    )
    banded = BandedDesignResult(
        spec=spec,
        band=failing,
        nominal=None,
        worst_per_metric={},
        flagged_points=failing,
    )
    assert modulation_envelope_flowables(banded) == []


def test_modulation_envelope_happy_path_carries_pagebreak_and_chart(
    banded_result,
) -> None:
    """Valid banded result → PageBreak + heading paragraph +
    band caption + chart Image + worst-case table."""
    from pfc_inductor.report.extras import modulation_envelope_flowables

    flow = modulation_envelope_flowables(banded_result)
    assert len(flow) > 0
    # First flowable always opens a fresh page so the section
    # never collides with the previous one.
    assert isinstance(flow[0], PageBreak)
    # Heading paragraph follows the page break.
    assert any(isinstance(f, Paragraph) and "Modulation envelope" in f.text for f in flow)
    # The 3-subplot matplotlib figure is embedded as an Image.
    assert any(isinstance(f, Image) for f in flow)
    # Worst-case summary table is included.
    assert any(isinstance(f, Table) for f in flow)


def test_modulation_envelope_table_has_metric_rows(
    banded_result,
) -> None:
    """The worst-case table carries one row per tracked metric
    (header + up to 4 data rows)."""
    from pfc_inductor.report.extras import modulation_envelope_flowables

    flow = modulation_envelope_flowables(banded_result)
    tables = [f for f in flow if isinstance(f, Table)]
    assert tables, "no table in flow"
    table = tables[0]
    # Header row + at least one metric row.
    assert len(table._cellvalues) >= 2
    # Header has 4 columns: Metric, Worst value, Worst fsw, Margin.
    assert table._cellvalues[0] == [
        "Metric",
        "Worst value",
        "Worst fsw",
        "Margin",
    ]


def test_modulation_envelope_flagged_points_emit_warning() -> None:
    """A mixed band (some succeed, some fail) emits an extra
    paragraph flagging the count of failures so the user
    knows the worst-case envelope ignored those points."""
    # A real successful BandPoint requires a DesignResult — too
    # heavy to forge by hand. Use eval_band on a feasible spec
    # and synthetically inject a failed point so we can assert
    # the warning paragraph is emitted.
    from pfc_inductor.data_loader import (
        ensure_user_data,
        load_cores,
        load_materials,
        load_wires,
    )
    from pfc_inductor.models import FswModulation, Spec
    from pfc_inductor.models.banded_result import (
        BandedDesignResult,
        BandPoint,
    )
    from pfc_inductor.modulation import eval_band
    from pfc_inductor.report.extras import modulation_envelope_flowables

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
    spec_b = spec.model_copy(
        update={
            "fsw_modulation": FswModulation(
                fsw_min_kHz=8,
                fsw_max_kHz=20,
                n_eval_points=3,
            ),
        }
    )
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    real = eval_band(spec_b, core, wire, mat)
    fake_failed = BandPoint(
        fsw_kHz=999.0,
        result=None,
        failure_reason="synthetic",
    )
    mixed = BandedDesignResult(
        spec=real.spec,
        band=(*real.band, fake_failed),
        nominal=real.nominal,
        worst_per_metric=real.worst_per_metric,
        flagged_points=(fake_failed,),
    )
    flow = modulation_envelope_flowables(mixed)
    assert any(isinstance(f, Paragraph) and "1 band point(s) failed" in f.text for f in flow)


# ---------------------------------------------------------------------------
# Worst-case envelope page
# ---------------------------------------------------------------------------
def test_worst_case_envelope_empty_summary_returns_empty_list() -> None:
    """Zero corners evaluated → empty list (the worst-case
    feature was skipped, the page disappears)."""
    from pfc_inductor.report.extras import worst_case_envelope_flowables
    from pfc_inductor.worst_case import WorstCaseSummary

    summary = WorstCaseSummary(
        n_corners_evaluated=0,
        n_corners_failed=0,
        nominal=None,
        corners=(),
        worst_per_metric={},
    )
    assert worst_case_envelope_flowables(summary) == []


def test_worst_case_envelope_happy_path(worst_case_summary) -> None:
    """Real DOE summary → PageBreak + headline + per-metric
    table + caveat paragraph."""
    from pfc_inductor.report.extras import worst_case_envelope_flowables

    flow = worst_case_envelope_flowables(worst_case_summary)
    assert len(flow) > 0
    assert isinstance(flow[0], PageBreak)
    assert any(
        isinstance(f, Paragraph) and "Production worst-case envelope" in f.text for f in flow
    )
    # Per-metric worst-case table.
    assert any(isinstance(f, Table) for f in flow)


def test_worst_case_envelope_table_has_three_columns(
    worst_case_summary,
) -> None:
    """The per-metric table is Metric / Worst value / Driving
    corner — three columns, one row per metric the engine
    aggregated."""
    from pfc_inductor.report.extras import worst_case_envelope_flowables

    flow = worst_case_envelope_flowables(worst_case_summary)
    table = next(f for f in flow if isinstance(f, Table))
    # Header + at least one metric row.
    assert len(table._cellvalues) >= 2
    assert table._cellvalues[0] == [
        "Metric",
        "Worst value",
        "Driving corner",
    ]


def test_worst_case_envelope_yield_section_appears_when_provided(
    worst_case_summary,
) -> None:
    """Passing a YieldReport adds the Monte-Carlo headline
    + pass-rate paragraph + (when present) the fail-modes
    line — three extra paragraphs over the corner-only flow."""
    from pfc_inductor.report.extras import worst_case_envelope_flowables
    from pfc_inductor.worst_case import YieldReport

    yield_report = YieldReport(
        n_samples=1000,
        n_pass=970,
        n_fail=30,
        n_engine_error=0,
        pass_rate=0.97,
        fail_modes={"T_winding": 18, "B_pk": 12},
    )
    flow = worst_case_envelope_flowables(worst_case_summary, yield_report)
    # Yield headline.
    assert any(isinstance(f, Paragraph) and "Yield estimate" in f.text for f in flow)
    # Pass-rate paragraph carries the percentage.
    assert any(isinstance(f, Paragraph) and "97.00 %" in f.text for f in flow)
    # Fail modes line.
    assert any(isinstance(f, Paragraph) and "Top fail modes" in f.text for f in flow)


def test_worst_case_envelope_yield_section_omits_fail_modes_when_empty(
    worst_case_summary,
) -> None:
    """When no fail modes are recorded (100 % pass), the
    fail-modes line is suppressed — the "Top fail modes:"
    string never appears."""
    from pfc_inductor.report.extras import worst_case_envelope_flowables
    from pfc_inductor.worst_case import YieldReport

    yield_report = YieldReport(
        n_samples=500,
        n_pass=500,
        n_fail=0,
        n_engine_error=0,
        pass_rate=1.0,
        fail_modes={},
    )
    flow = worst_case_envelope_flowables(worst_case_summary, yield_report)
    assert not any(isinstance(f, Paragraph) and "Top fail modes" in f.text for f in flow)


def test_worst_case_envelope_yield_color_threshold_pass(
    worst_case_summary,
) -> None:
    """≥95 % pass-rate uses the success colour."""
    from pfc_inductor.report.extras import worst_case_envelope_flowables
    from pfc_inductor.worst_case import YieldReport

    yield_report = YieldReport(
        n_samples=1000,
        n_pass=970,
        n_fail=30,
        n_engine_error=0,
        pass_rate=0.97,
        fail_modes={},
    )
    flow = worst_case_envelope_flowables(worst_case_summary, yield_report)
    rate_para = next(f for f in flow if isinstance(f, Paragraph) and "97.00 %" in f.text)
    assert "#15803D" in rate_para.text  # _PASS green


def test_worst_case_envelope_yield_color_threshold_warning(
    worst_case_summary,
) -> None:
    """≥90 % but <95 % uses the warning colour."""
    from pfc_inductor.report.extras import worst_case_envelope_flowables
    from pfc_inductor.worst_case import YieldReport

    yield_report = YieldReport(
        n_samples=1000,
        n_pass=920,
        n_fail=80,
        n_engine_error=0,
        pass_rate=0.92,
        fail_modes={"T_winding": 80},
    )
    flow = worst_case_envelope_flowables(worst_case_summary, yield_report)
    rate_para = next(f for f in flow if isinstance(f, Paragraph) and "92.00 %" in f.text)
    assert "#A16207" in rate_para.text  # _WARN amber


def test_worst_case_envelope_yield_color_threshold_fail(
    worst_case_summary,
) -> None:
    """<90 % uses the fail colour."""
    from pfc_inductor.report.extras import worst_case_envelope_flowables
    from pfc_inductor.worst_case import YieldReport

    yield_report = YieldReport(
        n_samples=1000,
        n_pass=800,
        n_fail=200,
        n_engine_error=0,
        pass_rate=0.80,
        fail_modes={"T_winding": 200},
    )
    flow = worst_case_envelope_flowables(worst_case_summary, yield_report)
    rate_para = next(f for f in flow if isinstance(f, Paragraph) and "80.00 %" in f.text)
    assert "#B91C1C" in rate_para.text  # _FAIL red


# ---------------------------------------------------------------------------
# Helpers — _read_metric is private but documented; cover its
# defensive branches because the public factories rely on it.
# ---------------------------------------------------------------------------
def test_read_metric_returns_none_for_missing_attribute() -> None:
    """The metric helper must return ``None`` (not raise)
    when the result lacks the attribute — guards future
    DesignResult schema drift."""
    from pfc_inductor.report.extras import _read_metric

    class Bare:
        pass

    assert _read_metric(Bare(), "T_winding_C") is None


def test_read_metric_returns_none_for_nonfinite() -> None:
    """NaN / inf metrics → None (the chart would otherwise
    crash matplotlib's autoscaler)."""
    from pfc_inductor.report.extras import _read_metric

    class Result:
        T_winding_C = float("nan")
        B_pk_T = math.inf

    assert _read_metric(Result(), "T_winding_C") is None
    assert _read_metric(Result(), "B_pk_T") is None


def test_read_metric_falls_back_to_losses_attr() -> None:
    """If the metric isn't on the result directly, the helper
    looks under ``result.losses`` — matches the structure of
    real DesignResult objects."""
    from pfc_inductor.report.extras import _read_metric

    class Losses:
        P_total_W = 12.5

    class Result:
        losses = Losses()

    assert _read_metric(Result(), "P_total_W") == 12.5


def test_style_helper_returns_provided_style_when_present() -> None:
    """``_style`` returns the host's style verbatim when the
    requested key is in the dict."""
    from reportlab.lib.styles import ParagraphStyle

    from pfc_inductor.report.extras import _style

    custom = ParagraphStyle("custom", fontName="Times-Roman", fontSize=42)
    out = _style({"h2": custom}, "h2")
    assert out is custom


def test_style_helper_falls_back_when_key_missing() -> None:
    """No style dict (or missing key) → safe Helvetica
    fallback. Means the factories work even when the host
    forgets to pass a style sheet."""
    from pfc_inductor.report.extras import _style

    out = _style(None, "h2", size=20, bold=True)
    assert out.fontName == "Helvetica-Bold"
    assert out.fontSize == 20

    out2 = _style({}, "h3", size=10)
    assert out2.fontName == "Helvetica"
    assert out2.fontSize == 10
