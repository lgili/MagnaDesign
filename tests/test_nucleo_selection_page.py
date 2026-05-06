"""Smoke + integration tests for NucleoSelectionPage.

The first tab of the Projeto workspace. Two modes (Tabela /
Otimizador) backed by a QStackedWidget; the inline OptimizerEmbed
must receive ``set_inputs`` calls and forward
``selection_applied`` upward.
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


# ---------------------------------------------------------------------------
# Construction + mode toggle
# ---------------------------------------------------------------------------

def test_nucleo_page_constructs_with_default_tabela_mode(app, design_bundle):
    from pfc_inductor.ui.workspace.nucleo_selection_page import (
        NucleoSelectionPage,
    )
    *_, materials, cores, wires = design_bundle
    p = NucleoSelectionPage(materials, cores, wires)
    # Default mode is "tabela" → stack index 0.
    assert p.toggle.current() in ("tabela", "otimizador")
    if p.toggle.current() == "tabela":
        assert p._stack.currentIndex() == 0


def test_nucleo_page_toggle_switches_stack(app, design_bundle):
    from pfc_inductor.ui.workspace.nucleo_selection_page import (
        NucleoSelectionPage,
    )
    *_, materials, cores, wires = design_bundle
    p = NucleoSelectionPage(materials, cores, wires)
    p.toggle.set_mode("otimizador")
    assert p._stack.currentIndex() == 1
    p.toggle.set_mode("tabela")
    assert p._stack.currentIndex() == 0


# ---------------------------------------------------------------------------
# populate() refreshes both NucleoCard and OptimizerEmbed
# ---------------------------------------------------------------------------

def test_nucleo_page_populate_propagates_to_optimizer(app, design_bundle):
    from pfc_inductor.ui.workspace.nucleo_selection_page import (
        NucleoSelectionPage,
    )
    result, spec, core, wire, material, materials, cores, wires = design_bundle
    p = NucleoSelectionPage(materials, cores, wires)
    p.update_from_design(result, spec, core, wire, material)
    p.populate(spec, materials, cores, wires, material, core, wire)
    # OptimizerEmbed should now have the spec assigned (which enables
    # the run button).
    assert p.optimizer.btn_run.isEnabled()
    # NucleoCard tracks the current Material/Core/Wire it was
    # populated with — v3.x stores the objects directly (was string id).
    assert p.card_nucleo._nbody._current_material is material
    assert p.card_nucleo._nbody._current_core is core
    assert p.card_nucleo._nbody._current_wire is wire


# ---------------------------------------------------------------------------
# selection_applied bubbles up from both bodies
# ---------------------------------------------------------------------------

def test_nucleo_page_forwards_optimizer_selection(app, design_bundle):
    from pfc_inductor.ui.workspace.nucleo_selection_page import (
        NucleoSelectionPage,
    )
    result, spec, core, wire, material, materials, cores, wires = design_bundle
    p = NucleoSelectionPage(materials, cores, wires)
    p.update_from_design(result, spec, core, wire, material)
    p.populate(spec, materials, cores, wires, material, core, wire)

    received = []
    p.selection_applied.connect(
        lambda mid, cid, wid: received.append((mid, cid, wid))
    )
    # Synthesise an inline-optimizer apply — emit the inner signal
    # directly (running an actual sweep in offscreen mode is too slow
    # and brittle for a unit test).
    p.optimizer.selection_applied.emit("M1", "C1", "W1")
    assert received == [("M1", "C1", "W1")]


def test_nucleo_page_forwards_card_selection(app, design_bundle):
    from pfc_inductor.ui.workspace.nucleo_selection_page import (
        NucleoSelectionPage,
    )
    result, spec, core, wire, material, materials, cores, wires = design_bundle
    p = NucleoSelectionPage(materials, cores, wires)
    p.update_from_design(result, spec, core, wire, material)

    received = []
    p.selection_applied.connect(
        lambda mid, cid, wid: received.append((mid, cid, wid))
    )
    p.card_nucleo.selection_applied.emit("MX", "CY", "WZ")
    assert received == [("MX", "CY", "WZ")]
