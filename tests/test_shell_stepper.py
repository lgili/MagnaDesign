"""ProgressIndicator (v3) — replaces the v2 ``WorkflowStepper``.

The stepper widget itself remains importable for back-compat, but
``MainWindow`` no longer mounts it. The new shell uses
``ProgressIndicator`` (4 informational states) instead.
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


def test_progress_indicator_default_current_is_spec(app):
    from pfc_inductor.ui.shell.progress_indicator import ProgressIndicator
    pi = ProgressIndicator()
    assert pi.state("spec") == "current"
    for k in ("design", "validar", "exportar"):
        assert pi.state(k) == "pending"


def test_progress_indicator_set_current_flips_state(app):
    from pfc_inductor.ui.shell.progress_indicator import ProgressIndicator
    pi = ProgressIndicator()
    pi.set_current("design")
    assert pi.state("design") == "current"
    assert pi.state("spec") == "pending"


def test_progress_indicator_mark_done_persists(app):
    from pfc_inductor.ui.shell.progress_indicator import ProgressIndicator
    pi = ProgressIndicator()
    pi.mark_done("spec")
    pi.set_current("validar")
    pi.mark_done("design")
    assert pi.state("spec") == "done"
    assert pi.state("design") == "done"
    assert pi.state("validar") == "current"


# Legacy WorkflowStepper still ships for back-compat — minimal smoke
# test that it constructs without raising. MainWindow no longer mounts
# it.

def test_workflow_stepper_back_compat_smoke(app):
    from pfc_inductor.ui.shell import WorkflowStepper
    s = WorkflowStepper()
    assert s.segment_state(0) == "active"
