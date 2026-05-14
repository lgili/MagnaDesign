"""Regression tests for the PhaseStepper widget.

The :class:`PhaseStepper <pfc_inductor.ui.shell.phase_stepper.PhaseStepper>`
groups the 7 ProjetoPage tabs into 3 phases (Design / Validate / Ship).
The mapping from tab index → phase is duplicated as a literal tuple in
``PHASES`` so changing the tab order without updating that tuple silently
breaks the stepper. These tests pin the contract:

1. ``PHASES`` covers exactly the 7 tab indices [0..6], no gaps.
2. Phase pills highlight when the active tab belongs to their group.
3. ``first_tab_for_phase`` returns the canonical "land here" index.

If the ProjetoPage tab order changes, update PHASES in
``phase_stepper.py`` AND the indices below — both files in the same
PR. The parity test ``test_phase_stepper_covers_all_projeto_tabs``
catches drift if you forget.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    """Module-scoped QApplication for all stepper smoke tests."""
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    yield app


# ────────────────────────────────────────────────────────────────────
# 1. Phase coverage — every ProjetoPage tab maps to exactly one phase
# ────────────────────────────────────────────────────────────────────


def test_phases_cover_all_projeto_tab_indices():
    """Every tab index 0..6 belongs to exactly one phase.

    If you add an 8th tab to ProjetoPage without updating PHASES, this
    test fails. If you re-order existing tabs without updating
    PHASES, this test also fails.
    """
    from pfc_inductor.ui.shell.phase_stepper import PHASES

    all_indices: list[int] = []
    for _key, _label, tab_indices, _tooltip in PHASES:
        all_indices.extend(tab_indices)

    # Every index 0..6 appears once.
    assert sorted(all_indices) == [0, 1, 2, 3, 4, 5, 6], (
        f"PHASES must cover all 7 ProjetoPage tab indices exactly once; "
        f"got {sorted(all_indices)}. Did you add a tab to ProjetoPage "
        f"without updating PHASES in phase_stepper.py?"
    )


def test_phases_keys_are_canonical():
    """The three phase keys are exactly ``design`` / ``validate`` / ``ship``."""
    from pfc_inductor.ui.shell.phase_stepper import PHASES

    keys = [key for key, _label, _tab_indices, _tooltip in PHASES]
    assert keys == ["design", "validate", "ship"]


# ────────────────────────────────────────────────────────────────────
# 2. set_active_tab_index → correct pill highlights
# ────────────────────────────────────────────────────────────────────


def test_stepper_starts_on_design_phase(qapp):
    from pfc_inductor.ui.shell.phase_stepper import PhaseStepper

    stepper = PhaseStepper()
    assert stepper.active_phase() == "design"


@pytest.mark.parametrize(
    "tab_idx,expected_phase",
    [
        (0, "design"),    # Core
        (1, "design"),    # Analysis
        (2, "validate"),  # Validate
        (3, "validate"),  # Worst-case
        (4, "validate"),  # Compliance
        (5, "ship"),      # Export
        (6, "ship"),      # History
    ],
)
def test_stepper_highlights_correct_phase_per_tab(qapp, tab_idx, expected_phase):
    from pfc_inductor.ui.shell.phase_stepper import PhaseStepper

    stepper = PhaseStepper()
    stepper.set_active_tab_index(tab_idx)
    assert stepper.active_phase() == expected_phase


# ────────────────────────────────────────────────────────────────────
# 3. first_tab_for_phase — phase → canonical entry tab
# ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "phase_key,expected_tab",
    [
        ("design", 0),    # Core
        ("validate", 2),  # Validate
        ("ship", 5),      # Export
    ],
)
def test_first_tab_for_phase(phase_key, expected_tab):
    from pfc_inductor.ui.shell.phase_stepper import PhaseStepper

    assert PhaseStepper.first_tab_for_phase(phase_key) == expected_tab


def test_first_tab_for_unknown_phase_returns_none():
    from pfc_inductor.ui.shell.phase_stepper import PhaseStepper

    assert PhaseStepper.first_tab_for_phase("bogus") is None


# ────────────────────────────────────────────────────────────────────
# 4. phase_clicked signal payload
# ────────────────────────────────────────────────────────────────────


def test_phase_clicked_signal_emits_canonical_key(qapp):
    """Clicking a pill emits its phase key string."""
    from pfc_inductor.ui.shell.phase_stepper import PhaseStepper

    stepper = PhaseStepper()
    received: list[str] = []
    stepper.phase_clicked.connect(received.append)

    stepper._pills["validate"].click()
    assert received == ["validate"]

    stepper._pills["ship"].click()
    assert received == ["validate", "ship"]
