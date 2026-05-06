"""Lucide icon registry + tinting smoke tests."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance() or QApplication([])
    yield inst


# Names guaranteed by the v2 spec — both v1 (back-compat) and new ones.
EXPECTED_NAMES = [
    # v1 — must keep working
    "sliders", "database", "compare", "search", "braid", "cube",
    "file", "zap", "moon", "sun", "play", "download_cloud",
    # v2 additions
    "layout-dashboard", "git-branch", "cpu", "gauge", "activity",
    "box", "cog", "bell", "chevron-down", "chevron-right", "download",
    "pencil", "check-circle", "alert-triangle", "x-circle", "info",
    "move-3d", "crop", "ruler", "share", "expand", "image",
    "eye", "eye-off", "filter", "plus", "minus", "more-horizontal",
    "arrow-up-right", "circle", "layers", "maximize-2", "settings-2",
    "file-text", "clock", "play-circle", "trending-up", "trending-down",
]


def test_registry_covers_v2_names(app):
    from pfc_inductor.ui.icons import available_icons, has_icon
    available = set(available_icons())
    for name in EXPECTED_NAMES:
        norm = name.replace("_", "-")
        assert has_icon(name), f"missing {name}"
        assert norm in available


def test_icon_returns_non_null(app):
    from pfc_inductor.ui.icons import icon
    ic = icon("layout-dashboard")
    assert ic is not None
    assert not ic.isNull()
    pix = ic.pixmap(18, 18)
    assert not pix.isNull()
    assert pix.width() == 18 and pix.height() == 18


def test_icon_unknown_name_raises_keyerror_with_suggestions(app):
    from pfc_inductor.ui.icons import icon
    with pytest.raises(KeyError) as excinfo:
        icon("layout-dahsboard")  # typo
    msg = str(excinfo.value)
    assert "layout-dahsboard" in msg
    assert "Available" in msg


def test_icon_accepts_underscore_or_hyphen(app):
    from pfc_inductor.ui.icons import icon
    a = icon("check_circle")
    b = icon("check-circle")
    assert not a.isNull()
    assert not b.isNull()


def test_icon_tinting_changes_pixel_colour(app):
    """Tinting must actually change the rendered pixel colour."""
    from pfc_inductor.ui.icons import pixmap

    red_pix = pixmap("circle", color="#FF0000", size=24)
    green_pix = pixmap("circle", color="#00FF00", size=24)

    img_r = red_pix.toImage()
    img_g = green_pix.toImage()

    # Sample a pixel that is on the circle stroke (above centre, top edge).
    # The 24×24 circle with stroke 2 has its top arc near y ~= 2.
    x, y = 12, 2
    pr = img_r.pixelColor(x, y)
    pg = img_g.pixelColor(x, y)

    # On the red icon, the stroke pixel should have red dominant; on
    # green, green dominant. Allow some margin because antialiasing
    # blends with the transparent backdrop.
    assert pr.red() > pr.green(), f"red icon pixel red={pr.red()} green={pr.green()}"
    assert pg.green() > pg.red(), f"green icon pixel red={pg.red()} green={pg.green()}"


def test_registry_size_at_least_40(app):
    from pfc_inductor.ui.icons import available_icons
    assert len(available_icons()) >= 40
