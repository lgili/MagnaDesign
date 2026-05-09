# MagnaDesign — Curso interno (apresentação)

Material de apresentação para o curso de uso do **MagnaDesign**:
estrutura LaTeX em `beamer + metropolis`, três casos reais de
referência (Boost PFC 1.5 kW, Reator de linha 22 kW, Flyback
65 W), e harness Python que gera todas as screenshots dos
widgets do app.

## Estrutura

```
presentation/
├── main.tex                 # Slide deck (LaTeX/Beamer)
├── Makefile                 # build + screenshots
├── theme/
│   └── magnadesign-colors.tex  # paleta sincronizada com a UI
├── sections/                # (vazio por enquanto — slides em main.tex)
├── scripts/
│   └── build_screenshots.py # harness que renderiza figures/
└── figures/                 # PNGs/PDFs incluídos pelo .tex
```

## Como compilar

### Pré-requisitos

* TeX Live 2023+ com `metropolis` (`tlmgr install metropolis
  beamer fontspec`)
* LuaLaTeX (vem com TeX Live; necessário pra fonte Fira Sans
  do metropolis)
* `latexmk` (também TeX Live)
* Python 3.12 + venv do projeto em `../.venv/bin/python`

### Build da apresentação

```bash
cd presentation
make           # → main.pdf
```

### Regenerar todas as screenshots

Se você modificar os widgets do app ou os exemplos de
referência no harness:

```bash
make screenshots
make           # rebuild com as figuras novas
```

### Modo watch (live preview enquanto edita)

```bash
make watch
```

Recompila automaticamente cada `Ctrl-S` no `main.tex`.

## Os três exemplos de referência

| # | Topologia | Specs | Referência de mercado |
|---|---|---|---|
| 1 | **Boost PFC CCM** | 85–265 V$_{rms}$ → 400 V, 1.5 kW, 100 kHz | TI UCC28019 ref-design + Magnetics Kool-Mu 0077439A7 toroid |
| 2 | **Line reactor 3φ** | 400 V$_{LL}$, 22 kW, 32 A, 3 % impedância | ABB MCB-32 / Schaffner FN3220 series |
| 3 | **Flyback DCM** | 85–265 V$_{rms}$ → 19 V/3.4 A, 65 W, 65 kHz | TI UCC28911 EVM (laptop adapter), PQ20/16 N97 |

Os três foram escolhidos para exercitar as features
distintas do app:

* **Boost CCM** ativa as 5 abas do FEA dialog, o swept-FEA
  L(I) e o B-H operacional — caso "completo" para a demo
  inicial.
* **Line reactor** ativa o card de **harmônicas IEC 61000-3-2**
  e demonstra o auto-fallback FEMMT → FEMM legacy quando
  N > 150 turns.
* **Flyback** demonstra o render de **2 windings** (primary
  + secondary com cores distintas) na geometry view, e o
  comportamento DCM em formas de onda.

## Substituindo screenshots por prints reais

O harness emite **placeholders** (PNGs com texto `"[ screenshot
pendente ]"`) para telas que precisam do app rodando ao vivo —
SpecDrawer, Otimizador Pareto, Cascade page, Compare dialog,
Export, viewer 3D, formas de onda do app real.

Para substituir por prints reais:

1. Abra o app: `python -m pfc_inductor`
2. Carregue um dos 3 exemplos (ou crie equivalente)
3. Capture com `Cmd-Shift-4` (macOS) ou Snipping Tool (Windows)
4. Salve como PNG no `figures/` com o **mesmo nome** que o
   placeholder
5. `make` rebuild — o LaTeX usa o arquivo novo automaticamente

Lista de placeholders:

```
example1_spec.png            ← Spec drawer (boost)
example1_formas_onda.png     ← FormasOndaCard (boost)
example2_spec.png            ← Spec drawer (line reactor)
example2_fea_dispatch.png    ← Log do auto-fallback
example3_spec.png            ← Spec drawer (flyback)
example3_formas_onda.png     ← FormasOndaCard (flyback)
example3_fea_summary.png     ← FEA Summary (flyback)
feature_otimizador_pareto.png ← Pareto front
feature_cascade.png          ← Cascade Top-N table
feature_compare.png          ← Compare designs dialog
feature_export.png           ← Datasheet HTML render
feature_3d.png               ← Qt3D viewer
logo-placeholder.pdf         ← Logo institucional
```

## Tema visual

O arquivo `theme/magnadesign-colors.tex` redefine as cores do
metropolis usando a paleta da UI (`accent_violet`, `warning`,
`success`, `danger`, etc. — extraídos de
`src/pfc_inductor/ui/theme.py`). Mudou paleta no app? Atualize
aqui também — uma única source of truth.

## Tempo de talk estimado

~ 30–45 minutos com Q&A (36 slides). Ajuste expandindo / cortando
seções conforme necessário — `\section{...}` agrupa os
slides para que o `\tableofcontents` no slide 2 mantenha-se
limpo.
