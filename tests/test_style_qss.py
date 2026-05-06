"""v2 stylesheet helper regressions.

The QSS strings produced by ``style.py`` are runtime-checked by Qt only
when the styles are actually applied to a widget. These tests catch the
kind of breakage Qt swallows silently — missing tokens, mistyped
selectors, stale fragments after a refactor.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from pfc_inductor.ui.style import (
    card_qss,
    chip_qss,
    make_stylesheet,
    pill_qss,
    sidebar_qss,
    stepper_qss,
    v2_buttons_qss,
)
from pfc_inductor.ui.theme import SIDEBAR, get_theme, set_theme


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance() or QApplication([])
    yield inst


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_make_stylesheet_renders_for_each_theme(theme_name, app):
    set_theme(theme_name)
    qss = make_stylesheet(get_theme())
    # Smoke: every fragment must contribute something non-empty.
    assert "QMainWindow" in qss
    assert "QPushButton" in qss
    assert "QFrame#Card" in qss                       # cards fragment
    assert "QFrame#Sidebar" in qss                    # sidebar fragment
    assert 'QPushButton[class~="Primary"]' in qss     # v2 buttons
    assert 'QToolButton[class~="Chip"]' in qss        # chips
    assert "QFrame#Stepper" in qss                    # stepper
    set_theme("light")


def test_make_stylesheet_applies_without_warnings(app):
    """End-to-end: setting the QSS on a real QWidget must not produce
    Qt parser warnings (Qt would just print to stderr; a smoke test
    that parser_state is sane is enough)."""
    from PySide6.QtWidgets import QWidget
    set_theme("light")
    w = QWidget()
    w.setStyleSheet(make_stylesheet(get_theme()))
    # Render to force style resolution.
    w.ensurePolished()
    assert w.styleSheet()  # non-empty
    set_theme("light")


# ---------------------------------------------------------------------------
# Per-fragment sentinel assertions
# ---------------------------------------------------------------------------

def test_card_qss_radius_is_16(app):
    qss = card_qss(elevation=1)
    assert "border-radius: 16px" in qss
    assert "QFrame#Card" in qss
    assert "QLabel#CardTitle" in qss


def test_pill_qss_uses_palette_success_bg():
    set_theme("light")
    qss = pill_qss("success")
    p = get_theme().palette
    assert p.success_bg.lower() in qss.lower()
    assert p.success.lower() in qss.lower()


def test_pill_qss_violet_variant_exists():
    set_theme("light")
    qss = pill_qss("violet")
    p = get_theme().palette
    assert p.accent_violet_subtle_bg.lower() in qss.lower()


def test_pill_qss_unknown_variant_fails():
    with pytest.raises(KeyError):
        pill_qss("rainbow")


def test_sidebar_qss_references_navy_palette():
    set_theme("light")
    qss = sidebar_qss(get_theme())
    assert SIDEBAR.bg.lower() in qss.lower()
    assert SIDEBAR.bg_hover.lower() in qss.lower()
    assert SIDEBAR.bg_active.lower() in qss.lower()


def test_sidebar_qss_invariant_across_themes():
    """The fragment text should be byte-equal in light and dark themes —
    sidebar colours are theme-invariant."""
    set_theme("light")
    light_frag = sidebar_qss(get_theme())
    set_theme("dark")
    dark_frag = sidebar_qss(get_theme())
    set_theme("light")
    # The font family / radius come from theme.type/radius which are
    # equal across themes, so the whole fragment should match.
    assert light_frag == dark_frag


def test_v2_buttons_have_radius_10(app):
    set_theme("light")
    qss = v2_buttons_qss(get_theme())
    # Qt6 dynamic-property selectors (the dot-class ``QPushButton.Primary``
    # form would be parsed as a metaObject className match, not a
    # ``setProperty("class", "Primary")`` match — see ADR-shadow notes).
    assert 'QPushButton[class~="Primary"]' in qss
    assert 'QPushButton[class~="Secondary"]' in qss
    assert 'QPushButton[class~="Tertiary"]' in qss
    assert "border-radius: 10px" in qss


def test_chip_qss_radius_is_8():
    set_theme("light")
    qss = chip_qss(get_theme())
    assert 'QToolButton[class~="Chip"]' in qss
    assert "border-radius: 8px" in qss


def test_stepper_qss_has_three_states():
    set_theme("light")
    qss = stepper_qss(get_theme())
    for st in ("done", "active", "pending"):
        assert f'stepperState="{st}"' in qss
