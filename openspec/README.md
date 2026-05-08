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

5 changes pendentes — 3 bloqueadas em algo que não é
engenharia (bench data, certificados, benchmark uplift) e 2
propostas de topologia ainda não iniciadas. Catorze itens
fecharam neste pass: validation-reference-set software
scaffolding, worst-case, mfg-spec, compliance, vfd-modulation,
acoustic, theory-docs, buck-CCM, **flyback-topology**,
**interleaved-boost-pfc**, redesign-ui-flow-v3,
ui-refactor-followups, cli-headless-runner, circuit-export,
crash-reporting. Ver seção "Mudanças arquivadas" abaixo.

| Change ID                          | Prio | Tamanho | Estado |
|------------------------------------|------|---------|--------|
| `add-validation-reference-set`     | P0   | L       | Software scaffolding shipped (`76d0aa8`). Bloqueado em **bench data física** — 3 protótipos com impedância + B-coil + térmico. Notebooks publicam predicted-vs-measured no GitHub Pages quando os números chegarem. |
| `add-cascade-optimizer`            | XL   | XL      | Phase A (Tier-0 + Tier-1 + RunStore + parallel + UI) shipped. Phases B/C/D (Tier-2 ODE / Tier-3 FEA / Tier-4 transient FEA) gated em benchmark com uplift demonstrado. |
| `add-code-signed-installers`       | P0¹  | M       | Phase 1 CI scaffolding shipped (`4e7d919`). **Bloqueado em certificados** — macOS notarization + Windows Authenticode requerem credenciais não-engenharia. |

¹ Operacional — sem isso não há adoção corporativa.

Pendentes não-bloqueadas em propostas de topologia:
`add-lcl-grid-tie-filter` e `add-psfb-output-choke`.

### Mudanças propostas — 2 novas topologias

A app cobre hoje 7 topologias (boost-CCM PFC, passive choke,
line reactor 1φ/3φ, buck-CCM DC-DC, **flyback DCM/CCM**,
**interleaved boost PFC 2φ/3φ** — interleaved shipped em
`873106f`, flyback em `6bdf51d`, buck em `c90f2ee`). Estas 2
propostas restantes alargam o escopo para inversores grid-tie
e DC-DC isolados de média potência — cada uma é independente
e pode entrar na sequência preferida pela engenharia.

| Change ID                          | Tamanho | Descrição |
|------------------------------------|---------|-----------|
| `add-lcl-grid-tie-filter`          | XL      | Filtro LCL trifásico para inversores grid-tie (PV / wind / V2G). Primeira topologia **multi-inductor** + primeira com **standards-as-design-constraint** (IEEE 1547, IEC 61727). Bode plot + Bode na aba Análise. |
| `add-psfb-output-choke`            | M       | Output choke do phase-shifted full-bridge (telecom 1–5 kW, EV charger isolado). Primeira topologia **secondary-side**. Math é buck-CCM com `f_sw_eff = 2·f_sw`. |

**Dependências cruzadas**:

- `add-lcl-grid-tie-filter` introduz o wrapper multi-inductor
  (``MultiInductorDesignResult`` + ``ConverterModel.inductor_roles()``).
  Flyback (`6bdf51d`) e interleaved-boost (`873106f`) shipparam
  sem o wrapper — o engine trata o primário / per-phase como
  "the inductor" e expõe os outros via campos Optional no
  DesignResult. O wrapper só vira pré-requisito real para LCL
  onde os 3 indutores têm papéis distintos.
- `add-psfb-output-choke` depende implicitamente do
  `add-buck-ccm-topology` (já arquivado). Ordem:
  buck (✓) → PSFB.

**Roadmap sugerido (60 dias)**: PSFB → LCL (full multi-inductor
+ standards). Após os 2, o app cobre ~85% do mercado de
power-magnetics design.

### Mudanças arquivadas (34 em `archive/`)

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
- `add-flyback-topology` — coupled-inductor isolado DCM + CCM
  (5–150 W: wall adapters, USB-PD bricks, LED drivers,
  aux supplies). Primeira **multi-winding magnetic** do app
  (Np / Ns + turns ratio + window split + L_leak + RCD
  snubber). DesignResult ganha 11 campos Optional para
  flyback-only metrics (Lp/Np/Ns/Ip/Is/V_drain/V_diode/
  P_snubber/...). Schematic com dot convention + air-gap
  notch; Análise card empilha Ip + Is no top axis. Datasheet
  ``_SAFETY_FLYBACK`` (IEC 62368-1 reinforced insulation
  checklist). 39 testes (TI UCC28780 EVM benchmark) + 13
  leakage table tests. Itens deferidos: 4-D cartesian
  optimizer (mat × core × pri_wire × sec_wire), full IEC
  62368 calculation, manufacturing-spec winding-sequence —
  cada um vira sua própria change.
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

**v6 (CLI + manufacturing + simulator export — May 2026)**
- `add-cli-headless-runner` — 10 subcomandos `magnadesign`
  (design / sweep / cascade / worst-case / compliance /
  datasheet / mfg-spec / report / circuit / catalog) com
  output JSON-default + ``--pretty`` + exit codes
  Unix-conventional. Phase 6 ``validate`` deferido (depende
  do reference set).
- `add-manufacturing-spec-export` — módulo
  `manufacturing/` com winding-layout solver, IEC 60085
  insulation-class lookup, IEC 61558 hi-pot calculator,
  6-row acceptance test plan; writers PDF (4-page vendor-
  quotable, ReportLab) + XLSX (Specs / BOM / Tests, openpyxl).
  CLI ``mfg-spec`` registrado.
- `add-circuit-export` — módulo `export/` com L(I) table
  builder + 3 emitters: LTspice ``.subckt`` (B-source flux
  integrator + table() PWL), PSIM Saturable-Inductor fragment
  (paste-into-element), Modelica package
  (CombiTable1Ds-based ``model PFCInductor``). CLI
  ``circuit`` registrado.
- `add-crash-reporting` — módulo `telemetry/` com Sentry-SDK
  glue (opt-in, defensive imports), consent state machine
  (QSettings + JSON fallback), per-event scrubber (paths /
  emails / blobs / project-file breadcrumbs), kill-switch env
  var, ``track_event(name, properties)`` analytics helper com
  pluggable backend.
- `redesign-ui-flow-v3` — shipped organicamente: Spec drawer
  + 4 áreas reais na sidebar + ProjetoPage com 6 tabs
  (Núcleo / Análise / Validar / Worst-case / Compliance /
  Exportar).
- `ui-refactor-followups` — score table, theme_changed
  signal, animações 300/250 ms para ``set_view`` + ``request_
  explode``, camera_changed → OrientationCube live sync,
  schematic DPR + theme tests, ``docs/UI.md`` cross-linked
  do README + POSITIONING. Visual-regression baseline e
  README screenshot refresh deferidos.

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
