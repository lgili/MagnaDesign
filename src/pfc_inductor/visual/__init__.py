"""Visual / mesh helpers — split for fast-import.

This package's public re-exports used to live in a flat
``__init__.py`` that eagerly imported ``core_3d``, ``bh_loop`` and
``views``. That eager import pulled pyvista (and pyvista transitively
imports matplotlib), which on a cold start is ~400 ms — paid every
time anything touched ``pfc_inductor.visual``, even just for the
cheap ``compute_bh_trajectory`` helper from ``bh_loop`` (which has
no pyvista dependency).

The lazy ``__getattr__`` below defers the heavy ``core_3d`` and
``views`` submodules until the first attribute access. So:

- ``from pfc_inductor.visual.bh_loop import compute_bh_trajectory``
  costs nothing extra over importing this module.
- ``from pfc_inductor.visual import make_core_mesh`` triggers the
  ``core_3d`` import on first access — which is exactly the path
  the 3D viewer uses when the user opens the dashboard.

For most callers, ``compute_bh_trajectory`` is the only entry-point
they need and pyvista never gets imported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# ``compute_bh_trajectory`` lives in a tiny module that doesn't pull
# anything heavy, so we keep it as an eager re-export for the very
# common ``from pfc_inductor.visual import compute_bh_trajectory``
# call path.
from pfc_inductor.visual.bh_loop import compute_bh_trajectory

if TYPE_CHECKING:  # pragma: no cover — typing only
    from pfc_inductor.visual.core_3d import (
        infer_shape,
        make_bobbin_mesh,
        make_core_mesh,
        make_winding_leads,
        make_winding_mesh,
        winding_fit_info,
    )
    from pfc_inductor.visual.views import (
        VIEW_CAMERAS,
        ViewName,
        set_camera_to_view,
    )

__all__ = [
    "VIEW_CAMERAS",
    "ViewName",
    "compute_bh_trajectory",
    "infer_shape",
    "make_bobbin_mesh",
    "make_core_mesh",
    "make_winding_leads",
    "make_winding_mesh",
    "set_camera_to_view",
    "winding_fit_info",
]

# Map name → (submodule, attribute). When someone does
# ``from pfc_inductor.visual import make_core_mesh`` we resolve the
# submodule import on demand. Subsequent accesses hit ``sys.modules``
# and are free.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "infer_shape": ("pfc_inductor.visual.core_3d", "infer_shape"),
    "make_bobbin_mesh": ("pfc_inductor.visual.core_3d", "make_bobbin_mesh"),
    "make_core_mesh": ("pfc_inductor.visual.core_3d", "make_core_mesh"),
    "make_winding_leads": ("pfc_inductor.visual.core_3d", "make_winding_leads"),
    "make_winding_mesh": ("pfc_inductor.visual.core_3d", "make_winding_mesh"),
    "winding_fit_info": ("pfc_inductor.visual.core_3d", "winding_fit_info"),
    "VIEW_CAMERAS": ("pfc_inductor.visual.views", "VIEW_CAMERAS"),
    "ViewName": ("pfc_inductor.visual.views", "ViewName"),
    "set_camera_to_view": ("pfc_inductor.visual.views", "set_camera_to_view"),
}


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute hook.

    Resolves ``pfc_inductor.visual.<name>`` on first access by
    importing the underlying submodule and caching the value back on
    the package so subsequent accesses bypass ``__getattr__``.
    """
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    mod = importlib.import_module(target[0])
    value = getattr(mod, target[1])
    # Cache on the package so subsequent lookups don't re-enter
    # ``__getattr__``. (Python's PEP 562 fallback only runs when
    # the name isn't already on the module.)
    globals()[name] = value
    return value
