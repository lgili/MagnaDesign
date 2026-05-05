# Tasks — Cross-platform automatic dependency setup

## 1. Module skeleton

- [x] 1.1 Create `src/pfc_inductor/setup_deps/__init__.py` exposing
      `setup_fea(report=...)`, `check_fea_setup() -> SetupStatus`,
      `SetupReport`, `SetupStep`.
- [x] 1.2 `platform_info.py`: detect tuple
      (`os: "darwin"|"linux"|"windows"`, `arch: "arm64"|"x86_64"`),
      raise `UnsupportedPlatform` for anything else.
- [x] 1.3 `urls.py`: ONELAB tarball URL per platform
      (`https://onelab.info/files/onelab-<Tag>.{tgz|zip}`).

## 2. Steps

- [x] 2.1 `onelab.py::download_onelab(target_dir, on_progress)` —
      idempotent (returns "already-installed" if `target_dir/onelab.py`
      exists), verifies SHA256 if shipped.
- [x] 2.2 `onelab.py::codesign_macos(target_dir)` — on macOS, runs
      `codesign --force --deep --sign - <bin>` for `getdp`, `gmsh`, and
      every `.dylib`. Skipped on other OSes.
- [x] 2.3 `femmt_config.py::write_config(onelab_dir)` — writes both
      `~/.femmt_settings.json` AND
      `<site-packages>/femmt/config.json` (FEMMT 0.5.x reads the
      latter; we cover both for safety).
- [x] 2.4 `workaround.py::install_path_workaround()` — only on macOS
      with a path-with-spaces virtualenv: creates `/tmp/femmt` symlink
      to the real femmt package, prepends to `sys.path`.
- [x] 2.5 `verify.py::verify_femmt()` — calls `import femmt;
      femmt.MagneticComponent(...)` with a tiny config; returns OK or a
      structured error.

## 3. CLI + console_script

- [x] 3.1 `cli.py::main()` — argparse:
      `--non-interactive`, `--onelab-dir`, `--skip-codesign`,
      `--verbose`. Calls `setup_fea` and prints colored status.
- [x] 3.2 `pyproject.toml`: add
      `pfc-inductor-setup = "pfc_inductor.setup_deps.cli:main"`.

## 4. UI

- [x] 4.1 `ui/setup_dialog.py`: modal `SetupDepsDialog` with header,
      step list, progress bar, log pane. Runs setup in `QThread`.
- [x] 4.2 `ui/main_window.py`: on `__init__`, if
      `check_fea_setup().fea_ready is False`, open the dialog
      (only-once: skip if user already declined this session).
- [x] 4.3 Toolbar action **"Reinstalar dependências FEA"** as escape
      hatch when something gets corrupted.

## 5. Tests

- [x] 5.1 Unit: `platform_info` returns expected tuples on faked
      `platform.system()` / `platform.machine()`.
- [x] 5.2 Unit: `femmt_config.write_config` produces files with the
      correct `onelab` key (uses `tmp_path`, doesn't touch real home).
- [x] 5.3 Unit: `download_onelab` is idempotent (fake target dir
      already populated → no-op).
- [x] 5.4 Integration: `check_fea_setup()` returns `fea_ready=True`
      when both FEMMT importable and ONELAB configured.

## 6. Docs

- [x] 6.1 README: replace the dense "Instalação (dev)" list with a
      one-liner pointing to `pfc-inductor-setup`. Keep manual fallback
      under a `<details>` block.
- [x] 6.2 `docs/fea-install.md`: split into "Automático
      (recomendado)" and "Manual (fallback)".
