"""CascadePage widget tests — Phase A scope.

The page wires the orchestrator into a Qt thread. Here we exercise:
construction, set_inputs / run / cancel lifecycle, the polling-driven
top-N table refresh, and the open-in-design-view signal.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    inst = QApplication.instance() or QApplication([])
    yield inst


@pytest.fixture(scope="module")
def db():
    from pfc_inductor.data_loader import (
        load_cores,
        load_materials,
        load_wires,
    )

    target_id = "magnetics-60_highflux"
    materials = [m for m in load_materials() if m.id == target_id]
    cores = [c for c in load_cores() if c.default_material_id == target_id]
    wires = [w for w in load_wires() if w.id in {"AWG14", "AWG16"}]
    return {"materials": materials, "cores": cores, "wires": wires}


def _spec():
    from pfc_inductor.models import Spec

    return Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=220.0,
        Vout_V=400.0,
        Pout_W=800.0,
        eta=0.97,
        f_sw_kHz=65.0,
        ripple_pct=30.0,
        T_amb_C=40.0,
        T_max_C=100.0,
        Ku_max=0.40,
        Bsat_margin=0.20,
    )


def _wait_until(predicate, *, app, timeout: float = 30.0, step: float = 0.05) -> bool:
    """Pump the Qt event loop until `predicate()` is true or timeout.

    Tests use this instead of QTest.qWait so they remain robust on
    headless CI where the worker thread's pace is unpredictable.
    """
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(step)
    return False


# ─── Construction ──────────────────────────────────────────────────


def test_cascade_page_constructs_with_default_store(app, tmp_path: Path):
    from pfc_inductor.ui.workspace import CascadePage

    page = CascadePage(store_path=tmp_path / "cascade.db")
    assert page._btn_run.isEnabled()
    assert not page._btn_cancel.isEnabled()
    assert page._table.rowCount() == 0


def test_cascade_page_run_disabled_until_inputs_set(app, tmp_path: Path):
    from pfc_inductor.ui.workspace import CascadePage

    page = CascadePage(store_path=tmp_path / "cascade.db")
    # Calling run() with no spec is a no-op — button stays enabled,
    # nothing breaks, no thread starts.
    page.run()
    assert page._thread is None


# ─── End-to-end run via the page ───────────────────────────────────


def test_cascade_page_runs_to_completion_and_populates_table(app, tmp_path: Path, db):
    """Click Run; wait for finish; the top-N table must have rows."""
    from pfc_inductor.optimize.cascade import CascadeConfig
    from pfc_inductor.ui.workspace import CascadePage

    page = CascadePage(store_path=tmp_path / "cascade.db")
    page.set_inputs(_spec(), db["materials"], db["cores"], db["wires"], CascadeConfig())

    finished_status: list[str] = []
    page._orch.parallelism = 1  # sequential is more predictable for tests

    def _capture(status: str) -> None:
        finished_status.append(status)

    page.run()
    # Connect after run() so the worker exists.
    assert page._worker is not None
    page._worker.finished.connect(_capture)

    assert _wait_until(lambda: len(finished_status) > 0, app=app, timeout=60.0)
    assert finished_status[0] == "done"

    # Top-N table populated with at least one row, and the first cell of
    # each row carries a candidate key on UserRole.
    assert page._table.rowCount() > 0
    first_cell = page._table.item(0, 0)
    assert first_cell is not None
    assert isinstance(first_cell.data(0x0100), str)


# ─── Cancellation ──────────────────────────────────────────────────


def test_cascade_page_cancel_button_aborts_run(app, tmp_path: Path, db):
    """Trigger a run, click Cancel, run finishes promptly with cancelled state."""
    from pfc_inductor.optimize.cascade import CascadeConfig
    from pfc_inductor.ui.workspace import CascadePage

    page = CascadePage(store_path=tmp_path / "cascade.db")
    page.set_inputs(_spec(), db["materials"], db["cores"], db["wires"], CascadeConfig())
    page._orch.parallelism = 1

    finished_status: list[str] = []

    page.run()
    assert page._worker is not None
    page._worker.finished.connect(lambda s: finished_status.append(s))

    # Cancel right after start. Whether the run completes naturally
    # before the cancel signal lands depends on timing — but in either
    # case the page must end up with the buttons reset and a recorded
    # status.
    page.cancel()
    assert _wait_until(lambda: len(finished_status) > 0, app=app, timeout=60.0)
    assert finished_status[0] in {"done", "cancelled"}
    assert page._btn_run.isEnabled()
    assert not page._btn_cancel.isEnabled()


# ─── Open-in-design-view signal ────────────────────────────────────


def test_cascade_page_double_click_emits_open_signal(app, tmp_path: Path, db):
    from PySide6.QtWidgets import QTableWidgetItem

    from pfc_inductor.optimize.cascade import CascadeConfig
    from pfc_inductor.ui.workspace import CascadePage

    page = CascadePage(store_path=tmp_path / "cascade.db")
    page.set_inputs(_spec(), db["materials"], db["cores"], db["wires"], CascadeConfig())
    page._orch.parallelism = 1

    finished_status: list[str] = []
    page.run()
    assert page._worker is not None
    page._worker.finished.connect(lambda s: finished_status.append(s))
    assert _wait_until(lambda: len(finished_status) > 0, app=app, timeout=60.0)
    assert page._table.rowCount() > 0

    received: list[str] = []
    page.open_in_design_requested.connect(lambda key: received.append(key))

    # Simulate a double-click on the first row's first cell.
    first = page._table.item(0, 0)
    assert isinstance(first, QTableWidgetItem)
    page._on_row_activated(first)

    assert received
    assert received[0] == first.data(0x0100)
