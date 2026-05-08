"""DashboardPage + per-card integration regressions."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    inst = QApplication.instance() or QApplication([])
    yield inst


@pytest.fixture
def design_bundle():
    """Build a real DesignResult by running the engine on the smallest
    in-tree spec/core/wire/material combo. Reuses the same data path as
    the application so tests catch model-shape regressions early."""
    from pfc_inductor.data_loader import (
        ensure_user_data,
        find_material,
        load_cores,
        load_materials,
        load_wires,
    )
    from pfc_inductor.design import design as run_design
    from pfc_inductor.models import Spec

    ensure_user_data()
    materials = load_materials()
    cores = load_cores()
    wires = load_wires()
    spec = Spec()  # defaults
    material = find_material(materials, materials[0].id)
    core = cores[0]
    wire = wires[0]
    result = run_design(spec, core, wire, material)
    return result, spec, core, wire, material


# ---------------------------------------------------------------------------
# Page structure
# ---------------------------------------------------------------------------


def test_dashboard_has_eight_cards(app):
    """v3 dropped the TopologiaCard (topology lives in SpecDrawer).
    Layout shrinks from 9 cards to 8."""
    from pfc_inductor.ui.dashboard import DashboardPage

    p = DashboardPage()
    assert len(p._cards) == 8


def test_dashboard_grid_positions(app):
    """v3 bento layout: row 0 = ResumoStrip (full width); row 1 =
    Núcleo + Viz3D; row 2 = FormasOnda (full width); row 3 = 4 sub-cards
    (Perdas/Bobinamento/Entreferro/Próximos)."""
    from pfc_inductor.ui.dashboard import DashboardPage

    p = DashboardPage()
    # Smoke: every card has a non-null geometry parent.
    for c in p._cards:
        assert c.parent() is not None


# ---------------------------------------------------------------------------
# Update from design fans out to every card
# ---------------------------------------------------------------------------


def test_update_from_design_populates_resumo(app, design_bundle):
    from pfc_inductor.ui.dashboard import DashboardPage

    p = DashboardPage()
    result, spec, core, wire, material = design_bundle
    p.update_from_design(result, spec, core, wire, material)
    # The KPI strip's L tile should show the formatted L_actual_uH.
    assert p.kpi_strip.m_L._val.text() == f"{result.L_actual_uH:.0f}"


def test_update_from_design_populates_perdas_bar(app, design_bundle):
    from pfc_inductor.ui.dashboard import DashboardPage

    p = DashboardPage()
    result, spec, core, wire, material = design_bundle
    p.update_from_design(result, spec, core, wire, material)
    expected_total = result.losses.P_total_W
    # v3: PerdasCard now uses HorizontalStackedBar instead of DonutChart.
    assert abs(p.card_perdas._pbody._bar.total() - expected_total) < 1e-6


def test_update_from_design_populates_bobinamento_table(app, design_bundle):
    from pfc_inductor.ui.dashboard import DashboardPage

    p = DashboardPage()
    result, spec, core, wire, material = design_bundle
    p.update_from_design(result, spec, core, wire, material)
    table = p.card_bobinamento._bbody._table
    # Row 0 = "Espiras (N)" — value should match N_turns
    assert table.value_text(0) == str(result.N_turns)


def test_update_from_design_populates_entreferro(app, design_bundle):
    from pfc_inductor.ui.dashboard import DashboardPage

    p = DashboardPage()
    result, spec, core, wire, material = design_bundle
    p.update_from_design(result, spec, core, wire, material)
    # H_peak text should match the formatted H_dc_peak_Oe.
    assert p.card_entreferro._ebody.m_H._val.text() == f"{result.H_dc_peak_Oe:.1f}"


def test_dashboard_clear_resets_every_card(app, design_bundle):
    from pfc_inductor.ui.dashboard import DashboardPage

    p = DashboardPage()
    result, spec, core, wire, material = design_bundle
    p.update_from_design(result, spec, core, wire, material)
    p.clear()
    assert p.kpi_strip.m_L._val.text() == "—"
    assert p.card_perdas._pbody._bar.total() == 0


# ---------------------------------------------------------------------------
# Resumo aggregate badge
# ---------------------------------------------------------------------------


def test_resumo_aggregate_badge_reflects_metric_statuses(app, design_bundle):
    from pfc_inductor.ui.dashboard import DashboardPage

    p = DashboardPage()
    result, spec, core, wire, material = design_bundle
    p.update_from_design(result, spec, core, wire, material)
    # v3.x: the badge now also appends " — reason1 · reason2 +N" when
    # any metric is warn/err. Just check the prefix.
    badge = p.kpi_strip.badge.text()
    assert badge.startswith(("Pass", "Check", "Fail", "Failed", "—"))


# ---------------------------------------------------------------------------
# Próximos passos signal forwarding
# ---------------------------------------------------------------------------


def test_proximos_passos_forwards_signals(app):
    from pfc_inductor.ui.dashboard import DashboardPage

    p = DashboardPage()
    fired = []
    p.fea_requested.connect(lambda: fired.append("fea"))
    p.compare_requested.connect(lambda: fired.append("compare"))
    p.litz_requested.connect(lambda: fired.append("litz"))
    p.report_requested.connect(lambda: fired.append("report"))
    p.similar_requested.connect(lambda: fired.append("similar"))

    # Fire the inner signals as if a row's CTA was clicked.
    p.card_proximos.fea_requested.emit()
    p.card_proximos.compare_requested.emit()
    p.card_proximos.litz_requested.emit()
    p.card_proximos.report_requested.emit()
    p.card_proximos.similar_requested.emit()
    assert fired == ["fea", "compare", "litz", "report", "similar"]


def test_dashboard_mark_action_done(app):
    from pfc_inductor.ui.dashboard import DashboardPage

    p = DashboardPage()
    p.mark_action_done("report")
    assert p.card_proximos._actions["report"] == "done"


# ---------------------------------------------------------------------------
# MainWindow integration
# ---------------------------------------------------------------------------


def test_main_window_emits_design_completed(app):
    """A successful construction-time _on_calculate must populate
    dashboard cards via the design_completed signal path."""
    from pfc_inductor.ui.main_window import MainWindow

    received = []
    w = MainWindow()
    w.design_completed.connect(lambda *args: received.append(args))
    # Trigger one more recompute manually so the signal fires.
    w._on_calculate()
    assert len(received) >= 1
    args = received[-1]
    # Order: result, spec, core, wire, material
    assert len(args) == 5
    w.close()
