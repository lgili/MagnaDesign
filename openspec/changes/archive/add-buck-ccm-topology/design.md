# Design — buck-CCM topology

## Mathematical model

### Steady-state averaging (CCM)

A synchronous buck regulator switches the input ``Vin`` onto the
inductor for a fraction ``D`` of each switching period and shorts
the inductor's left terminal to ground for the remainder. With
``η`` losses lumped into the duty:

```
Vout = D · Vin           (ideal CCM, η = 1)
D    = Vout / (Vin · η)  (real-world)
```

Output current ``Iout = Pout / Vout`` is the inductor's average
current. The inductor sees a triangle ripple:

```
v_L(t) = Vin − Vout      during D · T_sw  (switch ON)
v_L(t) = −Vout           during (1−D) · T_sw  (switch OFF)
```

Solving ``L · di/dt = v_L`` over each phase:

```
ΔI_pp = (Vout · (1 − D)) / (L · f_sw)
      = (Vout · (1 − Vout/Vin)) / (L · f_sw)
```

Worst-case ripple lands at ``Vin = Vin_max`` (because ``1 − D`` is
biggest there). The design fixes a target ripple ratio
``r ≡ ΔI_pp / Iout`` (typical 0.30 — Erickson §5.2) and solves
for L:

```
L_min = (Vout · (1 − Vout/Vin_max)) / (r · Iout · f_sw)
```

### Peak / RMS / boundary current

```
I_L_avg = Iout
I_L_pk  = Iout + ΔI_pp / 2
I_L_min = Iout − ΔI_pp / 2

I_L_rms ≈ Iout · √(1 + (r²/12))      (triangle on DC)

I_DCM_boundary = ΔI_pp / 2
```

Operation transitions to **DCM** when ``Iout < ΔI_pp/2`` (the
trough touches zero). The first cut of this change accepts only
operating points that stay in CCM.

### Saturation criterion

Buck inductors store energy at the peak DC current. Flux density:

```
B_pk = (L · I_L_pk) / (N · A_e)
```

The saturation guard is the same shape as for the boost choke
(``B_pk < B_sat · (1 − margin)``) but the ``I_L_pk`` formula uses
the buck-specific expression above, *not* the rectified-line peak
the engine currently uses for boost CCM PFC. That's the single
biggest engine fork.

### Core loss

For buck the inductor sees only the high-frequency triangle ripple
(no line-frequency envelope). Steinmetz integration over one
switching cycle uses ``ΔB = (Vout · (1−D) · T_sw) / (2 · N · A_e)``
(zero-to-peak swing) at frequency ``f_sw``. **No** "Pcore_line"
component — only ``Pcore_ripple`` applies. The loss row in the
report should hide the line-loss column for buck.

### Copper loss

DC component dominates: ``P_Cu_dc = I_L_avg² · R_dc``. The AC
component from the ripple is ``P_Cu_ac = (ΔI_pp/√12)² · R_ac``,
typically < 5 % of DC for reasonable r and short windings.

## Spec extensions

```python
class Spec(BaseModel):
    topology: Literal["boost_ccm", "passive_choke",
                      "line_reactor", "buck_ccm"] = "boost_ccm"

    # ---- DC-input fields (used by buck_ccm and future DC topologies) -
    Vin_dc_V: Optional[float] = Field(
        None,
        description=("DC input voltage. Used when topology is a DC "
                     "converter (buck_ccm). Ignored for AC inputs."),
    )
    # If Vin_dc_min/max are provided they describe the operating
    # range; otherwise Vin_dc_V is treated as both nominal and worst-case.
    Vin_dc_min_V: Optional[float] = None
    Vin_dc_max_V: Optional[float] = None

    # ---- Buck-specific design knob ----------------------------------
    ripple_ratio: Optional[float] = Field(
        0.30,
        description=("Target ΔI_pp / I_out for buck designs. "
                     "0.20–0.40 typical. Smaller values → bigger L, "
                     "smaller Cout. Ignored for non-buck topologies."),
    )
```

The legacy ``ripple_pct`` field stays — it's the boost-CCM ripple
*percentage* (different semantics: percent of peak inductor current,
not percent of average). A model-validator routes the right field
based on topology.

## Topology module

`pfc_inductor/topology/buck_ccm.py`

```python
def required_inductance_uH(spec: Spec, *, ripple_ratio: float = 0.30) -> float:
    """Minimum L to hold ΔI_pp ≤ ripple_ratio · I_out at Vin_max."""
    Vin_max = spec.Vin_dc_max_V or spec.Vin_dc_V or 0.0
    if Vin_max <= 0 or spec.Vout_V <= 0 or spec.Pout_W <= 0:
        return 0.0
    Iout = spec.Pout_W / spec.Vout_V
    f_sw = spec.f_sw_kHz * 1e3
    L_H = (spec.Vout_V * (1.0 - spec.Vout_V / Vin_max)
           / (ripple_ratio * Iout * f_sw))
    return L_H * 1e6


def output_current_A(spec: Spec) -> float:
    if spec.Vout_V <= 0:
        return 0.0
    return spec.Pout_W / spec.Vout_V


def peak_inductor_current_A(spec: Spec, L_uH: float) -> float:
    Iout = output_current_A(spec)
    Vin_max = spec.Vin_dc_max_V or spec.Vin_dc_V or 0.0
    if Vin_max <= 0 or L_uH <= 0:
        return Iout
    delta = ripple_pp_at_Vin(spec, L_uH, Vin_max)
    return Iout + 0.5 * delta


def rms_inductor_current_A(spec: Spec, L_uH: float) -> float:
    Iout = output_current_A(spec)
    Vin_max = spec.Vin_dc_max_V or spec.Vin_dc_V or 0.0
    delta = ripple_pp_at_Vin(spec, L_uH, Vin_max)
    if Iout <= 0:
        return 0.0
    r = delta / Iout
    return Iout * math.sqrt(1.0 + r * r / 12.0)


def ripple_pp_at_Vin(spec: Spec, L_uH: float, Vin: float) -> float:
    if Vin <= 0 or L_uH <= 0 or spec.Vout_V <= 0:
        return 0.0
    f_sw = spec.f_sw_kHz * 1e3
    L_H = L_uH * 1e-6
    return spec.Vout_V * (1.0 - spec.Vout_V / Vin) / (L_H * f_sw)


def waveforms(spec: Spec, L_uH: float, *,
              n_periods: int = 5, n_points: int = 600) -> dict:
    """Sample iL over ``n_periods`` switching cycles at Vin_nom."""
    Vin = spec.Vin_dc_V or spec.Vin_dc_max_V or 0.0
    Iout = output_current_A(spec)
    delta = ripple_pp_at_Vin(spec, L_uH, Vin)
    T_sw = 1.0 / (spec.f_sw_kHz * 1e3)
    D = spec.Vout_V / max(Vin, 1.0)
    t = np.linspace(0.0, n_periods * T_sw, n_points)
    phase = (t / T_sw) % 1.0
    # Triangle: ramp up during D·T_sw, ramp down during (1−D)·T_sw.
    on = phase < D
    iL = np.where(
        on,
        Iout - 0.5*delta + delta * (phase / max(D, 1e-9)),
        Iout + 0.5*delta - delta * ((phase - D) / max(1.0 - D, 1e-9)),
    )
    return {"t_s": t, "iL_A": iL, "I_pk_A": Iout + 0.5*delta,
            "I_rms_A": rms_inductor_current_A(spec, L_uH), "D": D}
```

## ConverterModel adapter

`pfc_inductor/topology/buck_ccm_model.py` — ports the math above
into the ``ConverterModel`` Protocol so the cascade optimizer's
Tier 0/1 paths drop in unchanged. ``state_derivatives`` for Tier 2
implements:

```python
def state_derivatives(t, x, inductor):
    # x[0] = i_L
    s = pwm.state_at(t)               # 1 when ON, 0 when OFF
    v_in = self._Vin                  # constant for buck
    v_L = (v_in - self._Vout) if s else (-self._Vout)
    return np.array([v_L / inductor.L_at(x[0])])
```

## Schematic primitive (UI)

`pfc_inductor/ui/widgets/schematic.py::_render_buck_ccm`

```
       Vin source
       ●━━━━━━━━━━━━━━━━━━━┑
                            │
                          [Q1] (high-side switch)
                            │
       ●━━━━━━━━━━━━━━━━━━━●  (sw node)
                            │
                          [L] (highlighted)
                            │
       ●━━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━●
                            │               │
                          [Cout]          [Rload]
                            │               │
       ●━━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━●  (gnd)
              freewheel diode (or sync FET) D2
              connects sw_node to gnd via [D2]
```

Implemented with the same primitives (``mosfet``, ``diode``,
``capacitor``, ``inductor`` highlighted) used by the existing
boost / passive renderers.

## Reports

The HTML datasheet (`report/datasheet.py`) currently emits four
sections per design:

1. Header + mechanical
2. Operating point + losses + waveforms
3. **Performance curves** — ``rolloff`` (powder cores only) +
   ``waveform`` (iL post-bridge) + ``harmonic_spectrum`` (line
   reactor only).
4. BOM + notes.

For buck:

- Section 3 drops the rolloff plot if the chosen material is a
  ferrite (no DC-bias rolloff curve to show), keeps it if it's
  powder.
- The waveform plot shows iL over 3–5 switching cycles (no line
  envelope to fit).
- The harmonic-spectrum plot becomes an **output-voltage-ripple
  plot** from ``Vout_ripple_pp = ΔI_pp / (8 · Cout · f_sw)`` —
  this is the buck-relevant analogue of the line reactor's IEC
  spectrum.

The spec-rows table and the loss-rows table get topology-aware
labels: "Vin DC" instead of "Vin RMS", "Iout" instead of "I_line_rms",
etc.

## Standards (compliance report)

The compliance-report PDF generator emits a topology-aware
preamble. For ``buck_ccm`` it prints:

> *DC-input topology — IEC 61000-3-2 / 3-12 (line current
> harmonics) and IEEE 519 (PCC harmonics) are not applicable.
> See the EMI section of the system-level compliance report for
> conducted-emissions limits.*

No new standards module is wired in this change.

## Tests

### Unit (`tests/test_topology_buck_ccm.py`)

- `test_required_inductance_matches_textbook` — Vin=12, Vout=3.3,
  Iout=5, fsw=500k, r=0.30 → L ≈ 4 µH (Erickson §5.2 worked
  example).
- `test_peak_current` — DC + half ripple.
- `test_rms_current` — closed-form triangle-on-DC.
- `test_ccm_dcm_boundary` — Iout = ΔI/2 boundary.
- `test_ripple_zero_at_no_load` — ΔI_pp at Iout=0 is the same as
  at full load (ripple is independent of Iout in CCM).

### Cascade integration (`tests/test_buck_ccm_model.py`)

- `test_tier0_envelope_includes_buck` — ``model_for(spec)`` returns
  the buck adapter and ``feasibility_envelope`` runs.
- `test_tier1_steady_state_matches_engine` — same Vin/Vout/Iout
  through both ``design()`` and ``model.steady_state()`` →
  identical L_actual, P_total, B_pk.
- `test_tier2_transient_converges` — short transient simulation
  reaches the engine's predicted average current within 2 %.

### Engine (`tests/test_design_engine.py` extension)

- `test_buck_ccm_design_at_textbook_point` — full engine run at
  the Erickson point; assert L_actual within ±5 % of analytical.
- `test_buck_ccm_high_vin_widens_ripple` — sweep Vin from min to
  max and confirm ΔI_pp grows monotonically.

### UI

- Picker now lists 5 cards.
- Schematic renderer paints buck without raising (same coverage
  the other 4 topologies have).
- Realistic waveform synthesis returns a triangle-on-DC with the
  expected average and ripple.

## Risks & open questions

1. **Sync-FET vs Schottky freewheel** — both implementations exist
   in the wild; conduction loss differs. v1 picks "ideal switch"
   for both branches; downstream change to add device-loss
   modelling is a separate effort.
2. **DCM operation** — explicitly out of scope for v1. The
   feasibility check rejects DCM operating points (returns
   ``"dcm_only"`` reason) so the user sees a clear "design wants
   to enter DCM, not supported" message instead of a silently
   wrong analysis.
3. **Field naming** — ``Vin_dc_V`` reads cleanly but introduces a
   third "Vin" family alongside ``Vin_min_Vrms`` and the
   line-reactor's nominal. The Pydantic model validator renames /
   migrates legacy specs so old ``.pfc`` files keep loading.
