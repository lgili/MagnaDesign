# PFC Inductor Designer

> Ferramenta especializada em projeto de indutores de PFC para inversores
> de compressores de geladeira (200–2000 W, entrada universal 85–265 Vac).

## Por que este projeto importa

Existem ferramentas open-source genéricas de magnéticos
([FEMMT](https://github.com/upb-lea/FEM_Magnetics_Toolbox),
[OpenMagnetics MAS](https://github.com/OpenMagnetics/MAS),
[AI-mag](https://github.com/ethz-pes/AI-mag)) e calculadoras de vendor
(Magnetics Inc, Coilcraft). Todas resolvem **uma fatia** do problema.
Este projeto resolve a fatia que ninguém atende:

- **Engenheiros de PFC** (boost CCM + choke passivo) que precisam de
  topologia-aware end-to-end — não de simulador FEM genérico.
- **Decisão de compra** com modelo de custo no Pareto do otimizador
  ($/kg de material + $/m de fio).
- **Mercado brasileiro** com vendors locais (Thornton, Magmattec) e UI
  em português.
- **UX moderna** (PySide6 com light/dark, viewer 3D, design system
  Linear-style) num app que o engenheiro usa todo dia.

Comparação completa em [`docs/POSITIONING.md`](docs/POSITIONING.md).
Ver também [ADR 0001 — Positioning](docs/adr/0001-positioning.md).

## O que faz

- **PFC ativo boost em CCM** + **choke passivo de linha** (50/60 Hz)
- **Otimizador Pareto** sobre cores × wires × materials, ranqueado
  por perda, volume, temperatura ou custo
- **Comparador** de até 4 designs lado a lado com export HTML/CSV
- **Otimizador de Litz** (Sullivan strand criterion) com salvar como
  novo fio
- **Loop B–H** no operating point + viewer 3D do core e bobinagem
- **Achar peças similares** entre vendors com tolerâncias configuráveis
- **Editor de banco de dados** integrado para adicionar materiais,
  cores, fios

### Modelagem com fidelidade de bancada

- Rolloff de permeabilidade vs DC bias (curvas calibradas por família:
  Magnetics Kool Mu/MPP/HighFlux/XFlux, Micrometals, Magmattec)
- iGSE para perda no núcleo (não Steinmetz puro)
- Perda AC no cobre via Dowell (round wire e Litz)
- Acoplamento térmico iterativo (ρ_cu varia com T)
- Forma de onda real do indutor PFC ao longo do ciclo de rede
- Custo BOM derivado de massa × $/kg + comprimento × $/m

## Setup rápido

```bash
uv venv --python 3.12   # FEMMT 0.5.x não suporta 3.13 ainda
uv pip install -e ".[dev,fea]"
pfc-inductor-setup       # baixa ONELAB + configura tudo (macOS/Linux/Win)
uv run pfc-inductor      # abre a UI
```

`pfc-inductor-setup` é cross-platform (macOS Intel + Apple Silicon,
Linux x86_64, Windows x86_64) e idempotente. Na primeira execução do
app, se ele detectar ONELAB ausente, abre o mesmo diálogo
automaticamente. Para apenas verificar o estado: `pfc-inductor-setup
--check`. Detalhes do passo-a-passo manual em
[`docs/fea-install.md`](docs/fea-install.md).

Tema claro por padrão; alternar em **Tema escuro/claro** no canto
direito da toolbar, ou via `PFC_THEME=dark`.

## Fluxo de uso (passo a passo)

A janela principal tem três colunas: **especificação** (esquerda),
**plots** (centro) e **resultado** (direita). O cálculo é em tempo
real — qualquer mudança na coluna esquerda recalcula tudo.

### 1. Definir a especificação

Coluna esquerda, de cima pra baixo:

| Bloco | Campo | Significado |
|-------|-------|-------------|
| TOPOLOGIA | Tipo | `PFC ativo (boost CCM)` para inversor de compressor com PFC ativo; `choke passivo` para filtro 50/60 Hz; `reator de linha` para drives diodo + DC-link sem PFC ativo (ver seção dedicada abaixo) |
| ENTRADA AC | Vin mín / máx | Faixa universal típica: 85–265 Vrms. O dimensionamento usa `Vin mín` (worst case de corrente de pico) |
| | Vin nominal | Operação típica (220 V no Brasil) — usado nos cálculos de perda média |
| | f rede | 50 ou 60 Hz |
| CONVERSOR | Vout (DC bus) | 400 V típico para boost universal |
| | Pout | Potência de saída em W |
| | Eficiência | 0.97 é o ponto de partida razoável |
| | fsw | Frequência de chaveamento em kHz (boost típico 50–100 kHz) |
| | Ripple pico-pico | % do `I_pk`; padrão 30% |
| TÉRMICO | T ambiente / máx enrolamento | Limite do enrolamento (100 °C para esmalte classe F é seguro) |
| | Ku máx | Fator de uso da janela (0.40 = 40% — limite prático com bobinagem manual) |
| | Margem Bsat | Margem de segurança para saturação (0.20 = usa no máx 80% do Bsat do material) |

### 2. Escolher material, núcleo e fio

Bloco **SELEÇÃO** (esquerda, em baixo):

- **Material**: powder cores (Kool Mu, HighFlux, MPP, XFlux, Magmattec) para choke PFC com DC bias alto; ferrites (N87, N95) só para baixo bias.
- **Núcleo**: a lista é filtrada para mostrar só cores compatíveis com o material. O texto inclui Ve (cm³) e AL (nH) — comece pelo menor que ainda dê designs sem warnings.
- **Fio**: AWG sólido para PFC convencional; clique **Litz** na toolbar quando fsw alto + corrente alta (efeito skin/proximity importa).

Marque **Mostrar apenas curados** se quiser esconder os ~410 materiais e ~1380 fios importados do catálogo OpenMagnetics — só os curados têm Steinmetz/rolloff calibrados.

### 3. Ler o resultado

Coluna direita:

- **L requerida vs L atual**: a topologia dita L mínimo para satisfazer ripple; o app escolhe N pra encostar nele. Se `L atual << L requerida`, ripple vai estourar.
- **N voltas** + **fator de uso** (Ku): se Ku > 0.40 a bobinagem é apertada demais.
- **B pico**: tem que estar abaixo de `Bsat × (1 − margem)`. Warning aparece se passar.
- **Perdas**: cobre (DC + AC), núcleo (iGSE), total. AC do cobre só importa em alto fsw + N alto.
- **Temperatura**: estimativa do gradiente convectivo ambiente → enrolamento.
- **Custo BOM**: massa de núcleo × $/kg + comprimento de fio × $/m. Aparece "—" para entradas sem cost data (catálogo OpenMagnetics).

Os plots no centro mostram a forma de onda do indutor ao longo do ciclo de rede, a curva de rolloff μ(H) com o ponto de operação destacado, e — se você abrir o **B-H loop** — a trajetória dinâmica completa.

### 4. Iterar com os otimizadores

Os botões da toolbar são pra quando o design manual não resolve:

- **Otimizador**: varre cores × fios para o material atual (ou todos), ranqueia por perda / volume / temperatura / custo / score combinado. Mostra o Pareto frontal num scatter.
- **Comparar**: até 4 slots de design lado a lado, exporta HTML.
- **Similares**: encontra cores equivalentes em outros vendors (útil pra second-source).
- **Litz**: dado `fsw` e `I_pk`, sugere número de strands × diâmetro pelo critério de Sullivan.
- **Validar (FEA)**: cross-check numérico — ver próxima seção.

## Reator de linha (drives diodo + DC-link)

Boa parte dos inversores que usamos são tradicionais — **retificador a
diodo + barramento CC + VSI**, sem PFC ativo. Para reduzir THD na
corrente de entrada e atender IEC 61000-3-2, adiciona-se um **reator
de linha** na entrada do retificador, dimensionado por **% de
impedância** em 50/60 Hz.

### Quando usar

- Drive de compressor sem PFC ativo (econômico, robusto).
- Necessidade de cortar THD da corrente de entrada de ~80% (com cap
  só) para 25–45% (com reator).
- Limitação de corrente de inrush durante carga inicial dos caps.

### Como configurar

Selecione **Topologia → "Reator de linha (50/60 Hz)"**. O bloco
**REATOR DE LINHA** aparece na coluna esquerda com:

- **Fases**: 3φ (típico industrial) ou 1φ (residencial).
- **V de linha**: para 3φ é V_LL (380, 440, 480 V), para 1φ é V_LN
  (220, 240 V).
- **I nominal (RMS)**: corrente contínua do drive na linha (não no
  motor).
- **% impedância alvo**: 3% (filtro leve) / 5% (padrão) / 8% (pesado).

O motor calcula `L = (%Z × V_phase / I_rated) / (2π·f_line)`.

### Como ler o resultado

Os campos extras na coluna direita explicam o trade-off:

| Métrica | Significado |
|---------|-------------|
| **L atual** | Em mH (não µH — reator é grande). Ajustado para o N inteiro mais próximo |
| **% Z atual** | Impedância realizada com `L atual`. Pequena diferença em relação ao alvo é normal |
| **Queda de tensão** | V_L em rated current, em % de V_phase. **Por definição igual a %Z**. É o custo do reator: quanto mais filtro, mais drop |
| **THD estimada** | Estimativa empírica `THD% ≈ 75/√(%Z)` para retificador 6 pulsos com cap |

### Tabela rápida (regra de bolso)

| %Z | THD esperada | Voltage drop | L típico (380 V/30 A 60 Hz) |
|----|--------------|--------------|------------------------------|
| 3% | ~43% | 3.0% | 0.58 mH |
| 5% | ~33% | 5.0% | 0.97 mH |
| 8% | ~26% | 8.0% | 1.55 mH |

### Material recomendado

A DB curada inclui três opções de núcleo laminado (não use
ferrite/powder em reator de linha):

- **M19 (0.50 mm)**: aço-silício NGO, custo baixo, ~2.5 W/kg @ 1 T
  60 Hz. Workhorse para reatores comerciais.
- **M5 (0.35 mm)**: aço-silício GO, ~1.5 W/kg, melhor para reatores
  de alta eficiência.
- **Metglas 2605SA1**: amorfo Fe, ~0.25 W/kg (~6× menos perda que
  M5). Premium para drives premium ou aplicações offshore.

A coluna de seleção mostra apenas cores compatíveis com o material
escolhido. Comece com M19 + um EI de tamanho compatível com seu
I_rated.

## Validação por FEA

### Para que serve

Os números da coluna direita vêm de **fórmulas analíticas** (Ampere-turns,
rolloff vs DC bias, iGSE/Steinmetz, Dowell para AC). São rápidas e
calibradas, mas assumem geometria idealizada. **FEA** (Finite Element
Analysis) resolve as equações de Maxwell na geometria real — verifica
se as suposições do analítico se sustentam.

Use FEA quando:

- O design está perto da margem de saturação (`B_pk` alto).
- Você usou um core com gap grande (fringing flux importa, analítico
  subestima).
- Você quer documentar o design com um "second source" numérico antes
  de mandar para protótipo.
- Você suspeita que a curva de rolloff que você editou na DB está
  errada (FEA usa apenas μ_eff no operating point, sem extrapolar).

### Como rodar

Toolbar → **Validar (FEA)**. Abre uma janela modal com:

- **Status do backend**: indica qual solver será usado e a fidelidade
  esperada para a forma do core.
- **Design alvo**: resumo do que vai ser simulado (N, I_pk, L analítica).
- Botão **Validar com FEA** roda numa thread; tipicamente 2–10 s.

A primeira execução em uma máquina nova baixa o ONELAB e configura
tudo (~50 MB) — isso é coberto pelo `pfc-inductor-setup` documentado
acima.

### Como ler o resultado

| Linha | O que significa |
|-------|-----------------|
| **Indutância (FEA vs analítica)** | Erro percentual entre `L_FEA` (numérico) e `L_analytic` (fórmula). Verde se ≤ 5%, amarelo até 15%, vermelho acima |
| **B pico (FEA vs analítico)** | Mesma comparação para flux density |
| **Tempo de solução** | Wall-clock do solver FEM |
| **Confiança** | `alta` se ambos os erros < 5%; `média` < 15%; `baixa` > 15% |

#### O que cada faixa de erro indica

- **0–5%** (alta): o analítico está tracking a realidade. Pode aprovar
  o design com confiança.
- **5–15%** (média): erro típico de modelagem axissimétrica vs
  geometria 3D real, especialmente em EE-cores. Significa "o design
  funciona, ajuste seu Pout target em ~10% se quiser margem".
- **15–30%** (baixa): a geometria FEMMT está aproximando muito ou o
  rolloff não está calibrado pra esse ponto de operação. Inspecione
  o `notes` no rodapé do diálogo — costuma explicar a fonte do desvio.
- **> 30%**: provável bug na DB (Ae, le, Wa errados) ou na curva de
  rolloff. Refaça com o Editor de DB ou troque para um material
  curado conhecido.

#### Por forma de núcleo (fidelidade)

| Forma | Backend preferido | Erro típico esperado |
|-------|-------------------|----------------------|
| Toroide | FEMM (axissimétrico nativo) | < 5% |
| Toroide via FEMMT | FEMMT (mapeado para PQ-equivalente) | 30–80% (apenas ordem de grandeza) |
| EE / EI | FEMMT (perna central de área-equivalente) | 10–25% |
| ETD / PQ / RM | FEMMT (perna redonda nativa) | 5–15% |

Se você projeta toroides, vale instalar FEMM legado para melhor
fidelidade — o app detecta e usa automaticamente.

### Backends disponíveis

- **FEMMT** (padrão, cross-platform): Python + ONELAB. Configurado pelo
  `pfc-inductor-setup`. Cobre EE/ETD/PQ nativamente; toroide via
  PQ-equivalente.
- **FEMM/xfemm** (legado): binário externo. `brew install xfemm` no
  macOS, `apt install xfemm` no Linux, instalador 4.2 no Windows.
  Excelente para toroide. Forçar com `PFC_FEA_BACKEND=femm`.

A UI auto-detecta o backend ativo e escolhe o melhor por forma. Sem
nenhum dos dois instalado, o botão "Validar com FEA" fica desabilitado
com instruções na própria janela.

### O que **não** é validado pelo FEA

O modelo é **magnetostático** (single-frequency). Não cobre:

- Perdas AC do cobre (proximidade entre voltas, skin profundo). Use
  o **Otimizador de Litz** para isso.
- Perdas no núcleo dependentes da forma de onda. Use os números iGSE
  do app (calibrados pelo Steinmetz da DB).
- Térmico. Use o cálculo do app (acoplado iterativamente com ρ_cu).

FEA aqui é um sanity check de `L` e `B_pk`, não substitui a engenharia
térmica/perdas do resto do app.

## Estendendo a base de dados

Os arquivos em `data/*.json` são copiados ao diretório de dados do
usuário no primeiro launch. Adicione materiais, cores ou fios via menu
**Editar base de dados** na toolbar (editor JSON validado por pydantic).

### Catálogo OpenMagnetics MAS

A toolbar tem uma ação **Atualizar catálogo** que importa o catálogo
público da OpenMagnetics (~410 materiais ferrite/pó + ~1380 fios redondos
Elektrisola) para a sua biblioteca local. O catálogo fica em
`data/mas/catalog/{materials,wires}.json` e nunca sobrescreve dados
curados ou suas próprias edições — colisões por `id` são pretensas
para o conjunto curado/usuário, e itens novos do catálogo são
anexados.

Importante: os Steinmetz/rolloff dos materiais curados foram
calibrados manualmente; os do catálogo OpenMagnetics não. Use o filtro
**Apenas curados** na coluna de seleção e no otimizador para confiar
apenas nos números calibrados quando o ranking importar.

Também é possível disparar o import pela linha de comando:

```bash
.venv/bin/python scripts/import_mas_catalog.py --dry-run     # só conta
.venv/bin/python scripts/import_mas_catalog.py               # escreve
.venv/bin/python scripts/import_mas_catalog.py --source /path/MAS/data
```

Para atualizar a fonte vendorada (`vendor/openmagnetics-catalog/`),
veja o cabeçalho do `VERSION.txt` daquele diretório.

## Para desenvolvedores

### Rodar testes

```bash
uv run pytest
```

### Estrutura

```
src/pfc_inductor/
  models/        # Pydantic: Spec, Material, Core, Wire, Result
  physics/       # Rolloff, perdas Cu/Núcleo (iGSE), Dowell, térmico, custo
  topology/      # boost_ccm.py, passive_choke.py
  design/        # Motor de cálculo (orquestrador)
  optimize/      # Pareto sweep, Litz optimizer, similar-parts finder
  visual/        # Mesh 3D + B-H trajectory
  fea/           # Validação por FEA (FEMMT primário, FEMM legado)
  setup_deps/    # Instalador cross-platform (ONELAB + FEMMT config)
  compare/       # Multi-design comparison
  report/        # HTML reports (single + multi-column)
  ui/            # Janela principal, painéis, dialogs, design system
data/            # Bases de dados JSON (50 mat, 1008 cores, 48 fios curados)
data/mas/catalog/# Catálogo OpenMagnetics importado (~410 mat, ~1380 fios)
docs/            # POSITIONING.md, ADRs, fea-install.md
openspec/        # Propostas de mudanças versionadas
tests/           # Regressão contra textbooks + vendor app notes
vendor/          # OpenMagnetics MAS catalog (NDJSON), versionado
```

## Contribuir

Veja [`CONTRIBUTING.md`](CONTRIBUTING.md) — em particular a seção "Scope
guardrails" antes de propor mudanças significativas.

## Licença

(em definição)
