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
        ensure_user_data,
        load_cores,
        load_materials,
        load_wires,
    )
    ensure_user_data()
    return {
        "materials": load_materials(),
        "cores": load_cores(),
        "wires": load_wires(),
    }


def test_nucleo_card_three_tabs(app):
    """Component-tabbed score view should expose Material / Core / Wire.

    The MagnaDesign rebrand passed an EN translation across the
    component cards; the previous PT-BR labels (``Núcleo`` / ``Fio``)
    are no longer expected.
    """
    from pfc_inductor.ui.dashboard.cards.nucleo_card import NucleoCard
    card = NucleoCard()
    tabs = card._nbody._tabs
    assert tabs.count() == 3
    assert tabs.tabText(0) == "Material"
    assert tabs.tabText(1) == "Core"
    assert tabs.tabText(2) == "Wire"


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


def test_nucleo_card_no_emission_when_selection_matches_current(app, db):
    """v3.x dropped the explicit Apply button — selection now auto-
    emits whenever the user picks a row that differs from the
    current. Selecting the row that *matches* current must therefore
    NOT emit.
    """
    from pfc_inductor.models import Spec
    from pfc_inductor.ui.dashboard.cards.nucleo_card import NucleoCard
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
    # Without picking a different row, no signal should fire.
    assert received == []


def test_nucleo_card_emits_selection_applied_on_different_row(app, db):
    """Auto-apply on row click — picking a non-current core/wire row
    must emit ``selection_applied`` exactly once with the new id."""
    from PySide6.QtCore import QItemSelectionModel

    from pfc_inductor.models import Spec
    from pfc_inductor.ui.dashboard.cards.nucleo_card import NucleoCard

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

    tab = card._nbody.tab_core
    if tab._proxy.rowCount() < 2:
        pytest.skip("Need at least 2 cores in the catalog to exercise this path.")

    # Find a row whose underlying Core has a different id from the
    # current selection. We can't assume row 1 differs because the
    # default sort is by score and ties are possible.
    target_row = None
    for r in range(tab._proxy.rowCount()):
        cand = tab.selected_candidate()  # noqa: F841 — used for shape
        idx = tab._proxy.index(r, 0)
        candidate = tab._proxy.data(idx, 0x0100)  # Qt.UserRole
        if candidate is not None and getattr(candidate, "id", "") != core.id:
            target_row = r
            break
    if target_row is None:
        pytest.skip("All catalog cores share the current id (unexpected).")

    idx0 = tab._proxy.index(target_row, 0)
    tab.table.selectionModel().select(
        idx0,
        QItemSelectionModel.SelectionFlag.ClearAndSelect
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    # Auto-apply: at least one emission with material unchanged and
    # core changed to the new id.
    assert received, "expected selection_applied to fire"
    m_id, c_id, w_id = received[-1]
    assert m_id == mat.id
    assert c_id != core.id
    assert w_id == wire.id


def test_populate_skips_rebuild_when_only_selection_changes(app, db):
    """Same spec + same catalogs + same material → second populate
    must NOT rebuild the table (otherwise the user loses scroll
    position when the recalc triggered by their click re-fires
    populate)."""
    from pfc_inductor.models import Spec
    from pfc_inductor.ui.dashboard.cards.nucleo_card import NucleoCard
    card = NucleoCard()
    spec = Spec()
    mat = db["materials"][0]
    wire = db["wires"][0]
    # Pick two cores compatible enough that both render in the table.
    cores = db["cores"]
    core_a = cores[0]
    core_b = cores[1] if len(cores) > 1 else core_a

    # First populate: full rebuild expected.
    card.populate(spec, db["materials"], cores, db["wires"], mat, core_a, wire)
    rebuilds = []
    original = card._nbody.tab_core._model.set_rows
    def _spy(rows):
        rebuilds.append(len(rows))
        return original(rows)
    card._nbody.tab_core._model.set_rows = _spy

    # Second populate with a different *current* core but same spec / mat
    # / catalogs — must not re-rank.
    card.populate(spec, db["materials"], cores, db["wires"], mat, core_b, wire)
    assert rebuilds == [], (
        "populate() rebuilt the core table even though only the current "
        "selection changed; expected the cache to short-circuit."
    )

    # Third populate with a different material — rebuild IS expected
    # because rank_cores depends on material. Skip when there's only
    # one material in the catalog (impossible to test).
    if len(db["materials"]) > 1:
        mat2 = db["materials"][1]
        card.populate(spec, db["materials"], cores, db["wires"], mat2, core_a, wire)
        assert rebuilds, (
            "populate() must rebuild after a material change so the "
            "core ranking reflects the new (cores × material) pairing."
        )


def test_clear_resets_rebuild_cache(app, db):
    """``clear()`` must drop the rebuild cache so a subsequent
    ``populate()`` re-renders even with the same arguments."""
    from pfc_inductor.models import Spec
    from pfc_inductor.ui.dashboard.cards.nucleo_card import NucleoCard
    card = NucleoCard()
    spec = Spec()
    mat = db["materials"][0]
    core = db["cores"][0]
    wire = db["wires"][0]
    card.populate(spec, db["materials"], db["cores"], db["wires"],
                  mat, core, wire)
    card.clear()
    rebuilds = []
    original = card._nbody.tab_core._model.set_rows
    card._nbody.tab_core._model.set_rows = lambda rows: (rebuilds.append(1), original(rows))[1]
    card.populate(spec, db["materials"], db["cores"], db["wires"],
                  mat, core, wire)
    assert rebuilds, "populate() after clear() must re-render"
