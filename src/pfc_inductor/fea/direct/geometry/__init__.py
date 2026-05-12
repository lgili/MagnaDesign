"""Geometry generators — one module per core shape.

The shape-specific modules (``ei``, ``ee``, ``toroidal``, ``pq``, …)
all conform to :class:`pfc_inductor.fea.direct.geometry.base.CoreGeometry`
so the runner can pick the right one off the ``Core.shape`` string
without case-by-case branches.
"""

from __future__ import annotations

__all__ = [
    "CoreGeometry",
    "build_ei",
]


def __getattr__(name: str):
    if name == "CoreGeometry":
        from pfc_inductor.fea.direct.geometry.base import CoreGeometry

        return CoreGeometry
    if name == "build_ei":
        from pfc_inductor.fea.direct.geometry.ei import build_ei

        return build_ei
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
