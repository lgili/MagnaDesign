# Cross-platform Setup Capability

## ADDED Requirements

### Requirement: One-shot dependency installer for FEA backend

The application SHALL provide a single command that installs and
configures the ONELAB solver and FEMMT configuration on macOS
(Intel + Apple Silicon), Linux x86_64 and Windows x86_64.

#### Scenario: macOS first install

- **GIVEN** a macOS machine with the package installed via
  `pip install pfc-inductor-designer[fea]` and ONELAB not present
- **WHEN** the user runs `pfc-inductor-setup`
- **THEN** ONELAB is downloaded to `~/onelab/`
- **AND** macOS Gatekeeper signing is applied to `getdp`, `gmsh` and
  every bundled dylib
- **AND** `~/.femmt_settings.json` and
  `<site-packages>/femmt/config.json` both contain the ONELAB path
- **AND** the verification step succeeds

#### Scenario: Re-running setup is idempotent

- **GIVEN** ONELAB is already installed and configured
- **WHEN** the user runs `pfc-inductor-setup` again
- **THEN** the installer detects the existing install
- **AND** does not re-download ONELAB
- **AND** exits with status `up-to-date`

#### Scenario: Linux first install

- **GIVEN** a Linux x86_64 machine
- **WHEN** the user runs `pfc-inductor-setup`
- **THEN** ONELAB is downloaded and extracted
- **AND** the codesign step is skipped (macOS-only)
- **AND** FEMMT config files are written

### Requirement: Auto-launch setup dialog when FEA backend is missing

The main window SHALL offer to run the dependency setup the first time
the user opens the app on a machine where the FEA backend is not yet
configured.

#### Scenario: Fresh install opens the app

- **GIVEN** the package is freshly installed and ONELAB is missing
- **WHEN** the user launches the GUI
- **THEN** a setup dialog opens explaining what will be downloaded
- **AND** the user can proceed (runs setup in a worker thread) or
  decline (dialog stays closed for the rest of the session)

### Requirement: Path-with-spaces workaround on macOS

The installer SHALL prepare a `/tmp/femmt` symlink and ensure the
runtime prepends it to `sys.path` whenever the active virtualenv lives
under a path that contains spaces, so that FEMMT's getdp invocations
do not break on whitespace.

#### Scenario: Project lives under a path with spaces

- **GIVEN** the venv lives at
  `~/Documents/02 - Trabalho/indutor/.venv`
- **WHEN** the user runs the FEA validation in the app
- **THEN** the FEMMT solver does not fail with
  "Unable to open file '/Users/.../02.pro'"
