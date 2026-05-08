# Add flyback topology (DCM + CCM, coupled inductor / transformer)

## Why

Flyback is the dominant topology for **isolated low-to-medium-power
DC-DC converters** (5 W to ~150 W): wall adapters, LED drivers,
auxiliary supplies inside larger converters, USB-PD bricks, set-top-
box supplies, two-wheeler chargers. Every consumer-electronics PSU
under ~75 W is some variant of flyback, and a non-trivial slice of
the industrial / automotive AC-DC adapter market sits between 75 W
and 150 W where flyback still beats forward / LLC on cost.

The "indutor" in a flyback is actually a **coupled inductor** —
a transformer with an air gap that stores energy magnetically every
switching cycle and dumps it to the secondary on the OFF half.
That makes flyback a categorically different design problem from
every topology MagnaDesign covers today:

- **Two windings** (sometimes three with auxiliary bias): primary
  and secondary turns, both on the same core, with a defined
  turns ratio ``n = Np/Ns``.
- **Energy storage** is the design driver: ``E = ½ · Lp · Ip²`` per
  cycle, ``Pout = E · f_sw · η``. The required primary inductance
  is ``Lp_max = (Vin_min · D_max)² / (2 · Pout · f_sw / η)``.
- **Reflected voltage**: the primary switch sees ``Vin + n·Vout +
  V_leakage_spike``. The secondary diode sees ``Vout + Vin/n``.
  Stress voltages constrain both the FET and the rectifier choice.
- **Operating mode** can be DCM (textbook starting point: discharge
  fully each cycle), QR (quasi-resonant, switch at minimum drain
  voltage), or CCM (no zero-current pause; lower peak currents but
  RHP zero in the control loop). Modern designs are mostly CCM at
  full load and DCM at light load.
- **Leakage inductance** is part of the design — the energy stored
  in ``L_leak`` becomes the snubber's job and a meaningful loss
  budget item (typically 3–8 % of Pout). Coupled inductor design
  *minimises* L_leak via interleaved windings, sandwich layouts,
  bifilar where possible.

This is also the **first multi-winding magnetic** the engine
models, which unlocks the eventual ``add-forward-topology`` and
``add-llc-topology`` chains.

## What changes

A new ``flyback`` topology with full design support: spec model,
engine, feasibility, optimizer hooks, UI (picker + waveform synth +
schematic + Análise card with the new "secondary" trace), reports
(BOM lists *both* windings + the rectifier diode, datasheet shows
both currents, RCD-snubber sizing notes), and tests.

Spec extends:

```python
spec.topology = Literal[..., "flyback"]   # ← new
spec.flyback_mode: Literal["dcm", "ccm"] = "dcm"  # design mode
spec.Vout_V: float                  # already exists
spec.Vout_secondary_V: Optional[float]   # for multi-output, future
spec.Vin_dc_V: float                # DC input (post-bridge if AC-DC)
spec.turns_ratio_n: Optional[float] # if user wants to fix it
```

The **catalog** also extends — flyback designs use **bobbin-wound
EFD / EE / RM / PQ ferrite cores almost exclusively**, with gapped
geometries. The existing core database has these shapes, but the
``Core`` model needs a ``window_for_secondary_mm2`` field (or a
calculation rule) so the optimizer can split the window between
primary and secondary.

## Impact

### Domain layer

- **`pfc_inductor/topology/flyback.py`** (new) — pure-physics:
  - DCM design path (most common starting point).
  - CCM design path (selected via ``flyback_mode``).
  - Reflected-voltage stress on the primary switch.
  - Peak primary current ``Ip_pk = 2·Pout / (Vin_min · D · η)``.
  - RMS primary current (DCM trapezoid) and secondary RMS
    (DCM ramp-down) — both needed for Cu loss.
  - Volt-seconds across primary and secondary, used for both
    flux-density and Steinmetz core loss.
  - ``estimate_thd_pct`` returns 0 (DC input).
- **`pfc_inductor/topology/flyback_model.py`** (new) — implements
  ``ConverterModel``. ``state_derivatives`` is interesting: two
  conduction phases (switch ON: primary current ramps up from
  zero or initial; switch OFF: secondary current ramps down to
  zero in DCM, or to a non-zero floor in CCM).
- **`pfc_inductor/topology/registry.py`** — register.
- **`pfc_inductor/models/spec.py`** — Topology Literal,
  ``flyback_mode``, ``turns_ratio_n``, ``Vin_dc_V`` (shared with
  buck-CCM if that change lands first).
- **`pfc_inductor/models/core.py`** — extend ``Core`` to expose a
  *split window* helper: how much window area is available for
  the secondary given a primary fill factor. Optional field
  ``window_split_for_secondary`` (default ``0.45`` — typical
  sandwich winding).
- **`pfc_inductor/physics/`** — leakage-inductance estimator
  ``L_leak_estimate(core, primary_turns, secondary_turns,
  layer_layout)`` so the BOM can predict the snubber loss budget.

### Engine

- **`pfc_inductor/design/engine.py`** — flyback branch picks the
  primary turns to satisfy ``Lp = required Lp(spec)``, the
  secondary turns by ``Ns = Np / n``, computes flux density at
  peak primary current at end of ON period, validates saturation
  and window fill *for both windings*, computes copper loss for
  *both* windings, and reports leakage-inductance estimate +
  RCD-snubber dissipation.

### Optimizer

- **`pfc_inductor/optimize/feasibility.py`** —
  ``N_HARD_CAP_BY_TOPOLOGY["flyback"] = 200`` (primary), and
  the window-fill check splits between primary and secondary.
- **`pfc_inductor/optimize/cascade/generators.py`** — cartesian
  needs to handle the two-winding case: each candidate is now a
  triple ``(material, core, primary_wire, secondary_wire)``.
  Either:
  - **Option A**: enumerate (mat × core × wire) for primary and
    pick secondary heuristically to satisfy turns ratio + window
    split (cheaper, 1 free var per candidate).
  - **Option B**: full 4-D cartesian (slower, more accurate).
  - **Decision**: Option A in v1; Option B if benchmarking shows
    the heuristic is locally optimal on > 90 % of designs.

### UI

- **Topology picker** — add a "Flyback (DCM/CCM)" card.
- **Schematic** — flyback drawing: Vin → Q1 (primary side) →
  primary winding (highlighted) → with the dot convention
  visible; secondary winding (also highlighted) → diode → Cout
  → load. The two highlighted windings sit side-by-side on the
  same core symbol so the coupled-inductor identity reads.
- **Spec panel** — show ``flyback_mode``, ``turns_ratio_n``,
  ``Vin_dc_V``. Hide the AC-line fields.
- **Realistic waveforms** — new synth: primary current ramps up
  during ON, drops to zero during OFF (DCM) or holds at a
  non-zero level (CCM). Secondary current is the inverse.
  Stack iL_primary + iL_secondary in the Análise card's top
  axis.
- **Resumo strip** — add a "Vstress (Q1)" KPI tile: ``Vin_max +
  n·Vout + V_leakage_spike``. This is the headline number the
  flyback designer must check against the chosen FET.

### Reports

- **HTML datasheet**:
  - Spec rows include ``Vin_dc_V``, ``Vout_V``, ``Pout_W``,
    ``f_sw_kHz``, ``D_max``, ``η_target``, ``flyback_mode``,
    ``turns_ratio_n``.
  - Operating-point rows include ``Lp_actual_uH``, ``Np``,
    ``Ns``, ``Ip_peak_A``, ``Ip_rms_A``, ``Is_peak_A``,
    ``Is_rms_A``, ``B_pk_T``, ``L_leak_estimate_uH``,
    ``V_drain_pk_V``, ``P_snubber_W``.
  - Loss table splits into ``P_Cu_pri``, ``P_Cu_sec``, ``P_core``,
    ``P_snubber`` (new column).
  - Waveform plot stacks Ip + Is on the same time axis.
- **BOM** — list the **two** wires (primary and secondary) plus
  any auxiliary winding for bias supply, plus the snubber
  components (``R_sn``, ``C_sn``, ``D_sn``) with sized values.
- **Manufacturing spec** — winding sequence (P / S, sandwich
  P-S-P, etc.), bobbin layer count, insulation tape between
  windings (essential for safety isolation per IEC 60950 /
  IEC 62368).

### Standards

- **IEC 60950 / IEC 62368** — isolation creepage / clearance and
  reinforced insulation requirements. Flyback is the *first*
  topology where this matters. The compliance-report PDF needs
  a new section for isolation. v1 emits a checklist (creepage
  ≥ 6.4 mm for 250 V_rms reinforced, primary-secondary clearance
  ≥ 2× operating peak voltage); a future change does the
  full-blown calculation.
- **EN 55032 / FCC Part 15** (conducted EMI) — flyback's hard
  switching means EMI is meaningful. Out of scope for v1; the
  Validar tab gets a TODO link to the future EMI module.

### Catalogs

- The existing core database has plenty of flyback-suitable cores
  (EFD, EE, RM, PQ, EP). No DB change needed; the existing fields
  cover the geometry. Verify that ``Wa_mm2`` is populated for the
  flyback-targeted shapes (EFD especially).
- Wire database OK as-is — the J pre-filter already picks the
  right gauge per winding once we extend ``rated_current_A`` to
  return primary RMS for the primary lookup and secondary RMS
  for the secondary lookup.

### Tests

- ``tests/test_topology_flyback.py`` — DCM design at 12 V → 5 V,
  10 W, 100 kHz benchmark (matches Texas Instruments' UCC28780
  EVM). CCM design at the same operating point with different
  Lp / D ratios.
- ``tests/test_flyback_model.py`` — Tier-0 / Tier-1 / Tier-2.
- ``tests/test_design_engine.py`` extension — full engine run on
  the TI EVM benchmark.
- ``tests/test_realistic_waveforms.py`` — both Ip and Is
  synthesised with correct peak / RMS.
- Visual regression: dashboard with flyback design, both light
  and dark themes.

### Docs

- `README.md` Topologies table: add "Flyback (isolated DC-DC)".
- `docs/POSITIONING.md` — flyback row.
- `docs/UI.md` — multi-winding spec-panel rules.
- New `docs/topology-flyback.md` — design-method writeup
  (DCM-vs-CCM tradeoff, RCD-snubber sizing, leakage-inductance
  reduction techniques, isolation safety considerations).

## Non-goals

- Not modelling **planar flyback transformers** in v1 — most users
  spec wirewound EFD/EE.
- Not implementing **multi-output flyback** (e.g., +5 V and +12 V
  from the same core) — single secondary only. Spec field is
  reserved for a future change.
- Not implementing **active clamp flyback** (ACF) — that's a
  separate topology with its own resonance dynamics. Future
  change.
- Not building the full **EMI compliance** module — out of scope.

## Risk

Medium. The change touches more layers than buck-CCM:

- **Multi-winding catalog model** — if the core's window-split
  helper turns out to need calibration data, we may need to
  ship a small "winding layout" table per shape. Mitigated by
  starting with a flat 0.45 split and surfacing the actual
  achieved fill in the Engine output.
- **DCM-vs-CCM mode selection** — the engine picks one at design
  time, but the runtime point can drift (light load → DCM even
  if designed CCM). v1 designs for the requested mode and warns
  if the operating point puts it in the other regime.
- **Leakage-inductance estimate** is empirical and depends on
  the winding strategy. v1 ships a lookup table per core shape
  (matched against published vendor app notes) and flags
  ``leakage_estimate_uncertainty: ±30 %`` in the report.
