# Tasks — Cost model

## 1. Data model

- [x] 1.1 Add to `Material`: `cost_per_kg: Optional[float] = None`,
      `cost_currency: str = "USD"`.
- [x] 1.2 Add to `Core`: `cost_per_piece: Optional[float] = None`,
      `mass_g: Optional[float] = None` (auto-derive from Ve_mm3 ·
      ρ_kg_m3 of default material if not provided).
- [x] 1.3 Add to `Wire`: `cost_per_meter: Optional[float] = None`,
      `mass_per_meter_g: Optional[float] = None` (derive from A_cu and
      copper density 8960 kg/m³).
- [x] 1.4 Update JSON schema; bumped version field.

## 2. Cost computation

- [x] 2.1 `physics/cost.py::CostBreakdown` pydantic model: `core_cost`,
      `wire_cost`, `total_cost`, `currency`.
- [x] 2.2 `cost.py::estimate(core, wire, material, N_turns, MLT_mm,
      currency="USD") -> CostBreakdown`. Returns `None` if any required
      cost field is missing on the inputs.
- [x] 2.3 Wire cost: total length = N · MLT (mm) · 1e-3 → m;
      cost = length_m · wire.cost_per_meter.
- [x] 2.4 Core cost: prefer `cost_per_piece` if set; else compute mass
      from Ve · density and use a (future) material `cost_per_kg`.

## 3. UI surfaces

- [x] 3.1 `ResultPanel`: add KPI group "Custo estimado" with rows for
      core $, wire $, total $. Hide if cost is `None`.
- [x] 3.2 `OptimizerDialog`: rank-by combo gets two new options
      "Menor custo" and "Score 40/30/30 (perda/volume/custo)".
- [x] 3.3 Pareto plot: optional toggle "Pareto custo × perda" instead of
      "volume × perda".
- [x] 3.4 `DbEditorDialog`: cost fields included automatically since the
      JSON editor exposes all model fields.

## 4. Currency

- [x] 4.1 Global preference (stored in user-data dir) for default currency.
      Drop-down in main window: "USD | BRL | EUR".
- [x] 4.2 Conversion at display time using a hard-coded reference rate
      (`USD = 5.0 BRL` placeholder), with a settings dialog to override.
- [x] 4.3 All stored costs are tagged with their original currency; UI
      converts on the fly.

## 5. Testing

- [x] 5.1 Test: a wire with `cost_per_meter=0.10` and a 50-turn winding on
      a core with MLT=80 mm yields wire_cost = 0.10 · 4.0 = $0.40.
- [x] 5.2 Test: a core with `cost_per_piece=2.50` returns core_cost=2.50.
- [x] 5.3 Test: `estimate` returns None when wire.cost_per_meter is None.
- [x] 5.4 Optimizer test: ranking by "cost" puts cheaper feasible designs
      first.

## 6. Docs

- [x] 6.1 README: how to populate cost fields (DB editor or seed JSON).
