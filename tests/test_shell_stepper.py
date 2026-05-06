"""WorkflowStepper visual-state regressions."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance() or QApplication([])
    yield inst


def test_stepper_has_eight_segments(app):
    from pfc_inductor.ui.shell import WorkflowStepper
    s = WorkflowStepper()
    # 8 segments + 7 connecting lines = 15 children of the layout
    # (we only count segments here).
    states = [s.segment_state(i) for i in range(8)]
    assert len(states) == 8


def test_set_state_marks_completed_and_active(app):
    from pfc_inductor.ui.shell import WorkflowStepper
    s = WorkflowStepper()
    s.set_state(active_idx=3, completed={0, 1, 2})
    assert s.segment_state(0) == "done"
    assert s.segment_state(1) == "done"
    assert s.segment_state(2) == "done"
    assert s.segment_state(3) == "active"
    assert s.segment_state(4) == "pending"
    assert s.segment_state(7) == "pending"


def test_step_circle_shows_check_when_done(app):
    from pfc_inductor.ui.shell import WorkflowStepper
    s = WorkflowStepper()
    s.set_state(active_idx=2, completed={0, 1})
    # Step 0 done — circle shows ✓
    assert s._segments[0]._circle.text() == "✓"
    # Step 2 active — circle shows the index+1
    assert s._segments[2]._circle.text() == "3"


def test_default_state_is_first_active(app):
    from pfc_inductor.ui.shell import WorkflowStepper
    s = WorkflowStepper()
    assert s.segment_state(0) == "active"
    for i in range(1, 8):
        assert s.segment_state(i) == "pending"


def test_stepper_segment_click_emits_step_clicked(app):
    from pfc_inductor.ui.shell import WorkflowStepper
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent, QPointF, Qt

    s = WorkflowStepper()
    received: list[int] = []
    s.step_clicked.connect(received.append)

    seg = s._segments[3]
    pos = QPointF(seg.width() / 2, seg.height() / 2)
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        pos, pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    seg.mousePressEvent(ev)
    assert received == [3]


def test_main_window_stepper_routes_to_sidebar(app):
    """Clicking stepper step 3 (Núcleo) must navigate to the
    "nucleos" area in the sidebar."""
    from pfc_inductor.ui.main_window import MainWindow, AREA_PAGES
    w = MainWindow()
    # Trigger the stepper-click handler directly.
    w._on_stepper_clicked(3)
    # Active sidebar area should now be the one mapped to step 3.
    assert w.sidebar._nav_buttons["nucleos"].isChecked()
    # The stack is showing the matching page.
    assert w.stack.currentIndex() == AREA_PAGES.index("nucleos")
    w.close()
