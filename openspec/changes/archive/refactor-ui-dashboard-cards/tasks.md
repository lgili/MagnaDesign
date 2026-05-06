# Tasks — Refactor dashboard layout to a 9-card grid

> **Status: shipped (substantively)**. All 9 cards mount, the
> `DashboardPage` updates atomically, the `design_completed` signal
> fans out, and "Modo clássico" preserves the v1 splitter behind a
> Configurações toggle. The Núcleo card uses a lightweight label-based
> selection summary instead of the full score-table view; that
> upgrade is **deferred to `ui-refactor-followups`**.

## 1. Reusable widgets

- [x] 1.1 `ui/widgets/card.py::Card(QFrame)`
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
- [x] 1.2 `ui/widgets/metric_card.py::MetricCard(QFrame)`
      - Compact tile: label (caption, `text_secondary`) above
        big-number value + small unit + optional trend chip
        (`▲ +5%` / `▼ −2%` with success / danger).
      - Number uses `numeric_family` with `tabular-nums` (best-effort
        — `QFont.setFeature("tnum")` requires Qt 6.7+).
      - Optional `status: "ok"|"warn"|"err"` adds a left coloured
        accent bar (3 px wide, 100 % height).
- [x] 1.3 `ui/widgets/data_table.py::DataTable(QFrame)`
      - Renders a flat table: `[(label, value, unit)]`.
      - Two-column layout: label (left, body weight, regular) + value
        (right-aligned, mono `tabular-nums`, semibold) inline with
        unit in muted weight.
      - Zebra rows optional via `striped: bool`.
- [x] 1.4 `ui/widgets/score_pill.py::ScorePill(QLabel)`
      - Subclasses `QLabel.Pill`, picks variant from numeric range:
        `[85,100]→success, [70,85)→info, [55,70)→warning,
        [40,55)→amber, [0,40)→danger`.
      - Text `"{score:.0f}%"` by default, but accepts a custom
        formatter.
- [x] 1.5 `ui/widgets/donut_chart.py::DonutChart(QWidget)`
      - Wraps a matplotlib `FigureCanvasQTAgg` (no toolbar).
      - `set_segments(list[tuple[label, value, color]])` re-renders.
      - Centre label option: total value + caption (e.g. "23.4 W
        Total").
- [x] 1.6 `ui/widgets/next_steps.py::NextStepsCard(QWidget)`
      - Renders a vertical list of `ActionItem(title, status, callback)`.
      - Each row: status icon (Lucide `check-circle`, `clock`, or
        `arrow-up-right` per `done|pending|todo`) + title + (when
        `todo`) primary CTA `arrow-up-right` icon button.

## 2. Dashboard page

- [x] 2.1 `ui/dashboard/dashboard_page.py::DashboardPage(QWidget)`
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
- [x] 2.2 Each row gets a `QFrame` with `setSizePolicy(Expanding,
      Preferred)` — vertical scroll only on the page itself when the
      window is too short.
- [x] 2.3 `update_from_design(result, spec, core, wire, material)` —
      single method dispatched to each card's own `update_from_design`.
- [x] 2.4 `clear()` — resets every card to its empty / placeholder state
      (used on first launch and after the user picks a new topology).

## 3. Card bodies

### 3a. Topologia Selecionada

- [x] 3a.1 `dashboard/cards/topologia_card.py::TopologiaCard(Card)`.
- [x] 3a.2 Body: a `TopologySchematicWidget` (provided by
      `add-topology-schematic-card`) + 4 `QLabel.Pill`s
      (Tipo / Pout / freq / Compliance) + footer
      `QPushButton.Secondary` "Alterar Topologia".
- [x] 3a.3 `update_from_design` updates pill text and switches the
      schematic to the appropriate variant (1ph / 3ph for line reactor).

### 3b. Resumo do Projeto

- [x] 3b.1 `dashboard/cards/resumo_card.py::ResumoCard(Card)`.
- [x] 3b.2 Body: a 3×2 grid of 6 `MetricCard`s — `Indutância (µH)`,
      `Corrente DC (A)`, `Ripple (A pp)`, `Indução pico (mT)`,
      `ΔT enrolamento (°C)`, `Perdas totais (W)`.
- [x] 3b.3 Footer badge: green "Aprovado" when all metric statuses
      are `ok`; amber "Verificar" when any is `warn`; red "Reprovado"
      when any is `err`.

### 3c. Formas de Onda

- [x] 3c.1 `dashboard/cards/formas_onda_card.py::FormasOndaCard(Card)`.
- [x] 3c.2 Body: a matplotlib canvas hosting the inductor-current
      waveform, with a custom dashboard-density visual treatment
      (1 px grid, tabular tick labels, no top/right spines).
- [x] 3c.3 Footer row: 4 `MetricCard`s — `Irms (A)`, `Ipk (A)`,
      `THD (%)`, `crest factor`.

### 3d. Seleção de Núcleo

- [x] 3d.1 `dashboard/cards/nucleo_card.py::NucleoCard(Card)`.
- [~] 3d.2 ~~Body: tab strip (Material | Núcleo | Fio), each tab a
      `QTableView` with `ScorePill` in the score column.~~
      _Deferred to `ui-refactor-followups`. Current card shows the
      live selection (material name, core part-number with Ve/Ae,
      wire name) instead._
- [~] 3d.3 ~~Filters above the table: searchable `QLineEdit` + 2-3
      checkbox filters (curated only, feasible only, vendor).~~
      _Deferred (depends on 3d.2)._
- [~] 3d.4 ~~Footer: "Aplicar seleção" primary button.~~
      _Deferred (depends on 3d.2)._

### 3e. Visualização 3D

- [x] 3e.1 `dashboard/cards/viz3d_card.py::Viz3DCard(Card)` hosting an
      embedded `CoreView3D` with the chrome controls from
      `refactor-3d-viewer-controls`.

### 3f. Perdas

- [x] 3f.1 `dashboard/cards/perdas_card.py::PerdasCard(Card)`.
- [x] 3f.2 Body: `DonutChart` with 3 segments — Cu DC / Cu AC / Núcleo.
      Centre label `"{P_total:.1f} W Total"`.
- [x] 3f.3 Below the donut: a small `DataTable` repeating the three
      values + their percentage shares.

### 3g. Bobinamento

- [x] 3g.1 `dashboard/cards/bobinamento_card.py::BobinamentoCard(Card)`.
- [x] 3g.2 Body: `DataTable` with rows `Espiras (N)`, `Preenchimento`,
      `AWG`, `Diâmetro fio`, `Estrandes`, `R_DC`, `R_AC@fsw`.

### 3h. Entreferro

- [x] 3h.1 `dashboard/cards/entreferro_card.py::EntreferroCard(Card)`.
- [x] 3h.2 Body: 3 `MetricCard`s — `A_L (nH/N²)`, `μ_eff`,
      `H_peak (Oe)`. Status on `H_peak` reflects saturation margin
      (`> 30 % → ok`, `15–30 % → warn`, `< 15 % → err`).

### 3i. Próximos Passos

- [x] 3i.1 `dashboard/cards/proximos_passos_card.py::ProximosPassosCard(Card)`.
- [x] 3i.2 Default actions:
      1. "Validar com FEM" → opens `FeaDialog` (`status: todo`).
      2. "Comparar com alternativos" → opens compare (`status: todo`).
      3. "Otimizar Litz" → opens `LitzDialog`
         (`status: pending` → `done` when wire kind is litz).
      4. "Buscar similares" → opens `SimilarPartsDialog`.
      5. "Gerar relatório" → calls `_export_report`
         (auto-marked `done` after the user generates a datasheet).

## 4. MainWindow integration

- [x] 4.1 Add `MainWindow.design_completed = Signal(DesignResult, Spec,
      Core, Wire, Material)` and emit it at the end of
      `_on_calculate()` after the existing panel updates.
- [x] 4.2 Mount `DashboardPage` as page 0 of the `QStackedWidget`.
- [x] 4.3 Move legacy panels (Spec / Plot / Result) into the
      Configurações page reachable via the sidebar; "Modo clássico"
      checkbox controls visibility (boolean `QSettings` key
      `classic_mode`).
- [x] 4.4 Connect `design_completed` to
      `DashboardPage.update_from_design`.

## 5. Tests

- [x] 5.1 `tests/test_widgets.py` — Card with badge + actions renders,
      overflow menu fires callbacks, set_badge updates variant.
- [x] 5.2 (covered by `tests/test_widgets.py`) — value, unit, trend
      strings rendered; status accent bar visible only when set.
- [x] 5.3 (covered by `tests/test_widgets.py`) — score 92→success,
      score 50→amber, score 30→danger.
- [x] 5.4 (covered by `tests/test_widgets.py`) — segments sum to total;
      `set_segments` replaces the previous content.
- [x] 5.5 `tests/test_dashboard_page.py` — feed a real engine result,
      assert each card's key labels show the expected values; `clear()`
      resets every card.
- [~] 5.6 Visual regression: render `DashboardPage` to PNG via
      pytest-qt screenshot; commit the baseline; later changes diff
      against it (tolerance 1 % per pixel).
      _Deferred to `ui-refactor-followups`._

## 6. Documentation

- [~] 6.1 Update `README.md` screenshots — replace any references to the
      old splitter layout with the new dashboard.
      _Deferred to `ui-refactor-followups`._
- [~] 6.2 Add a short `docs/UI.md` describing the card system + how to
      add a new dashboard card (1-page recipe).
      _Deferred to `ui-refactor-followups`._
