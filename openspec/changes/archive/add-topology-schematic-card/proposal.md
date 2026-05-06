# Add procedural topology schematic widget

## Why

The Topologia Selecionada card needs a small inline circuit schematic
showing what is being designed. Today we communicate topology via a
text combobox ("Boost CCM Active" / "Passive Choke" / "Line Reactor
1ph" / "Line Reactor 3ph") — adequate for an engineer who already
knows the field, hostile to a colleague checking a colleague's work.

A fixed PNG asset per topology is the easy choice but loses three
things we want: vector crispness at any DPI, the ability to highlight
the inductor block (the part this app is sizing), and live theme
adaptation (line/text colours that follow light/dark palettes).

A `QPainter`-driven schematic, parameterised by `Topology` enum,
gives all three. The 4 topologies we support are visually simple
enough (≤ 8 components each) that a procedural renderer is faster to
build than to vector-trace by hand.

## What changes

- New `ui/widgets/schematic.py`:
  - `TopologySchematicWidget(QWidget)` taking
    `set_topology(name: Literal["boost_ccm","passive_choke",
    "line_reactor_1ph","line_reactor_3ph"])`.
  - Renders via `QPainter` with theme-aware colours:
    - lines: `palette.text_secondary`
    - inductor (the part we are designing): drawn with
      `palette.accent` and a faint glow rectangle around it
    - other components: `palette.text_secondary`
    - text labels: `palette.text` semibold
  - Vector pattern: a small DSL of primitives — `wire(p1, p2)`,
    `inductor(p, orientation)`, `diode(p, orient)`,
    `transistor_mosfet(p, orient)`, `capacitor(p, orient)`,
    `bridge_4_diode(p)`, `voltage_source_ac(p)`,
    `phase_label(p, "L1")`, `dc_bus(p1, p2, label)`.
  - Each topology has a `_render_<name>(painter)` function building
    its layout from those primitives.
- Topology canvas size: 600×140 px logical, scales via DPR.
- The `TopologiaCard` body uses `TopologySchematicWidget` as its top
  area (~140 px) above the pills row.
- Tests:
  - `tests/test_schematic_widget.py`:
    - `set_topology("boost_ccm")` → paints without QPainter warnings
      in offscreen Qt.
    - All 4 names render successfully.
    - Inductor primitive uses `palette.accent` (pixel sample at the
      inductor centre returns the expected colour ±10).
  - `tests/test_schematic_dpr.py`:
    - Render at 1× and 2× device-pixel-ratio; both produce non-empty
      pixmaps; line widths scale correctly.

## Impact

- **Affected capabilities:** NEW `ui-schematic`.
- **Affected modules:** NEW `ui/widgets/schematic.py`. Used by
  `dashboard/cards/topologia_card.py` (from
  `refactor-ui-dashboard-cards`).
- **Dependencies:** none. Pure PySide6 paint code.
- **Risk:** Low. Bounded scope (4 topologies, fully synthetic
  rendering). The hardest part is keeping the line-art style
  consistent — addressed by the small primitive DSL.
- **Sequencing:** Depends on `refactor-ui-design-system-v2` (theme
  colours). Independent of `refactor-ui-shell`. Used by
  `refactor-ui-dashboard-cards` but does not block its other 8
  cards — TopologiaCard can ship with a placeholder until this
  widget is in.
