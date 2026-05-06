"""WorkflowState mutator + persistence regressions."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
from datetime import datetime, timedelta

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance() or QApplication([])
    yield inst


# ---------------------------------------------------------------------------
# Mutators
# ---------------------------------------------------------------------------

def test_set_current_step_clamps_to_valid_range(app):
    from pfc_inductor.ui.state import WorkflowState, WORKFLOW_STEPS
    s = WorkflowState()
    s.set_current_step(99)
    assert s.current_step == len(WORKFLOW_STEPS) - 1
    s.set_current_step(-5)
    assert s.current_step == 0


def test_mark_step_done_is_idempotent_emits_once(app):
    from pfc_inductor.ui.state import WorkflowState
    s = WorkflowState()
    received = []
    s.state_changed.connect(lambda: received.append(1))
    s.mark_step_done(2)
    assert s.completed_steps == frozenset({2})
    s.mark_step_done(2)  # already done — must not re-emit
    assert len(received) == 1


def test_set_warnings_emits_only_when_value_actually_changes(app):
    from pfc_inductor.ui.state import WorkflowState
    s = WorkflowState()
    fired = []
    s.state_changed.connect(lambda: fired.append(1))
    s.set_warnings(0)  # already 0
    s.set_warnings(3)  # change
    s.set_warnings(3)  # same
    assert s.warnings == 3
    assert len(fired) == 1


def test_mark_saved_clears_unsaved_and_sets_timestamp(app):
    from pfc_inductor.ui.state import WorkflowState
    s = WorkflowState()
    s.set_project_name("New name")  # marks dirty
    assert s.unsaved
    assert s.last_saved_at is None
    s.mark_saved()
    assert not s.unsaved
    assert isinstance(s.last_saved_at, datetime)


def test_snapshot_returns_independent_copy(app):
    from pfc_inductor.ui.state import WorkflowState
    s = WorkflowState()
    s.set_warnings(2)
    snap1 = s.snapshot()
    s.set_warnings(7)
    assert snap1.warnings == 2  # snap1 must not have changed


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_settings_round_trip(app):
    from PySide6.QtCore import QSettings
    from pfc_inductor.ui.state import WorkflowState

    with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as tmp:
        path = tmp.name
    try:
        a = WorkflowState()
        a.set_project_name("PFC-1500W-Wide-Input")
        a.mark_step_done(0)
        a.mark_step_done(1)
        a.set_current_step(3)
        # Backdate the saved timestamp so we can compare deterministically.
        ts = datetime.now() - timedelta(minutes=5)
        a._v.last_saved_at = ts
        a.mark_saved(at=ts)

        qs = QSettings(path, QSettings.Format.IniFormat)
        a.to_settings(qs)
        qs.sync()

        b = WorkflowState()
        b.from_settings(qs)

        assert b.project_name == "PFC-1500W-Wide-Input"
        assert b.current_step == 3
        assert b.completed_steps == frozenset({0, 1})
        assert b.last_saved_at is not None
        # ISO round-trip preserves to seconds.
        assert abs((b.last_saved_at - ts).total_seconds()) < 1.0
    finally:
        os.unlink(path)


def test_runtime_counters_are_not_persisted(app):
    from PySide6.QtCore import QSettings
    from pfc_inductor.ui.state import WorkflowState

    with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as tmp:
        path = tmp.name
    try:
        a = WorkflowState()
        a.set_warnings(7)
        a.set_errors(2)
        a.set_validations(11)
        qs = QSettings(path, QSettings.Format.IniFormat)
        a.to_settings(qs)
        qs.sync()

        b = WorkflowState()
        b.from_settings(qs)
        assert b.warnings == 0
        assert b.errors == 0
        assert b.validations_passed == 0
    finally:
        os.unlink(path)
