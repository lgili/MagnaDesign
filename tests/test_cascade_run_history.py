"""Run history dropdown + load-from-store flow on `CascadePage`.

Covers `_RunHistoryDialog` (modal listing past runs from the
SQLite store) and `CascadePage._load_run_id` (the hydration path
that fills stats + table + spec strip without re-running anything).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from pfc_inductor.data_loader import current_db_versions
from pfc_inductor.models import Spec
from pfc_inductor.optimize.cascade import (
    CandidateRow,
    RunStore,
)


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance() or QApplication([])
    yield inst


def _spec(Pout: float = 800.0) -> Spec:
    return Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
        Vout_V=400.0, Pout_W=Pout, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
        T_amb_C=40.0, T_max_C=100.0, Ku_max=0.40, Bsat_margin=0.20,
    )


def _seed_run(store: RunStore, *, spec: Spec, n_rows: int = 3) -> str:
    """Insert a synthetic 'done' run with a few feasible candidates."""
    run_id = store.create_run(spec, current_db_versions(), {})
    for i in range(n_rows):
        store.write_candidate(run_id, CandidateRow(
            candidate_key=f"core_{i}|mat|wire|_|_",
            core_id=f"core_{i}", material_id="mat", wire_id="wire",
            N=42 + i, gap_mm=None,
            highest_tier=1, feasible_t0=True,
            loss_t1_W=5.0 + i, temp_t1_C=70.0,
            cost_t1_USD=4.0,
        ))
    store.update_status(run_id, "done")
    return run_id


# ─── _RunHistoryDialog ─────────────────────────────────────────────


def test_history_dialog_lists_runs_in_store(app, tmp_path: Path):
    from pfc_inductor.ui.workspace.cascade_page import _RunHistoryDialog

    store = RunStore(tmp_path / "cascade.db")
    rid_a = _seed_run(store, spec=_spec(800.0), n_rows=2)
    rid_b = _seed_run(store, spec=_spec(1200.0), n_rows=4)

    dialog = _RunHistoryDialog(store)
    items = [dialog._list.item(i) for i in range(dialog._list.count())]
    listed_ids = [item.data(0x0100) for item in items]
    assert set(listed_ids) == {rid_a, rid_b}


def test_history_dialog_shows_topology_and_status_in_label(app, tmp_path: Path):
    from pfc_inductor.ui.workspace.cascade_page import _RunHistoryDialog

    store = RunStore(tmp_path / "cascade.db")
    _seed_run(store, spec=_spec(), n_rows=2)
    dialog = _RunHistoryDialog(store)
    label = dialog._list.item(0).text()
    assert "boost_ccm" in label
    assert "done" in label
    assert "cand" in label  # candidate count shown


def test_history_dialog_handles_empty_store(app, tmp_path: Path):
    """A fresh store shows a placeholder — Open button stays disabled."""
    from PySide6.QtWidgets import QDialogButtonBox

    from pfc_inductor.ui.workspace.cascade_page import _RunHistoryDialog

    store = RunStore(tmp_path / "cascade.db")
    dialog = _RunHistoryDialog(store)
    assert dialog._list.count() == 1
    assert "no runs" in dialog._list.item(0).text().lower()
    open_btn = dialog._buttons.button(QDialogButtonBox.StandardButton.Open)
    assert not open_btn.isEnabled()


def test_history_dialog_default_selection_matches_list_runs_order(app, tmp_path: Path):
    """`list_runs()` orders DESC by start time; the dialog defaults
    to the first row from that ordering. We don't assert *which*
    of two same-second runs is first (that's an implementation
    detail of SQLite's secondary ordering); we assert the default
    matches whatever `list_runs()` reports as element zero."""
    from pfc_inductor.ui.workspace.cascade_page import _RunHistoryDialog

    store = RunStore(tmp_path / "cascade.db")
    _seed_run(store, spec=_spec(800.0))
    _seed_run(store, spec=_spec(1200.0))
    expected_first = store.list_runs()[0].run_id
    dialog = _RunHistoryDialog(store)
    assert dialog.selected_run_id() == expected_first


def test_history_dialog_reports_selected_run_id(app, tmp_path: Path):
    from pfc_inductor.ui.workspace.cascade_page import _RunHistoryDialog

    store = RunStore(tmp_path / "cascade.db")
    rid_a = _seed_run(store, spec=_spec(800.0))
    _seed_run(store, spec=_spec(1200.0))
    dialog = _RunHistoryDialog(store)
    # Manually select the older run.
    for i in range(dialog._list.count()):
        if dialog._list.item(i).data(0x0100) == rid_a:
            dialog._list.setCurrentRow(i)
            break
    assert dialog.selected_run_id() == rid_a


# ─── CascadePage._load_run_id ──────────────────────────────────────


def test_load_run_id_populates_table_and_spec_strip(app, tmp_path: Path):
    from pfc_inductor.ui.workspace import CascadePage

    db_path = tmp_path / "cascade.db"
    store = RunStore(db_path)
    rid = _seed_run(store, spec=_spec(800.0), n_rows=4)

    page = CascadePage(store_path=db_path)
    page._load_run_id(rid)

    # Spec strip reflects the seeded run.
    assert page._spec_strip._fields["topology"].text() == "boost_ccm"
    # Table populated.
    assert page._table.rowCount() == 4
    # All tier bars marked done.
    for status in page._tiers._statuses.values():
        assert status.text() == "done"
    # Run id stored.
    assert page._run_id == rid
    # Status reflects "loaded".
    assert "loaded" in page._status_label.text()


def test_history_button_present_on_cascade_page(app, tmp_path: Path):
    from pfc_inductor.ui.workspace import CascadePage

    page = CascadePage(store_path=tmp_path / "cascade.db")
    assert page._btn_history is not None
    assert page._btn_history.isEnabled()
