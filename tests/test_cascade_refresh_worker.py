"""Cascade refresh worker — keeps the UI responsive during a run.

The cascade engine itself has run in a ``QThread`` since the page
was built. What used to freeze the UI was the **poll-timer's
``_refresh_dynamic`` body**: 8 SQLite reads + candidate re-ranking
+ a matplotlib redraw every 750 ms, all on the GUI thread. Under
a busy cascade (rows arriving from the worker as fast as the
ProcessPoolExecutor can write them) those redraws stacked up and
the app appeared to hang.

These tests pin the contracts that protect users from that:

- The page constructs a long-lived refresh worker thread that
  stays alive for the page's lifetime.
- ``_refresh_dynamic`` dispatches via a signal, not a synchronous
  call, so the GUI thread never blocks on SQLite.
- Rapid timer ticks coalesce — at most one in-flight + one pending
  — so the GUI thread doesn't accumulate a backlog of redraws.
- The fingerprint check skips matplotlib redraws when the payload
  hasn't changed (quiet-cascade phases are no-ops on the GUI
  thread).
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


def test_refresh_worker_thread_is_started(app):
    """The page wires up the off-UI refresh worker at construction
    so we're never running SQLite + matplotlib on the GUI thread."""
    from pfc_inductor.ui.workspace.cascade_page import CascadePage

    page = CascadePage()
    try:
        assert page._refresh_thread is not None
        assert page._refresh_thread.isRunning()
        assert page._refresh_worker is not None
        # The worker carries the store reference it needs to open
        # its own connection — sqlite3 connections aren't thread-
        # safe so we never share them across threads.
        assert page._refresh_worker._store is page._store
    finally:
        page.close()
        if page._refresh_thread is not None:
            page._refresh_thread.wait(2000)


def test_refresh_coalesces_back_to_back_ticks(app):
    """Multiple ``_refresh_dynamic`` calls before the worker
    finishes don't queue a backlog — only one pending re-fire
    survives, so the UI doesn't catch up by replaying every
    intermediate tick."""
    from pfc_inductor.ui.workspace.cascade_page import CascadePage

    page = CascadePage()
    try:
        # Simulate a run-in-progress by setting a fake run_id and
        # pinning the in-flight flag (we're not actually running
        # the worker — we just exercise the coalescer).
        page._run_id = "test-run"
        page._refresh_in_flight = True

        # Three rapid timer ticks. Each should mark the pending
        # flag without queueing extra work.
        page._refresh_dynamic()
        page._refresh_dynamic()
        page._refresh_dynamic()

        # Exactly one pending flag set, no backlog.
        assert page._refresh_pending is True
        # No spurious in-flight changes.
        assert page._refresh_in_flight is True
    finally:
        page._refresh_in_flight = False
        page._refresh_pending = False
        page.close()
        if page._refresh_thread is not None:
            page._refresh_thread.wait(2000)


def test_refresh_skip_when_no_run_id(app):
    """``_refresh_dynamic`` is a no-op when no run has started
    yet — important because the poll timer is wired before the
    user clicks Run."""
    from pfc_inductor.ui.workspace.cascade_page import CascadePage

    page = CascadePage()
    try:
        assert page._run_id is None
        page._refresh_dynamic()  # must not crash, must not dispatch
        assert page._refresh_in_flight is False
    finally:
        page.close()
        if page._refresh_thread is not None:
            page._refresh_thread.wait(2000)


def test_refresh_fingerprint_skips_redundant_repaints(app):
    """When the worker returns the same payload twice in a row,
    the UI skips the second repaint entirely — the cascade is
    typically mid-batch-flush between polls and the visible state
    hasn't moved."""
    from pfc_inductor.ui.workspace.cascade_page import (
        CascadePage,
        _RefreshPayload,
    )

    page = CascadePage()
    try:
        payload = _RefreshPayload(
            stats=(10, 7, 3, 5, 0, 0, 0),
            reasons_text="—",
            rows=(),
            chart_data=((), (), ()),
            pareto_indices=(),
            has_t2=False,
            has_t3=False,
        )

        # First dispatch should record the fingerprint.
        page._refresh_in_flight = True
        page._on_refresh_payload(payload)
        first = page._last_refresh_fingerprint
        assert first is not None

        # Second identical payload should leave the fingerprint
        # unchanged (i.e. ``skip`` branch hit).
        page._refresh_in_flight = True
        page._on_refresh_payload(payload)
        assert page._last_refresh_fingerprint == first

        # Mutating the stats triggers a fresh fingerprint.
        page._refresh_in_flight = True
        page._on_refresh_payload(
            _RefreshPayload(
                stats=(20, 14, 6, 12, 0, 0, 0),
                reasons_text="—",
                rows=(),
                chart_data=((), (), ()),
                pareto_indices=(),
                has_t2=False,
                has_t3=False,
            )
        )
        assert page._last_refresh_fingerprint != first
    finally:
        page.close()
        if page._refresh_thread is not None:
            page._refresh_thread.wait(2000)


def test_close_event_stops_refresh_thread(app):
    """``closeEvent`` must shut the worker thread down so Qt doesn't
    log "QThread destroyed while running" on quit (also stops the
    Windows process from hanging at exit waiting on the event loop)."""
    from pfc_inductor.ui.workspace.cascade_page import CascadePage

    page = CascadePage()
    thread = page._refresh_thread
    assert thread is not None
    assert thread.isRunning()
    page.close()
    thread.wait(2000)
    assert not thread.isRunning()
