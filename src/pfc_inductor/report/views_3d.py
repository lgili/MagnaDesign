"""Generate the four orthographic + isometric views used on page 1 of
the datasheet (front, top, side, iso).

Each view is a PNG rendered offscreen with the same colour scheme the
GUI uses, returned base64-encoded so the HTML datasheet remains
self-contained.

Strategy: build the same core + winding meshes the GUI builds, then
render four times with a fixed camera per view. Dimensioning text is
NOT overlaid on the image (clean line-drawing style is hard to
generate procedurally); the datasheet lists dimensions in a table
adjacent to the views.
"""

from __future__ import annotations

import base64
import os
from io import BytesIO
from typing import Optional

from pfc_inductor.models import Core, Material, Wire
from pfc_inductor.visual import (
    infer_shape,
    make_core_mesh,
    make_winding_mesh,
)

# Colour palette mirrors ``ui/core_view_3d.py``.
_CORE_COLORS = {
    "powder": "#b9a98c",
    "ferrite": "#3a3838",
    "nanocrystalline": "#5d6c7a",
    "amorphous": "#6e7178",
    "silicon-steel": "#a4a39e",
    "default": "#888888",
}
_COPPER = "#c98a4b"


def _setup_plotter(window_size: tuple[int, int]):
    """Create an offscreen pyvista plotter; return ``None`` if VTK
    can't initialize (CI / very stripped headless boxes)."""
    try:
        import pyvista as pv

        pv.OFF_SCREEN = True
        plotter = pv.Plotter(off_screen=True, window_size=window_size)
        plotter.set_background("white")
        try:
            plotter.enable_anti_aliasing("ssaa")
        except Exception:
            pass
        try:
            plotter.enable_lightkit()
        except Exception:
            pass
        return plotter
    except Exception:
        return None


def _add_to_scene(plotter, core: Core, wire: Wire, N_turns: int, material: Material) -> None:
    """Add core + winding using the same geometry helpers as the GUI."""
    mb, kind, info = make_core_mesh(core)
    wnd = make_winding_mesh(core, wire, N_turns, info)

    core_color = _CORE_COLORS.get(material.type, _CORE_COLORS["default"])
    is_closed = kind in ("ee", "etd", "pq")
    if material.type == "silicon-steel":
        core_kwargs = dict(metallic=0.65, roughness=0.45, specular=0.6, specular_power=20)
    elif material.type == "ferrite":
        core_kwargs = dict(metallic=0.05, roughness=0.40, specular=0.5, specular_power=18)
    elif material.type == "amorphous":
        core_kwargs = dict(metallic=0.7, roughness=0.30, specular=0.7, specular_power=25)
    else:
        core_kwargs = dict(metallic=0.05, roughness=0.65, specular=0.20, specular_power=10)
    opacity = 0.45 if is_closed else 1.0

    for blk in mb:
        if blk is None:
            continue
        plotter.add_mesh(
            blk,
            color=core_color,
            smooth_shading=True,
            ambient=0.20,
            diffuse=0.85,
            opacity=opacity,
            **core_kwargs,
        )
    if wnd is not None:
        plotter.add_mesh(
            wnd,
            color=_COPPER,
            smooth_shading=True,
            ambient=0.22,
            diffuse=0.55,
            specular=0.95,
            specular_power=40,
            metallic=0.85,
            roughness=0.18,
        )


# Camera presets are shared with the interactive 3D viewer overlay
# (``ui.viewer3d.view_chips``). The canonical definition lives in
# :mod:`pfc_inductor.visual.views` so both renderers consume the same
# directions and up-vectors.
from pfc_inductor.visual.views import (
    set_camera_to_view as _set_view_helper,
)


def _set_view(plotter, name: str) -> None:
    _set_view_helper(plotter, name)


def _render_one(
    core: Core,
    wire: Wire,
    N_turns: int,
    material: Material,
    view: str,
    window_size: tuple[int, int] = (640, 480),
) -> Optional[str]:
    plotter = _setup_plotter(window_size)
    if plotter is None:
        return None
    try:
        _add_to_scene(plotter, core, wire, N_turns, material)
        _set_view(plotter, view)
        plotter.render()
        buf = BytesIO()
        plotter.screenshot(buf)
        plotter.close()
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        try:
            plotter.close()
        except Exception:
            pass
        return None


def render_views(
    core: Core, wire: Wire, N_turns: int, material: Material
) -> dict[str, Optional[str]]:
    """Return a dict mapping view name → base64 PNG (or ``None`` if
    pyvista can't initialise on this machine).
    """
    # Headless-detect: skip 3D when the user runs in offscreen Qt.
    plat = os.environ.get("QT_QPA_PLATFORM", "").lower()
    if plat in ("offscreen", "minimal", "vnc"):
        # We can still render via pyvista's own offscreen path, so
        # don't bail here — try and let the caller deal with None.
        pass
    out: dict[str, Optional[str]] = {}
    for v in ("iso", "front", "top", "side"):
        out[v] = _render_one(core, wire, N_turns, material, v)
    return out


def derive_dimensions(core: Core) -> dict[str, str]:
    """Best-effort mechanical dimensions (mm) derived from the core
    record + the same geometry rules the 3D view uses. Reported as
    strings ready for the table.
    """
    from pfc_inductor.visual.core_3d import (
        _bobbin_dims,
        _ee_proportions,
        _toroid_dims,
    )

    kind = infer_shape(core)
    out: dict[str, str] = {}
    if kind == "toroid":
        dims = _toroid_dims(core)
        if dims is not None:
            OD, ID, HT = dims
            out["Outer Ø (OD)"] = f"{OD:.1f} mm"
            out["Inner Ø (ID)"] = f"{ID:.1f} mm"
            out["Height (HT)"] = f"{HT:.1f} mm"
            return out
    if kind in ("ee", "etd", "pq"):
        W, H, D = _bobbin_dims(core)
        out["Width (W)"] = f"{W:.1f} mm"
        out["Height (H)"] = f"{H:.1f} mm"
        out["Depth / stack (D)"] = f"{D:.1f} mm"
        if kind == "ee":
            outer_w, center_w, window_w = _ee_proportions(W)
            out["Centre-leg width"] = f"{center_w:.1f} mm"
            out["Outer-leg width"] = f"{outer_w:.1f} mm"
            out["Window width"] = f"{window_w:.1f} mm"
        return out
    side = max(core.Ve_mm3, 1.0) ** (1 / 3)
    out["Equivalent cube side"] = f"{side:.1f} mm"
    return out
