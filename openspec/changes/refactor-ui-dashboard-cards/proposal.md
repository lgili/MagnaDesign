# Refactor dashboard layout to a 9-card grid

## Why

Today the design data is split across three columns (`SpecPanel` |
`PlotPanel` | `ResultPanel`) inside a `QSplitter`. Information is *there*
but the user has to scan a wall of `QFormLayout` rows to find any single
fact. This is the core complaint behind the user's "esqueleto com várias
coisas separadas" diagnosis.

The MagnaDesign mock fixes this by *contextualising* each piece of
information inside a Card with a clear job:

- **Topologia Selecionada** — what we are designing (schematic + key
  pills + change-topology CTA). Lifted from the topology selector at
  the top of `SpecPanel`.
- **Resumo do Projeto** — six headline metrics + a green "Aprovado"
  status. Lifted from `ResultPanel` operational group.
- **Formas de Onda** — current waveform + four time-domain metrics.
  Lifted from `PlotPanel` waveform tab.
- **Seleção de Núcleo** — searchable / filtered table with a score
  pill column. Lifted from the material/core/wire combos.
- **Visualização 3D** — the existing 3D viewer, now embedded as a
  card with view-mode + action controls (controls themselves are
  scoped to `refactor-3d-viewer-controls`).
- **Perdas** — donut chart of P_dc / P_ac / P_core. Lifted from
  `PlotPanel` losses bar (re-rendered as donut for density).
- **Bobinamento** — compact data table (turns, layers, fill, AWG,
  diameter, length, mass). Lifted from `ResultPanel` window group.
- **Entreferro** — three metrics (`A_L`, `μ_eff`, `H_peak`). Lifted
  from `ResultPanel` flux group.
- **Próximos Passos** — action items with semantic icons (e.g.
  "Validar com FEM", "Selecionar fornecedor", "Gerar relatório").

Cards have visual hierarchy (16 px radius, subtle shadow, clear title)
and let the user *triangulate* — if losses look high, perdas card is
right next to bobinamento and entreferro for context.

## What changes

- New `ui/widgets/` package:
  - `card.py` — `Card(title: str, body: QWidget, *, badge: str|None,
    actions: list[QAction]|None, elevation: int)` reusable container.
    Header: title (14 px semibold) + optional `Badge` (right) +
    optional `…` overflow.
  - `metric_card.py` — `MetricCard(label, value, unit, *, trend, status)`
    compact stat tile (used as 6 children inside Resumo do Projeto).
  - `data_table.py` — `DataTable(rows: list[tuple[str, str, str|None]])`
    a labelled key-value-unit table with mono numeric column and
    `tabular-nums`. Used in Bobinamento and Entreferro cards.
  - `score_pill.py` — `ScorePill(score: float, suffix: str = "")`
    with five colour bands (≥85 success, 70–85 info, 55–70 warning,
    40–55 amber, <40 danger).
  - `donut_chart.py` — `DonutChart(segments: list[tuple[str,
    float, str]])` lightweight matplotlib renderer (uses the existing
    QtAgg infrastructure but without the full toolbar).
  - `next_steps.py` — `NextStepsCard(actions: list[ActionItem])`
    bullet list with status icon + click handlers.
- New `ui/dashboard/dashboard_page.py`:
  - `DashboardPage(QWidget)` — `QGridLayout` of 9 cards in a 3×3
    arrangement. Equal column widths; rows size to content.
  - Wires each card to data via a single `update_from_design(result,
    spec, core, wire, material)` method.
  - Listens to `MainWindow.design_completed` signal (new) and
    refreshes.
- Migration of existing functionality:
  - `SpecPanel` is split. Topology + AC input + converter / line-reactor
    sections move into a new "Topologia & Entrada" *page* (sidebar nav
    "Topologia"). The Núcleo card on the dashboard re-implements the
    *selection* concern (material/core/wire combos in card form).
  - `PlotPanel.tab_waveform` becomes the body of the Formas de Onda
    card (matplotlib canvas without tab bar).
  - `PlotPanel.tab_losses` becomes the donut renderer in Perdas.
  - `PlotPanel.tab_3d` becomes the body of Visualização 3D card.
  - `PlotPanel.tab_bh` and `tab_rolloff` move to a separate Análise
    page reachable from the sidebar (kept for power users; not on
    the main dashboard to preserve density).
  - `ResultPanel`'s six groups (operational, currents, flux, losses,
    thermal, window) split among Resumo, Entreferro, Perdas, and
    Bobinamento as detailed above.
- A new `MainWindow.design_completed = Signal(DesignResult, Spec, Core,
  Wire, Material)` is emitted at the end of `_on_calculate()`. The
  Dashboard subscribes; legacy panels keep working in parallel for
  fallback.

## Impact

- **Affected capabilities:** NEW `ui-dashboard`. Existing capabilities
  unchanged in behaviour (only re-presented).
- **Affected modules:** NEW `ui/widgets/*`, NEW `ui/dashboard/`,
  modified `ui/main_window.py` (the `QStackedWidget` page 0 swaps
  from "legacy splitter" to `DashboardPage`).
- **Removed:** `ui/spec_panel.py`, `ui/plot_panel.py`, `ui/result_panel.py`
  remain importable for one release as fallback (sidebar nav exposes
  a "Modo clássico" toggle in Configurações), then are deleted in a
  future cleanup change.
- **Dependencies:** none new. Donut uses existing matplotlib.
- **Risk:** Highest of the five UI changes — touches every visible
  widget. Mitigation: each card has its own dedicated test, the
  legacy panels keep working as a safety net during rollout, and the
  `update_from_design` API mirrors the data already produced by the
  engine (no new physics).
- **Sequencing:** Depends on `refactor-ui-design-system-v2` (tokens)
  and `refactor-ui-shell` (host stack). Parallelisable with
  `refactor-3d-viewer-controls` and `add-topology-schematic-card`
  since each only changes the body of one card.
