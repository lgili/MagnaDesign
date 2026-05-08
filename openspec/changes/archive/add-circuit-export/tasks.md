# Tasks — Circuit-simulator export

## 1. Common L(I) table

- [ ] 1.1 `export/curves.py::L_vs_I_table(material, core, N, I_max,
      n_points=20) -> list[tuple[I_A, L_H]]` — sweeps current 0..I_max,
      applies rolloff at each point, returns (I, L_effective).
- [ ] 1.2 `export/curves.py::flux_vs_current(...)` — same but emits
      (I_A, λ_Wb) where λ = ∫ L(I) dI; some simulators want flux rather
      than inductance.

## 2. LTspice emitter

- [ ] 2.1 `export/ltspice.py::to_subcircuit(design, name="L_PFC") -> str`
      — emits a 2-pin `.subckt` with:
      - a behavioural `B`-source whose `I=` expression interpolates the
        L(I) table
      - a series resistor = Rdc + Rac_avg
      - a header comment block with all design parameters
- [ ] 2.2 Test against LTspice XVII: round-trip the file, run a transient
      with sinusoidal current, verify L matches our analytic L_actual ±5%.

## 3. PSIM emitter

- [ ] 3.1 `export/psim.py::to_psim_fragment(design) -> str` — uses PSIM's
      "Saturable Inductor" element; embeds (I, λ) as `flux-current` table
      pairs in the element's parameters.
- [ ] 3.2 PSIM expects newline-separated `pair: I_A λ_Wb`; verify format.
- [ ] 3.3 Test by importing into PSIM and inspecting the resulting model.

## 4. Modelica emitter

- [ ] 4.1 `export/modelica.py::to_modelica(design, package="PFC") -> str`
      — emits a Modelica package with a single `model PFCInductor` that
      uses `Modelica.Magnetic.FluxTubes.Sources.MagneticPotentialDifference`
      and a piece-wise table for B(H).
- [ ] 4.2 Test in OpenModelica: load, simulate, compare flux at a chosen
      current step.

## 5. UI integration

- [ ] 5.1 Toolbar: action "Exportar para simulador". Opens a small dialog
      asking format (LTspice / PSIM / Modelica).
- [ ] 5.2 File dialog with appropriate extension filter.
- [ ] 5.3 Status bar message on success: "Exportado em <path>".

## 6. HTML report cross-link

- [ ] 6.1 In the HTML report, add a "Modelo para simulação" section with
      a link/anchor to the exported file (or instructions to export).

## 7. Testing

- [ ] 7.1 LTspice test: round-trip; assert subckt header has expected
      parameters; assert L(I) table monotonically decreases with I (sat
      effect).
- [ ] 7.2 PSIM test: parse the emitted XML fragment with our own validator,
      assert flux-current table is monotone.
- [ ] 7.3 Modelica test: emit + run `omc -s` on the file; assert
      no syntax errors.

## 8. Docs

- [ ] 8.1 README: "Export to simulators" with a screenshot of the dialog.
- [ ] 8.2 Per-format note about how to import (LTspice .lib include, PSIM
      element library, OpenModelica package import).
