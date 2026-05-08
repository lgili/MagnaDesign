# Design — flyback topology

## Mathematical model

### Flyback in DCM (Discontinuous Conduction Mode)

DCM is the textbook starting point — every cycle stores energy in
the primary, then dumps it through the secondary diode and falls
to zero before the next ON pulse. Three phases per period:

1. **ON** (``D · T_sw``): switch closed, primary current ramps
   linearly from 0 to ``I_p_pk = (Vin · D · T_sw) / Lp``.
2. **OFF / demag** (``D₂ · T_sw``): switch open, primary current
   collapses (clamped by RCD snubber + reflected ``n·Vout``);
   secondary diode conducts, secondary current ramps from
   ``I_s_pk = n · I_p_pk`` down to zero.
3. **Idle** (``(1 − D − D₂) · T_sw``): both windings off, zero
   current, switch sees ``Vin`` only (no reflected voltage —
   resonant ringing in QR mode).

Energy balance:

```
E_per_cycle = ½ · Lp · I_p_pk²
Pout        = E_per_cycle · f_sw · η
```

Solving for the primary inductance that limits ``I_p_pk`` to a
target peak (typically 1.5× I_avg at full load):

```
Lp_max = (Vin_min · D_max)² / (2 · Pout · f_sw / η)
       = η · Vin_min² · D_max² / (2 · Pout · f_sw)
```

The duty cycle at full load:

```
D_max = √(2 · Lp · Pout · f_sw / (η · Vin_min²))
```

The demag duty:

```
D₂ = D · Vin / (n · Vout)
```

DCM requires ``D + D₂ < 1`` always (the boundary picks the largest
allowable Lp). At low line and full load, D₂ is largest — pick
that as the design point.

### Flyback in CCM (Continuous Conduction Mode)

In CCM the primary current never falls to zero; both windings
overlap conduction at the boundary. Volt-seconds balance:

```
Vin · D = n · Vout · (1 − D)
⇒  D    = (n · Vout) / (Vin + n · Vout)
```

The ripple ratio determines the operating point relative to the
CCM/DCM boundary:

```
ΔI_p = (Vin · D · T_sw) / Lp
I_p_pk = I_p_avg + ΔI_p / 2
I_s_pk = n · I_p_pk
```

CCM gives lower peak currents than DCM at the same Pout (good for
core saturation and conduction loss) but introduces a right-half-
plane zero in the control loop, which limits compensator bandwidth.
Most modern silicon controllers handle CCM; v1 supports both.

### Reflected voltages

Primary switch off-state stress:

```
V_drain_pk = Vin_max + n · Vout + V_leak_spike
```

The leakage spike is the headline failure mode: ``V_leak_spike =
√(2 · L_leak / C_oss · Vin · I_p_pk)`` worst case, but is
clamped by the RCD snubber to a designer-chosen ``V_clamp =
α · n · Vout`` with ``α ∈ [1.5, 2.5]`` (smaller α → more
snubber loss; larger α → bigger FET).

Secondary diode reverse voltage:

```
V_diode_pk = Vout + Vin_max / n
```

These two stress voltages drive the BOM choice for the FET and
the rectifier diode and are surfaced as KPI tiles in the Análise
card.

### Saturation criterion

Flux density at primary peak current:

```
B_pk = (Lp · I_p_pk) / (Np · A_e)
```

Same shape as the boost / buck inductor formulas, but now ``Np``
is the *primary* turn count, not "the only winding". Fail if
``B_pk > B_sat · (1 − margin)``.

### Window fill (split)

Total window fill ``Ku_total = (Np · A_pri + Ns · A_sec) / W_a``
must be ≤ ``Ku_max``. Engine splits the window: ``Ku_pri = α ·
Ku_max``, ``Ku_sec = (1 − α) · Ku_max`` with ``α ∈ [0.4, 0.55]``
(default 0.45 — sandwich winding). The chosen split affects
leakage inductance (interleaved P-S-P sandwiches reduce L_leak by
~4× vs simple P-S layouts).

### Leakage inductance estimate (empirical)

```
L_leak_pri ≈ Lp · k_layout · (n_layers − 1) / n_layers
```

with ``k_layout ∈ {0.005 (interleaved sandwich), 0.02 (simple
P-S), 0.04 (poorly coupled)}`` calibrated against TI / Würth /
Coilcraft published numbers per shape. v1 ships a lookup table
keyed by core shape + winding strategy.

### Snubber dissipation

```
P_snubber = ½ · L_leak · I_p_pk² · f_sw · (V_clamp / (V_clamp − n · Vout))
```

Surfaced in the loss table. Typically 3–8 % of Pout for well-
designed flybacks, can balloon to 15 %+ with poor coupling.

### Copper loss (both windings)

Primary RMS in DCM (triangular pulse):

```
I_p_rms = I_p_pk · √(D / 3)
```

In CCM:

```
I_p_rms ≈ I_p_avg · √(D · (1 + r²/12))
```

where ``r = ΔI_p / I_p_avg``.

Secondary RMS mirrors the primary scaled by ``n`` and shifted to
the demag duty ``D₂``.

```
P_Cu_pri = I_p_rms² · R_dc_pri + I_p_ac_rms² · R_ac_pri
P_Cu_sec = I_s_rms² · R_dc_sec + I_s_ac_rms² · R_ac_sec
```

### Core loss

Steinmetz on the *AC component* of the flux waveform. In DCM the
primary flux ramps from 0 to ``B_pk`` and back to 0 — that's
``ΔB = B_pk`` per cycle. In CCM the trough is non-zero, so
``ΔB = ΔI_p · Lp / (Np · A_e)``. Always use the AC ΔB in the
Steinmetz formula, never the DC offset.

## Spec extensions

```python
class Spec(BaseModel):
    topology: Literal[..., "flyback"] = "boost_ccm"

    flyback_mode: Literal["dcm", "ccm"] = Field(
        "dcm",
        description=("Design-time operating mode. DCM is simpler "
                     "but has higher peak currents. CCM is lower-"
                     "stress but introduces a RHP zero in control."),
    )
    turns_ratio_n: Optional[float] = Field(
        None,
        description=("Np/Ns. When None, the engine picks the optimal "
                     "ratio that balances primary FET stress against "
                     "secondary rectifier stress (text: V_drain_pk = "
                     "V_diode_pk · n)."),
    )
    Vin_dc_V: float                # required for flyback
    Vin_dc_min_V: Optional[float]
    Vin_dc_max_V: Optional[float]

    # Window-split factor for primary (rest goes to secondary).
    # 0.45 is the textbook default for sandwich windings.
    window_split_primary: float = 0.45
```

## Topology module

`pfc_inductor/topology/flyback.py` exports:

- ``required_primary_inductance_uH(spec)`` — Lp_max for DCM at
  ``Vin_min``, ``D_max ≈ 0.45``.
- ``optimal_turns_ratio(spec)`` — picks ``n`` to equalise FET
  and diode stress: ``n = (V_drain_target − Vin_max) / Vout``.
- ``primary_peak_current(spec, Lp_uH, mode)``.
- ``primary_rms_current(spec, Lp_uH, Ip_pk, mode)``.
- ``secondary_peak_current(spec, Ip_pk, n)``.
- ``secondary_rms_current(spec, Ip_pk, n, mode)``.
- ``leakage_inductance_estimate(core, Np, Ns, layout)``.
- ``snubber_dissipation_W(L_leak, Ip_pk, f_sw, V_clamp, n, Vout)``.
- ``waveforms(spec, Lp_uH, n, mode)`` — sample Ip(t) + Is(t)
  over a few switching periods.
- ``estimate_thd_pct(spec) → 0.0``  (DC input).

## ConverterModel adapter

`pfc_inductor/topology/flyback_model.py` —
``state_derivatives`` is a 2-state ODE (Ip, Is). Switching events
flip between the four phases (ON-rising, OFF-demag, idle in DCM
or continuous overlap in CCM).

## Schematic

`pfc_inductor/ui/widgets/schematic.py::_render_flyback`

```
   Vin_DC source
       ●──────────────────────●  (drain rail)
                              │
                          [Lp]   ⟂   [Ls]      (highlighted, dot
                              │   ║      │     convention shown)
                              │  core   │
                          ●───┘   ⟂   └───●
                          │              │
                        [Q1]            [D]
                          │              │
                          │              ●──[Cout]──●──[Rload]──●
                          │              │           │           │
                          ●──────────────●           ●───────────●
                          (gnd primary)              (gnd secondary)
        [RCD snubber across primary winding]
```

The ``inductor`` primitive paints two highlighted coil symbols
side-by-side with a small "core" frame around them so the coupled-
inductor identity reads at a glance.

## Reports

- The Análise tab's ``FormasOndaCard`` stacks Ip(t) + Is(t) on the
  top axis (overlay with two colours), the v_drain(t) on the
  middle axis, and the Ip FFT on the bottom (since secondary is a
  scaled copy, one spectrum is enough).
- The HTML datasheet's BOM expands to list both wires and the
  snubber components.
- The compliance-report PDF gets a new "Isolation" section
  (creepage / clearance checklist).

## Standards (deferred to follow-on changes)

This change ships a *checklist-only* isolation section. The full
IEC 62368 reinforced-insulation calculation (working voltage, peak
voltage, pollution degree, material group) is its own module and a
later change. v1 surfaces the *inputs* the user needs to enter
(reinforced or basic, working voltage, environment) but doesn't
*compute* the required clearance — it just shows the checklist.

## Open questions

1. **Default DCM-vs-CCM** — proposal defaults to DCM (simpler,
   widest controller compatibility). User flips via spec field.
   OK?

2. **Auxiliary bias winding** — many flybacks use a third winding
   for the controller's bias supply. v1 ignores it (the spec
   doesn't require it; users add it manually in the BOM). v2 adds
   first-class support.

3. **Window split default** — 0.45 for primary is conservative
   (heavier winding gets more room). Some users prefer
   ``α = 0.5`` (symmetric). Make ``window_split_primary`` a
   user-tunable field with sensible bounds [0.30, 0.65]. **Yes,
   exposed in the spec drawer's "advanced" section.**
