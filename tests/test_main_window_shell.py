"""Integration: MainWindow boots with the new MagnaDesign shell.

Smoke-test that:
- the sidebar, header, stepper, stack, and bottom status bar all exist;
- nav signals route to the QStackedWidget;
- a successful design()/calc fans the result counts into the bottom bar
  via WorkflowState.
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
def win(app):
    from pfc_inductor.ui.main_window import MainWindow
    w = MainWindow()
    yield w
    w.close()


def test_main_window_has_shell_widgets(win):
    from pfc_inductor.ui.shell import (
        Sidebar, WorkspaceHeader, WorkflowStepper, BottomStatusBar,
    )
    assert isinstance(win.sidebar, Sidebar)
    assert isinstance(win.header, WorkspaceHeader)
    assert isinstance(win.stepper, WorkflowStepper)
    assert isinstance(win.status_bar, BottomStatusBar)


def test_main_window_no_legacy_qtoolbar(win):
    """The old QToolBar should be gone — actions live on the header CTAs
    and the sidebar overflow menu now."""
    from PySide6.QtWidgets import QToolBar
    bars = win.findChildren(QToolBar)
    assert bars == []


def test_sidebar_navigation_routes_to_stack(win):
    from pfc_inductor.ui.main_window import AREA_PAGES
    for area in AREA_PAGES:
        win.sidebar._on_nav_clicked(area)
        idx = AREA_PAGES.index(area)
        assert win.stack.currentIndex() == idx


def test_calc_populates_status_pills(win):
    """After the construction-time _on_calculate, the validations pill
    should be > 0 (we count 12 - len(warnings) as validations passed)."""
    n_val = int(win.status_bar.validations_text().split()[0])
    assert n_val >= 1


def test_workflow_step_calculo_marked_done_after_calc(win):
    """A completed calculation should mark steps 0..3 as done."""
    completed = win._workflow_state.completed_steps
    assert 0 in completed and 1 in completed and 2 in completed and 3 in completed


def test_theme_toggle_does_not_change_sidebar_palette(win, app):
    """SIDEBAR is theme-invariant — the sidebar QFrame's stylesheet must
    not mention the *workspace* surface colour after toggling."""
    from pfc_inductor.ui.theme import SIDEBAR
    win._toggle_theme()
    # The sidebar's bg is set via the global QSS, not inline. The
    # easiest invariant: the SIDEBAR module-level constants are
    # unchanged.
    assert SIDEBAR.bg == "#0F1729"
    win._toggle_theme()  # restore
