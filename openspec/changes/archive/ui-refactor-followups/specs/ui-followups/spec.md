# UI follow-ups

This change is a backlog of polish items left over from the five v2
UI changes. It introduces no new capability of its own — each item
incrementally improves an existing capability.

The two requirements below are the only ones with user-visible
behaviour worth pinning down with scenarios; everything else in
`tasks.md` is a list of small fixes / docs / tests that need no formal
spec language.

## ADDED Requirements

### Requirement: Núcleo card surfaces ranked candidates with scores

The system SHALL display, inside the Núcleo card, a ranked list of
material / core / wire candidates with a colour-graded score per row.
Filters above the list SHALL allow the user to narrow by curated /
feasible / vendor.

#### Scenario: Apply a different core from the list

- **GIVEN** the Núcleo card shows 30 candidate rows ranked by score
- **WHEN** the user clicks a row whose part-number differs from the
  current selection
- **AND** clicks "Aplicar seleção"
- **THEN** the spec panel's `cmb_core` updates to the picked id
- **AND** the dashboard recomputes; the Resumo card reflects the new
  design.

#### Scenario: Vendor filter narrows visible rows

- **GIVEN** the Núcleo card has 1 020 cores in its model
- **WHEN** the user checks the "Magmattec" vendor filter
- **THEN** the visible row count drops to the count of Magmattec
  cores in the database
- **AND** the score ordering is preserved within the filtered set.

### Requirement: Theme toggle propagates to custom-painted widgets

The system SHALL repaint custom-painted widgets
(`TopologySchematicWidget`, `DonutChart`, 3D viewer overlays) when the
user toggles between light and dark themes — without requiring an
end-to-end design recompute.

#### Scenario: Toggling theme refreshes the schematic

- **GIVEN** the dashboard is rendered in light theme
- **WHEN** the user clicks the sidebar's theme toggle
- **THEN** the topology schematic in the Topologia card repaints
  using the dark palette's `text_secondary` for lines and `accent`
  for the inductor highlight
- **AND** no design recompute happens — the only Qt event is the
  schematic's `paintEvent`.
