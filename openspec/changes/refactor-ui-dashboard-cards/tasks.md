# Tasks — Refactor dashboard layout to a 9-card grid

## 1. Reusable widgets

- [ ] 1.1 `ui/widgets/card.py::Card(QFrame)`
      - Constructor: `title: str, body: QWidget, *, badge: str|None=None,
        actions: list[QAction]|None=None, elevation: int=1`.
      - Header `QHBoxLayout`: title label + stretch + (optional) badge
        + (optional) `…` overflow `QToolButton`.
      - Body wraps `body` in a `QVBoxLayout` with `Spacing.card_pad`
        margins.
      - Applies `card_qss(elevation)` and a
        `QGraphicsDropShadowEffect` configured from
        `palette.card_shadow_sm` (or `_md` when elevation == 2).
      - Hover state increases shadow to `_md` over 150 ms via
        `QPropertyAnimation`.
- [ ] 1.2 `ui/widgets/metric_card.py::MetricCard(QFrame)`
      - Compact tile: label (caption, `text_secondary`) above
        big-number value + small unit + optional trend chip
        (`▲ +5%` / `▼ −2%` with success / danger).
      - Number uses `numeric_family` with `tabular-nums`.
      - Optional `status: "ok"|"warn"|"err"` adds a left coloured
        accent bar (3 px wide, 100 % height).
- [ ] 1.3 `ui/widgets/data_table.py::DataTable(QFrame)`
      - Renders a flat table: `[(label, value, unit)]`.
      - Two-column layout: label (left, body weight, regular) + value
        (right-aligned, mono `tabular-nums`, semibold) inline with
        unit in muted weight.
      - Zebra rows optional via `striped: bool`.
- [ ] 1.4 `ui/widgets/score_pill.py::ScorePill(QLabel)`
      - Subclasses `QLabel.Pill`, picks variant from numeric range:
        `[85,100]→success, [70,85)→info, [55,70)→warning,
        [40,55)→amber, [0,40)→danger`.
      - Text `"{score:.0f}%"` by default, but accepts a custom
        formatter.
- [ ] 1.5 `ui/widgets/donut_chart.py::DonutChart(QWidget)`
      - Wraps a matplotlib `FigureCanvasQTAgg` (no toolbar).
      - `set_segments(list[tuple[label, value, color]])` re-renders.
      - Centre label option: total value + caption (e.g. "23.4 W
        Total").
- [ ] 1.6 `ui/widgets/next_steps.py::NextStepsCard(QWidget)`
      - Renders a vertical list of `ActionItem(title, status, callback)`.
      - Each row: status icon (Lucide `check-circle`, `clock`, or
        `arrow-up-right` per `done|pending|todo`) + title + (when
        `todo`) primary CTA `arrow-up-right` icon button.

## 2. Dashboard page

- [ ] 2.1 `ui/dashboard/dashboard_page.py::DashboardPage(QWidget)`
      - Outer layout: `QVBoxLayout` with `Spacing.page` margins,
        no spacing.
      - Inside: `QGridLayout` with 3 columns, equal stretch, row
        spacing = column spacing = `Spacing.card_gap`.
      - Cards laid out:
        - row 0: TopologiaCard, ResumoCard, FormaOndaCard
        - row 1: NucleoCard (col-span 1), Visualizacao3DCard (col-span 2)
        - row 2: PerdasCard, BobinamentoCard, EntreferroCard,
                 ProximosPassosCard (4 cards in 4 sub-columns inside
                 a nested grid spanning all 3 outer cols).
- [ ] 2.2 Each row gets a `QFrame` with `setSizePolicy(Expanding,
      Preferred)` — vertical scroll only on the page itself when the
      window is too short.
- [ ] 2.3 `update_from_design(result, spec, core, wire, material)` —
      single method dispatched to each card's own `update_from_design`.
- [ ] 2.4 `clear()` — resets every card to its empty / placeholder state
      (used on first launch and after the user picks a new topology).

## 3. Card bodies

### 3a. Topologia Selecionada

- [ ] 3a.1 `dashboard/cards/topologia_card.py::TopologiaCard(Card)`.
- [ ] 3a.2 Body: a `TopologySchematicWidget` placeholder area (top, fixed
      ~140 px) + 3 `QLabel.Pill`s (Tipo / Pout / fsw or fline /
      Compliance) + a footer `QPushButton.Secondary` "Alterar Topologia".
      The schematic widget itself comes from
      `add-topology-schematic-card`; this card just hosts it.
- [ ] 3a.3 `update_from_design` updates pill text (e.g.
      `["Boost CCM Active", "1.5 kW", "70 kHz", "IEC 61000-3-2 ✓"]`).

### 3b. Resumo do Projeto

- [ ] 3b.1 `dashboard/cards/resumo_card.py::ResumoCard(Card)`.
- [ ] 3b.2 Body: a 3×2 grid of 6 `MetricCard`s — `L (mH)`, `Iout (A)`,
      `ΔI (A pp)`, `B_pk (mT)`, `T_rise (°C)`, `η_design`. Trend is
      computed against the last optimizer baseline if available, else
      hidden.
- [ ] 3b.3 Footer row: green `Pill` "Aprovado" with check icon when all
      MetricCard statuses are `ok`; amber "Verificar" when any is
      `warn`; red "Reprovado" when any is `err`.

### 3c. Formas de Onda

- [ ] 3c.1 `dashboard/cards/formas_onda_card.py::FormasOndaCard(Card)`.
- [ ] 3c.2 Body: a matplotlib canvas hosting the existing waveform plot
      (lifted from `PlotPanel.tab_waveform`). No toolbar, no axis
      decoration beyond what the dashboard density requires (1 px grid,
      tabular tick labels, no top/right spines).
- [ ] 3c.3 Footer row: 4 `MetricCard`s — `Irms (A)`, `Ipk (A)`,
      `THD (%)`, `crest factor`.

### 3d. Seleção de Núcleo

- [ ] 3d.1 `dashboard/cards/nucleo_card.py::NucleoCard(Card)`.
- [ ] 3d.2 Body: tab strip (Material | Núcleo | Fio), each tab a
      `QTableView` with `ScorePill` in the score column.
- [ ] 3d.3 Filters above the table: searchable `QLineEdit` + 2-3
      checkbox filters (curated only, feasible only, vendor: Magnetics
      / Magmattec / Micrometals / CSC / Dongxing).
- [ ] 3d.4 Footer: "Aplicar seleção" primary button (becomes enabled
      when the user picks a non-current row in any of the 3 tabs).

### 3e. Visualização 3D

- [ ] 3e.1 `dashboard/cards/viz3d_card.py::Viz3DCard(Card)` hosting an
      embedded `CoreView3D` (the existing widget; the new chrome
      controls come from `refactor-3d-viewer-controls`).

### 3f. Perdas

- [ ] 3f.1 `dashboard/cards/perdas_card.py::PerdasCard(Card)`.
- [ ] 3f.2 Body: `DonutChart` with 3 segments — `P_dc` (copper DC),
      `P_ac` (Dowell + skin), `P_core` (iGSE). Centre label
      `"{P_total:.1f} W Total"`.
- [ ] 3f.3 Below the donut: a small `DataTable` repeating the three
      values + their percentage shares.

### 3g. Bobinamento

- [ ] 3g.1 `dashboard/cards/bobinamento_card.py::BobinamentoCard(Card)`.
- [ ] 3g.2 Body: `DataTable` with rows `Turns`, `Layers`, `Fill (%)`,
      `AWG`, `Strands × Ø (mm)`, `Length (m)`, `Mass (g)`,
      `R_DC@25 °C (mΩ)`, `R_AC@fsw (mΩ)`.

### 3h. Entreferro

- [ ] 3h.1 `dashboard/cards/entreferro_card.py::EntreferroCard(Card)`.
- [ ] 3h.2 Body: 3 `MetricCard`s — `A_L (nH/N²)`, `μ_eff`,
      `H_peak (Oe)`. Status field maps to saturation margin
      (`> 30 % → ok`, `15–30 % → warn`, `< 15 % → err`).

### 3i. Próximos Passos

- [ ] 3i.1 `dashboard/cards/proximos_passos_card.py::ProximosPassosCard(Card)`.
- [ ] 3i.2 Default actions:
      1. "Validar com FEM" → opens `FeaDialog` (`status: todo`).
      2. "Comparar com alternativos" → opens compare
         (`status: todo` if compare empty, else `done`).
      3. "Otimizar Litz" → opens `LitzDialog`
         (`status: pending` until Litz wire is selected).
      4. "Gerar relatório" → calls `_export_report` (`status: todo`).
      5. "Buscar similares" → opens `SimilarPartsDialog`
         (`status: todo`).

## 4. MainWindow integration

- [ ] 4.1 Add `MainWindow.design_completed = Signal(DesignResult, Spec,
      Core, Wire, Material)` and emit it at the end of
      `_on_calculate()` after the existing panel updates.
- [ ] 4.2 Mount `DashboardPage` as page 0 of the `QStackedWidget`.
- [ ] 4.3 Move legacy panels (Spec / Plot / Result) into a hidden page
      reachable via Configurações → "Modo clássico". A boolean
      `QSettings` key controls visibility.
- [ ] 4.4 Connect `design_completed` to
      `DashboardPage.update_from_design`.

## 5. Tests

- [ ] 5.1 `tests/test_widgets_card.py` — Card with badge + actions
      renders with the right object names; hover bumps shadow class.
- [ ] 5.2 `tests/test_widgets_metric_card.py` — value, unit, trend
      strings rendered; status accent bar visible only when set.
- [ ] 5.3 `tests/test_widgets_score_pill.py` — score 92→success,
      score 50→amber, score 30→danger.
- [ ] 5.4 `tests/test_widgets_donut_chart.py` — segments sum to total;
      centre label matches.
- [ ] 5.5 `tests/test_dashboard_page.py` — feed a synthetic
      `DesignResult` + Core/Wire/Material/Spec, assert each card's
      key labels show the expected values.
- [ ] 5.6 Visual regression: render `DashboardPage` to PNG via
      pytest-qt screenshot; commit the baseline; later changes diff
      against it (tolerance 1 % per pixel).

## 6. Documentation

- [ ] 6.1 Update `README.md` screenshots — replace any references to the
      old splitter layout with the new dashboard.
- [ ] 6.2 Add a short `docs/UI.md` describing the card system + how to
      add a new dashboard card (1-page recipe).
