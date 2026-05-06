# Tasks — Redesign UI flow v3

## 1. New shell components

- [ ] 1.1 `ui/shell/spec_drawer.py::SpecDrawer(QFrame)` —
      collapsible left dock that hosts the existing `SpecPanel`.
      Toggle button (chevron) on the inner edge; remembers state in
      `QSettings`. Default expanded width ~360 px; collapsed width
      40 px (icon-only stub).
- [ ] 1.2 `ui/shell/progress_indicator.py::ProgressIndicator(QFrame)` —
      4-state pill row (Spec / Design / Validar / Exportar). Each
      state: pending (outline), current (violet fill), done (green
      fill + check). Not clickable.
- [ ] 1.3 `ui/shell/scoreboard.py::Scoreboard(QFrame)` — replaces
      `BottomStatusBar`. Layout: save-status pill | spacer |
      KPI strip (L / B_pk / ΔT / η) | spacer | Recalcular icon
      button (Ctrl+R). KPI strip auto-updates from `update_from_result`.

## 2. Workspace tabs

- [ ] 2.1 `ui/workspace/projeto_page.py::ProjetoPage(QWidget)` —
      hosts SpecDrawer (left) + a `QTabWidget` (right) with three
      tabs.
- [ ] 2.2 `ProjetoPage.tab_design` — wraps the existing
      `DashboardPage` minus the TopologiaCard.
- [ ] 2.3 `ui/workspace/validar_tab.py::ValidarTab(QWidget)` —
      stacked: FEA card (button + last result), BH-loop card
      (matplotlib canvas), Compare quick-look (last 4 saved slots).
- [ ] 2.4 `ui/workspace/exportar_tab.py::ExportarTab(QWidget)` —
      datasheet HTML preview area (read-only `QTextBrowser`) + Export
      button (writes `datasheet.html`) + recent-exports list.

## 3. Otimizador page + Catálogo page

- [ ] 3.1 `ui/workspace/otimizador_page.py::OtimizadorPage(QWidget)` —
      lifts the layout of `OptimizerDialog` into a `QWidget` (no
      modal). Pareto canvas + table + "Aplicar" button. Same
      `selection_applied(material_id, core_id, wire_id)` signal so
      `MainWindow` reuses `_apply_optimizer_choice`.
- [ ] 3.2 `ui/workspace/catalogo_page.py::CatalogoPage(QWidget)` —
      tabbed view: Materiais / Núcleos / Fios. Each tab a
      `QTableView` with edit-in-place. Buttons: "Atualizar do MAS",
      "Salvar alterações". Reuses `db_editor.py` table models.

## 4. Sidebar reduction (8 → 4)

- [ ] 4.1 `Sidebar` `SIDEBAR_AREAS` reduced to:
      `dashboard | otimizador | catalogo | configuracoes`.
      (Aliased: `dashboard` keeps the id for back-compat with
      QSettings keys; the displayed label is "Projeto".)
- [ ] 4.2 Update tooltips and Lucide icons accordingly.
- [ ] 4.3 Adjust `OVERFLOW_ACTIONS` — remove DB editor + MAS catalog
      (now first-class), keep Sobre / Litz / Similar / FEA setup as
      tools.

## 5. MainWindow rewire

- [ ] 5.1 Replace `_build_shell` with the v3 structure:
      `central = QHBoxLayout(Sidebar | QStackedWidget(workspace
      pages))`. Workspace pages: ProjetoPage / OtimizadorPage /
      CatalogoPage / ConfiguracoesPage.
- [ ] 5.2 ProjetoPage gets `header + ProgressIndicator + tabs +
      Scoreboard` stacked vertically.
- [ ] 5.3 Wire signals end-to-end:
      - `header.recalculate_requested → controller.calculate → _on_calc_done`
      - `header.compare_requested → _open_compare`
      - `header.report_requested → projeto_page.switch_to("exportar")`
      - `spec_drawer.calculate_requested → header.recalculate_requested`
      - `progress.set_current(...)` updates as the user moves between
        tabs.
- [ ] 5.4 Remove from MainWindow: `_make_placeholder_page`,
      `_make_classic_page_body`, `_classic_page`, `_extra_cards`,
      `AREA_TO_STEP`, `_on_stepper_clicked`, `_workspace`
      QFrame management.
- [ ] 5.5 Replace `WorkflowState` 8-step semantics with a 4-state
      enum (`spec | design | validar | exportar`). Keep the QObject
      + persistence path; just simplify the field types.

## 6. DashboardPage trim

- [ ] 6.1 `DashboardPage` no longer renders TopologiaCard (topology
      lives in the drawer). `card_topologia` attribute removed.
- [ ] 6.2 Layout becomes 2 rows: row 0 = Resumo + Formas-Onda,
      row 1 = Núcleo + Visualização 3D, row 2 = Perdas + Bobinamento +
      Entreferro + Próximos Passos.
- [ ] 6.3 Update `update_from_design` and `clear` accordingly.

## 7. Tests

- [ ] 7.1 Retire `tests/test_shell_stepper.py` (stepper removed).
- [ ] 7.2 Adapt `tests/test_shell_status_bar.py` →
      `tests/test_scoreboard.py` (new contract: KPI strip + save
      status + Recalcular shortcut).
- [ ] 7.3 New `tests/test_spec_drawer.py` — collapse/expand, toggle
      state persists via QSettings, Calcular signal fires.
- [ ] 7.4 New `tests/test_progress_indicator.py` — 4 states render
      correctly; `set_current("design")` flips the pill.
- [ ] 7.5 Update `tests/test_main_window_shell.py` →
      `test_main_window_v3.py`: 4 sidebar items, 3 tabs in Projeto,
      no QToolBar, no classic-mode toggle.
- [ ] 7.6 Update `tests/test_dashboard_page.py` — no TopologiaCard;
      the `_cards` list has 8 entries instead of 9.
- [ ] 7.7 Full suite green.

## 8. Cleanup + screenshot

- [ ] 8.1 Delete `_make_placeholder_page`, `_make_classic_page_body`
      helpers from `main_window.py`. Remove unused imports.
- [ ] 8.2 Update `openspec/README.md` — `redesign-ui-flow-v3`
      replaces `ui-refactor-followups` (which is now closed by this
      change).
- [ ] 8.3 Re-render the headless screenshot suite. Expected:
      Projeto/Design tab shows SpecDrawer left + cards right + KPI
      strip at bottom. Each sidebar area visibly distinct.
- [ ] 8.4 Commit.
