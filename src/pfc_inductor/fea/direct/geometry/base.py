"""Shared geometry primitives for the direct ONELAB backend.

A geometry generator's job is to populate the Gmsh model with:

1. The 2-D shape (core, windows, winding regions, air gap, outer
   air box).
2. **Physical groups** — Gmsh tags that the ``.pro`` file uses to
   refer to regions ("Core", "Coil_pos", "AirGap", "Air", etc.).
   Physical group tag numbers are conventionally chosen here and
   referenced as integer constants by the physics layer.
3. **Mesh-size fields** — telling Gmsh to refine near corners /
   gaps and coarsen in bulk air.

All of that is encapsulated in :class:`CoreGeometry`, which exposes
a single :meth:`build` method. The concrete subclasses
(``EIGeometry``, ``EEGeometry``, ``ToroidalGeometry`` …) only have
to override the geometry-construction step; everything else
(mesh-field setup, naming convention) is shared here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

# ─── Region tags ──────────────────────────────────────────────────
# Stable integer ids for physical groups. The ``.pro`` file in
# ``physics/magnetostatic.py`` references these by number, so any
# change here is a coordinated change across the package.


class RegionTag:
    """Canonical physical-group tag numbers.

    Keep these unique across all 2-D regions a geometry might emit.
    The ``.pro`` template literally interpolates these integers.
    """

    CORE = 1
    """Solid magnetic material — ``μ_r`` from ``Material``."""

    AIR_GAP = 2
    """Air slice cutting the magnetic circuit — discrete gap."""

    AIR_OUTER = 3
    """Outer air box / surrounding free space."""

    COIL_POS = 10
    """Winding bundle with current flowing INTO the page (``+J``)."""

    COIL_NEG = 11
    """Winding bundle with current flowing OUT of the page (``-J``)."""

    # Boundary tags (1-D / 0-D physical groups) start at 100 to
    # avoid any conflict with region tags.
    OUTER_BOUNDARY = 100
    """Outermost edge of the air box — Dirichlet ``A = 0``."""


@dataclass(frozen=True)
class GeometryBuildResult:
    """Hand-off from the geometry layer to the mesh + physics layers.

    Holds the Gmsh model's name (so the solver can re-open it) plus
    a description of which physical groups were emitted, so the
    ``.pro`` generator can sanity-check before writing.
    """

    model_name: str
    """The Gmsh model name (``gmsh.model.add(name)``)."""

    geo_path: Optional[str] = None
    """Path to the ``.geo_unrolled`` file Gmsh exports for the
    record. Useful for debugging — open in the Gmsh GUI to
    eyeball the geometry. ``None`` if export was skipped."""

    region_tags: tuple[int, ...] = (
        RegionTag.CORE,
        RegionTag.AIR_GAP,
        RegionTag.AIR_OUTER,
        RegionTag.COIL_POS,
        RegionTag.COIL_NEG,
    )
    """Region tags actually present in the model. The physics
    layer skips constraints for missing tags so a geometry without
    an air gap (closed core) still works."""


# ─── Abstract base ────────────────────────────────────────────────


class CoreGeometry(ABC):
    """Contract every shape-specific geometry module implements.

    The lifecycle is:

    1. Caller constructs the concrete subclass with everything it
       needs to know about dimensions (typically a shape-specific
       dataclass like :class:`EICoreDims`).
    2. Caller calls :meth:`build` with the active Gmsh module
       handle. The subclass populates ``gmsh.model`` with points,
       lines, surfaces, and physical groups.
    3. Caller proceeds with mesh generation + ``.pro`` emission.

    Subclasses must NOT call ``gmsh.initialize()`` or ``finalize()``
    — that's the caller's job (handled by ``runner.py``). The Gmsh
    handle is passed in so unit tests can mock it.
    """

    @abstractmethod
    def build(self, gmsh_module, model_name: str) -> GeometryBuildResult:
        """Populate ``gmsh.model`` with the core geometry.

        Parameters
        ----------
        gmsh_module:
            The imported ``gmsh`` module (``import gmsh``). Passed
            in rather than imported here so tests can substitute a
            fake or the same module that the rest of the pipeline
            uses (Gmsh's Python API holds global state — we never
            want two ``import gmsh`` calls colliding).
        model_name:
            Name the subclass will pass to ``gmsh.model.add``. Used
            by the solver layer to re-open the right model when
            multiple runs are pipelined.

        Returns
        -------
        GeometryBuildResult
            What was actually emitted — region tags, optional path
            to the ``.geo_unrolled`` debug file.
        """
        raise NotImplementedError
