"""Smoke tests for the v3.1 ProjetoPage 4-tab structure.

ProjetoPage now mounts four tabs (Core / Analysis / Validate /
Export) with a persistent ResumoStrip above the QTabWidget. These
tests guard the wiring at the page boundary — internal card
behaviour is exercised in test_nucleo_selection_page and
test_analise_page.
"""
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
    spec = Spec()
    material = find_material(materials, materials[0].id)
    core = cores[0]
    wire = wires[0]
    result = run_design(spec, core, wire, material)
    return result, spec, core, wire, material, materials, cores, wires


def test_projeto_page_has_four_tabs(app, design_bundle):
    from pfc_inductor.ui.workspace.projeto_page import ProjetoPage
    *_, materials, cores, wires = design_bundle
    p = ProjetoPage(materials, cores, wires)
    assert p.tabs.count() == 4
    assert p.tabs.tabText(0) == "Core"
    assert p.tabs.tabText(1) == "Analysis"
    assert p.tabs.tabText(2) == "Validate"
    assert p.tabs.tabText(3) == "Export"


def test_projeto_page_kpi_strip_persistent(app, design_bundle):
    """The ResumoStrip lives above the tab widget — it must be a
    direct child of ProjetoPage's column, not of any tab body."""
    from pfc_inductor.ui.workspace.projeto_page import ProjetoPage
    *_, materials, cores, wires = design_bundle
    p = ProjetoPage(materials, cores, wires)
    assert p.kpi_strip is not None
    # The strip's parent should not be the tab widget.
    assert p.kpi_strip.parent() is not p.tabs


def test_projeto_page_switch_to_each_tab(app, design_bundle):
    from pfc_inductor.ui.workspace.projeto_page import ProjetoPage
    *_, materials, cores, wires = design_bundle
    p = ProjetoPage(materials, cores, wires)
    for key, idx in [("nucleo", 0), ("analise", 1),
                     ("validar", 2), ("exportar", 3)]:
        p.switch_to(key)
        assert p.tabs.currentIndex() == idx


def test_projeto_page_update_from_design_fans_out(app, design_bundle):
    from pfc_inductor.ui.workspace.projeto_page import ProjetoPage
    result, spec, core, wire, material, materials, cores, wires = design_bundle
    p = ProjetoPage(materials, cores, wires)
    p.update_from_design(result, spec, core, wire, material)
    # KPI strip got the L value.
    assert p.kpi_strip.m_L._val.text() == f"{result.L_actual_uH:.0f}"
    # Analysis's PerdasCard got the loss total.
    assert abs(
        p.analise_tab.card_perdas._pbody._bar.total() - result.losses.P_total_W
    ) < 1e-6


def test_projeto_page_selection_applied_bubbles_up(app, design_bundle):
    """Selection from the Core tab (table or inline optimizer) must
    bubble up via ``ProjetoPage.selection_applied`` so MainWindow can
    re-run design()."""
    from pfc_inductor.ui.workspace.projeto_page import ProjetoPage
    *_, materials, cores, wires = design_bundle
    p = ProjetoPage(materials, cores, wires)
    received = []
    p.selection_applied.connect(
        lambda mid, cid, wid: received.append((mid, cid, wid))
    )
    p.nucleo_tab.selection_applied.emit("M", "C", "W")
    assert received == [("M", "C", "W")]


# test_projeto_page_progress_indicator_tracks_active_tab removed:
# the ProgressIndicator was retired from ProjetoPage in favour of
# letting the QTabWidget itself communicate the active phase. The
# ProgressIndicator widget still has its own unit tests in
# ``tests/test_shell_stepper.py`` for any future caller.


def test_projeto_page_mark_action_done_is_noop(app, design_bundle):
    """Legacy ProximosPassosCard hook — kept callable for back-compat."""
    from pfc_inductor.ui.workspace.projeto_page import ProjetoPage
    *_, materials, cores, wires = design_bundle
    p = ProjetoPage(materials, cores, wires)
    p.mark_action_done("report")  # must not raise
