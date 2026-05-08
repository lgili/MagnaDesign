# Tasks — Redesign UI flow v3

Shipped organically across multiple commits during the v3 → v4
UI overhaul (sidebar reduction, ProjetoPage with SpecDrawer +
KPI strip + 4 tabs, Otimizador / Catalogo / Configuracoes pages
with WorkspacePageHeader). Every shell component below now
exists in `src/pfc_inductor/ui/shell/` and `src/pfc_inductor/ui/
workspace/` and is exercised by the live app.

## 1. New shell components

- [x] 1.1 `ui/shell/spec_drawer.py::SpecDrawer(QFrame)` —
      collapsible left dock that hosts the existing `SpecPanel`.
- [x] 1.2 `ui/shell/progress_indicator.py::ProgressIndicator(QFrame)`.
- [x] 1.3 `ui/shell/scoreboard.py::Scoreboard(QFrame)` — replaces
      the legacy `BottomStatusBar`.

## 2. Workspace tabs

- [x] 2.1 `ui/workspace/projeto_page.py::ProjetoPage(QWidget)` —
      hosts SpecDrawer (left) + a tab stack (right). Tab shape
      evolved beyond the original 3-tab plan: today carries
      Núcleo / Análise / Validar / Worst-case / Compliance /
      Exportar (the audit flow demanded the extra tabs).
- [x] 2.2 Design tab content — split into `nucleo_selection_page`
      + `analise_page` for the same surface area.
- [x] 2.3 `ui/workspace/validar_tab.py::ValidarTab(QWidget)` —
      FEA + BH-loop + Compare quick-look.
- [x] 2.4 `ui/workspace/exportar_tab.py::ExportarTab(QWidget)` —
      datasheet preview + Export controls.

## 3. Otimizador page + Catálogo page

- [x] 3.1 `ui/workspace/otimizador_page.py::OtimizadorPage(QWidget)`.
- [x] 3.2 `ui/workspace/catalogo_page.py::CatalogoPage(QWidget)`.

## 4. Sidebar reduction (8 → 4)

- [x] 4.1 `Sidebar` `SIDEBAR_AREAS` reduced to the 4-area set
      (`projeto / otimizador / catalogo / configuracoes`).
- [x] 4.2 Tooltips + Lucide icons updated.
- [x] 4.3 Overflow actions trimmed.

## 5. MainWindow rewire

- [x] 5.1 `_build_shell` rewritten around the v3 structure
      (Sidebar | QStackedWidget of workspace pages).
- [x] 5.2 ProjetoPage stacked vertically with header + tab area
      + Scoreboard.
- [x] 5.3 Signals wired end-to-end (recalculate / compare /
      report / spec changes).
- [x] 5.4 Legacy stepper / classic-mode helpers removed.
- [x] 5.5 `WorkflowState` simplified to the v3 4-state enum.

## 6. DashboardPage trim

- [x] 6.1 TopologiaCard moved into the drawer / spec dialog;
      no longer rendered inside the dashboard.
- [x] 6.2 Layout reorganised into the audit-friendly 6-card
      arrangement on the Análise tab. Modulation envelope +
      Acoustic noise cards added later (`d681ead`, `3dd80bc`).
- [x] 6.3 `update_from_design` + `clear` updated accordingly.

## 7. Tests

- [x] 7.1 Legacy stepper test still present
      (`tests/test_shell_stepper.py`) and asserts the v3
      stepper-less behaviour. Kept as a regression guard rather
      than retired.
- [x] 7.2 Status-bar test adapted alongside the Scoreboard
      change. Coverage lives in `test_main_window_shell.py`
      rather than a dedicated `test_scoreboard.py` — the shell
      test exercises the strip end-to-end.
- [~] 7.3 Dedicated `tests/test_spec_drawer.py`. *Deferred —
      drawer behaviour is exercised via `test_main_window_shell.py`
      and `test_projeto_page.py`. Standalone file lands when a
      drawer-specific regression demands it.*
- [~] 7.4 Dedicated `tests/test_progress_indicator.py`.
      *Deferred — same as above.*
- [x] 7.5 `tests/test_main_window_shell.py` rewritten for the v3
      layout (4 sidebar items, no QToolBar, no classic-mode
      toggle).
- [x] 7.6 `tests/test_dashboard_page.py` updated for the trimmed
      card set.
- [x] 7.7 Full suite green.

## 8. Cleanup + screenshot

- [x] 8.1 Placeholder / classic-mode helpers deleted.
- [x] 8.2 `openspec/README.md` updates landed alongside each
      milestone commit; `ui-refactor-followups` keeps its own
      tail-end items (animations + UI docs).
- [x] 8.3 Headless screenshot suite re-rendered for the v3
      layout.
- [x] 8.4 Commits landed.
