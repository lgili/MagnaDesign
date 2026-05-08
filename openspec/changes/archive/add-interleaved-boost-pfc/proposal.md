# Add interleaved boost PFC (2-phase / 3-phase parallel boost)

## Why

Single-phase boost-CCM PFC is the topology MagnaDesign was born to
serve, and it works well for 200 W – 1.5 kW designs (refrigerator-
compressor inverters, small white goods). Above that power band the
single-phase design hits hard limits:

- **Inductor size** scales linearly with current; at 3 kW with
  Vin=85 V_rms and 30 % ripple the choke needs ~50 µH at ~36 A
  RMS. That's a physically large, heavy core (PQ40 or bigger),
  hard to mount in compact appliances.
- **Switch ratings** at 3 kW – 10 kW push past commodity TO-247
  silicon into expensive SiC or paralleled silicon parts. The
  conduction loss alone makes single-phase boost uneconomic.
- **Input ripple** at the line frequency × the switching
  frequency × the high RMS makes input filter caps very large
  (often electrolytic 470 µF × multiple).

The industry's universal answer is **interleaved boost PFC**:
N parallel boost stages, each carrying ``1/N`` of the total
current, with their PWM gates phase-shifted by ``360°/N``. Three
big wins:

1. **Each phase's inductor is sized for ``Pout/N``** — at 3 kW with
   N=2 each inductor sees 1.5 kW, fitting a PQ32. With N=3 it's
   1 kW per phase → PQ26.
2. **Ripple cancellation** at the *aggregate* input: the fundamental
   switching ripple disappears (the N triangular waveforms sum to a
   higher-order ripple at ``N · f_sw`` with much smaller amplitude).
   Real input filter caps shrink ~5–10× vs single-phase.
3. **Thermal spreading** — each switch / diode / inductor runs at
   ``1/N`` the loss of the equivalent single-phase. Smaller heat
   sinks, lower temperature rise, longer life.

This is the dominant high-power PFC topology in:

- **Server PSUs** (Open Compute Project specs, 80-Plus Titanium):
  2-phase or 3-phase interleaved at 1.5–3 kW.
- **AC residential / light commercial** (3–10 kW): 2-phase
  interleaved is the default.
- **EV chargers** at the grid-side stage (3–22 kW): 2-phase or
  3-phase interleaved boost as the PFC front-end.
- **Bridgeless totem-pole PFC** with interleaving for >5 kW
  designs.

For MagnaDesign this is **the most natural extension** — the math
reuses the existing ``boost_ccm`` topology, just multiplied across
phases with phase-shift logic. The user's compressor-inverter
applications scale into this band when they go from refrigerator
(< 1 kW) to industrial-cooling (3–10 kW) markets.

## What changes

A new ``interleaved_boost_pfc`` topology with a configurable
``n_interleave`` field (2 or 3). Designs **N inductors in parallel**
— same architectural pattern as LCL (multi-inductor result), but
unlike LCL all N are *identical by construction* (the engine sizes
one and replicates).

Spec extends:

```python
spec.topology = Literal[..., "interleaved_boost_pfc"]   # ← new
spec.n_interleave: Literal[2, 3] = 2
```

Everything else (Vin_min/max_Vrms, Vout_V, Pout_W, f_sw_kHz,
ripple_pct, η, T_amb_C, T_max_C, Ku_max, Bsat_margin) is reused
from ``boost_ccm``.

The output is conceptually one design replicated N times. The
engine sizes a single inductor for ``Pout/N`` (and the appropriate
per-phase RMS / peak currents) and the report lists "N identical
inductors per design".

## Impact

### Domain layer

- **`pfc_inductor/topology/interleaved_boost_pfc.py`** (new) — a
  *thin* module that delegates to ``boost_ccm`` after dividing
  the per-phase power:
  - ``per_phase_spec(spec)`` — returns a derived ``Spec`` with
    ``Pout_W / n_interleave`` (and the topology field changed
    to ``boost_ccm`` so the existing engine path takes over).
  - ``aggregate_input_ripple(per_phase_ripple, n_interleave)``
    — applies the analytical ripple-cancellation formula (Hwu &
    Yau, IEEE Trans IA 2008): ``ΔI_in_pp = ΔI_phase_pp ·
    (1 − k·D)·(k·D − k+1) / D``  where ``k = floor(N·D)`` is
    the cancellation order at the current duty.
  - ``effective_input_ripple_frequency`` — ``N · f_sw``.
  - ``estimate_thd_pct(spec)`` — slightly *better* than
    single-phase because the input-side ripple drops; for v1
    we just call ``boost_ccm.estimate_thd_pct(spec) ·
    (1 / √n_interleave)``  as a first-order improvement.
  - ``per_phase_currents(spec)`` — ``Iin_per_phase_rms =
    Iin_total_rms / N``  and ``Iin_per_phase_peak = Iin_total_peak
    / N``.
- **`pfc_inductor/topology/interleaved_boost_pfc_model.py`** (new)
  — implements ``ConverterModel.inductor_roles()`` returning
  ``["L1", "L2", ...]`` with N entries (or ``["L1"]`` only and
  the engine handles replication — see Design doc).
- **`pfc_inductor/models/spec.py`** — Topology Literal +
  ``n_interleave`` field.

### Engine

- **`pfc_inductor/design/engine.py`** — interleaved branch:
  - Compute per-phase spec (``Pout/N``).
  - Run the existing boost-CCM design path on the per-phase
    spec → get a single ``DesignResult``.
  - Replicate N times (same core, same wire, same N turns) into
    a ``MultiInductorDesignResult`` (the wrapper from the LCL
    change).
  - Compute the *aggregate* input ripple using the cancellation
    formula and emit it in the result's ``aggregate`` field.
  - Compute the *aggregate* loss = N × per-phase loss.
- The existing ``MultiInductorDesignResult`` wrapper handles
  the N-inductor case directly. No new architectural piece.

### Optimizer

- The cascade Tier-0/1 design space is **smaller** for interleaved
  than for LCL — all N inductors are identical, so the
  candidate enumeration is the same as boost-CCM with each
  candidate evaluated against per-phase ratings. Just route
  through ``per_phase_spec`` at the top of the cartesian.

### UI

- **Topology picker** — add an "Interleaved Boost PFC (2φ / 3φ)"
  card. Two phases is the default; 3-phase interleaving is a
  spec-side switch.
- **Schematic** — interleaved schematic showing N parallel boost
  channels (each with its own L, switch, diode), all feeding a
  common Cbus + load. Phase-shift hint (PWM signals colour-coded
  per phase).
- **Spec panel** — show ``n_interleave`` (radio: "2 phases" or
  "3 phases"). Reuse all other boost-CCM fields.
- **Análise card** — top trace stacks the N per-phase iL
  waveforms (already 120°-shifted for 3-phase, 180° for 2-phase)
  + the *summed* input current showing the ripple cancellation.
  This is the visual "wow" of interleaved PFC.
- **Núcleo selection page** — the user picks ONE core / wire
  / material; the engine assumes N identical instances.
  Display "× 2" or "× 3" badge on the selected core to hint
  that the BOM lists multiple parts.
- **Resumo strip** — add a "Phases" KPI tile that reads "2× /
  3× interleaved" so the user is reminded that what they're
  designing is per-phase.

### Reports

- **HTML datasheet**:
  - Spec rows include ``n_interleave``, ``Per-phase Pout``,
    ``Per-phase Iin_rms``.
  - Operating point reports per-phase **and** aggregate values.
  - **New plot**: input-current cancellation chart — three
    traces (per-phase iL + summed input current + the dashed
    "what single-phase would look like" reference). Sells the
    interleaved approach in one picture.
  - BOM lists the inductor as "× N" (count + part number) so
    the manufacturing spec can quote correctly.
- **Manufacturing spec** — explicit "N identical inductors;
  match within ±5 % L_actual to keep current sharing balanced".
- **Compliance** — IEC 61000-3-2 / IEEE 519: interleaved boost's
  better input-current shape lets it pass higher-power Class A
  / Class D limits at the same Pout. Aggregate THD is calculated
  from the cancelled input current, not per-phase.

### Standards

- IEC 61000-3-2 / 3-12 / IEEE 519 — same standards module the
  single-phase boost uses. The interleaved engine's *aggregate*
  current is what gets fed to the compliance evaluator.
  Per-phase emissions don't matter (the user doesn't sell a
  single phase).
- New: section in the report explaining the **current-sharing
  imbalance** budget. Real interleaved PFC needs balanced L
  values within ~10 % to share current evenly; >20 % imbalance
  causes one phase to carry most of the load and burn out
  early. The compliance section warns if any single inductor's
  manufacturing tolerance pushes the design past the budget.

### Tests

- **Pure-physics**: 2-phase 1.5 kW interleaved → per-phase
  matches boost-CCM at 750 W. 3-phase 3 kW → per-phase matches
  boost-CCM at 1 kW.
- **Cancellation formula**: at D=0.5 (Vin≈Vout/2) with N=2 the
  fundamental cancels completely; at D=0.33 with N=3 same.
- **Engine integration**: 3 kW 2-phase design at 90/240 V_rms
  range; output L_actual within ±5 % of analytical per-phase.

### Catalogs

- No catalog change. The same materials / cores / wires database
  serves interleaved per-phase. The cascade optimizer's wire
  pre-filter automatically picks the right gauge for the lower
  per-phase RMS.

### Docs

- `README.md` — Topologies table.
- `docs/POSITIONING.md` — interleaved row.
- `docs/topology-interleaved-boost-pfc.md` — design method,
  ripple-cancellation explanation, current-sharing matching
  guidance.
- `docs/UI.md` — interleaved-specific UI notes.

## Non-goals

- Not modelling **2-leg vs 3-leg topology variants** — only the
  symmetric N-phase case where all phases are identical.
- Not modelling **bridgeless totem-pole interleaved** — that's
  its own topology change (totem-pole is bridgeless, requires
  bidirectional switches; the inductor design is the same as
  this change but the rectifier is missing entirely).
- Not modelling **adaptive phase shedding** (drop a phase at
  light load to keep efficiency up) — control-loop concern.
- Not modelling **current-sharing drift** at runtime — only the
  manufacturing-tolerance imbalance budget at design time.

## Risk

Low-medium. The math reuses ``boost_ccm`` cleanly. The main risk
is the **aggregate-vs-per-phase reporting** clarity in the UI — if
users get confused and design for total Pout instead of per-phase,
they'll size the inductor 2× or 3× too big. Mitigated by:

- The Resumo strip's "× 2 / × 3" badge.
- The picker dialog's description: "designs ONE inductor; you
  build N of them".
- The HTML datasheet header stating "Per-phase design (× N
  identical units)".
- A unit test that asserts the per-phase L_required is exactly
  ``boost_ccm.required_inductance_uH`` of ``per_phase_spec(spec)``.
