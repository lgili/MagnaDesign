"""Smoke + integration tests for AnalisePage (v3.1).

The second tab of the Projeto workspace, hosting waveforms, losses,
winding and gap detail. Replaces the bento ``DashboardPage`` for the
post-selection design analysis flow.
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
    return result, spec, core, wire, material


def test_analise_page_has_five_cards(app):
    """The Análise tab holds five cards: FormasOnda, Perdas,
    Bobinamento, Entreferro, and DetalhesTecnicos (collapsed by
    default). NucleoCard / Viz3DCard / Resumo / ProximosPassos are
    NOT here — they live elsewhere in v3."""
    from pfc_inductor.ui.workspace.analise_page import AnalisePage
    p = AnalisePage()
    assert len(p._cards) == 5
    # Check the type of each card.
    from pfc_inductor.ui.dashboard.cards import (
        BobinamentoCard,
        DetalhesTecnicosCard,
        EntreferroCard,
        FormasOndaCard,
        PerdasCard,
    )
    types = {type(c) for c in p._cards}
    assert types == {
        FormasOndaCard, PerdasCard, BobinamentoCard, EntreferroCard,
        DetalhesTecnicosCard,
    }


def test_analise_page_update_propagates(app, design_bundle):
    from pfc_inductor.ui.workspace.analise_page import AnalisePage
    p = AnalisePage()
    result, spec, core, wire, material = design_bundle
    p.update_from_design(result, spec, core, wire, material)
    # PerdasCard now uses HorizontalStackedBar; total should match.
    assert abs(p.card_perdas._pbody._bar.total() - result.losses.P_total_W) < 1e-6


def test_analise_page_clear_resets_every_card(app, design_bundle):
    from pfc_inductor.ui.workspace.analise_page import AnalisePage
    p = AnalisePage()
    result, spec, core, wire, material = design_bundle
    p.update_from_design(result, spec, core, wire, material)
    p.clear()
    assert p.card_perdas._pbody._bar.total() == 0
