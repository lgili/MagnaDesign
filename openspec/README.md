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
| `add-cascade-optimizer`  | XL      | Otimizador brute-force em 4 tiers (feasibility → analítico → ODE transitório → FEA estático/transitório), `ConverterModel` interface para topologias plugáveis, RunStore SQLite e UI dedicada. Phase A entrega a fundação; Tiers 2/3/4 são gated em benchmark |
| `add-circuit-export`     | M       | Emitir subcircuitos LTspice / PSIM / Modelica do indutor projetado (deferred desde v2) |
| `redesign-ui-flow-v3`    | XL      | Reescreve a shell em torno de Spec drawer persistente + 3 tabs no workspace + 4 áreas reais na sidebar; remove Modo Clássico e o stepper de 8 segmentos |
| `ui-refactor-followups`  | M       | Tail-end items dos 5 refactors v2 — animations 3D, docs UI (Núcleo score table foi entregue) |

### Mudanças propostas — caminho para uso industrial (May 2026)

Levantamento "what's missing for industry adoption". Cada item
endereça um gap concreto identificado na auditoria do app. Ordem
reflete prioridade: **P0** (bloqueador para produção) → **P1**
(diferenciador forte) → operacional (sem isso, IT corporativa
não adota).

| Change ID                          | Prio | Tamanho | Descrição |
|------------------------------------|------|---------|-----------|
| `add-validation-reference-set`     | P0   | L       | 3 protótipos físicos com bench data (impedância + B-coil + térmico) + notebooks Jupyter rodando em CI; predicted-vs-measured publicado em GitHub Pages. **O multiplicador de credibilidade #1.** |
| `add-worst-case-tolerance-doe`     | P0   | M       | DOE de cantos (V_in × T × tolerâncias × Pout) + Monte-Carlo de yield. Crítico para auditoria IATF 16949 / IEC 60335. |
| `add-manufacturing-spec-export`    | P0   | M       | PDF estilo IPC-A-610 + Excel com layer-by-layer winding, gap shim, hi-pot, plano de teste de aceitação. Fecha o loop design → fornecedor. |
| `add-compliance-report-pdf`        | P0   | M       | PDF de compliance IEC 61000-3-2 / EN 55032 / UL 1411 / IEC 60335-1 com PASS/FAIL por harmônica. Reuse da física já existente. |
| `add-cli-headless-runner`          | P1   | M       | `magnadesign sweep / cascade / report / mfg-spec / compliance / worst-case` para CI, batch overnight, integração com pipelines de fornecedor. |
| `add-vfd-modulation-workflow`      | P1   | L       | `Spec.fsw_modulation` para inversores de compressor — engine avalia banda fsw em vez de ponto único; otimizador ranqueia por worst-case. |
| `add-acoustic-noise-prediction`    | P1   | M       | Estimador analítico de SPL @ 1 m (magnetostricção + Lorentz + ressonância de bobina). Calibrado ±3 dB(A) contra bench. |
| `add-code-signed-installers`       | P0¹  | M       | macOS notarized + Windows Authenticode + Sparkle/Squirrel auto-update. Remove o atrito de Gatekeeper / SmartScreen para IT corporativo. |
| `add-crash-reporting`              | P1   | S       | Sentry opt-in + analytics opt-in. Privacy-first: scrubbing de PII, primeiro consent dialog. |
| `add-theory-of-operation-docs`     | P1   | M       | Site Sphinx em GitHub Pages: 1 capítulo por módulo de física com derivação + citação + calibração + residual. Auditável para ISO 9001. |

¹ Operacional, não engenharia — mas sem ele não há adoção corporativa.

**Roadmap sugerido (90 dias)**: validation → worst-case →
mfg-spec → cli → compliance → signed installers. Após esses 6,
o app está em estado defensável diante de um auditor de
qualidade — o resto (acoustic, VFD modulation, crash reporting,
theory docs) entra na rodada seguinte.

### Mudanças propostas — 5 novas topologias (May 2026)

A app cobre hoje 4 topologias AC-input (boost-CCM PFC, passive
choke, line reactor 1φ/3φ). Estas 5 propostas alargam o escopo
para inversores e DC-DC isolados — cada uma é independente e pode
entrar na sequência preferida pela engenharia.

| Change ID                          | Tamanho | Descrição |
|------------------------------------|---------|-----------|
| `add-buck-ccm-topology`            | M       | DC-DC step-down síncrono (POL, automotivo 12→5V, telecom 48→12V). Primeira topologia DC-input do app; introduz `Vin_dc_V` e o knob `ripple_ratio`. Math diferente (sem envelope AC). |
| `add-flyback-topology`             | XL      | Coupled-inductor isolado para 5–150 W (adaptadores, supplies auxiliares). Primeira **multi-winding magnetic** + primeira **isolation safety** (IEC 62368 checklist). Modos DCM e CCM. |
| `add-lcl-grid-tie-filter`          | XL      | Filtro LCL trifásico para inversores grid-tie (PV / wind / V2G). Primeira topologia **multi-inductor** + primeira com **standards-as-design-constraint** (IEEE 1547, IEC 61727). Bode plot + Bode na aba Análise. |
| `add-interleaved-boost-pfc`        | M       | Boost PFC interleaved 2φ / 3φ para 1.5–10 kW (server PSU, EV charger PFC, AC residencial). Reusa toda a math do `boost_ccm` por phase + ripple-cancellation Hwu-Yau analítico. |
| `add-psfb-output-choke`            | M       | Output choke do phase-shifted full-bridge (telecom 1–5 kW, EV charger isolado). Primeira topologia **secondary-side**. Math é buck-CCM com `f_sw_eff = 2·f_sw`. |

**Dependências cruzadas**:

- `add-lcl-grid-tie-filter` introduz o wrapper multi-inductor
  (``MultiInductorDesignResult`` + ``ConverterModel.inductor_roles()``);
  `add-flyback-topology` e `add-interleaved-boost-pfc` reusam.
  Ordem natural: LCL → flyback / interleaved em paralelo.
- `add-psfb-output-choke` depende implicitamente do `add-buck-ccm-topology`
  (compartilham math). Ordem: buck → PSFB.
- `add-buck-ccm-topology` é independente de tudo o resto e pode
  ir primeiro pra estabelecer o pattern de DC-input topologies.

**Roadmap sugerido (60 dias)**: buck → flyback (com wrapper
mínimo) → interleaved → PSFB → LCL (full multi-inductor +
standards). Após os 5, o app cobre ~80% do mercado de
power-magnetics design.

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
