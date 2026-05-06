# Tasks — Refactor application shell to MagnaDesign layout

> **Status: shipped.** Sidebar, header, stepper, status bar and
> WorkflowState are all in place; the legacy splitter is reachable
> via Configurações → "Modo clássico". Stepper segments became
> *clickable* in the polish round (originally spec'd as static).

## 1. Sidebar

- [x] 1.1 `ui/shell/sidebar.py::Sidebar(QFrame)`
      - Fixed width 250 px, navy `SIDEBAR.bg` background.
      - Top section: logo row (Lucide `cube` icon + "MagnaDesign" wordmark
        18 px semibold + small "Inductor Design Suite" caption).
      - Middle section: 8 nav items as `QPushButton.SidebarItem` —
        Dashboard, Topologia, Núcleos, Bobinamento, Simulação, Mecânico,
        Relatórios, Configurações. Each has Lucide icon (left) +
        label (right).
      - Bottom section: theme toggle (sun/moon Lucide icon) + version
        label `v0.2 Pro` + a "more" overflow `…` button.
- [x] 1.2 Active state: clicking a nav item sets it active (filled
      `SIDEBAR.bg_active`) and emits `navigation_requested(area: str)`.
- [x] 1.3 Hover state: `SIDEBAR.bg_hover`. Focus ring uses
      `palette.focus_ring` per WCAG.
- [x] 1.4 The "more" overflow button shows a `QMenu` with the legacy
      tools the sidebar can't host directly (DB editor, MAS catalog,
      Optimizer, FEA, Litz, BH-loop, Similar parts, About).

## 2. Workspace header

- [x] 2.1 `ui/shell/header.py::WorkspaceHeader(QWidget)`
      - Left: `QLineEdit` with no border (project name) + Lucide
        `pencil` button. Editing emits `name_changed(str)`.
      - Centre: `QLabel.Pill` "Salvo" with green dot icon, switches to
        "Não salvo" / yellow when `WorkflowState.unsaved == True`.
      - Right: secondary `QPushButton.Secondary` "Comparar soluções"
        and primary `QPushButton.Primary` "Gerar Relatório".
- [x] 2.2 Header has 64 px fixed height, 24 px horizontal padding, a
      subtle `palette.border` bottom hairline.
- [x] 2.3 Buttons emit `compare_requested()` and `report_requested()`.

## 3. Workflow stepper

- [x] 3.1 `ui/shell/stepper.py::WorkflowStepper(QWidget)`
      - 8 segments laid out horizontally with equal stretch.
      - Each segment: numbered circle (24 px) + label below.
      - Connecting line between consecutive segments, 1 px thick.
- [x] 3.2 Segment states:
      - `done`: filled green circle with Lucide `check`, label normal weight.
      - `active`: filled `accent_violet` circle with white number,
        label semibold + violet text.
      - `pending`: outlined circle, muted text.
- [x] 3.3 `set_state(active_index: int, completed: set[int])` API.
- [x] 3.4 ~~Segments are *not* clickable in this iteration~~ —
      **upgraded in polish round**: each segment now emits
      ``clicked(idx)`` on left-click; ``MainWindow._on_stepper_clicked``
      maps the index to a sidebar area via the inverse of
      ``AREA_TO_STEP``. Cursor reads as a pointer.

## 4. Bottom status bar

- [x] 4.1 `ui/shell/status_bar.py::BottomStatusBar(QFrame)`
      - 32 px fixed height, `palette.surface` bg, top hairline.
      - Left: green dot + "Projeto salvo há {N} min" (when saved) /
        amber dot + "Alterações não salvas" (when dirty).
      - Right: 3 `QLabel.Pill`s — `0 Avisos` (warning variant),
        `0 Erros` (danger variant), `12 Validações` (success variant).
- [x] 4.2 Counters update via `set_warnings`, `set_errors`,
      `set_validations`. Zero-counts use the neutral pill variant
      (so a "0 Erros" still reads quietly green/grey, not screaming red).
- [x] 4.3 Save-status text auto-refreshes once per minute via a
      `QTimer` (relative time).

## 5. WorkflowState

- [x] 5.1 `ui/state/workflow_state.py::WorkflowState(QObject)`
      - Fields: `current_step`, `completed_steps`, `project_name`,
        `unsaved`, `last_saved_at`, `warnings`, `errors`,
        `validations_passed`.
      - Single signal `state_changed` (no per-field signals — keeps
        wiring simple; subscribers do a cheap full re-read).
- [x] 5.2 `to_settings(qs: QSettings)` / `from_settings(qs)` —
      round-trip the persistable subset (name + last_saved_at +
      completed_steps).
- [x] 5.3 Hook into existing engine path: after `MainWindow._on_calculate()`
      success, the engine's `DesignResult` is mapped to validation
      counters (`validations_passed = max(0, 12 - len(warnings))`).

## 6. MainWindow integration

- [x] 6.1 Rewrite `MainWindow._build_ui`:
      - Central widget = `QWidget` with horizontal `QHBoxLayout`.
      - Left = `Sidebar`.
      - Right = `QFrame#Workspace` with vertical layout containing
        `WorkspaceHeader`, `WorkflowStepper`, `QStackedWidget`,
        `BottomStatusBar`.
      - The `QStackedWidget` page 0 hosts the **DashboardPage**
        (refactor-ui-dashboard-cards). Page 7 (Configurações) hosts a
        "Modo clássico" toggle exposing the legacy splitter.
- [x] 6.2 Wire `Sidebar.navigation_requested → QStackedWidget.setCurrentIndex`
      via a small mapper.
- [x] 6.3 Move all toolbar actions onto either the header CTAs (Comparar,
      Gerar Relatório) or the sidebar overflow `…` menu.
- [x] 6.4 Replace `self.statusBar()` calls with `self.status_bar`
      (`BottomStatusBar`).

## 7. Tests

- [x] 7.1 `tests/test_shell_sidebar.py` — clicking each nav button
      emits `navigation_requested` with the right area string.
- [x] 7.2 `tests/test_shell_stepper.py` — `set_state(3, {0,1,2})`
      gives steps 0–2 the `done` class and step 3 the `active` class.
      Plus stepper-click integration coverage added in the polish round.
- [x] 7.3 `tests/test_shell_status_bar.py` — set warnings=2 / errors=0,
      assert the pill text is "2 Avisos" with warning variant,
      "0 Erros" with neutral variant.
- [x] 7.4 `tests/test_workflow_state.py` — round-trip via a
      throwaway `QSettings` (use `QSettings.IniFormat` with a tmp file).
- [x] 7.5 Integration: `tests/test_main_window_shell.py` launches
      `MainWindow` headlessly, asserts sidebar is visible, header has
      both CTAs, and the status bar shows three pills.

## 8. Migration

- [x] 8.1 `__main__.py` already calls `make_stylesheet(get_theme())`
      and `set_theme()` — the v2 helpers are emitted from
      `make_stylesheet()` so no boot-path change was required.
- [x] 8.2 Verify existing tests still pass (the splitter inside the
      classic-mode page still wires spec/plot/result correctly;
      total: 323 passed / 1 skipped after all 5 UI changes + polish).
