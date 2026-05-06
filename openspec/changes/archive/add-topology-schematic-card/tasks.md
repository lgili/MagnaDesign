# Tasks — Procedural topology schematic widget

> **Status: shipped.** All four topologies render via `QPainter`
> primitives, the inductor is accent-highlighted with a glow, and the
> Topologia card embeds the widget. The `theme_changed` subscription
> + DPR-specific tests are **deferred to `ui-refactor-followups`**.

## 1. Primitive DSL

- [x] 1.1 `ui/widgets/schematic.py::_SchematicPainter`
      - Wraps a `QPainter` with helpers that take logical
        coordinates and translate to pixels via the widget's
        bounding box.
      - Default pen width 1.5 px, default line colour
        `palette.text_secondary`.
- [x] 1.2 Primitives:
      - `wire(p1, p2)` — straight line.
      - `junction_dot(p, color)` — solid dot at junctions.
      - `inductor(centre, length, *, accent, glow_bg, highlighted)` —
        4 humps, accent-coloured when highlighted, glow rect 8 px
        around the bounding box.
      - `diode(centre, color, label="D")` — triangle + bar.
      - `bridge_4_diode(centre, size, color, label="BR")` — diamond
        with internal cross.
      - `mosfet(centre, color, label="Q1")` — vertical body + gate
        stub.
      - `capacitor(centre, color, label, polarised=True)` — flat /
        curved plate pair.
      - `voltage_source_ac(centre, color, label="Vac")` — circle
        with sine glyph.
      - `dc_bus(p1, p2, color, label="+VDC")` — heavier line with
        label.
      - `text(p, text, color, weight, size, align)` — central text.
- [x] 1.3 Coordinate system: logical units in [0, 1000] × [0, 250].
      Each renderer places components on a coarse 30/40-px grid.

## 2. Topology renderers

- [x] 2.1 `_render_boost_ccm(painter)` — Vac → bridge → L (highlighted)
      → Q1 + D → Cbus → load.
- [x] 2.2 `_render_passive_choke(painter)` — Vac → bridge → L
      (highlighted) → Cbus → load.
- [x] 2.3 `_render_line_reactor_1ph(painter)` — Vac → L (highlighted,
      AC side) → bridge → Cbus → load.
- [x] 2.4 `_render_line_reactor_3ph(painter)` — L1/L2/L3 → 3× L
      (highlighted) → 6-pulse bridge → Cbus → load.

## 3. Widget plumbing

- [x] 3.1 `TopologySchematicWidget(QWidget)`
      - `set_topology(name)` stores the name and calls `update()`.
      - `paintEvent`: builds the `_SchematicPainter` and dispatches
        to the right `_render_*` function.
      - Uses `QPainter.setRenderHint(Antialiasing | TextAntialiasing)`.
- [~] 3.1b Subscribe to a `theme_changed` signal to repaint with
      new colours when the user toggles light/dark.
      _Deferred — paintEvent reads the current palette every frame,
      so a `update()` after a theme change refreshes correctly. A
      Qt-native `theme_changed` signal isn't wired yet (the
      sidebar's theme-toggle handler in MainWindow already triggers
      a recalc which re-paints the dashboard, so users see the
      effect immediately). Tracked in `ui-refactor-followups`._
- [x] 3.2 Min height 140 px, expanding width up to ~180 px tall.
- [x] 3.3 No interactivity inside the schematic itself; the
      surrounding card has the "Alterar Topologia" CTA.

## 4. Theme integration

- [x] 4.1 The schematic respects the active theme's
      `palette.text_secondary` (neutral lines), `palette.accent`
      (inductor highlight), `palette.text` (implicit, via the
      painter's text helper).
- [x] 4.2 The glow effect around the inductor uses
      `palette.accent_subtle_bg` drawn before the inductor primitive.

## 5. Tests

- [x] 5.1 `tests/test_schematic_widget.py`:
      - For each of the 4 topology names, instantiate the widget,
        set the topology, render to a `QPixmap`, assert non-zero
        non-background pixels exist.
      - Sample a pixel near the inductor centre and assert it is
        within colour-distance 60 of `palette.accent`.
      - `set_topology("not_real")` raises `ValueError`.
      - `set_topology("line_reactor")` aliases to `line_reactor_1ph`.
      - `topology_picker_choices()` returns the canonical 4-tuple.
- [~] 5.2 `tests/test_schematic_dpr.py`:
      - Render at DPR 1.0 and 2.0; assert the 2.0 pixmap is 4× the
        pixel count and that line antialiasing is present.
      _Deferred to `ui-refactor-followups` — the existing widget
      test passes at the platform's native DPR, but the explicit
      DPR-comparison fixture is non-trivial to set up offscreen._
- [~] 5.3 `tests/test_schematic_theme_change.py`:
      - Render once in light, change to dark, render again; assert
        line colour pixel changes in the expected direction.
      _Deferred to `ui-refactor-followups`._

## 6. Integration

- [x] 6.1 Wire `TopologiaCard` to instantiate
      `TopologySchematicWidget` and call `set_topology(spec.topology)`
      when the card receives an `update_from_design` call.
- [x] 6.2 The "Alterar Topologia" button on the card opens
      `TopologyPickerDialog` (added in the polish round) presenting
      the 4 topologies; picking one updates the spec panel's combo
      and triggers a recalc.
