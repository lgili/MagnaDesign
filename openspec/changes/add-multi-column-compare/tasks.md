# Tasks — Multi-column design comparison

## 1. Data model

- [x] 1.1 `compare/__init__.py` with `CompareSlot` dataclass holding
      `(spec, core, wire, material, result)` per column.
- [x] 1.2 `compare/diff.py::categorize(metric_name, leftmost_value,
      this_value)` → returns one of `"better" | "worse" | "neutral"` per
      metric semantic (e.g. lower P_total = better; more sat_margin = better).

## 2. Dialog UI

- [x] 2.1 `ui/compare_dialog.py::CompareDialog(QDialog)` with a horizontal
      `QSplitter` containing 1..4 column widgets.
- [x] 2.2 Per-column widget mimics `ResultPanel` layout but with cell
      colouring on diff vs. column 0.
- [x] 2.3 Toolbar inside dialog: "Add current", "Add from optimizer",
      "Remove", "Apply to spec", "Export HTML", "Export CSV".

## 3. Sources for adding designs

- [x] 3.1 "Add current design": grabs the active `MainWindow` design.
- [x] 3.2 "Add from optimizer": pops a small picker showing top-20 of last
      sweep; user clicks one to add as next column.
- [x] 3.3 Persist the comparison set between dialog opens (in-memory only;
      reset on quit).

## 4. Export

- [x] 4.1 `report/html_compare.py::generate_compare_html(slots, out_path)`
      → reuses single-design template but with N-column tables.
- [x] 4.2 CSV export: one row per metric, one column per slot.

## 5. Wire-up

- [x] 5.1 `MainWindow`: toolbar action "Comparar designs".
- [x] 5.2 `CompareDialog.selection_applied(slot_idx)` signal → applies that
      slot back into the spec panel.

## 6. Testing

- [x] 6.1 Unit test: `categorize("P_total_W", 10.0, 12.0) == "worse"`,
      `categorize("sat_margin_pct", 30, 50) == "better"`.
- [x] 6.2 Render test: build CompareDialog with 3 mock slots, verify
      column count and that diff colours are set.
- [x] 6.3 HTML compare: smoke test that file is generated and contains all
      slot names.
