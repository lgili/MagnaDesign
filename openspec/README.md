# OpenSpec — PFC Inductor Designer

Estrutura de propostas e tarefas para evoluir o aplicativo. Convenção
[OpenSpec](https://openspec.dev): cada melhoria fica em
`openspec/changes/<id>/` com:

- `proposal.md` — por que, o que muda, impacto
- `tasks.md` — passos concretos de implementação (checklist)
- `design.md` — detalhes técnicos (apenas para mudanças complexas)
- `specs/<capability>/spec.md` — requisitos formais com cenários
  GIVEN/WHEN/THEN, no formato OpenSpec

## Mudanças propostas

| Change ID                     | Tamanho | Diferencial | Dep deps externas |
|-------------------------------|---------|-------------|-------------------|
| `add-fea-validation`          | XL      | **Único no mercado open-source** | FEMM (xfemm) |
| `add-bh-loop-visual`          | S       | Polimento didático | nenhuma |
| `add-multi-column-compare`    | M       | UX que comerciais cobram caro | nenhuma |
| `add-litz-optimizer`          | M       | Fechar lacuna vs. SFDT | nenhuma |
| `add-cost-model`              | M       | Decisão de compra | nenhuma |
| `add-similar-parts-finder`    | S       | UX padrão Coilcraft | nenhuma |
| `add-circuit-export`          | M       | Integração com fluxo de simulação | nenhuma |

## Ordem sugerida de execução

1. **`add-bh-loop-visual`** — pequeno, alto impacto visual, valida o
   pipeline iGSE/rolloff num único gráfico. Bom warm-up.
2. **`add-similar-parts-finder`** — pequeno, reusa otimizador, dá sensação
   de "biblioteca completa" ao usuário. Sem dependências externas.
3. **`add-multi-column-compare`** — UX significativo, complementa o
   otimizador, sem deps.
4. **`add-cost-model`** — toca em vários módulos mas cada toque é raso;
   destrava ranking por custo no otimizador.
5. **`add-litz-optimizer`** — vale fazer depois de `add-cost-model` para
   o otimizador já considerar custo do Litz.
6. **`add-circuit-export`** — médio, novo módulo isolado.
7. **`add-fea-validation`** — XL, dependência externa (FEMM); deixar por
   último porque é o mais arriscado e o mais transformador.

## Status — v2 (concluído)

- [x] `add-bh-loop-visual`
- [x] `add-similar-parts-finder`
- [x] `add-multi-column-compare`
- [x] `add-cost-model`
- [x] `add-litz-optimizer`
- [ ] `add-circuit-export` (pulado pelo usuário)
- [x] `add-fea-validation` (toroide v1; EE/ETD/PQ ficou para v2; requer FEMM/xfemm instalado para executar o solver)

---

## v3 — interoperabilidade e posicionamento

Após survey do open-source (FEMMT, OpenMagnetics MAS, AI-mag, Princeton
MagNet), 4 propostas para a próxima fase:

| Change | Tamanho | Depende de | Razão |
|---|---|---|---|
| `add-mas-schema-adoption` | XL | — | Adotar formato JSON do PSMA-incubated MAS; vira cidadão do ecossistema |
| `add-mas-catalog-import` | M | mas-schema | Importar 410 mat × 4 350 fios da OpenMagnetics: ~8× nosso DB |
| `add-femmt-integration` | L | — | Substituir FEMM stub por FEMMT (cross-platform, pip-installable, cobre EE/ETD/PQ) |
| `protect-differentials` | S | — | Documentar e proteger PFC focus + custo + Litz + UX + vendors BR |

### Ordem sugerida v3

1. **`protect-differentials`** (S) — primeiro porque é o guarda-chuva
   estratégico. Deveria preceder qualquer trabalho que toque em escopo.
2. **`add-femmt-integration`** (L) — independente do MAS, alto impacto
   de UX (resolve o pain point macOS+FEMM que o usuário enfrenta hoje).
3. **`add-mas-schema-adoption`** (XL) — refator profundo dos models;
   pode ser adiado mas habilita o item 4.
4. **`add-mas-catalog-import`** (M) — depende do item 3; fácil quando
   ele estiver pronto.

### Status v3

- [x] `protect-differentials` (ADR + POSITIONING + AboutDialog + CONTRIBUTING + 14 testes)
- [x] `add-femmt-integration` (Python 3.12 + `[fea]` extra com scipy<1.14 e setuptools<70; ONELAB setup em `docs/fea-install.md`; toroide-only v1; EE/ETD/PQ próximo)
- [x] `add-mas-schema-adoption` (camada `models/mas/` com adapters bidirecionais; loader auto-detecta MAS vs legado; `data/mas/{materials,cores,wires}.json` gerados via `scripts/migrate_to_mas.py`; 8 testes round-trip + format-detection)
- [ ] `add-mas-catalog-import`
