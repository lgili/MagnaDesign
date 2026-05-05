# Circuit Export Capability

## ADDED Requirements

### Requirement: Export inductor as LTspice subcircuit

The system SHALL emit a `.lib` file containing a 2-pin LTspice `.subckt`
that models the inductor as a current-dependent inductance plus a series
resistance, and that produces an inductance within 5% of the analytic
`L_actual_uH` at the design operating point when simulated.

#### Scenario: Export and verify in LTspice

- **GIVEN** a feasible boost-CCM design with L_actual = 387 µH at I_pk = 14 A
- **WHEN** the user exports to LTspice and runs a transient with a 14 A
  sinusoidal current source at 65 kHz
- **THEN** the simulated v(t)/(di/dt) at the peak yields L within ±5% of
  387 µH

### Requirement: Export inductor as PSIM saturable inductor fragment

The system SHALL emit a PSIM-compatible saturable-inductor element with a
flux-current table that captures the rolloff curve.

#### Scenario: Saturation visible in PSIM

- **GIVEN** the exported PSIM fragment for a Kool Mu 60µ inductor
- **WHEN** the user simulates with a current that exceeds 1.5·I_pk
- **THEN** the inductance in the simulation drops in line with the
  rolloff curve (to <70% of nominal)

### Requirement: Export inductor as Modelica model

The system SHALL emit a Modelica `.mo` package with a single `model` whose
B(H) characteristic table captures the rolloff curve, and that compiles
cleanly under OpenModelica.

#### Scenario: Compile under OpenModelica

- **GIVEN** the exported `PFCInductor.mo` file
- **WHEN** `omc -s PFCInductor.mo` is invoked
- **THEN** the compiler returns no errors
- **AND** the generated model can be instantiated within a connector
  network

### Requirement: Header traceability

Each exported file SHALL include a header comment with the source design
parameters: spec values, chosen core/material/wire, computed N,
L_actual_uH, B_pk, and a timestamp.

#### Scenario: Header content

- **WHEN** the file is opened in a text editor
- **THEN** the first lines contain a comment block listing
  - export timestamp
  - spec (Vin, Vout, P, fsw, ripple%)
  - core part number, vendor, material name
  - wire id, N turns
  - computed L_actual_uH and B_pk_T
