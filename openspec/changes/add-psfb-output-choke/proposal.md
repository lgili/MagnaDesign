# Add phase-shifted full-bridge (PSFB) output choke

## Why

The phase-shifted full-bridge is the **dominant high-power isolated
DC-DC topology** in the 1–10 kW band: telecom 48 V rectifiers,
EV-charger isolated stages (when not LLC), industrial battery
chargers, server PSU intermediate-bus stages above the AC-DC PFC.
Every Bel Power, Delta, Vicor, ABB, and Eaton high-power isolated
brick uses some PSFB variant, and 48 V telecom open-frame rectifiers
shipped in tens of millions of units a year run PSFB.

The output choke design problem is *deceptively similar* to a buck
converter but has three traits that make a generic buck design tool
get the answer wrong:

1. **Effective switching frequency is 2 × f_sw**. The full-bridge
   primary alternates polarity every half-period, so the secondary
   sees a square wave at 2·f_sw before the rectifier. The output
   inductor's ripple frequency is therefore *double* the PWM
   frequency of the primary switches — a 100 kHz primary makes a
   200 kHz output choke. This shrinks the inductor 2× vs a naïve
   buck design at the same primary fsw.
2. **Output voltage is variable** (it's an isolated stage with
   feedback regulating Vout against a wide Vin range). The choke
   has to handle the full duty range from D_min (high line) to
   D_max (low line / overload). RMS / peak currents change with
   Vin; the design picks the worst case automatically.
3. **Large DC bias + meaningful ripple** at high f_sw means
   ferrite cores at high B_pk run hot — most PSFB output chokes
   are ferrite gapped (PQ, ETD) but the loss budget is dominated
   by **AC core loss at 2·f_sw with ΔB ≈ 0.1 T**, not by Cu-DC.
   This flips the optimizer's preference: bigger core (lower B
   swing) > thicker wire (lower Cu_DC) for low-loss designs.

The PSFB output choke is also the **first secondary-side inductor**
the engine models — every prior topology has the inductor on the
input side / DC-link side. This unblocks the eventual
``add-current-doubler-rectifier`` and
``add-active-clamp-forward-output-choke`` chains.

## What changes

A new ``psfb_output_choke`` topology covering just the **secondary-
side output inductor**. The primary-side resonant inductor / leakage
is **out of scope** for v1 (it's a separate magnetic design problem
— ZVS-tank inductor design — that warrants its own topology). The
isolation transformer also stays out of scope (the user provides
``Vsec_pk_V`` directly; future change adds transformer-design support).

```
spec.topology = Literal[..., "psfb_output_choke"]   # ← new
```

New spec fields:

```python
spec.Vsec_pk_V: float                 # secondary-side peak voltage
                                       # (after rectifier, before L)
                                       # User computes from Vin / N_pri / N_sec
spec.f_sw_kHz: float                  # primary switching frequency
                                       # output sees 2 · f_sw
spec.D_max: float = 0.45              # max effective duty cycle
                                       # at the secondary (PSFB ZVS
                                       # eats some duty)
spec.Vout_V: float                    # already exists
spec.Iout_A: Optional[float] = None   # output current; if None,
                                       # derived from Pout / Vout
spec.ripple_pct: float = 30.0         # ΔI_pp / Iout
```

The output is a single output choke (one inductor). No multi-inductor
result needed.

## Impact

### Domain layer

- **`pfc_inductor/topology/psfb_output_choke.py`** (new) —
  pure-physics module, leans on ``buck_ccm`` after a frequency
  multiplier and a duty-range adjustment:
  - ``effective_switching_frequency_Hz(spec)`` → ``2 · f_sw_kHz·1e3``.
  - ``required_inductance_uH(spec, ripple_ratio)`` — same buck
    formula but uses ``Vsec_pk · D`` for the inductor "input"
    voltage and ``2 · f_sw`` for the frequency.
  - ``peak_inductor_current_A`` and ``rms_inductor_current_A``
    — same shape as buck.
  - ``effective_duty_range(spec)`` — returns ``(D_min, D_max)``
    given the spec's Vsec_pk + Vout. The Vsec_pk varies with
    Vin (which the user controls externally); D_min hits at
    Vin_max, D_max at Vin_min.
  - ``estimate_thd_pct(spec) → 0.0`` (DC output).
- **`pfc_inductor/topology/psfb_output_choke_model.py`** (new) —
  implements ``ConverterModel``. ``state_derivatives`` is a
  one-state ODE on iL, with ``v_L = Vsec_pk · D − Vout`` during
  ON and ``v_L = −Vout`` during freewheel.

### Engine

- **`pfc_inductor/design/engine.py`** — PSFB branch:
  - Per the spec, run buck-CCM-equivalent design at ``f_sw_eff
    = 2 · f_sw``.
  - Compute B_pk at Iout_pk ≈ Iout + ΔI_pp/2.
  - **Important**: AC core loss dominates because of the high
    f_sw_eff and meaningful ΔB. The engine's existing iGSE /
    Steinmetz integration handles this correctly once
    ``f_sw_eff`` is plumbed through.
  - Skip the PFC-side bridge / harmonic / THD math (no AC
    input).

### Optimizer

- The cascade Tier-0 / Tier-1 paths route through buck-CCM-style
  feasibility checks but with ``f_sw_eff = 2 · f_sw_kHz · 1e3``
  and the PSFB-specific peak-current formula. The wire pre-filter
  uses ``Iout_rms`` (DC output) for the J-band check.

### UI

- **Topology picker** — add a "PSFB output choke (high-power
  isolated DC-DC)" card.
- **Schematic** — show the *secondary side* of a PSFB: the centre-
  tapped winding (or full-wave bridge) → rectifiers → output
  inductor (highlighted) → Cout → Rload. Primary side is a
  greyed-out "isolated AC source" block so the user remembers
  this is *one piece* of a larger system.
- **Spec panel** — show ``Vsec_pk_V``, ``D_max``, ``Iout_A``.
  Reuse ``Vout_V``, ``Pout_W``, ``f_sw_kHz``, ``ripple_pct``.
  Hide the AC-line fields. **New helper**: a "Compute Vsec_pk
  from transformer" mini-dialog that takes Vin range + turns
  ratio and fills ``Vsec_pk_V`` — speeds up specs for users
  who haven't run the transformer math separately.
- **Análise card** — the iL waveform is a buck-style triangle on
  DC at ``2 · f_sw``. The harmonic spectrum sits at ``2 · f_sw,
  4 · f_sw, ...``. The middle-axis "source voltage" trace is
  the secondary-side rectified PWM (square wave at ``2 · f_sw``
  with magnitude ``Vsec_pk · D``).
- **Resumo strip** — add a "f_sw effective" KPI tile reading
  ``"2 · f_sw = 200 kHz"`` so the user is reminded the inductor
  sees double the primary frequency.

### Reports

- HTML datasheet:
  - Spec rows include ``Vsec_pk_V``, ``D_max``, ``f_sw_eff``.
  - Operating-point rows mention "Inductor sees 2 · f_sw =
    {…} kHz" so the loss numbers are intelligible.
  - Performance plot shows iL waveform at ``2 · f_sw`` (a few
    cycles) + output voltage ripple plot derived from
    ``ΔI_pp / (8 · Cout · 2 · f_sw)``.
- Manufacturing spec — PSFB chokes are usually wound on gapped
  ferrite (PQ32, ETD34, ETD39 typical for 1–5 kW). Add a
  preset specifying gap length tolerance (±5 % for 1 % L
  tolerance).
- Compliance — DC-output topology, no IEC 61000-3-2 / IEEE 519
  applicability. Same handling as buck-CCM.

### Standards

- No new module needed. PSFB shares the "DC output → no THD
  standards" stance with buck-CCM.

### Catalogs

- The existing core database covers the gapped-ferrite shapes
  (PQ, ETD, EE) PSFB designs use. Verify ``gap_mm`` is supported
  in the engine's path for these shapes (it is, but the optimizer
  currently doesn't sweep gap length explicitly — that's a
  follow-on for the cascade Tier-2 if PSFB designs reveal it).

### Tests

- ``tests/test_topology_psfb_output_choke.py`` — Bel Power 1.5 kW
  open-source reference (12 V → 5 V, 100 A, 100 kHz primary,
  ETD34). Verify L_actual within ±10 % of analytical.
- ``tests/test_psfb_model.py`` — Tier 0/1/2 cascade.
- ``tests/test_realistic_waveforms.py`` — iL synthesis at
  ``2·f_sw`` with the right DC + ripple.

### Docs

- `docs/POSITIONING.md` — PSFB row.
- `README.md` — Topologies table.
- `docs/topology-psfb-output-choke.md` — design method,
  effective-frequency explanation, secondary-side circuit
  context, transformer-design pointer.

## Non-goals

- **Primary-side ZVS-tank / leakage inductor** — separate topology
  change. The PSFB primary needs an extra inductor (or transformer
  leakage) to enable ZVS commutation; designing that inductor
  has different math (resonant, narrow operating window). v1
  models only the *output* choke.
- **Isolation transformer** — out of scope. User provides
  Vsec_pk_V directly. Future: full-blown PSFB transformer +
  output choke as one design.
- **Current-doubler rectifier** — variant where the secondary
  has TWO output inductors instead of one (popular for very
  high current designs). Future change once we settle this
  proposal.
- **Synchronous rectifier** — replacing the secondary diodes
  with FETs. Loss-model concern; future change.

## Risk

Low. PSFB output choke math is essentially buck-CCM with a
frequency multiplier — the engine already handles every other
piece (Steinmetz at high frequency, gapped ferrite, thermal
iteration). The biggest implementation risk is making the
"effective f_sw = 2 · f_sw" plumbing clean — if any code path
mis-computes the f_sw the inductor will be over- or under-sized
2×. Mitigated by:

- Centralising ``effective_switching_frequency_Hz`` in the
  topology module (single source of truth).
- A unit test that asserts the engine's reported "f_sw_eff" in
  the result matches ``2 · spec.f_sw_kHz``.
- Visual review: the Análise harmonic-spectrum bottom subplot
  must show the first peak at h = 2 · f_sw / fundamental_Hz —
  visible regression if the multiplier is missed.
