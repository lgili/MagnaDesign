# Design — interleaved boost PFC

## Mathematical model

### Per-phase scaling

Each of the N parallel boost stages carries 1/N of the total
input current. The per-phase derived spec is:

```python
def per_phase_spec(spec: Spec) -> Spec:
    """Returns a spec with Pout/N and topology=boost_ccm so the
    existing engine path can size one of the N inductors."""
    return spec.model_copy(update={
        "topology": "boost_ccm",
        "Pout_W": spec.Pout_W / spec.n_interleave,
        # All other fields unchanged — Vin / Vout / fsw / ripple
        # are the same per phase.
    })
```

The per-phase RMS / peak currents follow:

```
I_in_per_phase_rms  = (Pout / n_interleave) / (Vin · η)
I_in_per_phase_peak = √2 · I_in_per_phase_rms
ΔI_per_phase_pp     = (Vin · D · T_sw) / L_per_phase
```

These are exactly the boost-CCM values evaluated on the per-phase
spec. The engine sizes one inductor for these values.

### Aggregate input ripple (cancellation)

The N per-phase inductors are PWM-driven 360°/N apart. Their
triangular ripple currents sum constructively or destructively
depending on the duty cycle. The closed-form aggregate ripple
(Hwu & Yau, IEEE Trans IA 2008) is:

```
For N phases, duty D, each phase ripple ΔI_phase_pp:

    k         = floor(N · D)
    ΔI_in_pp  = ΔI_phase_pp · (1 − k·D)·(k·D − k + 1) / D
```

At ``D = 1/N, 2/N, …, (N-1)/N`` the cancellation is *complete*:
``ΔI_in_pp = 0``. Real designs sit between these nulls; the worst
case is at ``D = 1/(2N)`` (or ``(2N-1)/(2N)``) where ``ΔI_in_pp ≈
ΔI_phase_pp / N``.

For the report, sweep D over the line cycle and show:
- The peak ``ΔI_in_pp`` over the cycle.
- The RMS ripple current.
- Comparison vs single-phase ``ΔI_phase_pp`` (typically 5–10×
  smaller for N=2).

The fundamental ripple frequency at the input is ``N · f_sw``,
not ``f_sw`` — input-cap selection sees a higher frequency,
making smaller film caps viable.

### Current sharing imbalance

Real inductors have manufacturing tolerance on L_actual
(typically ±5 % to ±10 % for ferrite cores, larger for powder).
If the N inductors don't match, current sharing is unbalanced.
For N=2 inductors with values ``L₁ ≠ L₂``:

```
I_share_ratio = L₂ / (L₁ + L₂)
            ≈  0.5 · (1 ± δL/L)   for small mismatch
```

Worst case: 5 % L mismatch → 2.5 % current imbalance.
Acceptable. Above 10 % L mismatch → > 5 % imbalance →
thermal stress on the heavier-loaded phase. The engine emits
a warning if the chosen core's published tolerance pushes the
design past 5 % expected imbalance.

### Saturation / loss / etc.

Per-phase: identical to single-phase boost-CCM. Aggregate
(reported in the result):

```
P_total = N · P_per_phase
B_pk    = (single-phase value, same)
T_rise  = per-phase value (each inductor is independent)
```

## Spec extensions

```python
class Spec(BaseModel):
    topology: Literal[..., "interleaved_boost_pfc"] = "boost_ccm"

    n_interleave: Literal[2, 3] = Field(
        2,
        description=("Number of parallel boost channels. 2 is the "
                     "industry default for 1.5–3 kW server PSUs; "
                     "3 is used for 3–10 kW EV chargers and AC "
                     "compressor drives."),
    )
```

All other fields (Vin / Vout / Pout / fsw / ripple / thermal /
Bsat margin) are reused from boost-CCM.

## Topology module

`pfc_inductor/topology/interleaved_boost_pfc.py`:

```python
from pfc_inductor.topology import boost_ccm

def per_phase_spec(spec: Spec) -> Spec:
    return spec.model_copy(update={
        "topology": "boost_ccm",
        "Pout_W": spec.Pout_W / spec.n_interleave,
    })

def required_inductance_uH(spec: Spec, Vin_Vrms: float) -> float:
    """Per-phase required L."""
    return boost_ccm.required_inductance_uH(per_phase_spec(spec), Vin_Vrms)

def line_peak_current_A(spec: Spec, Vin_Vrms: float) -> float:
    """Per-phase peak."""
    return boost_ccm.line_peak_current_A(per_phase_spec(spec), Vin_Vrms)

def aggregate_input_ripple_pp(per_phase_pp: float, D: float, N: int) -> float:
    if N <= 1:
        return per_phase_pp
    k = int(N * D)
    return per_phase_pp * (1.0 - k * D) * (k * D - k + 1) / max(D, 1e-9)

def effective_input_ripple_frequency_Hz(f_sw_kHz: float, N: int) -> float:
    return f_sw_kHz * 1e3 * N

def estimate_thd_pct(spec: Spec) -> float:
    """Slightly better than single-phase due to ripple cancellation
    at the input. First-order improvement: divide by √N."""
    base = boost_ccm.estimate_thd_pct(spec)
    return base / max(spec.n_interleave ** 0.5, 1.0)
```

## ConverterModel adapter

`pfc_inductor/topology/interleaved_boost_pfc_model.py`:

```python
class InterleavedBoostPFCModel(ConverterModel):
    def inductor_roles(self) -> list[str]:
        return [f"L{i+1}" for i in range(self._spec.n_interleave)]

    def feasibility_envelope(self, core, material, wire):
        # Identical inductors → run boost-CCM check on per-phase spec
        per_spec = per_phase_spec(self._spec)
        return boost_ccm_model.BoostCCMModel(per_spec).feasibility_envelope(
            core, material, wire
        )

    def steady_state(self, core, material, wire):
        per_spec = per_phase_spec(self._spec)
        per_design = boost_ccm_model.BoostCCMModel(per_spec).steady_state(
            core, material, wire
        )
        # Replicate N times into a multi-inductor result
        return MultiInductorDesignResult(
            inductors={role: per_design for role in self.inductor_roles()},
            topology="interleaved_boost_pfc",
            spec=self._spec,
            aggregate=AggregateMetrics.from_replicated(per_design,
                                                       self._spec.n_interleave),
        )
```

The replication trick keeps the engine code path identical to
boost-CCM while satisfying the multi-inductor wrapper contract.

## Schematic

`pfc_inductor/ui/widgets/schematic.py::_render_interleaved_boost_pfc` —
N parallel boost channels (each with its own L_n, Q_n, D_n) feeding
the common Cbus. PWM gates labelled "G1, G2 (180° offset)" for N=2
and "G1, G2, G3 (120° offset)" for N=3. All N inductors highlighted.

## Análise card extensions

The "wow moment" plot for interleaved PFC: the **input-current
cancellation chart**.

Top axis stacks N + 1 traces:
- ``i_L1(t)``: per-phase 1 (accent colour)
- ``i_L2(t)``: per-phase 2 (accent_violet)
- (N=3 only) ``i_L3(t)``: per-phase 3 (warning colour)
- ``i_in(t) = Σ i_Li(t)``: aggregate (heavy black trace)

The reduced ripple amplitude on the aggregate vs the per-phase
ripples is *visually* the topology's value proposition.

Middle axis: ``v_in_rect(t)`` (same as single-phase).

Bottom axis: harmonic spectrum of the **aggregate** input current.
The spectrum has its first ripple peak at ``N · f_sw`` — visible
at "h = 200" for N=2, fsw=100 (much smaller than the boost-CCM
peak at "h = 100" of a single-phase). This is the FFT proof of
the cancellation.

## Reports

- **Spec rows**: include ``n_interleave``, ``Per-phase Pout``,
  ``Per-phase I_in_rms``, ``Aggregate I_in_rms``.
- **Operating-point rows**: per-phase L_actual, B_pk, P_per_phase,
  T_rise + aggregate ``P_total = N · P_per_phase``.
- **New plot**: input-current cancellation (the chart described
  above).
- **BOM**: the inductor is listed once with ``Quantity = N``. Same
  for the switching FET and rectifier diode.
- **Compliance**: aggregate input current evaluated against IEC
  61000-3-2 / 3-12 / IEEE 519. The reduced THD vs single-phase
  shows up here.

## Tests

### Pure-physics

- ``test_per_phase_scales_pout_correctly`` — N=2 at 1.5 kW gives
  per-phase 750 W; N=3 at 3 kW gives 1 kW.
- ``test_aggregate_ripple_cancels_at_D_eq_one_over_N`` — at D=0.5
  with N=2, aggregate ripple = 0; at D=0.333 with N=3, same.
- ``test_aggregate_ripple_at_worst_case`` — at D=0.25 with N=2
  the ripple is reduced to ≈ 50 % of single-phase.

### Engine integration

- ``test_interleaved_3kW_2phase`` — full engine run; per-phase
  L_actual within ±5 % of analytical; aggregate Pout matches
  spec.
- ``test_interleaved_emits_multi_inductor_result`` —
  ``MultiInductorDesignResult`` with N identical entries.

### Standards

- ``test_iec_61000_3_2_aggregate_better_than_single_phase`` —
  same Pout, N=2 vs N=1 → aggregate THD lower.

## Open questions

1. **N=4 interleaving** — used in some 5–10 kW server PSUs.
   Spec field accepts only 2 or 3 for v1; future change can
   extend to 4.

2. **Phase-shedding at light load** — for high-efficiency
   designs, shed phases when load drops below threshold. v1
   doesn't model this; it's a control-loop feature, not an
   inductor-design one.

3. **Current-sharing imbalance budget** — the report's manufacturing
   note warns about > 5 % expected imbalance. The actual
   tolerance comes from the core's published ``L_tolerance_pct``
   field (already in the catalog, set to 8 % default for ferrite
   and 10 % for powder). v1 surfaces the warning; v2 could
   actively penalise high-tolerance cores in the optimizer.
