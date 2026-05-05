# Add FEA validation via FEMM

## Why

Our analytic model uses anchored Steinmetz + rolloff curve fits + lumped
thermal — all first-order, calibrated against datasheet datapoints. For a
demanding user (Luiz: "precisa ser realmente fiel"), the next confidence
upgrade is a **finite-element cross-check**: take the same core+winding
geometry we already render in 3D, project it to a 2D-axisymmetric FEMM
problem, solve, and report the FEA-derived L, B-peak, and core/copper losses
side-by-side with our analytic numbers.

No commercial competitor (Frenetic, Magnetics Designer, Coilcraft selector)
ships FEMM integration in the same UI. Open source plus FEMM scripting via
`pyfemm` makes it feasible without weeks of work.

## What changes

- Optional FEA pane in the result/plot area: "Validar com FEA" button →
  generates `.fem` file from current design, runs FEMM solver in background,
  parses results, displays:
  - L_FEA vs L_analytic (% error)
  - B_pk distribution map (cross-section heatmap)
  - Eddy-loss density and Cu-loss density per region
- For toroids: 2D axisymmetric problem (cross-section × revolution).
- For EE/ETD/PQ: 2D planar problem (cross-section through the centre column).
- Background runner so the UI stays responsive (1–10 s typical solve).
- Soft dependency: detect FEMM at startup; if missing, hide the button and
  show install instructions in a tooltip.

## Impact

- Affected capabilities: NEW `fea-validation`
- Affected modules: NEW `pfc_inductor/fea/`, NEW `ui/fea_panel.py`,
  `ui/main_window.py` (toolbar action), `ui/plot_panel.py` (new tab).
- New optional dep: `pyfemm` (Linux/macOS via `xfemm`; Windows native FEMM).
- Heaviest single feature in the v2 roadmap; high differentiator.
