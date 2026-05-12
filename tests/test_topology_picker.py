"""Topology picker dialog regressions."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    inst = QApplication.instance() or QApplication([])
    yield inst


def test_picker_default_selection_matches_current(app):
    from pfc_inductor.ui.dialogs import TopologyPickerDialog

    dlg = TopologyPickerDialog(current="passive_choke")
    assert dlg.selected_key() == "passive_choke"


def test_picker_resolves_line_reactor_to_correct_variant(app):
    from pfc_inductor.ui.dialogs import TopologyPickerDialog

    # Default: 1ph
    dlg = TopologyPickerDialog(current="line_reactor", n_phases=1)
    assert dlg.selected_schematic_key() == "line_reactor_1ph"
    # 3ph
    dlg = TopologyPickerDialog(current="line_reactor", n_phases=3)
    assert dlg.selected_schematic_key() == "line_reactor_3ph"


def test_picker_clicking_an_option_changes_selection(app):
    from pfc_inductor.ui.dialogs import TopologyPickerDialog

    dlg = TopologyPickerDialog(current="boost_ccm")
    assert dlg.selected_key() == "boost_ccm"
    dlg._on_option_clicked("passive_choke")
    assert dlg.selected_key() == "passive_choke"


def test_picker_selected_n_phases_for_line_reactor(app):
    from pfc_inductor.ui.dialogs import TopologyPickerDialog

    dlg = TopologyPickerDialog(current="boost_ccm")
    dlg._on_option_clicked("line_reactor_3ph")
    assert dlg.selected_key() == "line_reactor"
    assert dlg.selected_n_phases() == 3
    dlg._on_option_clicked("line_reactor_1ph")
    assert dlg.selected_n_phases() == 1


def test_picker_has_all_topologies(app):
    """Picker exposes all engine topologies as cards.

    The two line-reactor variants (1φ and 3φ) appear as separate
    cards even though they map back to a single ``Spec.topology``
    value, so the user picks the phasing without a secondary combo.
    Same logic for the two interleaved-boost variants. Newest cards:
    buck-CCM (``add-buck-ccm-topology``) and flyback
    (``add-flyback-topology``).
    """
    from pfc_inductor.ui.dialogs import TopologyPickerDialog

    dlg = TopologyPickerDialog()
    keys = set(dlg._options.keys())
    # Required core topologies — every release ships these.
    assert {
        "boost_ccm",
        "passive_choke",
        "line_reactor_1ph",
        "line_reactor_3ph",
        "buck_ccm",
        "flyback",
    } <= keys, f"missing required topology cards: {keys}"


def test_picker_accept_returns_accepted_code(app):
    from pfc_inductor.ui.dialogs import TopologyPickerDialog

    dlg = TopologyPickerDialog()
    dlg.accept()
    assert dlg.result() == TopologyPickerDialog.DialogCode.Accepted


# ---------------------------------------------------------------------------
# Integration: clicking "Alterar Topologia" wires through to the spec panel
# ---------------------------------------------------------------------------


def test_main_window_topology_picker_applies_to_spec_panel(app, monkeypatch):
    """Simulate the user clicking "Alterar Topologia" → picker selects
    passive_choke → spec panel's topology combo should reflect that."""
    from pfc_inductor.ui.dialogs import TopologyPickerDialog
    from pfc_inductor.ui.main_window import MainWindow

    w = MainWindow(defer_initial_calc=False)

    # Force-apply: stub TopologyPickerDialog.exec to return Accepted
    # and pre-set the chosen key.
    def fake_exec(self_dlg):
        self_dlg._selected_key = "passive_choke"
        return TopologyPickerDialog.DialogCode.Accepted

    monkeypatch.setattr(TopologyPickerDialog, "exec", fake_exec)
    w._open_topology_picker()

    # The spec panel (now hosted inside the SpecDrawer) should reflect
    # the chosen topology via the new ``topology()`` accessor — the
    # ``cmb_topology`` QComboBox was removed when the SpecDrawer's
    # "Change Topology" button became the single source of truth.
    sp = w.projeto_page.spec_panel
    assert sp.topology() == "passive_choke"
    assert sp.get_spec().topology == "passive_choke"
    # Drawer button label tracks the SpecPanel's ``topology_changed``.
    assert "Passive choke" in w.projeto_page.drawer._btn_change_topo.text()
    w.close()


def test_spec_panel_set_topology_aliases_line_reactor_variants(app):
    """``line_reactor_1ph`` / ``line_reactor_3ph`` from the picker map
    to the canonical ``line_reactor`` Spec key + matching n_phases."""
    from pfc_inductor.ui.spec_panel import SpecPanel

    sp = SpecPanel()
    sp.set_topology("line_reactor_3ph")
    assert sp.topology() == "line_reactor"
    assert sp.n_phases() == 3
    sp.set_topology("line_reactor_1ph")
    assert sp.topology() == "line_reactor"
    assert sp.n_phases() == 1


def test_spec_panel_set_topology_idempotent_on_same_value(app):
    """Re-applying the same topology must not fire ``changed`` —
    otherwise MainWindow's debounced recalc thrashes."""
    from pfc_inductor.ui.spec_panel import SpecPanel

    sp = SpecPanel()
    sp.set_topology("boost_ccm")
    n_emitted: list[None] = []
    sp.changed.connect(lambda: n_emitted.append(None))
    sp.set_topology("boost_ccm")  # no-op
    assert n_emitted == []
    sp.set_topology("passive_choke")
    assert len(n_emitted) == 1


def test_spec_panel_rejects_unknown_topology(app):
    from pfc_inductor.ui.spec_panel import SpecPanel

    sp = SpecPanel()
    with pytest.raises(ValueError):
        sp.set_topology("not_a_topology")
