"""Sidebar widget regressions."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance() or QApplication([])
    yield inst


def test_sidebar_has_eight_nav_items(app):
    from pfc_inductor.ui.shell import Sidebar, SIDEBAR_AREAS
    sb = Sidebar()
    assert len(SIDEBAR_AREAS) == 8
    assert len(sb._nav_buttons) == 8


def test_sidebar_default_active_is_dashboard(app):
    from pfc_inductor.ui.shell import Sidebar
    sb = Sidebar()
    assert sb._nav_buttons["dashboard"].isChecked()
    for k, btn in sb._nav_buttons.items():
        if k != "dashboard":
            assert not btn.isChecked()


def test_sidebar_click_emits_navigation_requested(app):
    from pfc_inductor.ui.shell import Sidebar, SIDEBAR_AREAS
    sb = Sidebar()
    received: list[str] = []
    sb.navigation_requested.connect(received.append)

    for area_id, _label, _icon in SIDEBAR_AREAS:
        sb._nav_buttons[area_id].click()
    assert received == [a[0] for a in SIDEBAR_AREAS]


def test_sidebar_set_active_does_not_emit(app):
    """Programmatic set_active_area should NOT loop back through the
    navigation_requested signal."""
    from pfc_inductor.ui.shell import Sidebar
    sb = Sidebar()
    received: list[str] = []
    sb.navigation_requested.connect(received.append)
    sb.set_active_area("nucleos")
    assert received == []
    assert sb._nav_buttons["nucleos"].isChecked()


def test_sidebar_overflow_menu_lists_legacy_tools(app):
    from pfc_inductor.ui.shell.sidebar import Sidebar, OVERFLOW_ACTIONS
    sb = Sidebar()
    menu_items = sb._overflow_menu.actions()
    assert len(menu_items) == len(OVERFLOW_ACTIONS)
    titles = [a.text() for a in menu_items]
    # Every legacy tool name appears.
    for _key, label, _icon in OVERFLOW_ACTIONS:
        assert label in titles


def test_sidebar_theme_toggle_signal(app):
    from pfc_inductor.ui.shell import Sidebar
    sb = Sidebar()
    received = [0]
    sb.theme_toggle_requested.connect(lambda: received.__setitem__(0, received[0] + 1))
    sb._btn_theme.click()
    assert received[0] == 1
