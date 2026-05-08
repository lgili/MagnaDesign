# Positioning — MagnaDesign

> Sumário humano da matriz de diferenciais. A versão executável vive em
> `src/pfc_inductor/positioning.py` e o `tests/test_positioning.py`
> garante que ambos não divergem.

## Pitch (uma frase)

Ferramenta especializada em projeto de indutores de PFC para inversores
de compressores de geladeira (200–2000 W, entrada universal). Fiel à
física (rolloff DC bias, iGSE, Dowell, térmico iterativo) e desenhada
para o engenheiro **decidir**, não só calcular.

## Contexto

A pergunta a se fazer antes de mais um esforço open-source: *o que
exatamente este projeto entrega que os existentes não entregam?* O
mercado tem três classes de ferramenta:

1. **Open-source acadêmico** — FEMMT (Paderborn), AI-mag (ETH), MAS
   (OpenMagnetics). Fortes em FEM, dados, e otimização teórica; fracos
   em projeto end-to-end com decisões de produto.
2. **Comercial cloud** — Frenetic AI. Fortes em UX e otimização paga;
   fechado, sem controle do engenheiro.
3. **Calculadoras de fabricante** — Magnetics Inc Designer, Coilcraft
   selector. Restritos a um único catálogo.

Nada disso atende um engenheiro de inversor que precisa **escolher**
um indutor com custo, fornecedor brasileiro e topologia PFC específica
em mente.

## Os sete diferenciais defendidos

A lista vive em `positioning.py::DIFFERENTIALS`. Adicionar um diferencial
exige justificativa por escrito (ADR 0001). Removê-lo exige outra. Os
testes em `tests/test_positioning.py` impedem drift silencioso.

### 1. PFC topology specialização

Matemática de boost CCM, choke passivo de linha e reator de linha
(1ph + 3ph) embutidas end-to-end — forma de onda real `iL(t)`,
worst-case low-line, ripple `D(t)`, modelo cap-DC-link com pulso
half-cosine para conformidade IEC 61000-3-2. Outros tools são
genéricos; FEMMT, MAS e AI-mag tratam o transformador / indutor como
caixa-preta sem topologia anexa.

### 2. Modelo de custo no otimizador

`$/kg` de material + `$/m` de fio entram diretamente na função objetivo
do Pareto. Frenetic cobra caro por isso; ferramentas open não têm.
Nosso ngsweep otimiza simultaneamente perdas, volume, custo e margem
de saturação.

### 3. Otimizador de Litz com critério Sullivan

Recomenda diâmetro de strand e número de strands para um alvo AC/DC,
com critério clássico Sullivan + estimativa Dowell. Salva o resultado
como novo fio na base de dados. Built-in, sem dependências externas.

### 4. Comparar 2–4 designs lado a lado

Diff-aware highlighting (verde/vermelho), export HTML/CSV. Estilo
Magnetics Inc Designer, mas sem amarrar o usuário a um catálogo de
fabricante. O CompareDialog suporta até 4 colunas.

### 5. Loop B–H no operating point

Trajetória ao longo do meio-ciclo de rede + segmento do ripple, sobre
a curva estática. Valida visualmente a margem de saturação. Nenhuma
outra ferramenta open-source implementa essa visualização —
geralmente mostram só DC `H_peak` numérico.

### 6. UX moderna PySide6 com light/dark

Design system Linear/Notion-style, dashboard de 9 cards, 3D core
viewer com PyVista (vistas ortográficas + iso), ícones SVG inline
(Lucide), schematic procedural por topologia. Apps de engenharia
geralmente são feios — esse não é.

### 7. Vendors brasileiros + UI em português

Thornton, Magmattec, Dongxing na base de dados; terminologia técnica
em PT-BR; cost model com BRL/kg como opção. Mercado brasileiro de
inversores que ninguém atende oficialmente — nem MagInc nem Coilcraft
têm presença local relevante.

## Matriz competitiva (resumo)

| Diferencial            | FEMMT | MAS | AI-mag | Frenetic | MagInc | Coilcraft |
|------------------------|:-----:|:---:|:------:|:--------:|:------:|:---------:|
| PFC topology           |   ✗   |  —  |   ✗    |    ≈     |   ✗    |     ✗     |
| Modelo de custo        |   ✗   |  —  |   ✗    |    ✓     |   ✗    |     ✗     |
| Litz Sullivan          |   ≈   |  —  |   ✗    |    ✓     |   ✗    |     ✗     |
| Multi-design compare   |   ✗   |  —  |   ✗    |    ≈     |   ✓    |     ✗     |
| B–H loop op-point      |   ✗   |  —  |   ✗    |    ✗     |   ✗    |     ✗     |
| UX polida              |   ≈   |  —  |   ✗    |    ✓     |   ≈    |     ✓     |
| Vendors BR             |   ✗   |  ✗  |   ✗    |    ✗     |   ✗    |     ✗     |

✓ = atende, ≈ = atende parcialmente, ✗ = não atende, — = não se aplica.

## Quando *não* usar este projeto

Honestidade com o usuário:

- **Você precisa de FEM 3D** → use FEMMT ou Ansys Maxwell. Nosso
  ``add-fea-validation`` chama FEMM 2D-axisymmetric / FEMMT como
  *validador* do projeto analítico, não como ferramenta primária.
- **Você está projetando transformador, não indutor de PFC** → o
  domínio é PFC choke. Outras topologias funcionam mas a UI não foi
  desenhada para elas.
- **Você precisa de uma API/CLI batch** → ainda somos uma app desktop.
  As funções core (em `pfc_inductor.physics`, `topology`, `design`)
  são puras e usáveis programaticamente, mas sem CLI dedicada hoje.

## Próximos diferenciais (roadmap)

Documentados como propostas em `openspec/changes/`:

- `add-circuit-export` — emitir subcircuitos LTspice / PSIM / Modelica
  do indutor projetado.
- Cobertura completa de **DCM** e **boundary mode** PFC além do CCM.
- Importador automático de catálogos vendor → MAS schema.

Cada novo diferencial deve passar pelo critério em ADR 0001:
*"reduz uma decisão real do engenheiro?"*. Se a resposta for não,
fica fora.
