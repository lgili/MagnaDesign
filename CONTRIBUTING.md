# Contribuindo

Bem-vindo. Este projeto é uma **ferramenta especializada** — não um
framework genérico. Antes de abrir um PR significativo, leia
[`docs/POSITIONING.md`](docs/POSITIONING.md) e a
[ADR 0001](docs/adr/0001-positioning.md).

## Setup

```bash
uv venv --python 3.13
uv pip install -e ".[dev]"
.venv/bin/python -m pytest        # 85+ testes precisam passar
.venv/bin/python -m pfc_inductor  # rodar a UI
```

## Estilo

- Python 3.11+. Type hints onde fizer sentido (não obrigatório em
  expressões internas).
- Pydantic v2 para todo modelo de dados.
- PySide6 puro — sem Qt frameworks externos (PyQt5 etc.).
- QSS centralizado em `ui/style.py`; **nunca** colocar cor hard-coded
  fora de `ui/theme.py`.
- Português para microcopy de UI; inglês para nomes de função e
  comentários técnicos.

## Scope guardrails — quando dizer NÃO

Os 7 diferenciais que definem o produto:

1. **PFC topology specialização** (boost CCM + choke passivo)
2. **Modelo de custo** $/kg + $/m no otimizador
3. **Otimizador de Litz** com critério Sullivan
4. **Comparar 2–4 designs** lado a lado
5. **Loop B–H** no operating point
6. **UX polida** PySide6 com light/dark + 3D viewer
7. **Vendors BR + UI em português**

PRs que **trocam** qualquer um desses por algo "mais geral" ou
"mais simples" devem ser declinados, não aceitos. Se o PR remove
funcionalidade defensável, abra issue antes de codar.

### Quando declinar — cenários típicos

| PR propõe… | Resposta |
|---|---|
| Solver FEM próprio | Redirecionar para `add-femmt-integration` |
| "Generalizar para qualquer topologia" | Decline; defender PFC focus |
| Remover modelo de custo | Decline; é diferencial-chave |
| Trocar PySide6 por Tkinter/web | Decline; UX seria sacrificada |
| Remover vendors BR | Decline; é o moat de mercado |
| Migrar UI para inglês-only | Decline; bilingue protegido |

### Quando aceitar com gosto

- Polimento de UX dentro do design system existente
- Calibração de coeficientes de Steinmetz / rolloff contra
  datasheet de vendor
- Novos materiais/núcleos/fios na base de dados
- Cobertura de testes nas físicas (Dowell, iGSE, thermal)
- Performance do otimizador (Pareto sweep)
- Integração com FEMMT, OpenMagnetics MAS (são as direções
  declaradas)
- Bug fixes em qualquer canto

## OpenSpec

Mudanças não-triviais devem ter uma proposta em
`openspec/changes/<id>/` antes do código:

- `proposal.md` — Why · What changes · Impact
- `tasks.md` — checklist numerada
- `specs/<capability>/spec.md` — requisitos formais (cenários
  GIVEN/WHEN/THEN)
- `design.md` (opcional) — quando há decisões técnicas profundas

Veja propostas existentes em [`openspec/changes/`](openspec/changes/).

## Testes

Tudo que adiciona física/cálculo precisa de teste de regressão:

- Casos contra livros (Erickson, Hurley/Wölfle, Mohan) ou contra
  app notes de vendor (Magnetics, Ferroxcube)
- Cobertura idealmente ≥ 80% nos módulos `physics/`, `topology/`,
  `optimize/`, `compare/`, `fea/`, `visual/`
- UI: smoke tests offscreen com `QT_QPA_PLATFORM=offscreen`

## Commits

Mensagens em inglês imperativo, presente:

```
add iGSE for ripple loss
fix: rolloff cap to ±Bsat·1.05
docs: positioning matrix
```

Co-authoring com IA permitido se o trabalho foi assistido. Mantenha
PRs focados — uma melhoria por PR.

## Como reportar bugs

Issue com:

1. Versão (`pfc_inductor.__version__`)
2. SO + Python
3. Spec usado (Vin, Vout, P, fsw, ripple)
4. Design selecionado (material/core/wire)
5. O que esperava vs. o que aconteceu
6. Screenshot se for visual

Crashes na UI: incluir stack trace do terminal.
