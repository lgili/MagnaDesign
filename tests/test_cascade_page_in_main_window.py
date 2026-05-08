"""Cascade page wired into MainWindow / Sidebar (A.6.1 + A.6.6 follow-up).

Phase A's `CascadePage` shipped behind a feature flag (built but
not mounted in `MainWindow`); this regression confirms the v3
mount lands cleanly:

- Sidebar shows a `cascade` entry with the right label.
- `MainWindow` constructs a `CascadePage`, mounts it in the stack,
  and routes nav clicks to it.
- The page receives `set_inputs` updates after every successful
  recompute.
- Double-clicking a cascade row routes back through
  `_apply_optimizer_choice` and switches the active area to
  Projeto.
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


# ─── Sidebar registration ──────────────────────────────────────

def test_sidebar_lists_cascade_entry():
    """Sidebar entries are 4-tuples ``(id, label, icon, tooltip)`` —
    we only need the id+label here, so unpack defensively to stay
    forward-compatible with shape tweaks."""
    from pfc_inductor.ui.shell.sidebar import SIDEBAR_AREAS
    ids = {entry[0] for entry in SIDEBAR_AREAS}
    assert "cascade" in ids
    cascade_entry = next(e for e in SIDEBAR_AREAS if e[0] == "cascade")
    # Label is "Full optimizer" — we just need *some* "optimizer"
    # wording so the user recognises the destination from the
    # sidebar, regardless of the modifier ("full"/"complete"/etc).
    assert "optimizer" in cascade_entry[1].lower()


# ─── MainWindow mount ──────────────────────────────────────────

def test_main_window_mounts_cascade_page(app):
    from pfc_inductor.ui.main_window import AREA_PAGES, MainWindow
    from pfc_inductor.ui.workspace import CascadePage

    win = MainWindow()
    try:
        # Stack index for "cascade" matches the position in AREA_PAGES.
        cascade_idx = AREA_PAGES.index("cascade")
        page = win.stack.widget(cascade_idx)
        assert isinstance(page, CascadePage)
        assert win.cascade_page is page
    finally:
        win.close()


def test_main_window_navigates_to_cascade_page(app):
    """Clicking the sidebar entry routes the QStackedWidget to the
    cascade page."""
    from pfc_inductor.ui.main_window import AREA_PAGES, MainWindow

    win = MainWindow()
    try:
        win.sidebar.navigation_requested.emit("cascade")
        assert win.stack.currentIndex() == AREA_PAGES.index("cascade")
    finally:
        win.close()


def test_main_window_pipes_db_into_cascade_page(app):
    """After the initial recompute, `cascade_page._spec` and the
    DB lists must be populated — the cascade has everything it
    needs to start a run."""
    from pfc_inductor.ui.main_window import MainWindow

    win = MainWindow()
    try:
        # `set_inputs` was called inside `_on_calculate` during MainWindow
        # construction; verify the cascade page caught it.
        cp = win.cascade_page
        assert cp._spec is not None
        assert cp._materials  # non-empty
        assert cp._cores
        assert cp._wires
    finally:
        win.close()


# ─── Open-in-design routing ────────────────────────────────────

def test_cascade_selection_applied_routes_to_apply_optimizer_choice(app):
    """The new "Aplicar selecionado" button on the cascade page must
    push selections through the same `_apply_optimizer_choice` path
    the Pareto / Núcleo / Compare surfaces use, so the cascade
    winner becomes the active design without leaving the page."""
    from pfc_inductor.ui.main_window import AREA_PAGES, MainWindow

    win = MainWindow()
    try:
        win.sidebar.navigation_requested.emit("cascade")
        any_core = win._cores[0]
        any_material = next(
            m for m in win._materials
            if m.id == any_core.default_material_id
        )
        any_wire = win._wires[0]

        # Emit the cascade page's `selection_applied` directly.
        win.cascade_page.selection_applied.emit(
            any_material.id, any_core.id, any_wire.id,
        )

        # Selection updated on MainWindow.
        assert win._current_material_id == any_material.id
        assert win._current_core_id == any_core.id
        assert win._current_wire_id == any_wire.id
        # Apply does NOT switch pages — the engineer can keep
        # comparing on the cascade page. Open-in-design (separate
        # button) is the one that switches.
        assert win.stack.currentIndex() == AREA_PAGES.index("cascade")
    finally:
        win.close()


def test_cascade_open_in_design_signal_routes_to_dashboard(app):
    """Double-clicking a cascade row should hydrate the candidate
    via `_apply_optimizer_choice` and switch the visible area
    back to Projeto."""
    from pfc_inductor.ui.main_window import AREA_PAGES, MainWindow

    win = MainWindow()
    try:
        # Move to cascade first so we can verify the area-switch.
        win.sidebar.navigation_requested.emit("cascade")
        assert win.stack.currentIndex() == AREA_PAGES.index("cascade")

        # Pick a real (core, material, wire) the design engine knows about.
        any_core = win._cores[0]
        any_material = next(
            m for m in win._materials
            if m.id == any_core.default_material_id
        )
        any_wire = win._wires[0]
        key = (
            f"{any_core.id}|{any_material.id}|{any_wire.id}|_|_"
        )

        # Emit the cascade page's signal; the routing is what we test.
        win.cascade_page.open_in_design_requested.emit(key)

        # Active page is back on Projeto.
        assert win.stack.currentIndex() == AREA_PAGES.index("dashboard")
        # Current selection got updated.
        assert win._current_material_id == any_material.id
        assert win._current_core_id == any_core.id
        assert win._current_wire_id == any_wire.id
    finally:
        win.close()
