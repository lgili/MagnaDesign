# Design — phase-shifted full-bridge (PSFB) output choke

## System context (what we're modelling — and what we're not)

```
   isolated PSFB transformer    output stage (THIS change models the inductor)
   ┌─────────────────────────┐  ┌────────────────────────────────────────┐
                                                                          │
   primary (Vin / N_pri)        secondary  rectifier   L_out      Cout   Vout
        ───[Q1·Q4]───╲          ┌─[Ds1]──┐                                │
                       T (1:n)  │        ├──── L_out ─────────● ───┬─── ●
        ───[Q2·Q3]───╱          ├─[Ds2]──┘                          │
                                │                                   │
                                ●                                   │
                                                                    │
                                                                  [Cout]
                                                                    │
                                                                  [Rload]
                                                                    │
                                ─────────────────────────────────── ●  (gnd)
   └─────────────────────────┘  └────────────────────────────────────────┘
   USER PROVIDES: Vsec_pk_V       MAGNADESIGN DESIGNS: L_out
```

The PSFB primary side (full-bridge of MOSFETs, transformer, ZVS-tank
inductor) is **out of scope**. The user computes ``Vsec_pk_V = Vin /
N_pri · N_sec`` from the transformer turns ratio they've already
selected and provides it as an input.

## Mathematical model

### Effective switching frequency (the headline trick)

The full-bridge primary alternates polarity every half-period. The
secondary sees a *bipolar* PWM waveform that the rectifier converts
to *unipolar* PWM with twice the fundamental frequency:

```
f_sw_eff = 2 · f_sw_primary
```

A 100 kHz primary makes a 200 kHz output choke. This is the *single*
distinction from a generic buck design.

### Effective duty cycle

The PSFB modulates duty by phase-shifting one leg's gating relative
to the other. The effective duty seen by the secondary is:

```
D_eff = (φ / 180°)        where φ is the inter-leg phase shift in deg
                          and 180° = full output, 0° = no output
```

In practice the ZVS commutation eats some duty (the secondary is
"undefined" during the commutation interval), so:

```
D_eff_max ≈ 0.45    (typical; spec field, user-tunable)
```

The output voltage relates to D_eff:

```
Vout = Vsec_pk · D_eff      (assuming ideal rectifier)
```

For a chosen Vout and minimum Vsec_pk (low line):

```
D_eff_max = Vout / Vsec_pk_min   (must be ≤ 0.45)
```

### Required inductance (buck-style, with f_sw_eff)

```
ΔI_pp = (Vout · (1 − D_eff)) / (L_out · f_sw_eff)
      = (Vout · (1 − D_eff)) / (L_out · 2 · f_sw_primary)
```

Solving for L:

```
L_out_min = (Vout · (1 − D_eff_min)) / (r · Iout · 2 · f_sw_primary)
```

with ``r = ΔI_pp / Iout`` (typical 0.30, same as buck).

The factor of 2 is the headline win vs a single-ended buck at the
same primary fsw — half the inductance for the same ripple.

### Peak / RMS / boundary current

Identical to buck-CCM:

```
I_L_avg = Iout
I_L_pk  = Iout + ΔI_pp / 2
I_L_min = Iout − ΔI_pp / 2
I_L_rms ≈ Iout · √(1 + r²/12)
```

### Saturation criterion (high B at high f)

PSFB output chokes run hot because:
- ``f_sw_eff = 2 · f_sw`` is in the 100–500 kHz range.
- ``ΔB`` per cycle is ``L · ΔI_pp / (N · A_e)``, often 0.05–0.15 T
  zero-to-peak.
- Steinmetz: ``Pv = k · f^α · B^β``, with α ≈ 1.4 and β ≈ 2.6
  for ferrite at this frequency. AC core loss density can hit
  500 mW/cm³ if Bpk_AC isn't kept small.

Engine already integrates iGSE / Steinmetz correctly given the
right ``f_sw_eff`` — the only fix is to feed it the doubled
frequency.

### Output voltage ripple

```
Vout_ripple_pp = ΔI_pp / (8 · Cout · f_sw_eff)
              = ΔI_pp / (8 · Cout · 2 · f_sw_primary)
```

(Standard buck-output-cap formula at the doubled effective fsw.)

## Spec extensions

```python
class Spec(BaseModel):
    topology: Literal[..., "psfb_output_choke"] = "boost_ccm"

    Vsec_pk_V: float = Field(
        ...,
        description=("Secondary-side peak voltage after the rectifier, "
                     "before the output inductor. User computes from "
                     "Vin range and transformer turns ratio."),
    )

    D_max: float = Field(
        0.45,
        description=("Maximum effective duty cycle achievable at the "
                     "secondary. PSFB ZVS commutation eats some duty; "
                     "0.45 is a defensible default; users with tight "
                     "designs may push to 0.48."),
    )

    Vsec_pk_min_V: Optional[float] = None    # for Vin variation
    Vsec_pk_max_V: Optional[float] = None
```

## Topology module

`pfc_inductor/topology/psfb_output_choke.py`:

```python
from pfc_inductor.topology import buck_ccm

def effective_switching_frequency_Hz(spec: Spec) -> float:
    return 2.0 * spec.f_sw_kHz * 1e3

def effective_duty_at_Vsec(spec: Spec, Vsec_pk: float) -> float:
    if Vsec_pk <= 0:
        return 0.0
    return min(spec.Vout_V / Vsec_pk, spec.D_max)

def output_current_A(spec: Spec) -> float:
    if spec.Vout_V <= 0:
        return 0.0
    return spec.Pout_W / spec.Vout_V

def required_inductance_uH(spec: Spec, *, ripple_ratio: float = 0.30) -> float:
    Vsec_pk_min = spec.Vsec_pk_min_V or spec.Vsec_pk_V
    if Vsec_pk_min <= 0 or spec.Vout_V <= 0 or spec.Pout_W <= 0:
        return 0.0
    Iout = output_current_A(spec)
    f_sw_eff = effective_switching_frequency_Hz(spec)
    D_eff_min = effective_duty_at_Vsec(spec, spec.Vsec_pk_max_V or spec.Vsec_pk_V)
    L_H = (spec.Vout_V * (1.0 - D_eff_min) / (ripple_ratio * Iout * f_sw_eff))
    return L_H * 1e6

def peak_inductor_current_A(spec: Spec, L_uH: float) -> float:
    Iout = output_current_A(spec)
    f_sw_eff = effective_switching_frequency_Hz(spec)
    if L_uH <= 0 or f_sw_eff <= 0:
        return Iout
    D = effective_duty_at_Vsec(spec, spec.Vsec_pk_max_V or spec.Vsec_pk_V)
    delta = spec.Vout_V * (1.0 - D) / (L_uH * 1e-6 * f_sw_eff)
    return Iout + 0.5 * delta

def rms_inductor_current_A(spec: Spec, L_uH: float) -> float:
    Iout = output_current_A(spec)
    Ipk = peak_inductor_current_A(spec, L_uH)
    delta = 2.0 * (Ipk - Iout)
    if Iout <= 0:
        return 0.0
    r = delta / Iout
    return Iout * math.sqrt(1.0 + r * r / 12.0)

def waveforms(spec: Spec, L_uH: float, *,
              n_periods: int = 5, n_points: int = 600) -> dict:
    """Sample iL over n_periods of the EFFECTIVE switching cycle."""
    Vsec_pk = spec.Vsec_pk_V
    Iout = output_current_A(spec)
    L_H = L_uH * 1e-6
    f_sw_eff = effective_switching_frequency_Hz(spec)
    T_eff = 1.0 / f_sw_eff
    D = effective_duty_at_Vsec(spec, Vsec_pk)
    delta = (spec.Vout_V * (1.0 - D)) / (L_H * f_sw_eff)
    t = np.linspace(0.0, n_periods * T_eff, n_points)
    phase = (t / T_eff) % 1.0
    on = phase < D
    iL = np.where(
        on,
        Iout - 0.5*delta + delta * (phase / max(D, 1e-9)),
        Iout + 0.5*delta - delta * ((phase - D) / max(1.0 - D, 1e-9)),
    )
    return {"t_s": t, "iL_A": iL, "I_pk_A": Iout + 0.5*delta,
            "I_rms_A": rms_inductor_current_A(spec, L_uH),
            "f_sw_eff_Hz": f_sw_eff, "D_eff": D}

def estimate_thd_pct(spec: Spec) -> float:
    return 0.0   # DC output, no AC harmonic spec applies
```

## ConverterModel adapter

`pfc_inductor/topology/psfb_output_choke_model.py`:

```python
class PSFBOutputChokeModel(ConverterModel):
    def inductor_roles(self) -> list[str]:
        return ["L_out"]

    def state_derivatives(self, t, x, inductor):
        # Same form as buck, but with v_in_eff = Vsec_pk · D and
        # f_sw_eff = 2 · f_sw
        s = self._pwm.state_at(t)   # PWM at f_sw_eff
        v_L = (self._Vsec_pk * self._D - self._Vout) if s else (-self._Vout)
        return np.array([v_L / inductor.L_at(x[0])])
```

## Schematic

`pfc_inductor/ui/widgets/schematic.py::_render_psfb_output_choke`

```
   isolated PSFB primary (greyed)         OUTPUT STAGE (highlighted)
   ┌─────────────────────────┐    ┌───────────────────────────────┐
                                                                   │
        ╱ ╲   transformer      ────[Ds1]──────┐                   │
   PSFB                                       │                   │
   primary╲ ╱   (greyed-out box)──[Ds2]──────┴──[L_out]──●──┬───[Rload]
   stage   T                                              │   │
   (greyed)                                            [Cout] │
                                                          │   │
                                ─────────────────────────●───●
   └─────────────────────────┘    └───────────────────────────────┘
```

The primary block is rendered in ``text_muted`` colour and labelled
"isolated PSFB primary (out of design scope)" so the user knows
they're only spec'ing the output choke. The L_out is highlighted
in accent colour; rectifiers + cap + load in neutral.

## Reports

The HTML datasheet's section 2 (Operating Point & Losses) reads:

```
  Inductor effective frequency:     2 · f_sw_primary  =  200 kHz
  Effective duty (D_eff):           0.42  (Vout / Vsec_pk_min)
  Output ripple:                    Vout_ripple_pp = ΔI_pp / (8·Cout·f_sw_eff)
                                                    = 12.3 mV
```

Section 3's "Performance Curves" replaces the rolloff plot (powder-
PFC concept, n/a here unless powder material is selected) with a
waveform plot at ``2 · f_sw_primary`` and an output-ripple plot
identical to buck-CCM's.

The compliance-report PDF uses the same "Not applicable for DC-input
topology" stance buck-CCM uses for IEC 61000-3-2 / 3-12 / IEEE 519.

## Tests

### Pure-physics

- ``test_effective_frequency_doubles_primary`` — `effective_
  switching_frequency_Hz(spec) == 2 · spec.f_sw_kHz · 1e3`.
- ``test_required_L_halves_vs_buck_at_same_fsw`` — same Vout
  / Iout / r / Vsec_pk: PSFB L is half of buck L (because
  f_sw_eff is double).
- ``test_peak_current_buck_style`` — Iout + half ripple.
- ``test_estimate_thd_returns_zero``.

### Engine integration (`tests/test_design_engine.py`)

- ``test_psfb_1500W_telecom_brick`` — Bel Power 12V/125A
  reference: Vsec_pk = 16 V, Vout = 12 V, Iout = 125 A,
  fsw_primary = 100 kHz, D_eff_max = 0.42, target r = 0.20
  (low ripple). Expected L ~ 1.5 µH on ETD49 ferrite.

### UI

- Picker has 9 options now (existing 4 + buck + flyback + LCL +
  interleaved + PSFB).
- Schematic renders without error.
- Realistic waveform synthesis returns a triangle-on-DC at
  ``2 · f_sw_primary`` (verifiable by FFT first-peak frequency).
- Análise card's harmonic spectrum shows first peak at
  fundamental = ``2 · f_sw``.

## Open questions

1. **Vsec_pk variation** — when the user provides
   ``Vsec_pk_min_V`` and ``Vsec_pk_max_V``, the engine designs
   for D_eff_min (high line, low D, biggest ripple). When only
   ``Vsec_pk_V`` is provided, treat it as both nominal and
   worst-case. **OK**.

2. **Synchronous rectifier** — the secondary in modern PSFB is
   often two FETs (sync rectifier) instead of diodes. Conduction
   loss is meaningful in the loss budget. v1 ignores this
   distinction (treats both branches as ideal); future change
   wires the device-loss model.

3. **Current doubler** — split the secondary into two halves,
   each with its own output inductor. v1 does single-output-
   inductor only; current-doubler is a separate topology.
