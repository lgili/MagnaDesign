# Releasing

Tagged commits trigger a multi-platform build pipeline that produces
ready-to-run binaries (Linux x86_64 tarball, macOS arm64 `.app` zip,
Windows x86_64 zip) and attaches them to a GitHub Release.

## TL;DR

```bash
# Cut a new release from main
git checkout main && git pull
git tag -a v0.2.0 -m "v0.2.0 — short summary"
git push origin v0.2.0
```

The `Release` workflow then:

1. Builds with PyInstaller on `ubuntu-latest`, `macos-latest`,
   `windows-latest` in parallel (~10–15 min each, dominated by VTK).
2. Uploads each archive as a workflow artifact.
3. Publishes a GitHub Release at the tag, attaching all three.

Pre-releases (tags containing `-`, e.g. `v0.2.0-rc1`) are flagged
`prerelease: true` automatically and don't appear as *Latest*.

## What gets bundled

| Component | Bundled? | Notes |
|---|---|---|
| Python 3.12 runtime | ✅ | PyInstaller embeds the interpreter |
| PySide6 + Qt | ✅ | Including QtSvg, QtPrintSupport |
| pyvista + pyvistaqt + VTK | ✅ | ~350 MB; `collect_all` pulls every submodule |
| matplotlib | ✅ | Qt backend only; tkinter excluded |
| numpy / scipy / pandas | ✅ | Native wheels |
| pydantic v2 (with rust core) | ✅ | Hidden import declared |
| openpyxl (Excel report) | ✅ | Data files via `collect_data_files` |
| `data/` (cores, materials, wires, MAS catalog) | ✅ | Copied next to the executable |
| `img/logo.png` | ✅ | For in-app branding |
| **FEMMT + ONELAB (FEA)** | ❌ | Optional; user installs via *Configurações → Setup FEA* |
| Tests, lint, type-checkers | ❌ | Excluded from spec |

Approximate sizes (uncompressed → archive):
- Linux: ~620 MB → ~250 MB `.tar.gz`
- macOS: ~640 MB `.app` → ~270 MB `.zip`
- Windows: ~600 MB → ~280 MB `.zip`

## Local dry-run

Build the same artifact your runner will produce, before pushing the tag:

```bash
pip install pyinstaller==6.11.1
pyinstaller --clean --noconfirm packaging/pfc-inductor.spec
# → dist/pfc-inductor/      (Linux/Windows)
# → dist/pfc-inductor.app/  (macOS)
./dist/pfc-inductor/pfc-inductor   # smoke test
```

Use this to catch missing hidden imports before they fail in CI.

## Manual workflow run (no tag)

The `Release` workflow exposes `workflow_dispatch`, so you can build
artifacts on a branch without cutting a real release:

1. GitHub → Actions → Release → *Run workflow*
2. Pick a branch, supply a placeholder `tag_name` (e.g. `v0.0.0-dev`)
3. The build matrix runs end-to-end; the *Publish Release* job is
   skipped because there's no tag — artifacts stay attached to the
   workflow run for 7 days.

Useful for verifying a PySide6 / pyvista upgrade still bundles cleanly.

## Editing the bundle

| Want to … | Where |
|---|---|
| Add a hidden import | `packaging/pfc-inductor.spec`, `hidden += [...]` |
| Add a data file | Same file, `datas.append((src, dst))` |
| Add a runner OS | `.github/workflows/release.yml`, `matrix.include` |
| Change Python version | `release.yml` step *Set up Python* + matching pyproject `requires-python` |
| Sign the macOS app | Add an Apple Developer ID secret + `--codesign-identity` to spec; outside scope today |
| Convert to a Windows installer | Replace the `Compress-Archive` step with Inno Setup or NSIS; spec stays the same |

## Where the binary looks for `data/`

`pfc_inductor.data_loader._bundled_data_root` resolves the bundled
`data/` directory across three deployment shapes, in order:

1. `$PFC_INDUCTOR_DATA_DIR` (override, for packagers / docker images)
2. PyInstaller frozen build → `sys._MEIPASS/data` (one-file) or
   `<exe-dir>/data` (one-folder, what the workflow ships)
3. Source checkout → `<repo>/data`
4. Wheel install → `<site-packages>/pfc_inductor/data`

If you ever add a new bundled data directory, update the spec's
`datas` list and the `_bundled_data_root` resolver in lock-step.

## Caveats

- **Code signing**: artifacts are unsigned. macOS users see a Gatekeeper
  warning on first launch (right-click → Open); Windows users see
  SmartScreen (More info → Run anyway). Adding signing requires an
  Apple Developer ID and a Windows EV cert — secrets, not a CI change.
- **Apple Silicon only on macOS**: `macos-latest` runners are arm64.
  Intel-mac users need an x86_64 build via `macos-13` runner; not
  enabled today to keep matrix size down.
- **Linux runtime libs**: the bundle expects glibc 2.31+ (Ubuntu 22.04
  baseline used by `ubuntu-latest`). Older distros need a build from
  source.
