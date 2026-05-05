# UI Schematic

## ADDED Requirements

### Requirement: Topology schematic widget renders all four supported topologies

The system SHALL provide a `TopologySchematicWidget` that renders a
clear circuit schematic for each of the four supported topologies:
`boost_ccm`, `passive_choke`, `line_reactor_1ph`, `line_reactor_3ph`.
Each schematic SHALL show the AC source(s), bridge, inductor(s), DC
bus capacitor, and the load.

#### Scenario: Boost CCM schematic identifies its inductor

- **GIVEN** the widget has `set_topology("boost_ccm")` called
- **WHEN** it paints
- **THEN** the inductor symbol is drawn between the bridge DC+ output
  and the MOSFET drain
- **AND** the inductor uses `palette.accent` while every other
  component uses `palette.text_secondary`
- **AND** the inductor has a faint highlight rectangle behind it.

#### Scenario: 3-phase line reactor schematic shows three inductors

- **GIVEN** the widget has `set_topology("line_reactor_3ph")` called
- **WHEN** it paints
- **THEN** three inductors appear in series with the L1/L2/L3 phase
  conductors before a 6-pulse bridge.

### Requirement: Schematic adapts to active theme

The system SHALL repaint the schematic when the active theme changes
(light ↔ dark) so that line colours, text, and accent always match
the currently active palette.

#### Scenario: Toggling the theme refreshes the schematic colours

- **GIVEN** the schematic is rendered in the light theme
- **WHEN** the user toggles the theme to dark
- **THEN** the schematic repaints using the dark palette's
  `text_secondary` for lines and `text` for labels
- **AND** the inductor highlight uses the dark palette's `accent`.

### Requirement: Schematic is crisp at all device pixel ratios

The system SHALL render schematics using vector primitives so that
output is sharp at DPR 1.0, 1.5, 2.0, and 3.0 without rasterisation
artefacts.

#### Scenario: Rendering at 2× DPR doubles pixel resolution

- **GIVEN** the widget is on a 2× DPR display
- **WHEN** it paints
- **THEN** lines are drawn at 1.5 logical px (≈ 3 device px) with
  antialiasing
- **AND** the resulting pixmap pixel count is 4× the 1× DPR count.

### Requirement: Inductor primitive is the visual focus

The system SHALL emphasise the inductor block visually — it is the
component this application is designing. The primitive SHALL use the
brand accent colour and a subtle highlight rectangle behind it.

#### Scenario: Pixel sample at inductor centre is the accent colour

- **GIVEN** any of the 4 topologies is active
- **WHEN** the widget renders to a pixmap
- **THEN** the pixel at the inductor bounding-box centre is within
  ±10 of `palette.accent` RGB.
