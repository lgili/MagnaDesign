# Design — MAS schema adoption

## Why MAS specifically

- **Industry consensus**: PSMA Magnetics Committee is taking it; FEMMT, MKF
  and OpenMagnetics tooling already consume it.
- **Vendor-neutral**: separates "what magnetic must do" (Inputs) from "what
  it is" (Magnetic) from "what it computes" (Outputs) — exactly the split
  we already have informally between `Spec`, the entries, and
  `DesignResult`.
- **JSON Schema 2020-12**: validatable, generatable into typed classes for
  any modern language.
- **Active**: incubated at OpenMagnetics, in the path to PSMA stewardship.
  Pinning a version is acceptable risk.

## Why a layered model (don't replace the inner API)

Our physics modules accept `Material`, `Core`, `Wire` directly. Replacing
those classes wholesale would force rewrites everywhere. The pragmatic
plan:

```
        +-----------------+        +----------------+
JSON →  | mas/_generated  |  →     | mas/adapters   |  →   internal
        | (pydantic)      |        | (Material/etc) |       physics
        +-----------------+        +----------------+
```

The persisted form is MAS; the in-memory form is unchanged. Anything that
needs to write back goes through `to_mas()`.

## Schema version pin policy

- Pin MAS schema version in `pyproject.toml` (extra group `mas`).
- Bump as a minor release; full regression run gates the bump.
- Vendor the schema files (don't fetch at import time).

## Field mapping (excerpt)

Our internal model → MAS path:

| Internal | MAS |
|----------|-----|
| `Material.mu_initial` | `magnetic.material.permeability.initialPermeability` |
| `Material.Bsat_25C_T` | `magnetic.material.saturation[0]` (temp=25, value=…) |
| `Material.steinmetz` | `magnetic.material.coreLossesMethods[].steinmetz.coefficients` |
| `Material.rolloff` | `magnetic.material.permeability.dcBiasCurve` (table form) |
| `Core.shape`/`Ae`/`le`/`Ve` | `magnetic.core.shape` + `dimensions` |
| `Core.AL_nH` | `magnetic.core.inductanceFactor` |
| `Wire.A_cu_mm2` | `magnetic.coil.functionalDescription[].wire.conductingArea` |

Powder rolloff: MAS expresses DC bias as a curve (H, μ%) rather than a
3-coefficient fit. Migration will sample our `1/(a + b·H^c)` at a dense
H-grid and store the table; the inverse adapter fits back to (a,b,c) for
internal use.

## Risks & open questions

- **Custom fields** (e.g. our `cost_per_kg`, `cost_currency`, the
  `loss_datapoints` raw measurement table): MAS allows extension via
  `additionalProperties`; we'll namespace under `x-pfc-inductor`.
- **Round-trip fidelity** for non-canonical materials (Magmattec, Thornton
  brazilian-vendor entries) might surface gaps in MAS' material-type
  enumeration. Plan: open issues upstream; until merged, keep the
  legacy fields under the `x-pfc-inductor` extension.
- **Pydantic-v2 vs generated v1 models**: `datamodel-code-generator`
  emits pydantic v1 by default — we need the v2 backend. CI must pin both.
