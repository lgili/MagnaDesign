"""Tolerance grammar — what varies, by how much, with what shape.

Each :class:`Tolerance` describes a single dimension of variation
(line voltage, ambient temperature, AL deviation, Bsat deviation,
wire diameter, …). A :class:`ToleranceSet` is a named collection
that the engine uses as one DOE input.

Defaults
--------

``DEFAULT_TOLERANCES`` ships a conservative IEC + IPC blend that
matches what most appliance / inverter teams quote when they
don't have vendor-specific data:

- AL  ±8 %  (powder-core typical, vendor datasheets)
- Bsat ±5 %  (IEC 60401-3 lot-to-lot variation)
- µ_r ±25 % (IEC 60401-3 NiZn/MnZn ferrite spread)
- wire ø ±2 % (IPC-2152 for round bare copper)
- T_amb 5–55 °C uniform   (typical appliance shipping range)
- V_in min/max from ``Spec`` (no extra dispersion — already
  captured at the spec level)
- Pout 50–130 % nominal triangular (compressor-VFD load swing)

Loosen / tighten per project; vendor-specific sheets supersede.

Schema
------

Each tolerance carries a *kind* — the engine knows how to apply
it. Adding a new kind requires (a) the symbolic name here and
(b) the application logic in ``engine.apply_tolerance``. Keeping
the kinds string-typed (rather than a Python enum) makes JSON /
YAML round-tripping cleaner.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


ToleranceDistribution = Literal["gaussian", "uniform", "triangle"]
"""Statistical shape used by Monte-Carlo sampling.

- ``gaussian``: μ = 0, σ = ``p3sigma_pct / 3``. Truncated at ±3σ.
- ``uniform``: equal probability on ``[-p3sigma_pct, +p3sigma_pct]``.
- ``triangle``: peak at 0, falls linearly to zero at the edges.

Corner DOE always evaluates at ``±p3sigma_pct`` regardless of the
distribution — the distribution only matters for yield estimation.
"""


ToleranceKind = Literal[
    # Spec-level inputs
    "Vin_Vrms",   # ± offset on nominal Vin (Vrms)
    "T_amb_C",    # absolute deviation on T_amb (°C)
    "Pout_pct",   # ± deviation on Pout (% of nominal)
    # Component variations
    "AL_pct",     # ± deviation on inductance factor
    "Bsat_pct",   # ± deviation on saturation flux density
    "mu_r_pct",   # ± deviation on relative permeability
    "wire_dia_pct",  # ± deviation on copper diameter
]


class Tolerance(BaseModel):
    """A single dimension of variation."""

    name: str = Field(
        ...,
        description="Human-readable identifier shown in reports.",
    )
    kind: ToleranceKind
    p3sigma_pct: float = Field(
        ...,
        ge=0.0,
        description=(
            "Half-width of the ±3σ envelope, expressed as the unit "
            "the kind implies — percent for AL/Bsat/Pout/mu_r/wire, "
            "absolute °C for T_amb_C, absolute Vrms for Vin_Vrms."
        ),
    )
    distribution: ToleranceDistribution = "gaussian"
    source: str = Field(
        "",
        description=(
            "Citation for the value (datasheet section, IEC clause, "
            "vendor email). Echoed in the worst-case report so an "
            "auditor can trace the assumption back to its origin."
        ),
    )

    @field_validator("name")
    @classmethod
    def _name_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Tolerance.name must be non-empty")
        return value


class ToleranceSet(BaseModel):
    """Named collection of tolerances. JSON-friendly."""

    name: str
    description: str = ""
    tolerances: list[Tolerance]

    @classmethod
    def from_json(cls, payload: dict) -> "ToleranceSet":
        """Defensive loader — unknown fields ignored, missing
        ``description`` filled with empty string. Mirrors the
        ``ProjectFile`` loader's leniency so a stray vendor-edited
        JSON still opens."""
        return cls.model_validate(payload)

    @classmethod
    def from_path(cls, path: Path) -> "ToleranceSet":
        return cls.from_json(json.loads(Path(path).read_text()))

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    def by_kind(self, kind: ToleranceKind) -> list[Tolerance]:
        """Lookup helper — returns the list of tolerances of a
        given kind. The DOE engine uses this to enumerate corners
        for one variable at a time."""
        return [t for t in self.tolerances if t.kind == kind]


# ---------------------------------------------------------------------------
# Bundled defaults — IPC / IEC / vendor-typical blend.
# ---------------------------------------------------------------------------
DEFAULT_TOLERANCES: ToleranceSet = ToleranceSet(
    name="default-ipc-iec-vendor",
    description=(
        "Conservative defaults for a worldwide-input PFC inductor: "
        "IPC-2152 wire tolerances, IEC 60401-3 magnetic component "
        "lot-to-lot spreads, vendor-typical AL band, appliance-range "
        "ambient. Tighten per project when vendor sheets are tighter."
    ),
    tolerances=[
        Tolerance(
            name="AL ±8 %",
            kind="AL_pct",
            p3sigma_pct=8.0,
            distribution="gaussian",
            source="Magnetics Inc. powder-core datasheet AL spread",
        ),
        Tolerance(
            name="Bsat ±5 %",
            kind="Bsat_pct",
            p3sigma_pct=5.0,
            distribution="gaussian",
            source="IEC 60401-3 §4.3 lot-to-lot variation",
        ),
        Tolerance(
            name="µ_r ±25 %",
            kind="mu_r_pct",
            p3sigma_pct=25.0,
            distribution="gaussian",
            source="IEC 60401-3 NiZn / MnZn ferrite spread",
        ),
        Tolerance(
            name="Wire ø ±2 %",
            kind="wire_dia_pct",
            p3sigma_pct=2.0,
            distribution="uniform",
            source="IPC-2152 round-bare-copper diameter tolerance",
        ),
        Tolerance(
            name="T_amb 25–55 °C",
            kind="T_amb_C",
            p3sigma_pct=15.0,
            distribution="uniform",
            source="Appliance shipping range (typical)",
        ),
        Tolerance(
            name="Vin ±10 % nominal",
            kind="Vin_Vrms",
            p3sigma_pct=23.0,
            distribution="uniform",
            source="Worldwide mains (85–265 Vrms; ±10 % of 230 V)",
        ),
        Tolerance(
            name="Pout 50–130 %",
            kind="Pout_pct",
            p3sigma_pct=40.0,
            distribution="triangle",
            source="Compressor-VFD load swing (idle to peak)",
        ),
    ],
)


def load_tolerance_set(name: str) -> ToleranceSet:
    """Resolve a tolerance-set name to a :class:`ToleranceSet`.

    Search order:

    1. Bundled set under ``data/tolerances/<name>.json`` (when the
       follow-up phase ships them).
    2. The literal ``default`` resolves to
       :data:`DEFAULT_TOLERANCES`.
    3. Otherwise raises ``ValueError`` with the list of available
       names so the caller can correct the spelling.

    The function is intentionally narrow — production callers should
    deserialize :class:`ToleranceSet` from a `.pfc` directly when
    the user has edited their own values.
    """
    if name in ("default", "default-ipc-iec-vendor"):
        return DEFAULT_TOLERANCES
    raise ValueError(
        f"Unknown tolerance set: {name!r}. "
        f"Available: ['default', 'default-ipc-iec-vendor']. "
        f"Custom sets must be supplied as a `ToleranceSet` "
        f"deserialised from JSON.",
    )
