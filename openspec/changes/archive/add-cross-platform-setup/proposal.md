# Cross-platform automatic dependency setup

## Why

Hoje o setup do backend FEA (FEMMT + ONELAB) é manual e específico da
plataforma — `docs/fea-install.md` lista 5 passos com download, extração,
codesign no macOS, escrita do `config.json` da FEMMT em dois lugares e o
workaround de path-com-espaços. Para um app distribuído mundialmente
(Brasil + EUA + Europa), instalação manual destrói adoção.

Precisamos de um instalador único que rode em macOS (Intel + Apple
Silicon), Linux x86_64 e Windows x86_64, baixando ONELAB, configurando
caminhos e validando. Tem que rodar pela linha de comando E pela UI
(diálogo na primeira execução).

## What changes

- Novo módulo `pfc_inductor.setup_deps` com:
  - detecção de plataforma (`darwin-arm64`, `darwin-x86_64`,
    `linux-x86_64`, `windows-amd64`)
  - download e extração do ONELAB de `https://onelab.info/files/`
  - codesign ad-hoc dos binários no macOS (Gatekeeper)
  - escrita de `~/.femmt_settings.json` e
    `<site-packages>/femmt/config.json`
  - workaround de path-com-espaços no macOS (cria
    `/tmp/femmt` symlink + injeta no `sys.path`)
  - verificação por uma chamada mínima da API FEMMT
- Novo console_script `pfc-inductor-setup` (entrypoint
  `pfc_inductor.setup_deps.cli:main`).
- Diálogo Qt `SetupDepsDialog` que roda os passos em `QThread` com
  progress bar.
- `MainWindow` chama `check_fea_setup()` no boot; se faltar ONELAB,
  abre o diálogo (idempotente — só roda quando precisa).
- README + `docs/fea-install.md` apontam para o novo fluxo
  automático; o passo manual fica como fallback documentado.

## Impact

- Affected capabilities: NEW `cross-platform-setup`
- Affected modules: NEW `pfc_inductor/setup_deps/`,
  `ui/setup_dialog.py`; UPDATE `pyproject.toml`,
  `ui/main_window.py`, `README.md`, `docs/fea-install.md`.
- No new runtime deps: usa `urllib.request` + `tarfile`/`zipfile` da
  stdlib. `subprocess` para `codesign` no macOS.
- Tamanho do download: ~50 MB ONELAB por plataforma. Baixa uma vez,
  cache em `~/onelab/`.
