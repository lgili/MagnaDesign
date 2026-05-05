# AC line reactor topology (50/60 Hz harmonic mitigation)

## Why

Boa parte dos inversores que usamos para compressores são tradicionais —
**retificador a diodo + barramento CC + VSI** — sem PFC ativo. Para
reduzir THD na corrente de entrada e atender IEC 61000-3-2 / IEEE 519,
adiciona-se um **reator de linha** (AC choke) na entrada do retificador,
dimensionado por **% de impedância em 50/60 Hz**.

A física é diferente do boost CCM e do choke passivo que já temos:

- Frequência de operação é a da rede (não fsw).
- Núcleo típico é **aço-silício laminado** (M5/M19/M27), com Bsat ~1.7 T
  e μᵣ ~5000 — não powder/ferrite.
- Dimensionamento por **% de impedância** (3%, 5% ou 8% típicos), não
  por ripple ratio.
- Indutância resultante é grande (1–20 mH), perdas dominadas pelos
  harmônicos do retificador (5ª, 7ª, 11ª, 13ª).
- Sem ripple HF; sem rolloff de DC bias (fluxo só vai até Bsat).

Hoje o app não tem nem topologia, nem material adequado para projetar
isso. Os engenheiros usam planilha à parte.

## What changes

- Nova topologia `line_reactor` em `Topology` Literal.
- Novos campos no `Spec`: `n_phases` (1 ou 3), `pct_impedance`
  (%), `I_rated_Arms`, `V_line_Vrms` interpretado como L-L para 3-φ
  e L-N para 1-φ.
- Novo módulo `topology/line_reactor.py` com:
  - cálculo de Z_base por fase
  - L_required a partir de %Z e f_line
  - I_pk = √2·I_rated
  - estimativa de THD pela regra empírica
    `THD% ≈ 75/√(%Z)` (Pomilio, Erickson Cap 18)
  - voltage drop em rated current = %Z (definição)
- Engine despacha pelo `topology`: para line reactor, sem ripple
  HF, B_pk vem do fluxo fundamental
  `B_pk = √2·V_L_rms / (ω·N·Ae)`, perdas só DC + iGSE @ f_line.
- Novos materiais curados de **aço-silício**: M5 (0.35mm),
  M19 (0.50mm) e amorfo Metglas 2605SA1 — Bsat alto, perdas
  baixas em 50/60 Hz.
- `DesignResult` ganha campos opcionais: `pct_impedance_actual`,
  `voltage_drop_pct`, `thd_estimate_pct`.
- UI: bloco "REATOR DE LINHA" no spec panel aparece quando
  topologia é `line_reactor`; outros blocos (boost/PFC) ficam ocultos.
- Result panel mostra %Z atual, queda de tensão em rated, THD
  estimado.

## Impact

- Affected capabilities: NEW `line-reactor`
- Affected modules: NEW `topology/line_reactor.py`; UPDATE
  `models/spec.py` (novos campos + Topology), `models/result.py`
  (campos opcionais), `design/engine.py` (despacho), `data/mas/*`
  (materiais aço-silício), `ui/spec_panel.py` (bloco reator),
  `ui/result_panel.py` (métricas extras).
- Não quebra projetos existentes — campos novos têm default e a
  topologia padrão continua sendo `boost_ccm`.
