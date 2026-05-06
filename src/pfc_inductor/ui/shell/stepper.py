"""Horizontal 8-segment workflow stepper.

Each segment renders a numbered circle (or check glyph for completed
steps) and a label. State is one of ``done`` / ``active`` / ``pending``.
The QSS for these states ships in :mod:`pfc_inductor.ui.style`.
"""
from __future__ import annotations

from typing import Optional, Iterable

from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget, QSizePolicy,
)

from pfc_inductor.ui.state import WORKFLOW_STEPS


# Public alias so callers don't import the inner constant by mistake.
STEP_STATES = ("done", "active", "pending")


class _StepSegment(QFrame):
    """One numbered segment + label. Holds its own state via the
    ``stepperState`` dynamic property so the stylesheet picks it up.

    Emits ``clicked(idx)`` when the user clicks anywhere on the segment.
    Cursor changes to a pointing hand on hover.
    """

    clicked = Signal(int)

    def __init__(self, idx: int, label: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("StepperSegment")
        self.setProperty("stepperState", "pending")
        self._idx = idx
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        v.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self._circle = QLabel(str(idx + 1))
        self._circle.setObjectName("StepperCircle")
        self._circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._circle.setFixedSize(24, 24)

        self._label = QLabel(label)
        self._label.setObjectName("StepperLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setMinimumWidth(80)

        v.addWidget(self._circle, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(self._label, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addStretch(1)

    @property
    def idx(self) -> int:
        return self._idx

    def set_state(self, state: str) -> None:
        assert state in STEP_STATES, state
        self.setProperty("stepperState", state)
        # Done shows a check; pending/active show the number.
        self._circle.setText("✓" if state == "done" else str(self._idx + 1))
        # Re-evaluate dynamic-property selectors.
        st = self.style()
        st.unpolish(self)
        st.polish(self)
        self.update()
        for child in (self._circle, self._label):
            cs = child.style()
            cs.unpolish(child)
            cs.polish(child)
            child.update()

    def mousePressEvent(self, event):
        # Left-click only; modifier-aware navigation can come later.
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._idx)
        super().mousePressEvent(event)

    def event(self, e: QEvent) -> bool:  # type: ignore[override]
        # Tooltip showing the step name even on small screens.
        if e.type() == QEvent.Type.ToolTip:
            self.setToolTip(self._label.text())
        return super().event(e)


class WorkflowStepper(QFrame):
    """8-step workflow stepper.

    Segments are clickable — emit :attr:`step_clicked` with the segment
    index. The host (``MainWindow``) maps the index to a sidebar area
    via the canonical step-to-area mapping.
    """

    step_clicked = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Stepper")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        h = QHBoxLayout(self)
        h.setContentsMargins(24, 16, 24, 16)
        h.setSpacing(0)

        self._segments: list[_StepSegment] = []
        for idx, (_key, label) in enumerate(WORKFLOW_STEPS):
            seg = _StepSegment(idx, label, self)
            seg.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            seg.clicked.connect(self.step_clicked.emit)
            h.addWidget(seg, 1)
            self._segments.append(seg)

            # Connecting hairline (skip after the last segment)
            if idx < len(WORKFLOW_STEPS) - 1:
                line = QFrame(self)
                line.setObjectName("StepperLine")
                line.setFrameShape(QFrame.Shape.HLine)
                line.setSizePolicy(QSizePolicy.Policy.Expanding,
                                   QSizePolicy.Policy.Fixed)
                line.setMinimumWidth(20)
                line.setMaximumHeight(1)
                h.addWidget(line, 2)

        # Default state: step 0 active, none done.
        self.set_state(0, frozenset())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_state(self, active_idx: int,
                  completed: Iterable[int]) -> None:
        completed_set = frozenset(completed)
        for seg in self._segments:
            if seg.idx in completed_set:
                seg.set_state("done")
            elif seg.idx == active_idx:
                seg.set_state("active")
            else:
                seg.set_state("pending")

    def segment_state(self, idx: int) -> str:
        """Read-only view of the current state — used by tests."""
        return str(self._segments[idx].property("stepperState"))
