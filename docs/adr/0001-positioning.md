# ADR 0001 — Positioning

- **Status**: accepted
- **Date**: 2026-05-05
- **Owners**: Luiz Gili
- **Supersedes**: —

## Context

`docs/POSITIONING.md` lists seven diferenciais que o projeto defende
explicitamente. Sem um critério de aceitação, qualquer feature
"interessante" entra na backlog e o projeto vira um clone genérico de
FEMMT + Frenetic + MAS. Esse ADR fixa o critério.

## Decision

**Toda PR que introduz capability nova deve responder por escrito a uma
das seguintes perguntas, no `proposal.md` da OpenSpec change:**

1. *Reduz uma decisão real que o engenheiro de PFC faz hoje?*
2. *Aumenta a fidelidade física de um cálculo já existente?*
3. *Cobre uma topologia PFC ainda não suportada?*

Se a resposta for "não" para as três, a PR é rejeitada. "Seria legal
ter" não é justificativa suficiente.

## Os sete diferenciais protegidos

A lista canônica vive em `src/pfc_inductor/positioning.py`:

1. `pfc_topology` — matemática PFC end-to-end embutida (boost CCM,
   choke passivo, reator de linha 1ph/3ph).
2. `cost_model` — `$/kg` + `$/m` no Pareto do otimizador.
3. `litz_optimizer` — critério Sullivan com salvar-como-novo-fio.
4. `multi_compare` — comparar 2–4 designs lado a lado, diff-aware.
5. `bh_loop` — trajetória B–H no operating point sobre a curva estática.
6. `polished_ux` — design system v2 (MagnaDesign), 3D viewer, dashboard.
7. `br_market` — vendors brasileiros (Thornton, Magmattec, Dongxing) +
   UI em PT-BR.

Adicionar um oitavo exige outro ADR. Remover qualquer um exige outro
ADR. Modificar a `coverage` matrix em `positioning.py` é livre — o
mundo open-source se mexe e a matriz precisa refletir isso.

## Consequences

- **Boa**: O projeto não se dispersa em tópicos genéricos como FEM 3D
  ou treinamento de redes neurais. Quem quer FEM 3D usa FEMMT; quem
  quer ANN usa AI-mag.
- **Boa**: O `tests/test_positioning.py` falha em CI se um diferencial
  some do código. Drift silencioso é impossível.
- **Limitação**: Algumas features tecnicamente interessantes ficam de
  fora. Um exemplo: importar o LTspice em tempo-real para um
  co-simulador integrado seria útil, mas excede o escopo "indutor de
  PFC para inversor de compressor". Fica como ferramenta auxiliar via
  `add-circuit-export`.

## References

- `docs/POSITIONING.md` — versão humana da matriz competitiva.
- `src/pfc_inductor/positioning.py` — fonte de verdade machine-readable.
- `tests/test_positioning.py` — guardrails impedindo drift.
- `CONTRIBUTING.md` — política de scope guardrails (consumida por PRs).
