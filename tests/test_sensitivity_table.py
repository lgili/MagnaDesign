"""Sensitivity table — engine helper + UI integration tests."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


# ---------------------------------------------------------------------------
# Engine helper
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def reference_summary():
    """Run the corner DOE on the bundled boost-PFC reference so
    every test in this module can read the same summary."""
    from pfc_inductor.data_loader import (
        ensure_user_data, load_cores, load_materials, load_wires,
    )
    from pfc_inductor.models import Spec
    from pfc_inductor.worst_case import (
        DEFAULT_TOLERANCES, evaluate_corners,
    )

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
    return evaluate_corners(spec, core, wire, mat, DEFAULT_TOLERANCES)


def test_sensitivity_table_returns_per_metric_ranked(
    reference_summary,
) -> None:
    from pfc_inductor.worst_case import sensitivity_table
    table = sensitivity_table(reference_summary)
    # All four tracked metrics are ranked.
    assert "T_winding_C" in table
    assert "B_pk_T" in table
    assert "P_total_W" in table
    assert "T_rise_C" in table
    # Each metric ranked descending by impact.
    for metric, ranked in table.items():
        impacts = [impact for _, impact in ranked]
        assert impacts == sorted(impacts, reverse=True), (
            f"{metric} not sorted by impact"
        )


def test_t_winding_top_tolerance_is_thermal(
    reference_summary,
) -> None:
    """Engineering anchor: T_winding's #1 sensitivity comes from
    either ambient temperature swing or load swing. Neither
    should land BELOW the magnetic-only tolerances (AL, Bsat,
    µ_r) in the ranking — those don't move T_winding directly."""
    from pfc_inductor.worst_case import sensitivity_table

    table = sensitivity_table(reference_summary)
    ranked = table["T_winding_C"]
    top_name, _ = ranked[0]
    # The top contributor's name carries one of the thermal /
    # load-side keywords.
    assert any(kw in top_name.lower() for kw in (
        "t_amb", "ambient", "pout", "load", "vin",
    ))


def test_p_total_top_tolerance_is_load(
    reference_summary,
) -> None:
    """Engineering anchor: total-loss swing is dominated by
    Pout (current squared in copper, B² in core)."""
    from pfc_inductor.worst_case import sensitivity_table
    ranked = sensitivity_table(reference_summary)["P_total_W"]
    top_name, _ = ranked[0]
    assert "pout" in top_name.lower()


def test_sensitivity_with_no_corners_returns_empty() -> None:
    """A summary with no successful corners should return an
    empty dict — defensive against degenerate inputs."""
    from pfc_inductor.worst_case import sensitivity_table
    from pfc_inductor.worst_case.engine import WorstCaseSummary

    empty = WorstCaseSummary(
        n_corners_evaluated=0, n_corners_failed=0,
        nominal=None, corners=(),
    )
    assert sensitivity_table(empty) == {}


# ---------------------------------------------------------------------------
# UI integration
# ---------------------------------------------------------------------------
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


def test_sensitivity_table_widget_present_at_construction(tab) -> None:
    """The table is mounted as a Card on the tab; default state
    has zero rows until ``_on_corners_done`` runs."""
    assert tab._sensitivity_table is not None
    assert tab._sensitivity_table.rowCount() == 0
    assert tab._sensitivity_table.columnCount() == 3


def test_sensitivity_table_populates_on_corners_done(
    tab, reference_summary,
) -> None:
    """Drive ``_on_corners_done`` directly; the sensitivity table
    should pick up one row per metric with a non-empty top tolerance."""
    tab._on_corners_done(reference_summary)
    assert tab._sensitivity_table.rowCount() >= 1
    # Each row has all three columns filled in.
    for r in range(tab._sensitivity_table.rowCount()):
        for c in range(3):
            item = tab._sensitivity_table.item(r, c)
            assert item is not None
            assert item.text().strip(), (
                f"empty cell at row={r} col={c}"
            )


def test_sensitivity_table_units_match_metric_units(
    tab, reference_summary,
) -> None:
    """Format helper: T_winding_C and T_rise_C → °C, B_pk_T →
    mT, P_total_W → W. Reads from the rendered cell text."""
    tab._on_corners_done(reference_summary)
    expected = {
        "T winding": "°C",
        "ΔT":        "°C",
        "B peak":    "mT",
        "Losses":    "W",
    }
    for r in range(tab._sensitivity_table.rowCount()):
        metric = tab._sensitivity_table.item(r, 0).text()
        impact = tab._sensitivity_table.item(r, 2).text()
        if metric in expected:
            assert expected[metric] in impact, (
                f"row {r} metric={metric!r} impact={impact!r}"
            )
