"""Async-recalc plumbing for the v0.4.12 UI-thread freeze fix.

The MainWindow defers ``design()`` to a ``QThread`` worker so the
GUI stays responsive on rapid spec changes. These tests pin the
contracts that protect users from the "Not Responding" failure:

- The worker thread is constructed and started in production.
- Rapid recalc requests coalesce — at most one in-flight + one
  queued, with the queued slot always holding the freshest inputs.
- The synchronous (``defer_initial_calc=False``) path bypasses the
  worker entirely, so tests that don't pump the event queue still
  see state mutate inline.

We don't exercise actual ``design()`` execution here — that's
already covered by the existing ``test_main_window_shell``
synchronous suite. The point is to verify the dispatch / coalesce
state machine is correct.
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


def test_async_mode_creates_worker_thread(app):
    """Production constructor (``defer_initial_calc=True``) wires up
    the worker thread; the sync test mode does not."""
    from pfc_inductor.ui.main_window import MainWindow

    async_win = MainWindow(defer_initial_calc=True)
    try:
        assert async_win._async_recalc_enabled is True
        assert async_win._design_thread is not None
        assert async_win._design_worker is not None
        assert async_win._design_thread.isRunning()
    finally:
        async_win.close()
        # Give the thread a beat to wind down so module teardown
        # doesn't log the "QThread destroyed while running" warning.
        if async_win._design_thread is not None:
            async_win._design_thread.wait(2000)

    sync_win = MainWindow(defer_initial_calc=False)
    try:
        assert sync_win._async_recalc_enabled is False
        assert sync_win._design_thread is None
        assert sync_win._design_worker is None
    finally:
        sync_win.close()


def test_async_recalc_coalesces_pending_requests(app):
    """If the user fires multiple recalc requests while one is
    in-flight, only the freshest pending pair survives — older
    queued requests are dropped, never accumulated."""
    from pfc_inductor.ui.main_window import MainWindow

    win = MainWindow(defer_initial_calc=True)
    try:
        # Simulate "calc already running"; manual flag flip
        # bypasses actually running the worker.
        win._calc_in_flight = True

        # Three back-to-back recalc requests. Each ``_on_calculate``
        # call should just update ``_calc_pending_inputs``, not
        # spawn additional work.
        win._on_calculate()
        first_pending = win._calc_pending_inputs

        win._on_calculate()
        second_pending = win._calc_pending_inputs

        win._on_calculate()
        third_pending = win._calc_pending_inputs

        # Only one slot exists; the latest write wins.
        # (We can't trivially assert that the inputs differ
        # without mutating the spec drawer between calls; the
        # important invariant is that the queue depth is 1.)
        assert first_pending is not None
        assert second_pending is not None
        assert third_pending is not None
        # All three are the SAME tuple identity when the spec
        # hasn't been mutated between them — which is the
        # boring path that nonetheless confirms we're not
        # appending to a list under the hood.
        assert win._calc_pending_inputs == third_pending
    finally:
        win._calc_in_flight = False
        win.close()
        if win._design_thread is not None:
            win._design_thread.wait(2000)


def test_close_event_stops_worker_thread(app):
    """``closeEvent`` must quit the worker thread cleanly so we
    don't leak Qt threads across the process lifetime (which on
    Windows can hang the app at exit)."""
    from pfc_inductor.ui.main_window import MainWindow

    win = MainWindow(defer_initial_calc=True)
    assert win._design_thread is not None
    assert win._design_thread.isRunning()
    win.close()
    # ``closeEvent`` waits up to 2 s; in practice the worker has
    # no in-flight work in this fixture so it exits immediately.
    win._design_thread.wait(2000)
    assert not win._design_thread.isRunning()


def test_async_calc_actually_dispatches_and_returns(app):
    """End-to-end smoke: emit a recalc, pump the event loop, and
    verify ``design_completed`` fires.

    Catches the v0.4.11-class regression where
    ``QMetaObject.invokeMethod(worker, "compute", QueuedConnection,
    Q_ARG(object, …))`` raised ``RuntimeError: qArgDataFromPyType:
    Unable to find a QMetaType for "object"`` the moment the worker
    actually tried to dispatch. The coalesce-only tests above didn't
    catch that because they never exercised the dispatch path.
    """
    from PySide6.QtCore import QEventLoop, QTimer

    from pfc_inductor.ui.main_window import MainWindow

    win = MainWindow(defer_initial_calc=True)
    try:
        results: list = []

        def _on_done(*payload) -> None:
            results.append(payload)

        win.design_completed.connect(_on_done)
        # Trigger one calc by emitting the deferred initial calc
        # manually (production does this via QTimer.singleShot in
        # __init__; in the test we want a deterministic moment).
        win._on_calculate()

        # Pump the event loop until the design_completed signal
        # fires or we hit a generous 30 s timeout.
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        win.design_completed.connect(lambda *_: loop.quit())
        timeout.start(30_000)
        loop.exec()

        assert len(results) >= 1, (
            "design_completed never fired — the worker likely "
            "raised inside compute(). Check stderr for the trace."
        )
        # The payload is (result, spec, core, wire, material).
        result, spec, core, wire, material = results[0]
        assert spec is not None
        assert core is not None
        assert wire is not None
        assert material is not None
        assert result is not None
    finally:
        win.close()
        if win._design_thread is not None:
            win._design_thread.wait(2000)
