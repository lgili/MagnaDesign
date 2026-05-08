"""Winding-layout solver — turn the engine's N-turns answer into
a per-layer winding plan a vendor can wind.

The engine reports ``N_turns`` as a scalar. A vendor needs the
layer-by-layer breakdown:

- How many turns fit per layer (function of bobbin breadth and
  wire outer diameter).
- How many layers does that take?
- How much of the bobbin window does that fill (``Ku``-like
  metric)?
- Does the stack fit within the bobbin's window height?

All of the above generalise across topologies. Toroids and
EE / ETD bobbins differ in *which* dimension the turns spread
along; the solver normalises to a "layer breadth" + "window
height" pair so the same formula works.

Inter-layer insulation
----------------------

Production-quality bobbins carry a dielectric tape between
layers — typically 0.05 mm Mylar / Nomex polyester. The default
(``INTER_LAYER_TAPE_MM = 0.05``) matches the IEC 60085 Class B
default; bumps to 0.07 mm or 0.1 mm for Class F / H constructions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from pfc_inductor.models import Core, Wire


# Default thickness of inter-layer dielectric tape (mm). Matches
# the IEC 60085 Class B default; the caller can override per
# project.
INTER_LAYER_TAPE_MM = 0.05


@dataclass(frozen=True)
class LayerPlan:
    """One layer of the winding stack."""

    index: int
    """1-based — vendor-friendly numbering ("Layer 1", "Layer 2"...)."""

    turns: int
    """Number of turns laid in this layer."""

    breadth_mm: float
    """Linear span used by the turns in this layer (mm)."""

    height_mm: float
    """Cumulative stack height up to and including this layer (mm)."""


@dataclass(frozen=True)
class WindingPlan:
    """Result of laying ``N`` turns onto the bobbin."""

    n_turns: int
    n_layers: int
    layers: tuple[LayerPlan, ...]

    layer_breadth_mm: float
    """Available linear span along the bobbin direction (mm)."""

    window_height_mm: float
    """Available bobbin / window depth (mm). Stack must fit within."""

    bobbin_used_pct: float
    """Stack height / window height × 100. Engineering rule of
    thumb: < 30 % is wasted material; > 90 % is hard to wind by
    hand and triggers a warning."""

    inter_layer_tape_mm: float
    """The tape thickness assumed in the layout (mm)."""

    warnings: tuple[str, ...]
    """Layer-stack warnings (over-fill, under-fill, geometry
    can't fit). Empty when the layout is comfortable."""


def plan_winding(
    *,
    core: Core,
    wire: Wire,
    n_turns: int,
    inter_layer_tape_mm: float = INTER_LAYER_TAPE_MM,
) -> WindingPlan:
    """Lay ``n_turns`` of ``wire`` onto ``core``.

    Toroidal cores spread turns along the inner diameter; bobbin
    cores (EE / ETD / PQ etc.) spread along the bobbin breadth.
    The solver normalises both to a ``(layer_breadth, window_height)``
    pair, computed from the available core fields.

    Returns a :class:`WindingPlan`. Even when the geometry is
    pathological (zero breadth, zero turns) the function returns
    an explanatory plan with a warning rather than raising — the
    caller (UI / PDF writer) can render the warnings inline.
    """
    if n_turns <= 0:
        return _empty_plan(
            n_turns=n_turns,
            layer_breadth_mm=0.0,
            window_height_mm=0.0,
            inter_layer_tape_mm=inter_layer_tape_mm,
            extra_warnings=("n_turns is zero — nothing to wind",),
        )

    layer_breadth_mm, window_height_mm = _bobbin_dimensions(core)
    if layer_breadth_mm <= 0 or window_height_mm <= 0:
        return _empty_plan(
            n_turns=n_turns,
            layer_breadth_mm=layer_breadth_mm,
            window_height_mm=window_height_mm,
            inter_layer_tape_mm=inter_layer_tape_mm,
            extra_warnings=(
                "Bobbin breadth or window height ≤ 0 — core "
                "geometry incomplete, layout skipped",
            ),
        )

    wire_od = wire.outer_diameter_mm()
    if wire_od <= 0:
        return _empty_plan(
            n_turns=n_turns,
            layer_breadth_mm=layer_breadth_mm,
            window_height_mm=window_height_mm,
            inter_layer_tape_mm=inter_layer_tape_mm,
            extra_warnings=(
                f"Wire {wire.id} has zero outer diameter — "
                "layout skipped",
            ),
        )

    turns_per_layer = max(1, int(layer_breadth_mm // wire_od))
    n_layers = math.ceil(n_turns / turns_per_layer)

    layers: list[LayerPlan] = []
    cumulative_height = 0.0
    remaining = n_turns
    for idx in range(n_layers):
        layer_turns = min(turns_per_layer, remaining)
        cumulative_height += wire_od
        if idx > 0:
            cumulative_height += inter_layer_tape_mm
        layers.append(LayerPlan(
            index=idx + 1,
            turns=layer_turns,
            breadth_mm=round(layer_turns * wire_od, 3),
            height_mm=round(cumulative_height, 3),
        ))
        remaining -= layer_turns

    bobbin_used_pct = (
        100.0 * cumulative_height / window_height_mm
        if window_height_mm > 0 else math.inf
    )

    warnings: list[str] = []
    if bobbin_used_pct > 100.0:
        warnings.append(
            f"Stack height {cumulative_height:.2f} mm exceeds "
            f"available window {window_height_mm:.2f} mm — "
            f"won't fit ({bobbin_used_pct:.0f} % of window).",
        )
    elif bobbin_used_pct > 90.0:
        warnings.append(
            f"Bobbin {bobbin_used_pct:.0f} % full — hard to "
            f"wind by hand; consider a fewer-layer plan.",
        )
    elif bobbin_used_pct < 30.0:
        warnings.append(
            f"Bobbin only {bobbin_used_pct:.0f} % full — "
            f"oversized core for this turn count, wasting "
            f"material and footprint.",
        )

    return WindingPlan(
        n_turns=n_turns,
        n_layers=n_layers,
        layers=tuple(layers),
        layer_breadth_mm=round(layer_breadth_mm, 3),
        window_height_mm=round(window_height_mm, 3),
        bobbin_used_pct=round(bobbin_used_pct, 1),
        inter_layer_tape_mm=inter_layer_tape_mm,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Geometry resolution
# ---------------------------------------------------------------------------
def _bobbin_dimensions(core: Core) -> tuple[float, float]:
    """Resolve ``(layer_breadth_mm, window_height_mm)`` from the
    core's fields.

    Toroids: layer_breadth = π · ID (inner perimeter), window_height
    = (OD − ID) / 2 (radial window depth). When OD/ID aren't on
    the model (common for MAS-imported cores that only carry
    ``Wa_mm2``), fall back to a circular-window approximation:

    - ``Wa = π · (ID/2)²`` ⇒ ``ID = 2·√(Wa/π)``
    - ``radial_window ≈ ID/2`` (typical for the small toroids
      we ship; conservative for large ones).

    EE / ETD / PQ / similar: layer_breadth = HT (bobbin window
    height in the magnetic-axis direction), window_height ≈
    Wa / HT (the window area divided by breadth — a first-order
    estimate).

    Returns ``(0, 0)`` when the core lacks the geometry to figure
    it out — the caller handles that case as "layout skipped".
    """
    shape = (core.shape or "").lower()
    if shape in {"toroid", "toroide", "round-toroid", "t"}:
        if core.ID_mm and core.OD_mm and core.OD_mm > core.ID_mm:
            inner_perimeter = math.pi * core.ID_mm
            radial_window = (core.OD_mm - core.ID_mm) / 2.0
            return (inner_perimeter, radial_window)
        # MAS-imported toroids only have Wa — derive a circular-
        # window approximation. ID = 2·√(Wa/π); the radial depth
        # we use ID/2 (one wire-diameter shy of the centre).
        if core.Wa_mm2 and core.Wa_mm2 > 0:
            id_mm = 2.0 * math.sqrt(core.Wa_mm2 / math.pi)
            inner_perimeter = math.pi * id_mm
            radial_window = id_mm / 2.0
            return (inner_perimeter, radial_window)
        return (0.0, 0.0)

    # Bobbin-style cores — fall back to Wa + HT when present.
    breadth = float(core.HT_mm or 0.0)
    if breadth <= 0 and core.Wa_mm2 and core.OD_mm:
        # Last-resort: approximate breadth from Wa / radial-window
        # estimate. Less accurate but better than zero.
        radial = (core.OD_mm - (core.ID_mm or 0)) / 2.0 or 1.0
        breadth = max(1.0, core.Wa_mm2 / radial)
    elif breadth <= 0 and core.Wa_mm2 and core.Wa_mm2 > 0:
        # No HT and no OD/ID — assume a square window for the
        # rough sizing. Better than crashing the layout.
        breadth = math.sqrt(core.Wa_mm2)

    if breadth <= 0:
        return (0.0, 0.0)

    if core.Wa_mm2 and core.Wa_mm2 > 0:
        height = core.Wa_mm2 / breadth
        return (breadth, height)
    return (breadth, 0.0)


def _empty_plan(
    *,
    n_turns: int,
    layer_breadth_mm: float,
    window_height_mm: float,
    inter_layer_tape_mm: float,
    extra_warnings: tuple[str, ...],
) -> WindingPlan:
    """Build a degenerate plan that carries the warnings without
    crashing the caller. Used for the "I can't compute this" path
    so the PDF writer can still render an explanatory page."""
    return WindingPlan(
        n_turns=n_turns,
        n_layers=0,
        layers=(),
        layer_breadth_mm=layer_breadth_mm,
        window_height_mm=window_height_mm,
        bobbin_used_pct=0.0,
        inter_layer_tape_mm=inter_layer_tape_mm,
        warnings=extra_warnings,
    )
