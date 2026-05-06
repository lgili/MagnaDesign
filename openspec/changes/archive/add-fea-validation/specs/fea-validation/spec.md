# FEA Validation Capability

## ADDED Requirements

### Requirement: FEMM availability detection

The application SHALL detect at startup whether a FEMM solver is available
on the host system, and expose the result to the UI as a boolean property
on `MainWindow`.

#### Scenario: FEMM is installed

- **WHEN** the application starts and the FEMM binary is on PATH
- **THEN** `MainWindow.fea_available` is `True`
- **AND** the "Validar com FEA" toolbar action is enabled

#### Scenario: FEMM is missing

- **WHEN** the application starts and no FEMM binary is detected
- **THEN** `MainWindow.fea_available` is `False`
- **AND** the "Validar com FEA" action is visible but disabled
- **AND** its tooltip explains how to install FEMM on the current OS

### Requirement: FEA validation of an inductor design

The application SHALL provide a one-click FEA validation that takes the
currently-displayed design and reports analytic-vs-FEA differences for
inductance, peak flux density, core loss, and copper loss.

#### Scenario: Validate a feasible toroid design

- **GIVEN** a feasible boost-CCM design with a toroid core
- **WHEN** the user clicks "Validar com FEA"
- **THEN** an axisymmetric FEMM problem is generated
- **AND** the solver runs in a background thread without blocking the UI
- **AND** within 30 s the FEA tab shows L_FEA, B_pk_FEA, P_core_FEA,
  P_cu_FEA, each annotated with the % difference from the analytic value
- **AND** a B-field heatmap of the cross-section is displayed

#### Scenario: FEMM solver fails

- **WHEN** the FEMM solver returns non-zero or times out
- **THEN** the FEA tab displays the last 50 lines of the solver log
- **AND** the analytic results remain unchanged
- **AND** no exception propagates to the rest of the UI

### Requirement: Material library extension

The system SHALL register any material not present in the FEMM standard
library by emitting a transient material file from our anchored-Steinmetz
coefficients.

#### Scenario: Validate a Magmattec-core design

- **GIVEN** a design using a Magmattec 026 core
- **WHEN** the user runs FEA validation
- **THEN** the FEMM problem registers a new material "Magmattec_026" with
  μ_r, Bsat, and Steinmetz coefficients from the project database
- **AND** the FEA core-loss calculation uses the registered coefficients
