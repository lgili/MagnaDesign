# UI Design System (v2)

## ADDED Requirements

### Requirement: Sidebar palette is theme-invariant

The system SHALL expose a `SIDEBAR` palette whose colours do not change
between light and dark themes. The sidebar always reads as the dark
navy chrome of the application.

#### Scenario: Theme toggle does not alter the sidebar

- **GIVEN** the user is in light theme and the sidebar background is
  rendered with `SIDEBAR.bg`
- **WHEN** the user switches to dark theme
- **THEN** the sidebar background colour is byte-equal to the prior
  value
- **AND** sidebar text remains readable (contrast ≥ 4.5:1 against
  `SIDEBAR.bg`).

### Requirement: Brand accent pair (primary + violet)

The system SHALL provide both a primary brand accent (`accent`, blue
family) and a supporting brand accent (`accent_violet`) on every
palette, with subtle background and subtle text variants of each.

#### Scenario: Stepper uses violet for active step

- **GIVEN** an 8-step stepper widget rendering on the dashboard header
- **WHEN** the active step is "Núcleo"
- **THEN** that segment's pill background is `palette.accent_violet`
- **AND** the segment label colour is `palette.text_inverse` or a
  white-grade tone with contrast ≥ 4.5:1.

### Requirement: Distinct radii for cards, buttons, and chips

The system SHALL provide `Radius.card = 16`, `Radius.button = 10`,
`Radius.chip = 8` as named tokens, and these tokens SHALL be used by
their respective widget classes.

#### Scenario: Card and button have different radii

- **GIVEN** a `Card` widget rendering its frame
- **AND** a `QPushButton.Primary` rendering inside that card
- **WHEN** both are visible
- **THEN** the card's outer corner radius is exactly 16 px
- **AND** the button's corner radius is exactly 10 px.

### Requirement: Card shadow elevation tokens

The system SHALL define three shadow elevations (`card_shadow_sm`,
`card_shadow_md`, `card_shadow_focus`) as structured records (colour,
blur, x-offset, y-offset) that callers attach via
`QGraphicsDropShadowEffect`. The tokens SHALL be valid in both light
and dark themes (e.g. dark theme uses higher alpha for visibility on
near-black surfaces).

#### Scenario: Hovering a card raises elevation

- **GIVEN** a `Card` widget rendered with `card_shadow_sm`
- **WHEN** the cursor enters the card bounds
- **THEN** the effect's parameters update to `card_shadow_md`
- **AND** the transition completes within 150 ms.

### Requirement: Dashboard density spacing scale

The system SHALL provide `Spacing.page = 24`, `Spacing.card_pad = 20`,
`Spacing.card_gap = 16`, and `Spacing.section = 32` tokens, used by
the dashboard layout, card content margins, and inter-section gaps
respectively.

#### Scenario: Dashboard grid uses card_gap

- **GIVEN** the dashboard grid layout
- **WHEN** a 3×3 card grid is laid out
- **THEN** the row and column spacing equal `Spacing.card_gap` (16 px).

### Requirement: Inter as primary UI face with full system fallback

The system SHALL set the default UI font family to a stack starting
with Inter Variable / Inter, falling through Apple system, Segoe UI
Variable, and a sans-serif terminator. When Inter is not installed
locally the application SHALL still render at native quality on
macOS, Windows, and major Linux desktops.

#### Scenario: Linux without Inter installed

- **GIVEN** a Linux box without Inter installed
- **WHEN** the application launches
- **THEN** Qt resolves the family to the next available fallback
- **AND** no widget renders with Times Roman or another serif as a
  side-effect.

### Requirement: Lucide icon registry with tinting

The system SHALL provide an `icon(name: str, color: str | None,
size: int)` API that returns a `QIcon` rendered from a bundled SVG
asset. Unknown names SHALL raise `KeyError` with a message listing
available names. When `color` is given, the resulting pixmap SHALL be
tinted to that colour while preserving the source alpha.

#### Scenario: Tinted icon for sidebar text

- **GIVEN** the sidebar wants a "layout-dashboard" icon at 18 px in
  the sidebar text colour
- **WHEN** `icon("layout-dashboard", color=SIDEBAR.text, size=18)`
  is called
- **THEN** a non-null `QIcon` is returned
- **AND** its pixmap's mean RGB is within ±10 of `SIDEBAR.text`.

#### Scenario: Unknown icon name fails loudly

- **GIVEN** a developer typo'd the icon name
- **WHEN** `icon("layout-dahsboard")` is called
- **THEN** `KeyError` is raised
- **AND** the message lists at least 5 of the 40 valid names so the
  fix is obvious.
