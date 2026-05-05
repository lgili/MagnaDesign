# Design — Circuit simulator export

## Choice of model

For a PFC choke we have:

1. **Linear inductance**: trivial, but throws away rolloff and AC resistance.
2. **Current-dependent inductance L(I)**: captures the soft-saturation
   rolloff, ignores frequency dependence of R.
3. **Frequency- and current-dependent**: full fidelity, but most simulators
   don't natively support both axes.

We pick **option 2 + a constant series R + Rac correction note in the
header**. This is what PSIM's saturable inductor and LTspice's
`E`/`B`-source model both natively support.

## Format-specific shape

| Simulator | Format | Element | Source of nonlinearity |
|-----------|--------|---------|------------------------|
| LTspice   | `.lib` (`.subckt`) | `B`-source `B1 1 2 V=...` | piecewise expression |
| PSIM      | XML fragment | `Saturable Inductor` | (I, λ) table |
| Modelica  | `.mo` package | `Modelica.Magnetic.FluxTubes` | B(H) characteristic |

## Common L(I) export table

For each material+core+N, evaluate at 20 points spanning 0..1.5·I_pk_max.
At each I_dc:
- H_dc = N·I_dc / le
- μ_pct = rolloff(H_dc)
- L_eff = N² · AL · μ_pct
- λ_eff = ∫₀^{I_dc} L(I') dI'  (cumulative trapezoidal)

Both the (I, L) and (I, λ) tables are exported in the header comment so
all three downstream formats can reconstruct what they need.

## Round-trip testing

A "round-trip" test takes our exported file, runs it in the target
simulator (LTspice in batch mode, OpenModelica via `omc`, PSIM
non-interactively if licensed), and checks that the simulated L at the
design operating point matches our `L_actual_uH` within 5%.

This is the strongest correctness guarantee we can offer the user.

## Open questions

- PSIM file format is poorly documented and version-dependent. May need
  to settle for a `.psimsch` fragment that the user pastes in, rather
  than a full project file. Mitigation: short, well-commented snippet.
- Modelica + Magmattec: the `Modelica.Magnetic.FluxTubes` library doesn't
  ship soft-saturation profiles for our specific material families. We
  need to emit a table-driven `MagneticReluctance` model.
