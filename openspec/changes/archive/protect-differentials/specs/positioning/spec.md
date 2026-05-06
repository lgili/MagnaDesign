# Positioning Capability

## ADDED Requirements

### Requirement: Documented differential matrix

The repository SHALL contain a single source of truth for our
competitive differentials, kept in `docs/POSITIONING.md`, comparing the
project to at least: FEMMT, OpenMagnetics MAS, AI-mag, Frenetic AI, and
Magnetics Inc Designer.

#### Scenario: Differential matrix is comprehensive

- **WHEN** `docs/POSITIONING.md` is opened
- **THEN** it lists every differential (PFC focus, cost model, Litz
  optimizer, multi-design compare, B–H loop, polished UX, BR vendors)
- **AND** for each differential, it has a row marking which competitor
  has it (✓/✗/⚠)

### Requirement: Architecture decision record exists

The decision to specialise rather than generalise SHALL be captured in
an ADR under `docs/adr/0001-positioning.md` with the standard
context / decision / consequences sections.

#### Scenario: ADR survives audit

- **WHEN** the ADR is reviewed
- **THEN** it explains *why* we chose specialisation over a generic
  magnetics framework
- **AND** it explicitly defers the FEM authority to FEMMT and the data
  schema authority to OpenMagnetics MAS

### Requirement: In-app About dialog with positioning

The application SHALL ship a "Sobre" dialog (accessible via Help menu)
that surfaces the positioning differentials inline for the user.

#### Scenario: User opens About dialog

- **GIVEN** the application is running
- **WHEN** the user picks Help → Sobre
- **THEN** a modal dialog appears showing the app version, a 1-paragraph
  pitch and a small differentials table
- **AND** every differential row corresponds to one in
  `docs/POSITIONING.md` (single source of truth)

### Requirement: Contributor scope guardrails

A `CONTRIBUTING.md` SHALL exist at the repository root with a "When to
say no" rubric so PRs that drift away from our differentials are
declined or scoped down.

#### Scenario: Hypothetical PR proposes generic 3D FEM viewer

- **GIVEN** a PR proposing to replace the analytic engine with full 3D FEM
- **WHEN** the maintainer consults `CONTRIBUTING.md`
- **THEN** the rubric flags the PR as "out of scope" because it trades
  our PFC specialisation for a feature better served by FEMMT
