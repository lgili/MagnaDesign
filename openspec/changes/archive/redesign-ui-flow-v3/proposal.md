# Redesign UI flow v3 — single workspace, persistent spec drawer

## Why

After v4 (MagnaDesign cards) shipped + polish, the user audit caught a
deeper structural problem the visual layer alone cannot fix:

1. **Two paradigms compete.** The MagnaDesign 9-card dashboard and
   the v1 3-column splitter (SpecPanel | PlotPanel | ResultPanel)
   both ship — the splitter hides behind a "Modo clássico" toggle in
   Configurações. Engineers don't know which to use; the toggle is
   discoverable only by accident.
2. **The 8-area sidebar mostly *navigates back to subsets of the
   dashboard*.** Topologia, Núcleos, Bobinamento, Simulação and
   Mecânico each mount one or two cards already on the Dashboard,
   wrapped in a header. That's *more clicks for less information* —
   the opposite of what a sidebar should buy.
3. **The 8-step stepper at the top fakes a linear workflow** that
   doesn't match how PFC engineers actually work (they loop spec ↔
   results dozens of times). It implies progress that isn't there.
4. **The spec input is hidden.** SpecPanel only appears in classic
   mode. Users hit the "Recalcular" header CTA against a spec they
   can't see or change unless they discover the toggle.
5. **Bottom status pills** ("Avisos / Erros / Validações") are
   abstract — `12 - len(warnings)` reads as a magic number, not a
   useful scoreboard.

This change rebuilds the shell around a *single* workspace anchored on
a *persistent spec drawer*. The dashboard becomes one of three
workspace tabs; the legacy splitter is removed; the sidebar shrinks to
four real destinations.

## What changes

- **Sidebar** (8 → 4 areas):
  - Projeto (default)
  - Otimizador (was modal `OptimizerDialog`, promoted to a page)
  - Catálogo (was overflow-menu DB editor / MAS catalog import)
  - Configurações (theme, paths, FEA install, sobre)
- **Workspace** (Projeto area):
  - Persistent **SpecDrawer** on the left (~360 px, collapsible to a
    40 px icon strip) hosting the existing `SpecPanel` content.
  - Three tabs at the top of the workspace body:
    - **Design** (default) — a slim DashboardPage (no TopologiaCard;
      topology lives in the drawer).
    - **Validar** — FEA + BH-loop + Compare quick-look cards.
    - **Exportar** — datasheet preview + export CTA.
- **Header CTAs** rearranged: Recalcular (Primary, single Primary on
  the surface), Comparar (Secondary, opens dialog), Gerar Relatório
  (Secondary, switches to Exportar tab).
- **ProgressIndicator** — replaces `WorkflowStepper`. A 4-state line
  (Spec → Design → Validar → Exportar) showing where the user is in
  the loop. Not user-clickable; informational only.
- **Scoreboard** — replaces `BottomStatusBar`. Save status (left) +
  KPIs of the last result (centre, "L=376 µH · ΔT=60 °C · η=97 %") +
  Recalcular pinned right (Ctrl+R).
- **Removed:**
  - "Modo clássico" toggle and the legacy splitter mount inside the
    shell. (`SpecPanel` / `PlotPanel` / `ResultPanel` modules stay —
    `SpecPanel` is *reused* inside `SpecDrawer`; the other two are
    no longer mounted by `MainWindow`.)
  - `_extra_cards` mapping and the 7 placeholder pages
    (Topologia/Núcleos/Bobinamento/Simulação/Mecânico/Relatórios as
    standalone areas).
  - `WorkflowStepper` widget (state object kept; semantics simplified
    to 4 states matching the ProgressIndicator).
  - 8-step `WORKFLOW_STEPS` constant; replaced by 4-state enum.
  - `BottomStatusBar` pill counters (Avisos/Erros/Validações).
  - `AREA_TO_STEP` map.
- **Otimizador as a page**: the `OptimizerDialog` becomes a `QWidget`
  page mounted in the sidebar's Otimizador area. Pareto plot + table
  + "Aplicar" wiring is preserved; the modal lifecycle is gone.
- **Catálogo as a page**: same treatment for the DB editor + MAS
  catalog import controls — they live as a tabbed page so the user
  can browse the catalog without dismissing modals.
- **Wiring guarantees** (the user explicitly asked):
  - Recalcular (header) → `_on_calculate`.
  - Calcular (drawer footer) → `_on_calculate`.
  - Topology picker (drawer) → updates spec + recalcs.
  - Núcleo card "Aplicar seleção" → `_apply_optimizer_choice` → recalc.
  - Comparar (header) → opens compare dialog.
  - Gerar Relatório (header) → switches to Exportar tab.
  - Próximos Passos cards → existing dialogs (FEA, Litz, Similar).
  - Sidebar Otimizador / Catálogo → page navigation (no modal).
  - Sidebar Configurações → theme toggle + FEA install + about.

## Impact

- **Affected capabilities:** existing `ui-shell`, `ui-dashboard`
  capabilities reduced/restructured. No new capability introduced;
  this is a structural cleanup of v4.
- **Affected modules:** `ui/main_window.py` (significant rewrite),
  NEW `ui/shell/spec_drawer.py`, NEW `ui/shell/progress_indicator.py`,
  NEW `ui/shell/scoreboard.py`, NEW `ui/workspace/` (Projeto +
  Otimizador + Catálogo pages), modifications to `Sidebar`
  (4 areas) and `WorkspaceHeader` (3 reordered CTAs).
- **Removed:** `_make_classic_page_body`, `_classic_page` state,
  `_extra_cards`, the placeholder per-area pages, `WorkflowStepper`,
  `BottomStatusBar` pill counters.
- **Tests:** `test_shell_stepper.py` retired (stepper removed);
  `test_shell_status_bar.py` adapted to scoreboard; new
  `test_spec_drawer.py`, `test_progress_indicator.py`,
  `test_scoreboard.py`, `test_main_window_v3.py` covering the new
  shell shape.
- **Risk:** highest of any UI change so far — touches every visible
  surface. Mitigation: `SpecPanel` keeps its existing API and is
  remounted *unmodified* inside the drawer, so the spec form keeps
  every field/validation it had. `DashboardPage` cards keep their
  contracts; only the host changes.
