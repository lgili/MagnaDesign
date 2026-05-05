# FEA Validation Capability — FEMMT delta

## MODIFIED Requirements

### Requirement: FEM availability detection (was: FEMM detection)

The application SHALL detect at startup whether a FEM solver backend is
available, and SHALL prefer FEMMT (Python+ONELAB) over the legacy FEMM
binary when both are present.

#### Scenario: FEMMT installed, FEMM not installed

- **WHEN** the application starts and `import femmt` succeeds
- **THEN** `MainWindow.fea_available` is `True`
- **AND** `active_backend()` returns `"femmt"`
- **AND** the toolbar action label reads "Validar com FEA"
  (no "FEMM" qualifier)

#### Scenario: Both backends available, env var forces FEMM

- **GIVEN** `PFC_FEA_BACKEND=femm` is set
- **WHEN** the application starts
- **THEN** `active_backend()` returns `"femm"`
- **AND** the dialog header reads "Backend: FEMM (legado)"

### Requirement: FEA validation runs on macOS without external binaries

When FEMMT is installed via pip, the FEA validation flow SHALL execute on
macOS, Linux and Windows without requiring the user to install any
operating-system-specific binary.

#### Scenario: macOS user runs validation with FEMMT

- **GIVEN** the user installed `pfc-inductor-designer[fea]` on macOS
- **WHEN** the user clicks "Validar com FEA" on a feasible toroid design
- **THEN** the validation completes within the documented timeout
- **AND** the dialog reports L_FEA, B_pk_FEA, and percent-error
- **AND** no separate binary install was required

## ADDED Requirements

### Requirement: EE/ETD/PQ support via FEMMT

When the active backend is FEMMT, the FEA validation SHALL support
EE, ETD and PQ core shapes in addition to toroidal cores.

#### Scenario: Validate an EE design

- **GIVEN** a feasible boost-CCM design with an EE core and the active
  backend is FEMMT
- **WHEN** the user clicks "Validar com FEA"
- **THEN** the validation completes
- **AND** the L_FEA result is within 10% of the analytic L

### Requirement: Backend setting persisted

The user's chosen FEA backend SHALL be persisted in QSettings and
restored across sessions.

#### Scenario: Switch backend, restart app

- **GIVEN** the user switched the backend setting to "FEMM (legado)"
- **WHEN** the app is restarted
- **THEN** `active_backend()` returns `"femm"` until the user changes it
  again

## REMOVED Requirements

### Requirement: macOS-only Wine warning

The previous proposal documented that FEA validation requires Wine on
macOS. With FEMMT as the default backend, this requirement is removed —
the warning shall not be shown when FEMMT is the active backend.
