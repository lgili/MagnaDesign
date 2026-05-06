"""NucleoCard score-table view (tabbed)."""
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
def db():
    from pfc_inductor.data_loader import (
        ensure_user_data, load_materials, load_cores, load_wires,
    )
    ensure_user_data()
    return {
        "materials": load_materials(),
        "cores": load_cores(),
        "wires": load_wires(),
    }


def test_nucleo_card_three_tabs(app):
    from pfc_inductor.ui.dashboard.cards.nucleo_card import NucleoCard
    card = NucleoCard()
    tabs = card._nbody._tabs
    assert tabs.count() == 3
    assert tabs.tabText(0) == "Material"
    assert tabs.tabText(1) == "Núcleo"
    assert tabs.tabText(2) == "Fio"


def test_nucleo_card_populates_all_tabs(app, db):
    from pfc_inductor.models import Spec
    from pfc_inductor.ui.dashboard.cards.nucleo_card import NucleoCard
    card = NucleoCard()
    spec = Spec()
    mat = db["materials"][0]
    core = db["cores"][0]
    wire = db["wires"][0]
    card.populate(spec, db["materials"], db["cores"], db["wires"],
                  mat, core, wire)
    assert card._nbody.tab_material._model.rowCount() == len(db["materials"])
    assert card._nbody.tab_core._model.rowCount() == len(db["cores"])
    assert card._nbody.tab_wire._model.rowCount() == len(db["wires"])


def test_nucleo_card_search_filter_narrows_rows(app, db):
    from pfc_inductor.models import Spec
    from pfc_inductor.ui.dashboard.cards.nucleo_card import NucleoCard
    card = NucleoCard()
    spec = Spec()
    mat = db["materials"][0]
    core = db["cores"][0]
    wire = db["wires"][0]
    card.populate(spec, db["materials"], db["cores"], db["wires"],
                  mat, core, wire)

    full = card._nbody.tab_core.visible_row_count()
    card._nbody.tab_core._proxy.set_search("magnetics")
    filtered = card._nbody.tab_core.visible_row_count()
    assert 0 < filtered < full


def test_nucleo_card_curated_filter(app, db):
    from pfc_inductor.models import Spec
    from pfc_inductor.ui.dashboard.cards.nucleo_card import NucleoCard
    card = NucleoCard()
    spec = Spec()
    mat = db["materials"][0]
    core = db["cores"][0]
    wire = db["wires"][0]
    card.populate(spec, db["materials"], db["cores"], db["wires"],
                  mat, core, wire)
    full = card._nbody.tab_core.visible_row_count()
    card._nbody.tab_core._proxy.set_curated_only(True)
    curated = card._nbody.tab_core.visible_row_count()
    assert 0 < curated <= full


def test_nucleo_card_apply_disabled_until_different_row(app, db):
    from pfc_inductor.models import Spec
    from pfc_inductor.ui.dashboard.cards.nucleo_card import NucleoCard
    card = NucleoCard()
    spec = Spec()
    mat = db["materials"][0]
    core = db["cores"][0]
    wire = db["wires"][0]
    card.populate(spec, db["materials"], db["cores"], db["wires"],
                  mat, core, wire)
    # No selection yet → button disabled.
    assert not card._nbody._btn_apply.isEnabled()


def test_nucleo_card_emits_selection_applied(app, db):
    from pfc_inductor.models import Spec
    from pfc_inductor.ui.dashboard.cards.nucleo_card import NucleoCard
    from PySide6.QtCore import QItemSelectionModel

    card = NucleoCard()
    spec = Spec()
    mat = db["materials"][0]
    core = db["cores"][0]
    wire = db["wires"][0]
    card.populate(spec, db["materials"], db["cores"], db["wires"],
                  mat, core, wire)

    received: list[tuple[str, str, str]] = []
    card.selection_applied.connect(
        lambda m, c, w: received.append((m, c, w))
    )

    # Select the second row of the Núcleo tab (different from current).
    tab = card._nbody.tab_core
    if tab._proxy.rowCount() >= 2:
        idx0 = tab._proxy.index(1, 0)  # row 1 (second row)
        tab.table.selectionModel().select(
            idx0,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows,
        )
        # Click apply.
        if card._nbody._btn_apply.isEnabled():
            card._nbody._btn_apply.click()
            assert len(received) == 1
            m_id, c_id, w_id = received[0]
            assert m_id == mat.id  # material unchanged
            assert c_id != core.id  # core changed to row 1
            assert w_id == wire.id  # wire unchanged
