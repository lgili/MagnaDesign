# Design — LCL grid-tie filter

## System diagram

```
   +Vdc ──┬──[Q1]─┬──[L_inv]──┬──[L_grid]──● grid (per phase)
          │       │           │
          │      ●            ●
          │       │           │
          │      [Q2]        [C_filter]
          │       │           │
          ├───────┴── pwm     │
          │                   │
   −Vdc ──┴───────────────────● gnd
                                      ↑
                              passive damping
                              R_d in series with C
                              (one branch per phase)
```

Three of these branches in parallel for a 3-phase inverter.

## Mathematical model (per phase)

### Inverter-side inductance

The inverter PWM creates a switching ripple current at every odd
harmonic of ``f_sw / 2`` (for unipolar SPWM) or in characteristic
sidebands around ``f_sw`` (for SVPWM). The dominant component
sits at ``f_sw`` for SVPWM with magnitude ``ΔI_pp_max ≈ Vdc /
(8 · L_inv · f_sw)`` (Holmes-Lipo §6.3, eqs. 6-30 and 6-32).
Solving for ``L_inv``:

```
L_inv ≥ V_dc / (8 · ΔI_pp_max · f_sw)
```

with ``ΔI_pp_max`` chosen as 10–25 % of nominal peak phase
current (typical 15 %).

### Filter capacitance

Constrained by the reactive power the cap pulls from the grid at
the line frequency. IEEE 1547 §4.7.2 says ``Q_filter ≤ 5 % ·
Pout``. For a 3-phase wye:

```
Q_filter = 3 · ω_grid · C · V_phase²
        ≤ 0.05 · Pout
```

So:

```
C ≤ Pout / (60 · π · f_grid · V_phase²)
```

(divide the 3-phase formula by 3 to get the per-phase cap value
when the cap is wye-connected.)

### Grid-side inductance

Picked relative to ``L_inv`` via a splitting ratio ``r =
L_grid / L_inv``:

```
L_grid = r · L_inv,   r ∈ [0.10, 0.25]
```

Smaller ``r`` → tighter grid-side ripple but pushes resonance up
toward ``f_sw`` where it's harder to damp. Common values: 0.20.

### Resonance frequency

```
f_res = (1 / 2π) · √((L_inv + L_grid) / (L_inv · L_grid · C))
```

Required positioning:

```
10 · f_grid  ≤  f_res  ≤  f_sw / 2
```

If the inequality fails, the engine emits an ``infeasible_design``
warning with the current ``f_res`` and the violated boundary.

### Passive damping

A resistor ``R_d`` in series with the filter capacitor damps the
resonance peak. Optimal value (Pena-Alzola, Liserre et al.,
ITS-T 2013):

```
R_d = 1 / (3 · ω_res · C)
```

Damping loss at full load:

```
P_damp = I_d_rms² · R_d
       ≈ (3·V_phase·ω_grid·C)² · R_d / 2     (small for well-sized C)
```

Typically < 0.3 % of Pout.

### Saturation criterion (per inductor)

Same shape as the boost case: ``B_pk < B_sat · (1 − margin)``,
with the right ``I_pk`` for each inductor:

- ``L_inv``: peak current is ``√2 · I_phase_rms +
  ΔI_pp_at_fsw / 2`` (line peak + ripple half).
- ``L_grid``: peak is ``√2 · I_phase_rms``  (ripple is
  attenuated to negligible levels by the L-C-L tank).

### Predicted grid-current THD

The inverter injects PWM-band harmonics at characteristic
frequencies (``m·f_sw ± k·f_grid`` for SVPWM, with magnitude
proportional to ``J_k(m·π/2)``, Bessel function of the first
kind). These are attenuated through the L-C-L transfer function:

```
H_LCL(s) = 1 / (s · L_inv) ·
           1 / (s² · L_grid · C + 1) ·
           (s · C · R_d + 1) / (s · C · (R_d + s · L_grid · C/...))
```

For each PWM harmonic ``h``, evaluate ``|H_LCL(j·2π·h·f)|``.
Multiply by the inverter-side harmonic amplitude (Holmes-Lipo
table). Sum-of-squares of the resulting grid-side amplitudes
gives the THD prediction.

The engine emits both the per-harmonic predictions (for the
compliance plot) and the aggregate THD (for the metric tile).

## Spec extensions

```python
class Spec(BaseModel):
    topology: Literal[..., "lcl_grid_tie"] = "boost_ccm"

    # Existing fields are reused/repurposed for the inverter case.
    n_phases: int = 3                       # 1 or 3
    f_grid_Hz: float = 60.0                 # 50 / 60
    V_grid_Vrms: float = 400.0              # phase-to-phase for 3φ,
                                             # phase-to-neutral for 1φ

    # Inverter side
    Vdc_V: float                            # DC bus
    f_sw_kHz: float = 20.0                  # already exists; means inverter PWM here
    modulation: Literal["spwm", "svpwm"] = "svpwm"

    # Design knobs
    target_thd_pct: float = 4.0             # IEEE 1547 cap is 5 %
    target_ripple_pct_inv: float = 15.0     # ΔI_pp on inverter side
    splitting_ratio: float = 0.20           # L_grid / L_inv
    damping: Literal["passive", "active", "none"] = "passive"

    # Reactive-power constraint
    max_reactive_pct: float = 5.0           # IEEE 1547 §4.7.2
```

## Topology module

`pfc_inductor/topology/lcl_grid_tie.py`:

- ``required_inverter_inductance_uH(spec)`` — from the ripple
  formula.
- ``required_filter_capacitance_uF(spec)`` — from the reactive-
  power limit.
- ``required_grid_inductance_uH(spec, L_inv_uH)`` — from
  splitting ratio.
- ``resonance_frequency_Hz(L_inv_uH, L_grid_uH, C_uF)``.
- ``passive_damping_resistor_ohm(spec, C_uF, f_res_Hz)``.
- ``predict_grid_thd_pct(spec, L_inv_uH, L_grid_uH, C_uF,
  R_damp_ohm)`` — analytical PWM harmonic content × LCL
  transfer function.
- ``filter_transfer_function(L_inv_uH, L_grid_uH, C_uF,
  R_damp_ohm)`` — returns ``(freqs, H_mag, H_phase)`` for the
  Bode plot.
- ``estimate_thd_pct(spec, result)`` — wraps
  ``predict_grid_thd_pct``.

## Multi-inductor design wrapper

This is the architectural change that unblocks LCL (and future
flyback / DAB):

```python
# pfc_inductor/models/result.py
@dataclass
class MultiInductorDesignResult:
    """Wrapper around N independent ``DesignResult``s for topologies
    that need more than one inductor (LCL: 2; flyback: 1 transformer
    that we still treat as a coupled-inductor problem with two
    sub-designs)."""

    inductors: dict[str, DesignResult]    # keyed by role
    topology: str
    spec: Spec
    aggregate: AggregateMetrics            # cross-inductor totals

    # Convenience: legacy single-inductor accessors that surface the
    # "primary" inductor's values for back-compat with existing UI
    # code that reads ``result.L_actual_uH`` etc.
    @property
    def L_actual_uH(self) -> float:
        return self.inductors["L_inv"].L_actual_uH
    # … (forward every legacy field to the primary) …
```

The engine's main entry point ``design()`` is type-narrowed:

```python
def design(spec, core, wire, material) -> DesignResult:    # legacy
def design_multi(spec, cores, wires, materials) -> MultiInductorDesignResult:
    # cores / wires / materials are dicts keyed by the same role
    # ("L_inv", "L_grid", …)
```

The single-inductor path stays as today (no breaking change). The
new ``design_multi`` is opt-in for topologies that need it.

## ConverterModel adapter

`pfc_inductor/topology/lcl_model.py`:

- ``feasibility_envelope`` runs both inductors' viability checks
  and returns ``infeasible`` if either fails. The reasons list
  carries which inductor failed and why.
- ``steady_state`` calls ``design_multi`` and returns the
  wrapped result.
- ``state_derivatives`` is a 2-state ODE (``i_inv``,
  ``v_capacitor``) per phase. The grid-side current ``i_grid``
  is computed from these via the LCL coupling.

## Schematic

`pfc_inductor/ui/widgets/schematic.py::_render_lcl_grid_tie` —
the diagram from the proposal's "System diagram" section, with
both inductors highlighted in accent colour (the "what we're
designing" property), the capacitor and damping resistor in
neutral.

## Análise card extensions

For LCL the FormasOndaCard's bottom subplot becomes a **Bode
plot** of ``H_LCL(f)`` instead of the harmonic-spectrum bar
chart:

- X-axis: log frequency from ``f_grid / 10`` to ``f_sw · 10``.
- Y-axis: magnitude in dB.
- Annotations: ``f_grid``, ``f_res``, ``f_sw``.
- Resonance peak called out with its dB height.

The harmonic spectrum stays available as a third tab inside the
card. Toggle between Bode and spectrum.

## Standards module

- `pfc_inductor/standards/ieee_1547.py`:

```python
# IEEE 1547-2018 Table 4 — current harmonic limits at the PCC.
# Limits expressed as % of full-load fundamental.
LIMITS_PCT = {
    3:   4.0,  5:   4.0,  7:   4.0,  9:   4.0,
    11:  2.0, 13:  2.0, 15:  2.0,
    17:  1.5, 19:  1.5, 21:  1.5,
    23:  0.6, 25:  0.6, 27:  0.6, 29:  0.6,
    31:  0.3, 33:  0.3, 35:  0.3, 37:  0.3, 39:  0.3,
    # Total demand distortion (TDD)
    "TDD": 5.0,
}

def evaluate_compliance(harmonics_A: dict[int, float],
                        I_full_A: float) -> ComplianceResult:
    ...
```

- `pfc_inductor/standards/iec_61727.py` — same shape with the
  IEC limits (slightly different per-harmonic numbers).
- `pfc_inductor/standards/iec_62109.py` — PV-inverter safety
  checklist; v1 emits a "manual review required" badge on the
  compliance report. Full implementation is its own future
  change.

## Reports

- The HTML datasheet's BOM section *expands* to two rows per
  phase × ``n_phases``. Each row has its own (core, wire,
  turns, dimensions) — the report becomes longer.
- New "Filter transfer function" section after the operating-
  point section. Bode plot generated by matplotlib (already a
  dep).
- New "Compliance" page (page 4) with per-harmonic emission
  prediction overlaid on the IEEE 1547 limit. Pass/fail
  badges per harmonic. Aggregate TDD called out at the top.

## Tests

### Benchmarks

- 1 kW microinverter (Enphase IQ8 reference) — closed-form
  L_inv ≈ 280 µH, C ≈ 5 µF, L_grid ≈ 56 µH, R_d ≈ 1 Ω.
- 30 kW utility-scale (NREL DOE Solar PV reference design) —
  L_inv ≈ 50 µH, C ≈ 100 µF, L_grid ≈ 10 µH.

### Compliance

- IEEE 1547 — predicted grid-side THD ≤ 5 % for the benchmark
  designs.
- Per-harmonic — every individual h ≤ table limit.

### Resonance placement

- ``f_res ∈ [10·f_grid, f_sw/2]`` for every benchmark.

### Multi-inductor result

- ``MultiInductorDesignResult`` legacy-field forwards work.
- Existing single-inductor tests still pass.

## Open questions

1. **Single-phase microinverters** — proposal scopes 3-phase
   only. Single-phase is a 1/3 subset of the math; ship 1φ as a
   follow-on after the wrapper architecture lands.

2. **Active damping** — out of scope. Spec field accepts
   ``damping="active"`` but the engine emits a warning and
   skips the damping-loss calculation (assumes zero).

3. **Higher-order filters** — LCLCL, LCLR, etc. are out of
   scope. They're rare in commercial inverters; if needed,
   a follow-on change.
