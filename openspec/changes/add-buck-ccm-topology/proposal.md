# Add buck-CCM (synchronous DC-DC step-down) topology

## Why

MagnaDesign today covers three AC-input topologies (boost-CCM PFC,
passive choke, line reactor 1φ/3φ). Every one of them has an AC
envelope and a diode bridge; none of them models a pure DC-in →
DC-out converter. **Buck CCM is the most-used topology in power
electronics, period** — POL regulators, 12 V → 5 V / 3.3 V
automotive supplies, 48 V → 12 V telecom front-ends, EV charger
post-bridge stages, switch-mode adapter primaries. Skipping it
limits the app to the PFC-input niche.

The buck inductor sees a fundamentally different waveform than the
PFC chokes the engine handles today:

- **No AC line envelope** — only the switching-frequency triangle
  ripple riding on a constant DC average.
- **Saturation criterion** is dominated by the *peak* of (Iout +
  ΔI_pp/2), not by the line-frequency RMS or rectified peak.
- **Required inductance** is a different formula:
  ``L = (Vout · (1 − Vout/Vin)) / (ΔI_pp · fsw)``, and the design
  knob is the **ripple ratio** ``r = ΔI_pp / Iout`` (the textbook
  optimum sits at ~0.30, balancing inductor volume against output
  capacitance).
- **Steady-state operating mode** can be CCM or DCM, decided by
  the load and L; the same hardware can run in either mode.

This is also the gateway to every other DC-DC topology — the cards
that follow (flyback, PSFB, interleaved boost, LCL) all reuse the
buck-CCM analysis as a building block.

## What changes

A new ``buck_ccm`` topology end-to-end: spec field, design engine,
feasibility helpers, optimizer, UI (picker + waveform synthesis +
schematic + Análise card), reports, tests and docs. No regression
to the existing 3 topologies — every dispatch site adds a branch,
the existing branches are untouched.

Concretely:

```
spec.topology  =  Literal["boost_ccm",
                          "passive_choke",
                          "line_reactor",
                          "buck_ccm"]      # ← new
```

Plus a new spec field ``Vin_dc_V`` (used only when topology is a DC-
input one) to keep the AC ``Vin_min_Vrms`` semantics clean.

## Impact

### Domain layer

- **`pfc_inductor/topology/buck_ccm.py`** (new) — pure-physics module:
  ``required_inductance_uH(spec, ripple_ratio)``,
  ``peak_inductor_current_A``, ``rms_inductor_current_A``,
  ``duty_cycle``, ``ccm_dcm_boundary_A``, ``waveforms`` (sample iL
  over a few switching periods for the plot panel).
- **`pfc_inductor/topology/buck_ccm_model.py`** (new) — implements
  the existing ``ConverterModel`` Protocol so the cascade
  optimizer's Tier 0/1/2 paths drop in unchanged. Includes
  ``feasibility_envelope``, ``steady_state``, ``state_derivatives``
  (for Tier 2's transient ODE).
- **`pfc_inductor/topology/registry.py`** — register the new model
  under ``"buck_ccm"``.
- **`pfc_inductor/topology/__init__.py`** — re-export the module.
- **`pfc_inductor/models/spec.py`** — extend the ``Topology``
  Literal; add ``Vin_dc_V`` field (default ``None``); validator
  routes ``Vin_dc_V`` for DC topologies and ``Vin_min/max_Vrms``
  for AC ones.
- **`pfc_inductor/optimize/feasibility.py`** —
  ``N_HARD_CAP_BY_TOPOLOGY["buck_ccm"]`` (≈ 200, buck inductors
  rarely need more than that), ``required_L_uH`` and
  ``peak_current_A`` dispatch.
- **`pfc_inductor/design/engine.py`** — main design path branch:
  buck has no rectifier (skip the bridge-loss math), uses
  switch-frequency core loss at Bpk_AC = ΔB·N (no line envelope),
  and reports the duty-cycle range (Vin_min → Vin_max).

### Optimizer

- **`pfc_inductor/optimize/scoring.py`** — score weights tuned for
  buck (low Cu loss matters more than low core loss because the
  ripple is small relative to DC; saturation guard at full load).
- **`pfc_inductor/optimize/cascade/generators.py`** —
  ``viable_wires_for_spec`` already handles arbitrary topology via
  the spec's ``rated_current_A`` helper; extend that helper to
  return ``Pout / Vout`` for buck (DC) instead of the AC formula.

### UI

- **Topology picker** (`ui/dialogs/topology_picker.py`) — add a
  fifth card "Buck CCM (sync DC-DC)" with a clean schematic and
  one-line description. The grid is currently 2×2; bump to 3×2.
- **Schematic widget** (`ui/widgets/schematic.py`) —
  ``_render_buck_ccm`` (Vin source → high-side switch + diode
  freewheel → L → Cout → Rload, ground rail). The inductor's
  the highlighted component as in the other renderers.
- **Spec panel** (`ui/spec_panel.py`) — show ``Vin_dc_V`` only when
  topology is buck_ccm (or future DC topologies). Hide ``Vin_min/
  max/nom_Vrms`` and ``f_line_Hz`` for DC topologies.
- **Realistic waveforms** (`simulate/realistic_waveforms.py`) —
  ``_buck_ccm`` synthesizer: triangle ripple of amplitude
  ``ΔI_pp = Vout·(1−D)·T_sw/L`` riding on constant ``Iout``. No
  envelope; the chart shows ~5 switching periods so the ripple
  is visible.
- **Análise card** — same multi-trace layout we already have, but
  the source-voltage subplot becomes V_sw (switch node) instead
  of V_in_rectified, and the harmonic spectrum is at f_sw, 2·f_sw,
  3·f_sw (not 2·f_line).

### Reports

- **HTML datasheet** (`report/datasheet.py`) — new
  topology-specific page-2 layout: replace the rolloff plot
  (powder-PFC concept) with a duty-cycle vs Vin chart, replace the
  IEC 61000-3-2 harmonic plot (line-side, n/a for DC) with an
  output-voltage-ripple plot derived from ΔI_pp and Cout.
- **Manufacturing spec** — buck inductors are usually toroidal or
  drum-core (DR / open-cell shielded) rather than ETD/EE cores;
  the BOM and assembly notes need a topology-aware preset.

### Standards

- **No new compliance module needed** for buck — there's no line-
  side harmonic spec for a DC input. (If/when EMI conducted-emissions
  comes to the app, that lives in a separate change.) The
  compliance-report PDF generator emits "Not applicable for DC-input
  topology" for the IEC 61000-3-2 / 3-12 / IEEE 519 sections.

### Catalogs

- No catalog change needed — the same materials / cores / wires
  database serves buck designs. The ``viable_wires_for_spec``
  filter automatically picks the right J range from the new
  ``rated_current_A``.

### Tests

- ``tests/test_topology_buck_ccm.py`` — pure-physics unit tests
  (peak / RMS current, required L, CCM/DCM boundary).
- ``tests/test_buck_ccm_model.py`` — Tier-0 / Tier-1 / Tier-2
  cascade integration.
- ``tests/test_design_engine.py`` — extend with one buck design at
  a benchmark operating point (Vin=12V, Vout=3.3V, Iout=5A,
  fsw=500kHz, target 30% ripple). Reference: TI TPS54360 datasheet.
- ``tests/test_realistic_waveforms.py`` — synthesised iL has the
  expected ripple amplitude and DC offset.
- ``tests/test_topology_picker.py`` — picker has 5 options now.

### Docs

- `docs/POSITIONING.md` — add buck to the "what we cover" matrix.
- `README.md` — Topologies table + screenshot.
- `docs/UI.md` — note the spec-panel field-visibility rules for
  DC vs AC topologies.

## Non-goals

- Not modelling the **synchronous switch** body-diode loss —
  buck's freewheel is usually a sync FET, but our loss model
  treats both switch and freewheel as ideal. Adding a real
  conduction-loss model is a separate change.
- Not modelling **DCM operation** in v1 — we accept the spec only
  if CCM is feasible. DCM design is a future enhancement.
- Not modelling the **input filter** (Lin + Cin) for buck — the
  app is an inductor-design tool and the input filter is its own
  problem.

## Risk

Low. The change is additive (new code paths, new branches) and
every existing call site already dispatches on ``spec.topology`` —
the new value just routes to the new module. The biggest risk is
the spec-field validator: introducing ``Vin_dc_V`` and conditionally
hiding the AC fields could regress old saved ``.pfc`` files. Mitigated
by a Pydantic ``model_validator(mode="before")`` that fills
``Vin_dc_V`` from the legacy ``Vin_nom_Vrms`` when it's missing on a
DC topology.
