"""v2 design-system token regressions.

Asserts that every field promised by the ``ui-design-system`` capability
exists on both palettes, parses as a valid colour, and that the named
spacing / radius / typography constants match the documented values.
"""

from __future__ import annotations

import os

# Ensure offscreen mode so QColor can construct without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from pfc_inductor.ui.theme import (
    DARK,
    LIGHT,
    SIDEBAR,
    Palette,
    Radius,
    ShadowSpec,
    Sidebar,
    Spacing,
    Typography,
    get_theme,
    set_theme,
)


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    inst = QApplication.instance() or QApplication([])
    yield inst


# ---------------------------------------------------------------------------
# Palette structure + parseability
# ---------------------------------------------------------------------------

V2_FIELDS = [
    "accent_violet",
    "accent_violet_hover",
    "accent_violet_subtle_bg",
    "accent_violet_subtle_text",
]


@pytest.mark.parametrize("field", V2_FIELDS)
def test_v2_palette_fields_exist(field):
    assert hasattr(LIGHT, field)
    assert hasattr(DARK, field)


@pytest.mark.parametrize("palette,name", [(LIGHT, "LIGHT"), (DARK, "DARK")])
def test_palette_hex_strings_parse_via_qcolor(palette: Palette, name, app):
    from PySide6.QtGui import QColor

    # All hex-style colour fields on Palette should QColor-parse cleanly.
    for fname in palette.__dataclass_fields__:
        v = getattr(palette, fname)
        if not isinstance(v, str):
            continue
        if not v.startswith("#"):
            # rgba(...) legacy is fine for the back-compat ``shadow`` field.
            continue
        c = QColor(v)
        assert c.isValid(), f"{name}.{fname} = {v} did not parse via QColor"


@pytest.mark.parametrize("palette", [LIGHT, DARK])
def test_card_shadow_specs_are_structured(palette: Palette):
    for fname in ("card_shadow_sm", "card_shadow_md", "card_shadow_focus"):
        spec = getattr(palette, fname)
        assert isinstance(spec, ShadowSpec)
        assert spec.color.startswith("#")
        # 8 hex digits => has alpha — required for the dark theme to read.
        assert len(spec.color) == 9, f"{fname} colour must be #AARRGGBB"
        assert spec.blur > 0


# ---------------------------------------------------------------------------
# Spacing / Radius constants
# ---------------------------------------------------------------------------


def test_spacing_dashboard_density_constants():
    sp = Spacing()
    assert sp.page == 24
    assert sp.card_pad == 20
    assert sp.card_gap == 16
    assert sp.section == 32


def test_radius_card_button_chip():
    r = Radius()
    assert r.card == 16
    assert r.button == 10
    assert r.chip == 8
    # back-compat alias preserved
    assert r.lg == 8


# ---------------------------------------------------------------------------
# Sidebar invariance
# ---------------------------------------------------------------------------


def test_sidebar_is_theme_invariant():
    """Toggling theme must not change the sidebar palette."""
    set_theme("light")
    light_sb = get_theme().sidebar
    set_theme("dark")
    dark_sb = get_theme().sidebar
    # Same object identity (module-level singleton) and same byte values.
    assert isinstance(light_sb, Sidebar)
    assert isinstance(dark_sb, Sidebar)
    assert light_sb.bg == dark_sb.bg == SIDEBAR.bg
    assert light_sb.text == dark_sb.text == SIDEBAR.text
    set_theme("light")  # restore default for other tests


def test_sidebar_text_contrast_against_bg(app):
    """Sidebar text against navy bg must clear WCAG AA body (4.5:1)."""
    from PySide6.QtGui import QColor

    bg = QColor(SIDEBAR.bg)
    fg = QColor(SIDEBAR.text)

    def _luminance(c: QColor) -> float:
        # WCAG relative luminance.
        def chan(x: float) -> float:
            x /= 255.0
            return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

        return 0.2126 * chan(c.red()) + 0.7152 * chan(c.green()) + 0.0722 * chan(c.blue())

    l1, l2 = _luminance(fg), _luminance(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    contrast = (l1 + 0.05) / (l2 + 0.05)
    assert contrast >= 4.5, f"sidebar text contrast {contrast:.2f} below WCAG AA"


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------


def test_typography_brand_face_starts_with_inter():
    t = Typography()
    assert "Inter" in t.ui_family_brand
    # First family in the stack should be Inter (variable preferred).
    first = t.ui_family_brand.split(",")[0].strip().strip('"').lower()
    assert first.startswith("inter")


def test_typography_numeric_family_present():
    t = Typography()
    # Numeric family must be a mono stack — assert at least one canonical
    # mono family is in the list.
    fams = t.numeric_family.lower()
    assert "jetbrains mono" in fams or "sf mono" in fams or "menlo" in fams
