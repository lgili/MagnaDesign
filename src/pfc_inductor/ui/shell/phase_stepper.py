"""``PhaseStepper`` — top-of-tabs phase indicator.

The Project workspace has 7 tabs: Core, Analysis, Validate,
Worst-case, Compliance, Export, History. Without grouping, the
engineer scans 7 labels on every visit and easily misses the audit
tabs in the middle (Worst-case, Compliance) and the History tab at
the right edge.

This widget surfaces three high-level **phases** above the tab
strip:

    Design     →  Validate          →  Ship
    (Core,        (Validate,            (Export,
     Analysis)     Worst-case,           History)
                   Compliance)

Each phase pill:

- Highlights when the active QTabWidget tab belongs to that phase.
- Switches the QTabWidget to the *first* tab of its phase on click
  (Core for Design, Validate for Validate, Export for Ship).

The widget is **additive** — it does not change the QTabWidget
itself, so every existing keyboard shortcut, ``switch_to`` key, and
test continues to work. The phase indicator is a navigation
short-cut, not a structural replacement.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from pfc_inductor.ui.theme import get_theme, on_theme_changed


# Canonical phase definitions. The string keys match the
# ``TabKey`` literal in :mod:`pfc_inductor.ui.workspace.projeto_page`
# so callers can pass them through to ``ProjetoPage.switch_to``
# without remapping.
#
# Indices reference the QTabWidget tab order — keep in lock-step
# with ``projeto_page.py``'s ``addTab`` order, enforced by the
# parity test ``tests/test_phase_stepper.py``.
PHASES: tuple[tuple[str, str, tuple[int, ...], str], ...] = (
    (
        "design",
        "Design",
        (0, 1),  # Core, Analysis
        "Pick the magnetic core and look at how the chosen design behaves.",
    ),
    (
        "validate",
        "Validate",
        (2, 3, 4),  # Validate, Worst-case, Compliance
        "FEA cross-check, corner / Monte-Carlo, IEC compliance.",
    ),
    (
        "ship",
        "Ship",
        (5, 6),  # Export, History
        "Generate the report and review the iteration history.",
    ),
)


class PhaseStepper(QFrame):
    """Horizontal 3-segment phase indicator above the tab strip."""

    phase_clicked = Signal(str)  # phase key (design / validate / ship)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("PhaseStepper")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(34)

        h = QHBoxLayout(self)
        h.setContentsMargins(16, 4, 16, 4)
        h.setSpacing(6)

        self._pills: dict[str, QPushButton] = {}
        for i, (key, label, _tab_indices, tooltip) in enumerate(PHASES):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.setAccessibleName(label)
            btn.setAccessibleDescription(tooltip)
            btn.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            btn.clicked.connect(lambda _checked=False, k=key: self.phase_clicked.emit(k))
            self._pills[key] = btn
            h.addWidget(btn)

            # Chevron between phases — communicates "Design → Validate
            # → Ship" reading order without forcing a fully-rendered
            # arrow widget. Cheap label, theme-aware via _refresh_qss.
            if i < len(PHASES) - 1:
                chevron = QLabel("›")
                chevron.setProperty("role", "muted")
                chevron.setAlignment(Qt.AlignmentFlag.AlignCenter)
                chevron.setFixedWidth(12)
                h.addWidget(chevron)

        h.addStretch(1)

        # Default to the first phase highlighted — the host calls
        # ``set_active_tab_index`` post-init to sync.
        self._pills["design"].setChecked(True)
        self._active_phase = "design"

        self._refresh_qss()
        on_theme_changed(self._refresh_qss)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_active_tab_index(self, tab_idx: int) -> None:
        """Update which phase pill is highlighted given the active tab.

        Called by the host whenever ``QTabWidget.currentChanged``
        fires so the stepper mirrors the underlying tab state. The
        mapping is the inverse of ``PHASES[i][2]`` — find the phase
        whose tab-index tuple contains ``tab_idx`` and check that
        pill exclusively.
        """
        new_phase: Optional[str] = None
        for key, _label, tab_indices, _tooltip in PHASES:
            if tab_idx in tab_indices:
                new_phase = key
                break
        if new_phase is None or new_phase == self._active_phase:
            # Either the tab index is out of range (shouldn't happen
            # if the test holds) or the phase hasn't changed.
            return
        self._pills[self._active_phase].setChecked(False)
        self._pills[new_phase].setChecked(True)
        self._active_phase = new_phase

    def active_phase(self) -> str:
        """Currently highlighted phase key."""
        return self._active_phase

    @staticmethod
    def first_tab_for_phase(phase_key: str) -> Optional[int]:
        """Return the first tab index belonging to ``phase_key``.

        Used by the host to translate a phase-click into a
        ``QTabWidget.setCurrentIndex`` call. Returns ``None`` for an
        unknown key (defensive — the only callers are tests and
        ``ProjetoPage`` itself).
        """
        for key, _label, tab_indices, _tooltip in PHASES:
            if key == phase_key:
                return tab_indices[0] if tab_indices else None
        return None

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------
    def _refresh_qss(self) -> None:
        p = get_theme().palette
        t = get_theme().type
        self.setStyleSheet(
            f"QFrame#PhaseStepper {{ background: {p.bg}; "
            f"  border: 0; "
            f"  border-bottom: 1px solid {p.border}; "
            f"}}"
            f"QPushButton {{ "
            f"  background: transparent; "
            f"  color: {p.text_muted}; "
            f"  border: 0; "
            f"  border-radius: 6px; "
            f"  padding: 4px 14px; "
            f"  font-family: {t.ui_family_brand}; "
            f"  font-size: {t.body_md}px; "
            f"  font-weight: {t.medium}; "
            f"}}"
            f"QPushButton:hover {{ "
            f"  background: {p.surface_elevated}; "
            f"  color: {p.text}; "
            f"}}"
            f"QPushButton:checked {{ "
            f"  background: {p.surface}; "
            f"  color: {p.text}; "
            f"  font-weight: {t.semibold}; "
            f"  border: 1px solid {p.border}; "
            f"}}"
            f"QLabel {{ color: {p.text_muted}; "
            f"  font-size: {t.title_md}px; "
            f"  background: transparent; "
            f"}}"
        )
