"""Design overrides — the "ajuste de protótipo" model.

After the engine solves a design, the bench reality often diverges:
the engineer winds 32 turns instead of the 30 the solver chose
(because the bobbin layer fit better), uses a thicker wire on hand,
or wants to see how the same physical build behaves at 60 °C summer
ambient. :class:`DesignOverrides` captures those tweaks as a small,
optional payload that the engine applies on top of the canonical
spec → core/wire/material inputs.

Empty overrides round-trip transparently — when every field is
``None``, the design pipeline is byte-identical to the legacy
``design(spec, core, wire, material)`` call. This keeps the
override path strictly additive: existing code, snapshots, and
``.pfc`` files keep working without a migration.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DesignOverrides(BaseModel):
    """Manual tweaks applied on top of the calculated design.

    Each field is optional. ``None`` means "use the value the engine
    would normally pick"; a concrete value forces the engine to use
    it instead of solving for it (or reading it from the spec).

    Fields
    ------
    N_turns
        Force the winding turn count. Skips the engine's
        ``_solve_N`` step. May result in ``L_actual < L_required`` —
        the result panel surfaces this as a warning.
    wire_id
        Use a different wire than the project's selection (e.g. the
        AWG you actually had in stock). The controller looks the id
        up in the active catalog before passing it to the engine.
    core_id
        Same, for the magnetic core.
    T_amb_C
        Override the spec's ambient temperature for the thermal
        solve. Useful for "what does this design look like at the
        summer worst-case?" without editing the spec itself.
    """

    N_turns: Optional[int] = Field(
        default=None,
        ge=1,
        le=2000,
        description="Forced turn count (skips _solve_N).",
    )
    wire_id: Optional[str] = Field(
        default=None,
        description="Catalog id of a wire to use instead of the project's selection.",
    )
    core_id: Optional[str] = Field(
        default=None,
        description="Catalog id of a core to use instead of the project's selection.",
    )
    T_amb_C: Optional[float] = Field(
        default=None,
        ge=-40.0,
        le=150.0,
        description="Override ambient °C for the thermal solver.",
    )
    n_stacks: Optional[int] = Field(
        default=None,
        ge=1,
        le=8,
        description=(
            "Stacked core count — engineer's practical 'make the inductor "
            "bigger' lever. n=2 means two physical cores assembled together "
            "(two stacked toroids, two paralleled EE halves). Scales Ae, Ve, "
            "AL, mass, MLT by n; window and magnetic-path stay constant."
        ),
    )
    gap_mm: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=20.0,
        description=(
            "Forced air-gap length in mm. Replaces the catalog ``lgap_mm`` "
            "(and the engine's auto-computed gap for ungapped ferrites). "
            "Has no effect on powder / distributed-gap cores."
        ),
    )

    model_config = {"extra": "ignore"}

    def is_empty(self) -> bool:
        """True when every field is ``None`` (or n_stacks == 1) — the
        override is a no-op against the catalog core."""
        for name in type(self).model_fields:
            v = getattr(self, name)
            if v is None:
                continue
            if name == "n_stacks" and v == 1:
                continue
            return False
        return True
