"""Camera presets + helper used by both the report renderer and the
interactive 3D viewer overlay.

Coordinate convention (matches the mesh builder):

- ``+X`` = width  (left-right)
- ``+Y`` = depth  (front-back)
- ``+Z`` = height (up-down)
"""

from __future__ import annotations

from typing import Literal

import numpy as np

ViewName = Literal["front", "top", "side", "iso"]


# (camera direction from origin, up vector). The eye is placed at
# ``centre + dir·distance`` and looks back at the centre.
VIEW_CAMERAS: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
    "front": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "side": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "iso": ((1.0, -1.0, 0.7), (0.0, 0.0, 1.0)),
}


def set_camera_to_view(plotter, view: ViewName, *, parallel_for_orthographic: bool = True) -> None:
    """Configure ``plotter``'s camera for the named canonical view.

    ``front``, ``top``, and ``side`` switch the camera to parallel
    projection so the resulting image reads as a technical orthographic
    view; ``iso`` keeps perspective for a more natural feel.
    """
    cam_dir, up_vec = VIEW_CAMERAS[view]
    bounds = plotter.bounds  # (xmin, xmax, ymin, ymax, zmin, zmax)
    centre = np.array(
        [
            (bounds[0] + bounds[1]) / 2,
            (bounds[2] + bounds[3]) / 2,
            (bounds[4] + bounds[5]) / 2,
        ]
    )
    span = max(
        bounds[1] - bounds[0],
        bounds[3] - bounds[2],
        bounds[5] - bounds[4],
    )
    distance = span * 2.4
    eye = centre + np.array(cam_dir, dtype=float) * distance
    plotter.camera_position = [tuple(eye), tuple(centre), up_vec]
    if view in ("front", "top", "side") and parallel_for_orthographic:
        try:
            plotter.camera.parallel_projection = True
            plotter.camera.parallel_scale = span / 1.7
        except Exception:
            pass
    else:
        try:
            plotter.camera.parallel_projection = False
        except Exception:
            pass
