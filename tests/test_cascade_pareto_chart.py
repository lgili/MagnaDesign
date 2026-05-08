"""Pareto chart on `CascadePage` — `_ParetoChart` + tab widget integration."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from typing import ClassVar

import pytest

from pfc_inductor.models import Core
from pfc_inductor.optimize.cascade import CandidateRow


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    inst = QApplication.instance() or QApplication([])
    yield inst


def _row(key: str, *, loss: float, core_id: str) -> CandidateRow:
    return CandidateRow(
        candidate_key=key,
        core_id=core_id,
        material_id="mat",
        wire_id="wire",
        N=42,
        gap_mm=None,
        highest_tier=1,
        feasible_t0=True,
        loss_t1_W=loss,
        temp_t1_C=70.0,
        cost_t1_USD=4.0,
    )


def _core(core_id: str, *, Ve_mm3: float) -> Core:
    return Core(
        id=core_id,
        vendor="x",
        shape="Toroid",
        part_number="T-X",
        default_material_id="mat",
        Ae_mm2=100.0,
        le_mm=80.0,
        Ve_mm3=Ve_mm3,
        Wa_mm2=200.0,
        MLT_mm=80.0,
        AL_nH=200.0,
    )


# ─── _pareto_indices ──────────────────────────────────────────────


def test_pareto_indices_picks_non_dominated_set():
    """Three points: (1,5) is best on volume, (3,1) is best on
    loss, (2,3) sits between and is also non-dominated. (4,5)
    is dominated by (1,5)."""
    from pfc_inductor.ui.workspace.cascade_page import _pareto_indices

    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [5.0, 3.0, 1.0, 5.0]
    pareto = sorted(_pareto_indices(xs, ys))
    assert pareto == [0, 1, 2]  # last point (4,5) dominated by (1,5)


def test_pareto_indices_handles_duplicate_points():
    from pfc_inductor.ui.workspace.cascade_page import _pareto_indices

    xs = [1.0, 1.0, 2.0]
    ys = [3.0, 3.0, 1.0]
    pareto = _pareto_indices(xs, ys)
    # Both duplicates dominate each other (strict-dominate rule),
    # so neither is in the Pareto set.
    assert 2 in pareto


# ─── _ParetoChart ─────────────────────────────────────────────────


def test_pareto_chart_renders_empty_state(app):
    from pfc_inductor.ui.workspace.cascade_page import _ParetoChart

    chart = _ParetoChart()
    # No populate call → empty state. The widget itself is constructed
    # without errors and `_row_keys` is empty.
    assert chart._row_keys == []


def test_pareto_chart_populates_skipping_rows_without_loss(app):
    from pfc_inductor.ui.workspace.cascade_page import _ParetoChart

    chart = _ParetoChart()
    rows = [
        _row("k1|m|w", loss=5.0, core_id="cA"),
        _row("k2|m|w", loss=4.0, core_id="cB"),
        # Tier-0-only row: no loss yet — must be skipped.
        CandidateRow(
            candidate_key="k3|m|w",
            core_id="cA",
            material_id="mat",
            wire_id="wire",
            N=None,
            gap_mm=None,
            highest_tier=0,
            feasible_t0=False,
            loss_t1_W=None,
            temp_t1_C=None,
            cost_t1_USD=None,
        ),
    ]
    cores_by_id = {
        "cA": _core("cA", Ve_mm3=20_000),
        "cB": _core("cB", Ve_mm3=50_000),
    }
    chart.populate(rows, cores_by_id)
    assert chart._row_keys == ["k1|m|w", "k2|m|w"]


def test_pareto_chart_skips_rows_with_unknown_core(app):
    """A row pointing at a core not in `cores_by_id` is dropped —
    the chart's contract is that any plotted point can be located
    on the volume axis."""
    from pfc_inductor.ui.workspace.cascade_page import _ParetoChart

    chart = _ParetoChart()
    rows = [
        _row("k1|m|w", loss=5.0, core_id="known"),
        _row("k2|m|w", loss=4.0, core_id="ghost"),
    ]
    cores_by_id = {"known": _core("known", Ve_mm3=20_000)}
    chart.populate(rows, cores_by_id)
    assert chart._row_keys == ["k1|m|w"]


def test_pareto_chart_emits_selection_changed_on_pick(app):
    """Simulate a matplotlib pick event with index 0 — the chart
    must emit the corresponding candidate_key."""
    from pfc_inductor.ui.workspace.cascade_page import _ParetoChart

    chart = _ParetoChart()
    rows = [
        _row("k1|m|w", loss=5.0, core_id="cA"),
        _row("k2|m|w", loss=4.0, core_id="cB"),
    ]
    cores_by_id = {
        "cA": _core("cA", Ve_mm3=20_000),
        "cB": _core("cB", Ve_mm3=50_000),
    }
    chart.populate(rows, cores_by_id)

    received: list[str] = []
    chart.selection_changed.connect(lambda key: received.append(key))

    class _PickEvent:
        ind: ClassVar[list[int]] = [1]

    chart._on_pick(_PickEvent())
    assert received == ["k2|m|w"]


# ─── CascadePage tabs integration ─────────────────────────────────


def test_cascade_page_has_results_tabs(app, tmp_path: Path):
    """The redesigned page hosts both the table and the Pareto
    chart inside a QTabWidget — the engineer can toggle without
    losing the run state.

    Tab labels were translated to English during the MagnaDesign
    rebrand (``Lista`` → ``List``).
    """
    from pfc_inductor.ui.workspace import CascadePage

    page = CascadePage(store_path=tmp_path / "cascade.db")
    assert page._results_tabs.count() == 2
    assert page._results_tabs.tabText(0).lower() == "list"
    assert page._results_tabs.tabText(1).lower() == "pareto"


def test_cascade_page_chart_pick_syncs_table_selection(app, tmp_path: Path):
    """Picking a point on the Pareto chart must select the same
    row in the sibling top-N table — the user can flip between
    the two views without losing focus."""
    from PySide6.QtWidgets import QTableWidgetItem

    from pfc_inductor.ui.workspace import CascadePage
    from pfc_inductor.ui.workspace.cascade_page import _USER_ROLE_KEY

    page = CascadePage(store_path=tmp_path / "cascade.db")
    page._table.setColumnCount(len(page._table.BASE_HEADERS))
    page._table.setRowCount(2)
    for i, key in enumerate(["a|m|w|_|_", "b|m|w|_|_"]):
        page._table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
        page._table.item(i, 0).setData(_USER_ROLE_KEY, key)

    page._on_chart_pick("b|m|w|_|_")
    selected = page._table.currentRow()
    cell = page._table.item(selected, 0)
    assert cell is not None
    assert cell.data(_USER_ROLE_KEY) == "b|m|w|_|_"
