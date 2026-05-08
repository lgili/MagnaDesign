"""Variable-frequency-drive (VFD) engine wrapper.

When :class:`Spec.fsw_modulation` is set, callers route through
:func:`eval_band` instead of calling :func:`pfc_inductor.design.design`
directly. The wrapper iterates the band's fsw points, calls the
engine once per point, and aggregates the results into a
:class:`BandedDesignResult`.

The wrapper lives at top-level (not inside ``topology/``) because:

- It's not topology-specific — every existing topology benefits
  from a banded run when its ``f_sw_kHz`` is the relevant knob.
- ``topology/`` is actively expanding with new topology files
  (buck, flyback, LCL, …) — keeping the wrapper outside avoids a
  merge race.
- The wrapper is thin (~80 LOC) and the only thing it imports is
  the existing engine entry point.

Public API
----------

- :func:`eval_band` — run the engine across the band, return a
  :class:`BandedDesignResult`.
- :func:`design_or_band` — convenience dispatcher used by the
  legacy single-point callers: hands off to ``design()`` when the
  spec has no band, ``eval_band`` when it does.
"""
from __future__ import annotations

from pfc_inductor.modulation.engine import (
    design_or_band,
    eval_band,
)

__all__ = [
    "design_or_band",
    "eval_band",
]
