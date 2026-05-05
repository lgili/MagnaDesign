# Add circuit-simulator export (Modelica / PSIM / LTspice)

## Why

After choosing the inductor, the next step is to verify it inside the full
converter — closed-loop control, EMI, transient response. Today our app
ends at the L value; the user retypes the parameters into PSIM or LTspice
and (more importantly) loses the operating-point fidelity our model
captured: B-bias rolloff, AC resistance at fsw, temperature-dependent Rdc.

Exporting a saturable-inductor subcircuit closes the loop. PSIM and
LTspice are dominant in industry; Modelica covers the open-source side
(OpenModelica, Wolfram SystemModeler). Each requires a different format
but the underlying model is the same: a current-controlled inductance
with L(I) curve and a series resistance.

## What changes

- New module `export/circuit.py` with three emitters:
  - `to_ltspice_subcircuit(design) -> str` — `.subckt` with B-source for
    nonlinear flux, parameterized R + L pieces.
  - `to_psim_xml(design) -> str` — PSIM netlist fragment with their
    saturable inductor model.
  - `to_modelica(design) -> str` — `.mo` Modelica package with our
    inductor as a `Modelica.Magnetic` component.
- Toolbar action "Exportar para simulador" → file dialog with format
  picker (.lib for LTspice, .psimsch for PSIM, .mo for Modelica).
- Each export embeds the L(I) lookup table from our rolloff curve so the
  saturation behaviour is preserved.
- Each export includes a comment header with the source design parameters
  for traceability.

## Impact

- Affected capabilities: NEW `circuit-export`
- Affected modules: NEW `pfc_inductor/export/`, `ui/main_window.py`
  (toolbar action), small additions to `report/html_report.py` (link to
  exported subcircuit alongside).
- No new deps.
- Medium effort. PSIM XML is the trickiest format; Modelica is the most
  faithful; LTspice is simplest and most-used.
