# Tasks — Procedural topology schematic widget

## 1. Primitive DSL

- [ ] 1.1 `ui/widgets/schematic.py::SchematicPainter`
      - Wraps a `QPainter` with helpers that take logical (mm-like)
        coordinates and translate to pixels via the widget's bounding
        box.
      - Default pen width 1.5 px (scales with DPR), default line
        colour `palette.text_secondary`.
- [ ] 1.2 Primitives:
      - `wire(p1, p2)` — straight line.
      - `corner(p, "elbow")` — T or L junction with dot when 3+ wires
        meet.
      - `inductor(p, orientation, *, highlighted=True)` — 4 humps,
        `palette.accent` when highlighted, glow rect 8 px around the
        bounding box.
      - `diode(p, orient)` — triangle + bar, anode/cathode label
        optional.
      - `bridge_4_diode(p, *, label="BR")` — 4 diodes in the standard
        Graetz configuration with input AC nodes and DC ± output
        nodes.
      - `transistor_mosfet(p, orient, *, label="Q1")` — symbol with
        gate/drain/source nodes.
      - `capacitor(p, orient, *, label="C", polarised=True)` — flat
        plate + curve (or two plates if non-polarised).
      - `voltage_source_ac(p, *, label="Vac")` — circle with sine
        glyph.
      - `dc_bus(p1, p2, label="+VDC")` — heavier line with label.
      - `text_label(p, text, weight=400)` — uses
        `Typography.ui_family_brand`.
- [ ] 1.3 Coordinate system: logical units in [0, 1000] × [0, 250].
      Topologies place components on a fixed grid (50-px steps).

## 2. Topology renderers

- [ ] 2.1 `_render_boost_ccm(painter)`:
      - Vac → bridge → Lboost (highlighted) → Q1 + D → Cbus → load.
      - Labels: "230 Vac", "BR", "L", "Q1", "D", "C_bus", "+VDC".
- [ ] 2.2 `_render_passive_choke(painter)`:
      - Vac → bridge → Lchoke (highlighted) → Cbus → load.
      - Labels: "230 Vac", "BR", "L", "C_bus", "+VDC".
- [ ] 2.3 `_render_line_reactor_1ph(painter)`:
      - Vac → Lreactor (highlighted, on AC side) → bridge → Cbus →
        load.
      - Labels: "230 Vac", "L", "BR", "C_bus", "+VDC".
- [ ] 2.4 `_render_line_reactor_3ph(painter)`:
      - 3-phase mains (L1/L2/L3) → 3× Lreactor (highlighted) →
        6-pulse bridge → Cbus → load.
      - Labels: "L1/L2/L3", "L_a, L_b, L_c", "BR", "C_bus", "+VDC".
      - This canvas is the densest — increase logical width to 1000
        and rely on horizontal compression of node spacing.

## 3. Widget plumbing

- [ ] 3.1 `TopologySchematicWidget(QWidget)`
      - `set_topology(name)` stores the name and calls `update()`.
      - `paintEvent`: builds the `SchematicPainter` and dispatches to
        the right `_render_*` function.
      - Uses `QPainter.setRenderHint(Antialiasing | TextAntialiasing)`.
      - Subscribes to `theme_changed` to repaint with new colours
        when the user toggles light/dark.
- [ ] 3.2 Min height 140 px, expanding width up to 600 px.
- [ ] 3.3 No interactivity (clicking does nothing in this iteration);
      the surrounding card has the "Alterar Topologia" CTA.

## 4. Theme integration

- [ ] 4.1 The schematic respects the active theme's
      `palette.text_secondary` (neutral lines), `palette.accent`
      (inductor highlight), `palette.text` (labels).
- [ ] 4.2 The glow effect around the inductor uses
      `palette.accent_subtle_bg` with 50 % alpha, drawn before the
      inductor primitive.

## 5. Tests

- [ ] 5.1 `tests/test_schematic_widget.py`:
      - For each of the 4 topology names, instantiate the widget,
        set the topology, render to a `QPixmap` of (600, 140),
        assert non-zero non-background pixels exist.
      - Sample the pixel at the centre of the inductor bounding box
        and assert it is within ±10 of `palette.accent` RGB.
- [ ] 5.2 `tests/test_schematic_dpr.py`:
      - Render at DPR 1.0 and 2.0; assert the 2.0 pixmap is 4× the
        pixel count and that line antialiasing is present.
- [ ] 5.3 `tests/test_schematic_theme_change.py`:
      - Render once in light, change to dark, render again; assert
        line colour pixel changes in the expected direction (lighter
        in dark theme).

## 6. Integration

- [ ] 6.1 Wire `TopologiaCard` (from `refactor-ui-dashboard-cards`)
      to instantiate `TopologySchematicWidget` and call
      `set_topology(spec.topology)` when the card receives an
      `update_from_design` call.
- [ ] 6.2 The "Alterar Topologia" button on the card opens a small
      dialog presenting the 4 topologies as cards (radio-style);
      picking one updates `Spec.topology` and triggers a recalc.
