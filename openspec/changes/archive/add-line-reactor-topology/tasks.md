# Tasks — AC line reactor topology

## 1. Spec model

- [x] 1.1 Adicionar `"line_reactor"` ao Literal `Topology` em
      `models/spec.py`.
- [x] 1.2 Novos campos no `Spec`:
      - `n_phases: int = 3`
      - `pct_impedance: float = 5.0` (% de impedância da rede)
      - `I_rated_Arms: float = 30.0`
- [x] 1.3 Validador: `Vin_nom_Vrms` é L-L se `n_phases==3`, L-N se
      `n_phases==1`. `Vout_V`, `f_sw_kHz`, `ripple_pct` ignorados
      para line reactor.

## 2. Topology module

- [x] 2.1 `topology/line_reactor.py`:
      - `phase_voltage_Vrms(spec)`
      - `base_impedance_ohm(spec)`
      - `required_inductance_mH(spec)` a partir de %Z
      - `line_pk_current_A(spec)` = √2·I_rated
      - `line_rms_current_A(spec)`
      - `voltage_drop_Vrms(L_actual_mH, spec)`
      - `voltage_drop_pct(L_actual_mH, spec)`
      - `estimate_thd_pct(pct_Z)` — regra empírica
- [x] 2.2 Módulo testado contra valores de referência (Pomilio Cap. 11
      / IEEE 519 application notes).

## 3. Engine integration

- [x] 3.1 `design/engine.py` despacha para `line_reactor.*` quando
      `spec.topology == "line_reactor"`.
- [x] 3.2 Sem ripple HF; `delta_iL_avg = 0`, `I_rip_rms = 0`.
- [x] 3.3 `B_pk = √2·V_L_rms / (ω_line·N·Ae)` (fluxo fundamental).
- [x] 3.4 Perdas: DC copper + iGSE @ f_line. AC copper desprezado
      (skin depth a 60 Hz ≈ 8 mm).
- [x] 3.5 `DesignResult` populado com `pct_impedance_actual`,
      `voltage_drop_pct`, `thd_estimate_pct`.

## 4. Material database

- [x] 4.1 Adicionar 3 materiais de aço-silício curados:
      - M5 (0.35 mm laminação, Bsat 2.03 T, μᵣ 7000)
      - M19 (0.50 mm, Bsat 2.0 T, μᵣ 5000)
      - Metglas 2605SA1 (amorfo, Bsat 1.56 T, μᵣ 30000)
- [x] 4.2 Cada material com Steinmetz calibrado em 50–60 Hz +
      densidade típica 7650 kg/m³ (silício) ou 7180 (amorfo).

## 5. UI

- [x] 5.1 `ui/spec_panel.py`: novo bloco **"REATOR DE LINHA"**
      visível apenas quando topologia é `line_reactor`.
      Campos: nº de fases, V de linha, I rated, %Z.
- [x] 5.2 Esconder/desabilitar Vout, fsw, ripple_pct quando line
      reactor.
- [x] 5.3 `ui/result_panel.py`: linhas extras (`Z atual`,
      `Queda de tensão`, `THD estimada`) visíveis quando line
      reactor.

## 6. Tests

- [x] 6.1 Unit: `required_inductance_mH` para 380V/30A/5%/60Hz =
      0.97 mH (referência clássica).
- [x] 6.2 Unit: `voltage_drop_pct(L_actual = 0.97 mH) ≈ 5%` quando
      I = rated.
- [x] 6.3 Unit: `estimate_thd_pct(5)` ≈ 33% (regra empírica
      Pomilio).
- [x] 6.4 Engine: design completo com material aço-silício, asserta
      L na faixa esperada e B_pk < Bsat.
- [x] 6.5 Cross-topology: trocar `topology` de `boost_ccm` para
      `line_reactor` no mesmo Spec não levanta validação.

## 7. Docs

- [x] 7.1 README: novo bloco no Fluxo de uso explicando quando usar
      line reactor (drives diodo + DC-link sem PFC ativo).
- [x] 7.2 Tabela com valores típicos: 3% / 5% / 8% → THD esperado,
      voltage drop, L típico para drive de 5/10/30 HP.
