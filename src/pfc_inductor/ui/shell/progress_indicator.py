"""4-state progress indicator for the workspace.

Replaces the v2 ``WorkflowStepper`` (8 segments, clickable) with a
simpler 4-state line that *communicates where the user is* in the
loop without faking a linear workflow:

    ● Spec   ●  Design   ○  Validar   ○  Exportar

States: ``pending`` (outline), ``current`` (violet fill),
``done`` (green fill + check). The widget is **informational only**
— clicks do nothing, the cursor stays default. Navigation lives on
the workspace tabs.
"""
from __future__ import annotations

from typing import Iterable, Literal, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from pfc_inductor.ui.theme import get_theme, on_theme_changed

StepState = Literal["pending", "current", "done"]
StepKey = Literal["spec", "design", "validar", "exportar"]


_STEPS: tuple[tuple[StepKey, str], ...] = (
    ("spec",     "Spec"),
    ("design",   "Design"),
    ("validar",  "Validar"),
    ("exportar", "Exportar"),
)


class ProgressIndicator(QFrame):
    """Read-only 4-state progress line."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProgressIndicator")
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        # Compact: ~36 px tall (was ~56 with the inner segment paddings).
        # The strip is informational only, so we don't need the extra
        # breathing room.
        self.setFixedHeight(36)

        h = QHBoxLayout(self)
        # Trimmed vertical padding 10→6, horizontal 20→16 to match.
        h.setContentsMargins(16, 6, 16, 6)
        h.setSpacing(0)

        self._segments: dict[StepKey, _ProgressSegment] = {}
        for i, (key, label) in enumerate(_STEPS):
            seg = _ProgressSegment(key, label, self)
            self._segments[key] = seg
            h.addWidget(seg, 1)
            if i < len(_STEPS) - 1:
                line = QFrame(self)
                line.setObjectName("ProgressLine")
                line.setFrameShape(QFrame.Shape.HLine)
                line.setMinimumWidth(20)
                line.setMaximumHeight(1)
                h.addWidget(line, 2)

        self._current: StepKey = "spec"
        self._done: frozenset[StepKey] = frozenset()
        self._refresh()
        on_theme_changed(self._refresh)
        self.setStyleSheet(self._self_qss())

    # ------------------------------------------------------------------
    def set_current(self, key: StepKey) -> None:
        if key == self._current:
            return
        self._current = key
        self._refresh()

    def mark_done(self, key: StepKey) -> None:
        if key in self._done:
            return
        new: set[StepKey] = set(self._done)
        new.add(key)
        self._done = frozenset(new)
        self._refresh()

    def set_done(self, keys: Iterable[StepKey]) -> None:
        new = frozenset(keys)
        if new == self._done:
            return
        self._done = new
        self._refresh()

    def state(self, key: StepKey) -> StepState:
        if key in self._done:
            return "done"
        if key == self._current:
            return "current"
        return "pending"

    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        for key, seg in self._segments.items():
            seg.set_state(self.state(key))
        # Re-style line colour.
        p = get_theme().palette
        for w in self.findChildren(QFrame, "ProgressLine"):
            w.setStyleSheet(f"QFrame#ProgressLine {{ background: {p.border}; }}")
        self.setStyleSheet(self._self_qss())

    @staticmethod
    def _self_qss() -> str:
        p = get_theme().palette
        return (
            f"QFrame#ProgressIndicator {{"
            f"  background: {p.surface};"
            f"  border: 0;"
            f"  border-bottom: 1px solid {p.border};"
            f"}}"
        )


class _ProgressSegment(QFrame):
    """One status dot + label, laid out horizontally (compact mode).

    The original v3 design stacked dot above label which doubled the
    strip height. Inline keeps the same visual hierarchy (dot draws
    the eye, label provides context on hover/scan) at half the
    vertical cost.
    """

    def __init__(self, key: StepKey, label: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProgressSegment")
        self._key = key
        self._state: StepState = "pending"

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)

        self._dot = QLabel("●")
        self._dot.setObjectName("ProgressDot")
        self._dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._dot.setFixedSize(14, 14)

        self._label = QLabel(label)
        self._label.setObjectName("ProgressLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        h.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self._label, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_state(self, state: StepState) -> None:
        self._state = state
        p = get_theme().palette
        if state == "done":
            dot_color = p.success
            label_color = p.text
            label_weight = "600"
            self._dot.setText("✓")
        elif state == "current":
            dot_color = p.accent_violet
            label_color = p.accent_violet_subtle_text
            label_weight = "600"
            self._dot.setText("●")
        else:
            dot_color = p.text_muted
            label_color = p.text_secondary
            label_weight = "500"
            self._dot.setText("○")
        self._dot.setStyleSheet(
            f"color: {dot_color}; font-size: 14px;"
            f" background: transparent; border: 0;"
        )
        t = get_theme().type
        self._label.setStyleSheet(
            f"color: {label_color}; font-size: {t.caption}px;"
            f" font-weight: {label_weight};"
            f" background: transparent; border: 0;"
        )

    @property
    def state(self) -> StepState:
        return self._state
