# Add LCL grid-tie inverter output filter

## Why

Grid-tie inverters — solar PV, wind, battery storage, V2G, EV
chargers operating in V2G mode — push high-frequency PWM into the
utility grid. Without an output filter the grid sees switching-
ripple currents that violate every utility code on the planet
(IEEE 1547, IEC 61727, IEC 62109, AS/NZS 4777). The **LCL filter**
is the universal answer: a series ``L_inverter`` on the inverter
side, a shunt ``C_filter`` to ground, then a series ``L_grid`` on
the grid side. The L's are dimensionally inductors, but the design
problem is fundamentally different from every choke MagnaDesign
covers today.

What's new mathematically:

- **Two coupled inductors** in one design. Their values are
  *jointly* constrained by the resonance frequency target
  (``f_res = (1/2π) · √((L_inv + L_grid) / (L_inv · L_grid · C))``
  must sit one decade above the line and one decade below the
  switch frequency).
- **Resonance damping** — the LCL has a sharp peak at ``f_res``
  that, undamped, will ring. Either passive damping (resistor in
  series with C, costs efficiency) or active damping (control-
  loop based, free but adds complexity). The user picks one.
- **Compliance is the design driver**. Unlike PFC chokes where
  THD is a *consequence* of L sizing, here the IEEE 1547 / IEC
  61727 limit at each harmonic *is* the design constraint —
  the L's are sized to attenuate the inverter's PWM-band
  emission below the grid-current limit at every relevant
  harmonic.
- **Three-phase by default** — most grid-tie applications above
  10 kW are 3-phase. Each phase has its own LCL (3 × L_inv +
  3 × C + 3 × L_grid). The design engine has to handle a 6-
  inductor BOM for one project.
- **Reactive power handling**: the filter capacitor itself draws
  reactive current at the line frequency. Spec must include the
  inverter's allowed Q range; the filter design must keep
  ``Q_filter < 5 %`` of nominal Pout (per IEEE 1547 §4.7.2).

This is also the gateway to **inverter applications** in
MagnaDesign — every motor drive output choke (DC-AC), every UPS
inverter, every EV-charger AC-side filter is a variant of LCL or
the simpler LC / L. The architecture this change introduces
generalises.

## What changes

A new ``lcl_grid_tie`` topology end-to-end, plus a small
"inverter" infrastructure layer (since the inverter itself isn't
modelled — only its output filter):

```
spec.topology = Literal[..., "lcl_grid_tie"]   # ← new
```

New spec fields:

```python
spec.n_phases: int = 3                # 1 or 3
spec.f_grid_Hz: float = 60.0          # 50 or 60
spec.V_grid_Vrms: float = 400.0       # phase-to-phase for 3φ
spec.f_sw_kHz: float = 20.0           # already exists, but here means
                                       # the inverter PWM frequency
spec.Pout_W: float                    # already exists — inverter rating
spec.modulation: Literal["spwm", "svpwm"] = "svpwm"
spec.target_thd_pct: float = 4.0      # IEEE 1547 cap is 5 %
spec.damping: Literal["passive", "active"] = "passive"
```

The output of the design is a *triple* per phase: ``L_inverter``
(on the inverter side, sees switching ripple), ``C_filter``,
``L_grid`` (on the grid side, sees mostly fundamental).

## Impact

### Domain layer

- **`pfc_inductor/topology/lcl_grid_tie.py`** (new) — the LCL design
  math:
  - Inverter-side inductance from the maximum allowed ripple
    current at ``f_sw``: ``L_inv ≥ V_dc / (8 · ΔI_pp_max · f_sw)``
    (Liserre, Blaabjerg & Hansen — IEEE Trans IA 2005).
  - Filter capacitance from the reactive-power limit: ``C ≤
    0.05 · Pout / (2π · f_grid · V_grid²) × 3`` (3-phase).
  - Grid-side inductance from the attenuation requirement
    at ``f_sw``: ``L_grid = L_inv · r`` where r is the splitting
    ratio (typical 0.10–0.25; smaller reduces grid-side current
    THD but raises resonance frequency).
  - Resonance frequency: ``f_res = (1/2π) ·
    √((L_inv + L_grid) / (L_inv · L_grid · C))``. Constraint:
    ``10 · f_grid < f_res < f_sw / 2``.
  - Passive damping resistor: ``R_d = 1 / (3 · ω_res · C)``
    (one-third of the C's reactance at resonance).
  - Each L's flux density at peak grid current.
  - ``estimate_thd_pct`` returns the predicted grid-current
    THD using the analytical PWM harmonic content (Holmes &
    Lipo) attenuated through the LCL transfer function.
- **`pfc_inductor/topology/lcl_model.py`** (new) — implements the
  ``ConverterModel`` Protocol. Note: this topology has TWO
  inductors per phase, so ``feasibility_envelope`` has to
  validate both. The ``ConverterModel`` Protocol may need to
  return a list of inductor-design-problems instead of a single
  one — see Design doc for details.

### Engine

The engine is **the** big change. Today every pipeline is
"one design → one inductor". For LCL that becomes "one design →
two inductors per phase" (3 phases × 2 inductors = 6 magnetic
parts for a 3-φ inverter).

Two architectural options (Design doc has the full debate):

- **Option A**: Engine returns a list of ``DesignResult`` objects,
  one per inductor; the UI renders a tabbed view.
- **Option B**: New ``MultiInductorDesignResult`` wrapper with
  ``primary: DesignResult``, ``secondary: DesignResult``; UI
  renders both side-by-side.

**Decision (this proposal)**: Option B for v1 — backwards
compatible (today's single-inductor flow keeps the same
``DesignResult`` type; LCL adds a new wrapper). Future flyback
already has a similar problem (primary + secondary winding) so
the wrapper unifies both.

### Optimizer

- LCL designs are 2-D in the magnetics catalog: for each phase
  we pick (mat × core × wire) for ``L_inv`` AND (mat × core ×
  wire) for ``L_grid``. The cascade Tier-0/1 has to handle this.
- Heuristic: optimise the inverter-side first (higher current
  ripple, more constrained), then the grid-side using the
  inverter's reflected current. Greedy is good enough; v2 can
  do joint optimisation.

### UI

- **Topology picker** — add an "LCL Grid-Tie Filter (1φ / 3φ)" card.
- **Schematic** — schematic widget gets a new renderer that
  shows the inverter side, the LCL, and the grid. Two highlighted
  inductors. Filter capacitor in shunt. Ground reference shown.
- **Spec panel** — show ``f_grid_Hz``, ``V_grid_Vrms``,
  ``modulation``, ``target_thd_pct``, ``damping``. Hide the AC-
  PFC fields.
- **Análise card** — needs to render the **filter transfer
  function** (Bode plot magnitude + phase) which is *the*
  signature of an LCL design. Add a new card or repurpose the
  spectrum bottom subplot for this topology.
- **Núcleo selection page** — needs to show *two* core selections
  (one per inductor) instead of one.
- **Realistic waveforms** — synthesise grid current (mostly
  sinusoidal, small ripple) and inverter current (high ripple,
  PWM band visible).

### Reports

- HTML datasheet has *two* magnetic-component sections (one per
  inductor). Spec pages stay shared.
- BOM expands: 2 cores + 2 wires per phase × 3 phases = 12 rows
  for a 3-φ inverter.
- New section: "**Filter transfer function**" — Bode plot of the
  L-C-L network from inverter switching node to grid current,
  with the resonance peak called out.
- Compliance report: IEEE 1547 / IEC 61727 / IEC 62109
  per-harmonic limits with the design's predicted emissions
  overlaid; pass/fail per harmonic up to h=50.

### Standards

- **`pfc_inductor/standards/ieee_1547.py`** (new) — Table 4 of
  IEEE 1547-2018 (current harmonic limits at the PCC).
- **`pfc_inductor/standards/iec_61727.py`** (new) — equivalent
  for the European-grid market.
- **`pfc_inductor/standards/iec_62109.py`** (new) — PV-inverter-
  specific safety limits (focused on isolation + leakage current,
  not THD; checklist-style for v1).

### Catalogs

- LCL inductors at higher power (>10 kW) are usually wound on
  iron-powder or amorphous metal cores (the latter for high-
  efficiency installations). Verify the existing material DB has:
  - **Iron powder** ('-26', '-52' Micrometals): yes.
  - **Amorphous metal** (Metglas 2605SA1): NO — would need a
    catalog import. Out of scope for this change; v1 uses the
    existing materials and notes amorphous as a future addition.
- Cores: at high power (10–100 kW), inductors are often
  custom-wound on a stack of toroids or a U-core. The existing
  catalog has the toroid family well-covered; gap insertion for
  ferrite EE/UU cores at this power is essential and supported.

### Tests

- Benchmark: SunGrow 30 kW commercial PV inverter (open-source
  parameters published by NREL). Verify the design hits the
  published L_inv / C / L_grid values within ±15 %.
- IEEE 1547 compliance: design 1 kW solar microinverter,
  inject the analytical PWM harmonic content, predict grid-side
  THD, compare to IEEE 1547 limits.
- Resonance-frequency placement: f_res lands in the
  [10·f_grid, f_sw/2] window for every benchmark spec.

### Docs

- New `docs/topology-lcl-grid-tie.md` — design method writeup
  + standards references + worked example.
- `README.md` — Topologies table.
- `docs/POSITIONING.md` — LCL row.

## Non-goals

- Not modelling the **inverter itself** (DC-AC switching stage)
  — only the output filter. Future ``add-inverter-stage`` change
  could model the modulator and emit per-harmonic injection
  currents directly instead of the analytical Holmes-Lipo formulas.
- Not modelling **active damping** — v1 supports passive (R_d
  in series with C). Active damping requires control-loop
  modelling that's outside the design tool's scope. Spec field
  exists but evaluating to "user provides damping" for active.
- Not modelling **single-phase grid-tie** — v1 is 3-phase only.
  Single-phase will land as a follow-on (the math is a subset).
- Not modelling **EMI conducted emissions** — IEC 62109 has a
  whole separate EMI section that needs a different filter
  (CMC + DM). Out of scope for v1.

## Risk

High. The change introduces three new architectural concepts at
once:

- **Multi-inductor designs** (the wrapper type).
- **Standards compliance as a design constraint** (instead of
  output report).
- **Filter transfer-function analysis** (frequency-domain visual
  on the Análise card).

Mitigation: ship behind a feature flag (``MAGNADESIGN_ENABLE_LCL=1``)
for the first release, get internal validation with at least two
real designs, then promote to default in v0.2. Each architectural
piece (multi-inductor wrapper, standards constraint, transfer-
function visual) has its own unit-test suite so regressions
surface quickly.
