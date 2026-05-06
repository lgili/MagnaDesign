# OpenSpec — PFC Inductor Designer

Estrutura de propostas e tarefas para evoluir o aplicativo. Convenção
[OpenSpec](https://openspec.dev): cada melhoria fica em
`openspec/changes/<id>/` com:

- `proposal.md` — por que, o que muda, impacto
- `tasks.md` — passos concretos de implementação (checklist)
- `design.md` — detalhes técnicos (apenas para mudanças complexas)
- `specs/<capability>/spec.md` — requisitos formais com cenários
  GIVEN/WHEN/THEN, no formato OpenSpec

## Estado atual

### Mudanças ativas

| Change ID                | Tamanho | Descrição |
|--------------------------|---------|-----------|
| `add-circuit-export`     | M       | Emitir subcircuitos LTspice / PSIM / Modelica do indutor projetado (deferred desde v2) |
| `redesign-ui-flow-v3`    | XL      | Reescreve a shell em torno de Spec drawer persistente + 3 tabs no workspace + 4 áreas reais na sidebar; remove Modo Clássico e o stepper de 8 segmentos |
| `ui-refactor-followups`  | M       | Tail-end items dos 5 refactors v2 — animations 3D, docs UI (Núcleo score table foi entregue) |

### Mudanças arquivadas (17 em `archive/`)

**v2 (físico + UX)**
- `add-bh-loop-visual` — trajetória B-H no operating point
- `add-similar-parts-finder` — drop-in replacement search
- `add-multi-column-compare` — comparar 2-4 designs lado a lado
- `add-cost-model` — `$/kg` + `$/m` no Pareto
- `add-litz-optimizer` — critério Sullivan + salvar fio
- `add-fea-validation` — toroide axisimétrico via FEMM (EE/ETD/PQ
  superseded por FEMMT)
- `add-line-reactor-topology` — reator de linha 1ph + 3ph

**v3 (interoperabilidade)**
- `protect-differentials` — ADR + POSITIONING + AboutDialog + 14 testes
- `add-femmt-integration` — Python 3.12 + `[fea]` extra; cobre EE/ETD/PQ
- `add-mas-schema-adoption` — adapters bidirecionais MAS ↔ legado
- `add-mas-catalog-import` — importar 410 mat × 4 350 fios da
  OpenMagnetics
- `add-cross-platform-setup` — instalador automático ONELAB + FEMMT

**v4 (refactor UI MagnaDesign)**
- `refactor-ui-design-system-v2` — tokens v2 (Sidebar navy invariant,
  accent_violet, card_shadow_*, Radius.card/button/chip,
  Spacing.page/card_pad, Inter font, 40 ícones Lucide bundled)
- `refactor-ui-shell` — sidebar 250px navy + workspace header com CTAs
  + 8-step stepper + bottom status bar com 3 pills + WorkflowState
- `refactor-ui-dashboard-cards` — 9-card grid 3×3 + 6 widgets
  reusáveis (Card/MetricCard/DataTable/ScorePill/DonutChart/NextSteps)
  + DashboardPage + classic-mode toggle
- `refactor-3d-viewer-controls` — overlay HUD (chips + cubo orientação
  + side toolbar + bottom actions) + camera_changed signal
- `add-topology-schematic-card` — schematic procedural via QPainter
  para 4 topologias com inductor accent-highlighted

## Convenção de status

Quando uma change termina, mover a pasta inteira para
`openspec/changes/archive/`. Os tasks.md ficam preservados como
histórico — qualquer item arquivado com `[~]` indica algo
deferido / superseded, com a explicação inline.

## Política de scope (ADR 0001)

Toda PR que introduz capability nova deve responder a uma das três
perguntas em `docs/adr/0001-positioning.md`:

1. Reduz uma decisão real do engenheiro de PFC?
2. Aumenta a fidelidade física de um cálculo existente?
3. Cobre uma topologia PFC ainda não suportada?

Se a resposta for "não" para as três, a proposta é rejeitada — não
expandimos escopo para virar genérico-FEM ou genérico-magnetics.
