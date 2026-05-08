"""Compliance workspace tab — smoke tests for the UI shell."""
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
def tab(app):
    from pfc_inductor.ui.workspace.compliance_tab import ComplianceTab
    w = ComplianceTab()
    yield w
    w.deleteLater()


@pytest.fixture(scope="module")
def reference_inputs():
    """Line reactor — picked because the IEC dispatcher actually
    has rows to render for it (boost-PFC is "trivially compliant"
    with a single-cell summary)."""
    from pfc_inductor.data_loader import (
        ensure_user_data, load_cores, load_materials, load_wires,
    )
    from pfc_inductor.design import design as run_design
    from pfc_inductor.models import Spec

    ensure_user_data()
    mats = load_materials()
    cores = load_cores()
    wires = load_wires()
    spec = Spec(
        topology="line_reactor",
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vin_nom_Vrms=230,
        Pout_W=600, n_phases=1, L_req_mH=10.0,
        I_rated_Arms=2.6, T_amb_C=40,
    )
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores
                if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    result = run_design(spec, core, wire, mat)
    return spec, core, wire, mat, result


def test_compliance_tab_default_state(tab) -> None:
    """Construction should leave the Evaluate button enabled and
    the PDF button disabled (nothing to export until evaluate
    runs)."""
    assert tab._btn_evaluate.isEnabled()
    assert not tab._btn_pdf.isEnabled()


def test_compliance_tab_region_combo_has_four_entries(tab) -> None:
    """Worldwide / EU / BR / US match
    ``ComplianceBundle.region`` literal."""
    items = [tab._cmb_region.itemText(i)
             for i in range(tab._cmb_region.count())]
    assert set(items) == {"Worldwide", "EU", "BR", "US"}


def test_compliance_tab_renders_bundle_with_per_standard_card(
    tab, reference_inputs,
) -> None:
    """Drive ``_on_done`` directly with a real bundle. The card
    stack should grow by one widget per standard, and the
    Export-PDF button should enable."""
    from pfc_inductor.compliance import evaluate

    spec, core, wire, mat, result = reference_inputs
    tab.update_from_design(result, spec, core, wire, mat)

    bundle = evaluate(spec, core, wire, mat, result,
                      project_name="ui-test", region="EU")
    tab._on_done(bundle)

    assert tab._btn_pdf.isEnabled()
    # One Card per standard. We don't peek into the Card's body
    # — the per-row table content is covered by the dispatcher
    # tests; here we only assert the card count matches the
    # bundle's standard list.
    assert tab._cards_layout.count() == len(bundle.standards)


def test_compliance_tab_handles_empty_bundle_gracefully(tab) -> None:
    """A US-region run today produces no standards. The verdict
    strip should land on NOT APPLICABLE with the explanatory
    summary visible to the user."""
    from pfc_inductor.compliance import ComplianceBundle

    empty = ComplianceBundle(
        project_name="x", topology="boost_ccm", region="US",
        standards=[],
    )
    tab._on_done(empty)
    assert tab._cards_layout.count() == 0
    # Verdict strip's label includes the "no applicable" hint.
    label_text = tab._overall._label.text()
    assert "NOT APPLICABLE" in label_text
    assert "No applicable standards" in label_text


def test_compliance_tab_set_project_name_propagates(tab) -> None:
    tab.set_project_name("My Project")
    assert tab._project_name == "My Project"
    # Empty / falsy values fall back to the default sentinel —
    # the PDF metadata always has a project label.
    tab.set_project_name("")
    assert tab._project_name == "Untitled Project"
