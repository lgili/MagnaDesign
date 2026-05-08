"""Single source of truth for the application shell state.

The sidebar, workspace header, workflow stepper and bottom status bar all
read from one ``WorkflowState`` instance and subscribe to its
``state_changed`` signal. This decouples the shell widgets — none of them
mutate each other, and any change funnels through the state object so the
update path is single-rooted.

Persistence
-----------

A subset of fields (``project_name``, ``last_saved_at``,
``completed_steps``) survives application restarts via ``QSettings``. The
runtime-only fields (``warnings``, ``errors``, ``validations_passed``)
reset on launch — they describe the *current* design, not history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, QSettings, Signal

# ---------------------------------------------------------------------------
# Workflow definition
# ---------------------------------------------------------------------------

# 8-step linear PFC inductor design workflow. Order is significant — index
# in this tuple is the canonical `current_step` integer.
WORKFLOW_STEPS: tuple[tuple[str, str], ...] = (
    ("topologia", "Topology"),
    ("entrada", "Data Entry"),
    ("calculo", "Calculation"),
    ("nucleo", "Core"),
    ("bobinamento", "Winding"),
    ("simulacao", "FEM Simulation"),
    ("mecanico", "Mechanical"),
    ("relatorio", "Report"),
)


# ---------------------------------------------------------------------------
# State container
# ---------------------------------------------------------------------------


@dataclass
class _StateValues:
    """Plain-data view of the mutable state, used internally and exposed
    by ``WorkflowState.snapshot()`` for read-only consumers."""

    project_name: str = "Untitled Project"
    current_step: int = 0
    completed_steps: frozenset[int] = field(default_factory=frozenset)
    unsaved: bool = False
    last_saved_at: Optional[datetime] = None
    warnings: int = 0
    errors: int = 0
    validations_passed: int = 0


class WorkflowState(QObject):
    """Mutable shell state. Subscribers connect to ``state_changed``."""

    state_changed = Signal()

    # QSettings key prefix — keeps shell state separate from per-design.
    SETTINGS_PREFIX = "shell"

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._v = _StateValues()

    # ------------------------------------------------------------------
    # Read API — properties (cheap; no signal traffic)
    # ------------------------------------------------------------------
    @property
    def project_name(self) -> str:
        return self._v.project_name

    @property
    def current_step(self) -> int:
        return self._v.current_step

    @property
    def completed_steps(self) -> frozenset[int]:
        return self._v.completed_steps

    @property
    def unsaved(self) -> bool:
        return self._v.unsaved

    @property
    def last_saved_at(self) -> Optional[datetime]:
        return self._v.last_saved_at

    @property
    def warnings(self) -> int:
        return self._v.warnings

    @property
    def errors(self) -> int:
        return self._v.errors

    @property
    def validations_passed(self) -> int:
        return self._v.validations_passed

    def snapshot(self) -> _StateValues:
        """Return a *copy* of the current values — safe for subscribers
        to hold without risking aliasing."""
        return _StateValues(
            project_name=self._v.project_name,
            current_step=self._v.current_step,
            completed_steps=self._v.completed_steps,
            unsaved=self._v.unsaved,
            last_saved_at=self._v.last_saved_at,
            warnings=self._v.warnings,
            errors=self._v.errors,
            validations_passed=self._v.validations_passed,
        )

    # ------------------------------------------------------------------
    # Mutators — each emits ``state_changed`` exactly once.
    # ------------------------------------------------------------------
    def set_project_name(self, name: str) -> None:
        if name == self._v.project_name:
            return
        self._v.project_name = name
        self._v.unsaved = True
        self.state_changed.emit()

    def set_current_step(self, idx: int) -> None:
        idx = max(0, min(len(WORKFLOW_STEPS) - 1, int(idx)))
        if idx == self._v.current_step:
            return
        self._v.current_step = idx
        self.state_changed.emit()

    def mark_step_done(self, idx: int) -> None:
        if idx in self._v.completed_steps:
            return
        self._v.completed_steps = frozenset(self._v.completed_steps | {idx})
        self.state_changed.emit()

    def set_completed_steps(self, steps: set[int] | frozenset[int]) -> None:
        new = frozenset(steps)
        if new == self._v.completed_steps:
            return
        self._v.completed_steps = new
        self.state_changed.emit()

    def set_warnings(self, n: int) -> None:
        if n == self._v.warnings:
            return
        self._v.warnings = max(0, int(n))
        self.state_changed.emit()

    def set_errors(self, n: int) -> None:
        if n == self._v.errors:
            return
        self._v.errors = max(0, int(n))
        self.state_changed.emit()

    def set_validations(self, n: int) -> None:
        if n == self._v.validations_passed:
            return
        self._v.validations_passed = max(0, int(n))
        self.state_changed.emit()

    def mark_saved(self, at: Optional[datetime] = None) -> None:
        self._v.last_saved_at = at or datetime.now()
        self._v.unsaved = False
        self.state_changed.emit()

    def mark_dirty(self) -> None:
        if self._v.unsaved:
            return
        self._v.unsaved = True
        self.state_changed.emit()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def to_settings(self, qs: QSettings) -> None:
        """Persist the durable subset (name, last_saved_at, completed
        steps). Runtime counters (warnings/errors/validations) are NOT
        saved — they describe the current design only."""
        qs.beginGroup(self.SETTINGS_PREFIX)
        qs.setValue("project_name", self._v.project_name)
        qs.setValue(
            "last_saved_at",
            self._v.last_saved_at.isoformat() if self._v.last_saved_at else "",
        )
        qs.setValue(
            "completed_steps",
            ",".join(str(i) for i in sorted(self._v.completed_steps)),
        )
        qs.setValue("current_step", int(self._v.current_step))
        qs.endGroup()

    def from_settings(self, qs: QSettings) -> None:
        """Restore the durable subset; emits ``state_changed`` once at
        the end if anything was restored."""
        qs.beginGroup(self.SETTINGS_PREFIX)
        name = qs.value("project_name", self._v.project_name)
        ts = qs.value("last_saved_at", "")
        steps_raw = qs.value("completed_steps", "")
        cur = qs.value("current_step", self._v.current_step)
        qs.endGroup()

        self._v.project_name = str(name) if name else self._v.project_name
        if ts:
            try:
                self._v.last_saved_at = datetime.fromisoformat(str(ts))
            except ValueError:
                self._v.last_saved_at = None
        else:
            self._v.last_saved_at = None
        try:
            self._v.completed_steps = frozenset(
                int(x) for x in str(steps_raw).split(",") if x.strip()
            )
        except ValueError:
            self._v.completed_steps = frozenset()
        try:
            self._v.current_step = int(cur)
        except (TypeError, ValueError):
            pass

        self._v.unsaved = False
        self.state_changed.emit()
