"""Overlay HUD widgets for the 3D viewer."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance() or QApplication([])
    yield inst


# ---------------------------------------------------------------------------
# ViewChips
# ---------------------------------------------------------------------------

def test_view_chips_default_active_is_iso(app):
    from pfc_inductor.ui.viewer3d import ViewChips
    c = ViewChips()
    assert c.active() == "iso"


def test_view_chips_click_emits_view_changed(app):
    from pfc_inductor.ui.viewer3d import ViewChips
    c = ViewChips()
    received: list[str] = []
    c.view_changed.connect(received.append)
    for k in ("front", "top", "side", "iso"):
        c._buttons[k].click()
    assert received == ["front", "top", "side", "iso"]


def test_view_chips_set_active_does_not_emit(app):
    from pfc_inductor.ui.viewer3d import ViewChips
    c = ViewChips()
    received: list[str] = []
    c.view_changed.connect(received.append)
    c.set_active("front")
    assert received == []
    assert c.active() == "front"


# ---------------------------------------------------------------------------
# OrientationCube
# ---------------------------------------------------------------------------

def test_orientation_cube_paints(app):
    from pfc_inductor.ui.viewer3d import OrientationCube
    cube = OrientationCube()
    assert cube.size().width() == cube.SIZE
    assert cube.size().height() == cube.SIZE


def test_orientation_cube_face_click_emits_signals(app):
    """Pretend-click each visible face by calling the signals directly —
    fully simulating mousePressEvent on a paintevent-only widget is
    flaky in offscreen mode. The contract we care about: hitting a +X
    face routes to the side view, +Y to front, +Z to top."""
    from pfc_inductor.ui.viewer3d import OrientationCube
    cube = OrientationCube()
    received: list[str] = []
    cube.view_requested.connect(received.append)
    # Synthesise a click at the centre of each visible face polygon.
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent, QPointF, Qt
    for name, poly in cube._face_polygons.items():
        cx = sum(poly.at(i).x() for i in range(poly.size())) / poly.size()
        cy = sum(poly.at(i).y() for i in range(poly.size())) / poly.size()
        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(cx, cy),
            QPointF(cx, cy),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        cube.mousePressEvent(ev)
    # Every visible face mapped to a view.
    assert set(received) >= {"front", "top", "side"}


# ---------------------------------------------------------------------------
# SideToolbar
# ---------------------------------------------------------------------------

def test_side_toolbar_button_set(app):
    from pfc_inductor.ui.viewer3d import SideToolbar
    t = SideToolbar()
    expected = {"maximize-2", "image", "layers", "crop", "ruler", "settings-2"}
    assert set(t._buttons.keys()) == expected


def test_side_toolbar_screenshot_signal(app):
    from pfc_inductor.ui.viewer3d import SideToolbar
    t = SideToolbar()
    fired = []
    t.screenshot_requested.connect(lambda: fired.append(1))
    t._buttons["image"].click()
    assert fired == [1]


def test_side_toolbar_layers_emits_dict(app):
    from pfc_inductor.ui.viewer3d import SideToolbar
    t = SideToolbar()
    received: list[dict] = []
    t.layers_requested.connect(received.append)
    # Simulate user unchecking "winding".
    t._chk_winding.setChecked(False)
    assert received and received[-1]["winding"] is False
    assert received[-1]["bobbin"] is False
    assert received[-1]["airgap"] is True


# ---------------------------------------------------------------------------
# BottomActions
# ---------------------------------------------------------------------------

def test_bottom_actions_have_4_buttons(app):
    from pfc_inductor.ui.viewer3d import BottomActions
    b = BottomActions()
    for label_attr in ("btn_explode", "btn_section", "btn_measure", "btn_export"):
        assert getattr(b, label_attr) is not None


def test_bottom_actions_export_menu_emits_format(app):
    from pfc_inductor.ui.viewer3d import BottomActions
    b = BottomActions()
    received: list[str] = []
    b.export_requested.connect(received.append)
    # Trigger each export-menu action.
    actions = b.btn_export.menu().actions()
    for act in actions:
        act.trigger()
    assert "png" in received and "stl" in received and "vrml" in received


def test_bottom_actions_explode_emits_bool(app):
    from pfc_inductor.ui.viewer3d import BottomActions
    b = BottomActions()
    fired: list[bool] = []
    b.explode_toggled.connect(fired.append)
    b.btn_explode.click()
    b.btn_explode.click()
    assert fired == [True, False]


# ---------------------------------------------------------------------------
# Shared camera presets
# ---------------------------------------------------------------------------

def test_visual_views_exposed(app):
    from pfc_inductor.visual import VIEW_CAMERAS, set_camera_to_view, ViewName
    assert set(VIEW_CAMERAS.keys()) == {"front", "top", "side", "iso"}
    # Each entry is (dir, up) where up is non-zero in some axis.
    for name, (cam_dir, up_vec) in VIEW_CAMERAS.items():
        assert any(abs(v) > 0.5 for v in up_vec), name


# ---------------------------------------------------------------------------
# CoreView3D fallback (offscreen ⇒ no plotter, but overlays still mount)
# ---------------------------------------------------------------------------

def test_core_view_3d_falls_back_in_offscreen(app):
    from pfc_inductor.ui.core_view_3d import CoreView3D
    v = CoreView3D()
    # Plotter is None under offscreen Qt.
    assert v.plotter is None
    # Overlays still constructed for layout purposes.
    assert hasattr(v, "chips")
    assert hasattr(v, "cube")
    assert hasattr(v, "toolbar")
    assert hasattr(v, "action_bar")
