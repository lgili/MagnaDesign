"""Topology schematic widget — paints, picks accent for inductor,
respects theme."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    inst = QApplication.instance() or QApplication([])
    yield inst


@pytest.mark.parametrize(
    "topology",
    [
        "boost_ccm",
        "passive_choke",
        "line_reactor_1ph",
        "line_reactor_3ph",
    ],
)
def test_schematic_renders_each_topology(app, topology):
    """Every topology must paint without raising and produce a pixmap
    with non-zero non-background pixels."""
    from pfc_inductor.ui.widgets import TopologySchematicWidget

    w = TopologySchematicWidget()
    w.resize(600, 140)
    w.set_topology(topology)
    pix = w.grab()
    assert not pix.isNull()
    img = pix.toImage()
    # At least 1 % of pixels should be non-background.
    bg_color = img.pixelColor(0, 0)
    n_background = 0
    n_total = 0
    step = 8  # sample every 8 px to keep this fast
    for y in range(0, img.height(), step):
        for x in range(0, img.width(), step):
            n_total += 1
            if img.pixelColor(x, y) == bg_color:
                n_background += 1
    non_bg_ratio = 1.0 - (n_background / max(n_total, 1))
    assert non_bg_ratio > 0.01, f"only {non_bg_ratio * 100:.1f}% non-bg pixels"


def test_schematic_aliases_line_reactor_to_1ph(app):
    from pfc_inductor.ui.widgets import TopologySchematicWidget

    w = TopologySchematicWidget()
    w.set_topology("line_reactor")  # alias
    assert w.topology() == "line_reactor_1ph"


def test_schematic_unknown_topology_raises(app):
    from pfc_inductor.ui.widgets import TopologySchematicWidget

    w = TopologySchematicWidget()
    with pytest.raises(ValueError):
        w.set_topology("not_real")


def test_schematic_inductor_uses_accent_colour(app):
    """Sample a pixel inside the inductor's bounding region and assert
    it is closer to the accent colour than to the neutral colour."""
    from pfc_inductor.ui.theme import get_theme, set_theme
    from pfc_inductor.ui.widgets import TopologySchematicWidget

    set_theme("light")
    w = TopologySchematicWidget()
    w.resize(600, 140)
    w.set_topology("passive_choke")
    pix = w.grab()
    img = pix.toImage()
    # In the passive-choke layout the inductor centre is near logical
    # (430, 80) — convert to device coords. Logical canvas: 1000×250.
    px = int(430 / 1000 * img.width())
    py = int(80 / 250 * img.height())
    # Search in a small neighbourhood for a stroke pixel (the inductor
    # arc is thin so the exact centre point may be background).
    p_accent = get_theme().palette.accent
    from PySide6.QtGui import QColor

    accent = QColor(p_accent)

    def _dist(a: QColor, b: QColor) -> float:
        return (
            (a.red() - b.red()) ** 2 + (a.green() - b.green()) ** 2 + (a.blue() - b.blue()) ** 2
        ) ** 0.5

    found = False
    for dx in range(-12, 13):
        for dy in range(-12, 13):
            x, y = px + dx, py + dy
            if 0 <= x < img.width() and 0 <= y < img.height():
                c = img.pixelColor(x, y)
                # Skip plain background.
                if c.alpha() == 0:
                    continue
                if _dist(c, accent) < 60:
                    found = True
                    break
        if found:
            break
    assert found, "no accent-coloured pixel found near the inductor"


def test_schematic_topology_picker_choices(app):
    from pfc_inductor.ui.widgets import topology_picker_choices

    choices = topology_picker_choices()
    keys = [k for k, _ in choices]
    assert keys == [
        "boost_ccm",
        "passive_choke",
        "line_reactor_1ph",
        "line_reactor_3ph",
    ]
    # Every label is non-empty.
    for _key, label in choices:
        assert label.strip()


# ---------------------------------------------------------------------------
# DPR (devicePixelRatio) — pixmap honours HiDPI scaling
# ---------------------------------------------------------------------------
def test_schematic_pixmap_has_logical_size(app):
    """The grabbed pixmap must carry the widget's logical size.
    On HiDPI displays the underlying buffer is larger; ``size()``
    still returns the logical size that callers expect.
    """
    from pfc_inductor.ui.widgets import TopologySchematicWidget

    w = TopologySchematicWidget()
    w.resize(600, 140)
    w.set_topology("boost_ccm")
    pix = w.grab()
    # Logical size matches what the widget was sized to.
    assert pix.width() == 600
    assert pix.height() == 140
    # devicePixelRatio is at least 1.0 on the offscreen platform
    # and may be higher on Retina builds; either way the value
    # must be a positive float so downstream painters pick it up.
    assert pix.devicePixelRatio() >= 1.0


# ---------------------------------------------------------------------------
# Theme change — light vs. dark pixmaps differ
# ---------------------------------------------------------------------------
def test_schematic_repaints_on_theme_change(app):
    """Switching themes must change *some* pixels. The accent
    + background palette flips, so byte-identical pixmaps would
    indicate a hard-coded colour escaped the theme module."""
    from pfc_inductor.ui.theme import set_theme
    from pfc_inductor.ui.widgets import TopologySchematicWidget

    set_theme("light")
    w_light = TopologySchematicWidget()
    w_light.resize(600, 140)
    w_light.set_topology("boost_ccm")
    light_bytes = bytes(w_light.grab().toImage().constBits())

    set_theme("dark")
    w_dark = TopologySchematicWidget()
    w_dark.resize(600, 140)
    w_dark.set_topology("boost_ccm")
    dark_bytes = bytes(w_dark.grab().toImage().constBits())

    # Restore the canonical light theme so subsequent tests
    # start from a known state.
    set_theme("light")

    assert light_bytes != dark_bytes
