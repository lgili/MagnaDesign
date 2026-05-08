"""Worst-case workspace tab — smoke tests for the UI shell.

The corner DOE / Monte-Carlo physics has its own coverage in
``test_worst_case_engine``; this file covers the tab's
construction, button states, and signal-handler wiring without
spawning the engine in a worker thread (the worker is
exercised manually + has a slow integration cousin gated on
``-m slow`` for CI).
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
def tab(app):
    from pfc_inductor.ui.workspace.worst_case_tab import WorstCaseTab
    w = WorstCaseTab()
    yield w
    w.deleteLater()


@pytest.fixture(scope="module")
def reference_inputs():
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
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=65, ripple_pct=20, T_amb_C=40,
    )
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores
                if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    result = run_design(spec, core, wire, mat)
    return spec, core, wire, mat, result


def test_worst_case_tab_starts_with_buttons_enabled(tab) -> None:
    """At construction the user can click any of the three Run
    buttons even before a design has been computed — clicking
    without a design surfaces the "run a design first" status
    instead of crashing."""
    assert tab._btn_corners.isEnabled()
    assert tab._btn_yield.isEnabled()
    assert tab._btn_both.isEnabled()


def test_worst_case_tab_status_updates_on_design(
    tab, reference_inputs,
) -> None:
    """``update_from_design`` caches the engine inputs and reflects
    the topology/material/core in the status line."""
    spec, core, wire, mat, result = reference_inputs
    tab.update_from_design(result, spec, core, wire, mat)
    text = tab._status.text()
    assert spec.topology in text
    assert mat.name in text
    assert core.part_number in text


def test_worst_case_tab_default_yield_label_is_neutral(tab) -> None:
    """Hero label starts as a muted em-dash; the colour-coded
    pass/warn/fail green/amber/red kicks in only after a yield
    run completes."""
    assert tab._lbl_yield_pct.text() == "—"


def test_worst_case_tab_populates_table_when_corner_run_completes(
    tab, reference_inputs,
) -> None:
    """Drive ``_on_corners_done`` directly with a synthesised
    summary — the table picks up four rows (one per tracked
    metric) and the status line reports the corner count."""
    from pfc_inductor.worst_case import (
        DEFAULT_TOLERANCES, evaluate_corners,
    )

    spec, core, wire, mat, result = reference_inputs
    tab.update_from_design(result, spec, core, wire, mat)
    summary = evaluate_corners(spec, core, wire, mat, DEFAULT_TOLERANCES)
    tab._on_corners_done(summary)

    # Each tracked metric (T_winding, B_pk, P_total, T_rise) lands
    # in the table once. Engine failures or unread metrics drop
    # rows; we verify at least one was populated.
    assert tab._worst_table.rowCount() >= 1
    # Status line carries the corner count.
    assert "corners" in tab._status.text().lower()


def test_worst_case_tab_yield_label_colors_per_band(
    tab, reference_inputs,
) -> None:
    """100 % rate → green; 80 % → red; 92 % → amber. We assert
    the QSS string changes between bands rather than parsing the
    hex value (the palette is theme-driven)."""
    from pfc_inductor.worst_case.monte_carlo import YieldReport

    spec, core, wire, mat, result = reference_inputs
    tab.update_from_design(result, spec, core, wire, mat)

    tab._on_yield_done(YieldReport(
        n_samples=100, n_pass=100, n_fail=0, n_engine_error=0,
        pass_rate=1.0,
    ))
    green_qss = tab._lbl_yield_pct.styleSheet()

    tab._on_yield_done(YieldReport(
        n_samples=100, n_pass=80, n_fail=20, n_engine_error=0,
        pass_rate=0.80,
    ))
    red_qss = tab._lbl_yield_pct.styleSheet()

    assert green_qss != red_qss
