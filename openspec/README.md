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

### Mudanças ativas (May 2026)

12 changes pendentes. Os 7 itens P0/P1 do roadmap industrial
(validation, worst-case, mfg-spec, compliance, vfd-modulation,
acoustic, theory-docs) já fecharam — ver seção "Mudanças
arquivadas" abaixo.

| Change ID                          | Prio | Tamanho | Estado |
|------------------------------------|------|---------|--------|
| `add-validation-reference-set`     | P0   | L       | Software scaffolding shipped (`76d0aa8`). Bloqueado em **bench data física** — 3 protótipos com impedância + B-coil + térmico. Notebooks publicam predicted-vs-measured no GitHub Pages quando os números chegarem. |
| `add-manufacturing-spec-export`    | P0   | M       | Não iniciado. PDF estilo IPC-A-610 + Excel layer-by-layer winding, gap shim, hi-pot, FAT plan. Fecha o loop design → fornecedor. |
| `add-cli-headless-runner`          | P1   | M       | Phases 1-4 + 5/7 parciais shipped (`db3294e`, `7d1fef3`, `89056ac`, `a9f62af`). **Falta**: `magnadesign datasheet / mfg-spec / report` subcomandos + Phase 6 (`catalog`/`validate`) + docs. |
| `add-cascade-optimizer`            | XL   | XL      | Phase A (Tier-0 + Tier-1 + RunStore + parallel + UI) shipped. Phases B/C/D (Tier-2 ODE / Tier-3 FEA / Tier-4 transient FEA) gated em benchmark com uplift demonstrado. |
| `add-code-signed-installers`       | P0¹  | M       | Phase 1 CI scaffolding shipped (`4e7d919`). **Bloqueado em certificados** — macOS notarization + Windows Authenticode requerem credenciais não-engenharia. |
| `add-crash-reporting`              | P1   | S       | Não iniciado. Sentry opt-in + analytics opt-in com scrubbing de PII e consent dialog. |
| `add-circuit-export`               | M    | M       | Não iniciado. LTspice / PSIM / Modelica subcircuits do indutor projetado (deferred desde v2). |
| `ui-refactor-followups`            | —    | M       | Score table shipped; **falta**: animações 3D + visual-regression test + `docs/UI.md`. |

¹ Operacional — sem isso não há adoção corporativa.

### Mudanças propostas — 5 novas topologias

A app cobre hoje 5 topologias (boost-CCM PFC, passive choke,
line reactor 1φ/3φ, buck-CCM DC-DC — buck shipped em `c90f2ee`).
Estas 4 propostas restantes alargam o escopo para inversores e
DC-DC isolados — cada uma é independente e pode entrar na
sequência preferida pela engenharia.

| Change ID                          | Tamanho | Descrição |
|------------------------------------|---------|-----------|
| `add-flyback-topology`             | XL      | Coupled-inductor isolado para 5–150 W (adaptadores, supplies auxiliares). Primeira **multi-winding magnetic** + primeira **isolation safety** (IEC 62368 checklist). Modos DCM e CCM. |
| `add-lcl-grid-tie-filter`          | XL      | Filtro LCL trifásico para inversores grid-tie (PV / wind / V2G). Primeira topologia **multi-inductor** + primeira com **standards-as-design-constraint** (IEEE 1547, IEC 61727). Bode plot + Bode na aba Análise. |
| `add-interleaved-boost-pfc`        | M       | Boost PFC interleaved 2φ / 3φ para 1.5–10 kW (server PSU, EV charger PFC, AC residencial). Reusa toda a math do `boost_ccm` por phase + ripple-cancellation Hwu-Yau analítico. |
| `add-psfb-output-choke`            | M       | Output choke do phase-shifted full-bridge (telecom 1–5 kW, EV charger isolado). Primeira topologia **secondary-side**. Math é buck-CCM com `f_sw_eff = 2·f_sw`. |

**Dependências cruzadas**:

- `add-lcl-grid-tie-filter` introduz o wrapper multi-inductor
  (``MultiInductorDesignResult`` + ``ConverterModel.inductor_roles()``);
  `add-flyback-topology` e `add-interleaved-boost-pfc` reusam.
  Ordem natural: LCL → flyback / interleaved em paralelo.
- `add-psfb-output-choke` depende implicitamente do
  `add-buck-ccm-topology` (já arquivado, ver abaixo). Ordem:
  buck (✓) → PSFB.

**Roadmap sugerido (60 dias)**: flyback (com wrapper mínimo) →
interleaved → PSFB → LCL (full multi-inductor + standards).
Após os 4, o app cobre ~80% do mercado de power-magnetics
design.

### Mudanças arquivadas (24 em `archive/`)

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
- `redesign-ui-flow-v3` — Spec drawer persistente + 4 áreas reais
  na sidebar + ProjetoPage com 6 tabs (Núcleo / Análise / Validar
  / Worst-case / Compliance / Exportar); Modo Clássico e stepper
  de 8 segmentos retirados

**v5 (industrial readiness — May 2026)**
- `add-buck-ccm-topology` — DC-DC step-down síncrono (POL,
  automotivo 12→5 V, telecom 48→12 V); primeira topologia
  DC-input do app
- `add-vfd-modulation-workflow` — `Spec.fsw_modulation` para
  inversores de compressor; engine avalia banda fsw com worst-
  case envelope, datasheet com página de modulação
- `add-worst-case-tolerance-doe` — DOE de cantos (3^N corner
  factorial + Monte-Carlo yield) + UI tab + sensitivity table +
  datasheet "Production worst-case envelope"
- `add-acoustic-noise-prediction` — estimador A-weighted SPL @
  1 m (magnetostrição + Lorentz + ressonância de bobina) + card
  na Análise; calibração ±3 dB(A) gated em bench data
- `add-compliance-report-pdf` — IEC 61000-3-2 + EN 55032 + UL
  1411 dispatcher + PDF + Compliance tab + CLI subcommand;
  IEC 60335-1 deferido (precisa creepage no schema)
- `add-theory-of-operation-docs` — site Sphinx com derivação +
  citação + LaTeX para Steinmetz/iGSE, Dowell, rolloff, thermal,
  feasibility, compliance + 4 capítulos de topologia + API
  reference; deploy automático para GitHub Pages

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
