"""ModulationBandChart widget + Analysis-tab integration tests."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    inst = QApplication.instance() or QApplication([])
    yield inst


@pytest.fixture(scope="module")
def reference_inputs():
    from pfc_inductor.data_loader import (
        ensure_user_data,
        load_cores,
        load_materials,
        load_wires,
    )
    from pfc_inductor.design import design as run_design
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
                fsw_min_kHz=4,
                fsw_max_kHz=25,
                n_eval_points=5,
            ),
        }
    )
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    nominal = run_design(spec, core, wire, mat)
    return spec, spec_b, core, wire, mat, nominal


# ---------------------------------------------------------------------------
# Widget — ModulationBandChart
# ---------------------------------------------------------------------------
def test_band_chart_initial_state(app) -> None:
    from pfc_inductor.ui.widgets.modulation_band_chart import (
        ModulationBandChart,
    )

    chart = ModulationBandChart()
    try:
        # Empty-state caption is blank until show_band runs.
        assert chart._caption.text() == ""
    finally:
        chart.deleteLater()


def test_band_chart_show_band_renders_caption(
    app,
    reference_inputs,
) -> None:
    """Feeding a real ``BandedDesignResult`` populates the
    caption with the band summary."""
    from pfc_inductor.modulation import eval_band
    from pfc_inductor.ui.widgets.modulation_band_chart import (
        ModulationBandChart,
    )

    _, spec_b, core, wire, mat, _ = reference_inputs
    banded = eval_band(spec_b, core, wire, mat)
    chart = ModulationBandChart()
    try:
        chart.show_band(banded)
        caption = chart._caption.text()
        # Caption carries the band shape + profile.
        assert "Band:" in caption
        assert "kHz" in caption
        assert "5 points" in caption
        assert "uniform" in caption
    finally:
        chart.deleteLater()


def test_band_chart_clear_resets_caption(
    app,
    reference_inputs,
) -> None:
    from pfc_inductor.modulation import eval_band
    from pfc_inductor.ui.widgets.modulation_band_chart import (
        ModulationBandChart,
    )

    _, spec_b, core, wire, mat, _ = reference_inputs
    banded = eval_band(spec_b, core, wire, mat)
    chart = ModulationBandChart()
    try:
        chart.show_band(banded)
        assert chart._caption.text() != ""
        chart.clear()
        assert chart._caption.text() == ""
    finally:
        chart.deleteLater()


def test_band_chart_handles_all_failed_band_points(app) -> None:
    """Every band point failed → caption shows the error
    message instead of the band summary."""
    from pfc_inductor.models import Spec
    from pfc_inductor.models.banded_result import (
        BandedDesignResult,
        BandPoint,
    )
    from pfc_inductor.ui.widgets.modulation_band_chart import (
        ModulationBandChart,
    )

    spec = Spec(
        topology="boost_ccm",
        Pout_W=600,
        Vin_min_Vrms=85,
        Vin_max_Vrms=265,
        Vout_V=400,
        f_sw_kHz=10,
        ripple_pct=20,
        T_amb_C=40,
    )
    failing_band = (
        BandPoint(fsw_kHz=4.0, result=None, failure_reason="x"),
        BandPoint(fsw_kHz=10.0, result=None, failure_reason="y"),
    )
    banded = BandedDesignResult(
        spec=spec,
        band=failing_band,
        nominal=None,
        worst_per_metric={},
        flagged_points=failing_band,
    )
    chart = ModulationBandChart()
    try:
        chart.show_band(banded)
        # No data path → caption is empty (set inside _render_empty
        # which is called via show_band's "no points" branch).
        assert "Every band point failed" in chart._figure.axes[0].texts[0].get_text()
    finally:
        chart.deleteLater()


# ---------------------------------------------------------------------------
# AnalisePage integration
# ---------------------------------------------------------------------------
def test_analise_page_hides_modulation_card_for_single_point(
    app,
    reference_inputs,
) -> None:
    """Legacy single-point spec → modulation card hidden,
    Analysis layout unchanged."""
    from pfc_inductor.ui.workspace.analise_page import AnalisePage

    spec, _spec_b, core, wire, mat, nominal = reference_inputs
    page = AnalisePage()
    try:
        page.update_from_design(nominal, spec, core, wire, mat)
        assert page._modulation_card.isHidden()
    finally:
        page.deleteLater()


def test_analise_page_reveals_modulation_card_for_banded_spec(
    app,
    reference_inputs,
) -> None:
    """Banded spec → card revealed; the chart widget renders
    the per-fsw curves."""
    from pfc_inductor.design import design as run_design
    from pfc_inductor.ui.workspace.analise_page import AnalisePage

    _spec, spec_b, core, wire, mat, _ = reference_inputs
    page = AnalisePage()
    try:
        result = run_design(spec_b, core, wire, mat)
        page.update_from_design(result, spec_b, core, wire, mat)
        assert not page._modulation_card.isHidden()
        # Chart's caption is non-empty after a successful band run.
        assert page._modulation_chart._caption.text() != ""
    finally:
        page.deleteLater()


def test_analise_page_modulation_card_toggles_back_off(
    app,
    reference_inputs,
) -> None:
    """User flips the band off → card hides on the next
    update_from_design cycle."""
    from pfc_inductor.design import design as run_design
    from pfc_inductor.ui.workspace.analise_page import AnalisePage

    spec, spec_b, core, wire, mat, _ = reference_inputs
    page = AnalisePage()
    try:
        # Banded first.
        result_b = run_design(spec_b, core, wire, mat)
        page.update_from_design(result_b, spec_b, core, wire, mat)
        assert not page._modulation_card.isHidden()
        # Toggle off.
        result = run_design(spec, core, wire, mat)
        page.update_from_design(result, spec, core, wire, mat)
        assert page._modulation_card.isHidden()
    finally:
        page.deleteLater()
