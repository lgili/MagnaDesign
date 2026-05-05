# UI 3D Viewer

## ADDED Requirements

### Requirement: Canonical view chip group

The system SHALL provide a chip group with four buttons — Frente,
Cima, Lateral, Iso — overlaid on the upper-left of the 3D viewer.
Selecting a chip SHALL animate the camera to the canonical view.
Exactly one chip is active at any time.

#### Scenario: Click "Cima" snaps to top-down

- **GIVEN** the viewer is showing the iso view (Iso chip active)
- **WHEN** the user clicks the "Cima" chip
- **THEN** the camera animates over ~300 ms to look down +Z
- **AND** "Cima" becomes the active chip while "Iso" deactivates
- **AND** the orientation cube reflects the new camera orientation.

### Requirement: Orientation cube widget

The system SHALL render an orientation cube widget in the upper-right
of the 3D viewer showing world-axis colours (X/Y/Z) and labels on
each face. The cube SHALL stay synchronised with the live camera.
Clicking a face SHALL snap the camera to make that face point
toward the viewer.

#### Scenario: Click +Y face snaps to front view

- **GIVEN** the cube renders the +Y face on the right side because
  the camera is in the iso preset
- **WHEN** the user clicks the +Y face
- **THEN** the camera snaps to the front preset (+Y faces the viewer)
- **AND** the chip group updates to highlight "Frente".

### Requirement: Vertical side toolbar with utility actions

The system SHALL render a vertical icon toolbar on the right edge of
the viewer with these buttons in this order: fullscreen, screenshot,
layers, cross-section, measure, settings. Each SHALL emit a
distinct signal.

#### Scenario: Toggle layers menu

- **GIVEN** the side toolbar is rendered
- **WHEN** the user clicks the "layers" icon
- **THEN** a popup opens with three checkboxes — Bobinagem, Bobina,
  Entreferro
- **AND** unchecking "Bobinagem" calls `enable_layer("winding", False)`
- **AND** the winding mesh disappears from the scene without rebuilding
  the core mesh.

### Requirement: Bottom action bar with named operations

The system SHALL render a bottom action bar with four labelled
tertiary buttons — Explodir, Corte, Medidas, Exportar — each
triggering the matching viewer operation.

#### Scenario: "Exportar" lets the user pick a format

- **GIVEN** the user clicks "Exportar"
- **WHEN** the format menu opens
- **THEN** the menu shows PNG, STL, and VRML options
- **AND** picking PNG opens a save dialog and writes a file with
  non-zero size.

### Requirement: Layer toggling does not rebuild the core mesh

The system SHALL toggle individual layers (winding, bobbin, airgap)
by adding or removing the corresponding actor from the renderer
*without* re-running the mesh builders. This keeps the toggle
interaction sub-frame.

#### Scenario: Toggling winding twice is fast and stable

- **GIVEN** the viewer has rendered a complete scene with all layers
- **WHEN** the user toggles the winding layer off and on twice
- **THEN** each toggle takes < 50 ms wall time
- **AND** the core actor is never destroyed and recreated.

### Requirement: Section plane and measurement widgets

The system SHALL provide a clipping plane and a 2-click distance
measurement tool, each toggleable from both the side toolbar and
the bottom action bar (sharing state).

#### Scenario: Section toggled from either control updates the other

- **GIVEN** the section state is off and both controls are unset
- **WHEN** the user clicks the side-toolbar section icon
- **THEN** the section plane appears, the side icon shows active
  state, and the bottom "Corte" button also shows active state.

### Requirement: Camera-change observer drives overlay sync

The system SHALL emit a `camera_changed` signal whenever the user
finishes a mouse interaction with the 3D scene (drag, scroll, or
trackball). The orientation cube and chip group SHALL subscribe to
this signal and update.

#### Scenario: Manual orbit updates the cube

- **GIVEN** the iso chip is active
- **WHEN** the user drags the scene by 45° azimuth
- **THEN** the chip group de-activates "Iso" (no preset matches the
  new camera)
- **AND** the orientation cube redraws to match the new orientation.
