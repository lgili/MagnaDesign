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
| numpy / scipy / pandas | ✅ | `collect_all` — see note below |
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

### Why numpy / scipy / pandas need `collect_all`

PyInstaller's static-analysis pass walks `import` statements but
stops at the C-extension boundary. NumPy 2.x reorganised its
internals into `numpy._core` (with an underscore), and the .so
extension modules in that subpackage re-import pure-Python
dispatchers (`_exceptions`, `multiarray`, `numeric`) that the
analyser never sees. Same defect on scipy and pandas — both ship
.so glue that imports .py modules at runtime.

Result if you skip the dance: the frozen app launches, the .so
files are on disk, and the very first `import numpy` raises
`ModuleNotFoundError: numpy._core._exceptions`. The v0.4.0 macOS
build hit exactly that — fixed in v0.4.1 by adding the three
packages to the spec's `collect_all` loop.

Rule: any wheel that ships a `_libs/` directory full of `.so`
files is a candidate for `collect_all`. When in doubt, freeze a
build locally and `find dist/magnadesign -name "*.py" | wc -l`
inside each suspect package — a count of zero next to dozens of
`.so` files is the smoking gun.

## Local dry-run

Build the same artifact your runner will produce, before pushing the tag:

```bash
pip install pyinstaller==6.11.1
pyinstaller --clean --noconfirm packaging/magnadesign.spec
# → dist/magnadesign/      (Linux/Windows)
# → dist/magnadesign.app/  (macOS)
./dist/magnadesign/magnadesign   # smoke test
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
| Add a hidden import | `packaging/magnadesign.spec`, `hidden += [...]` |
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
  See `docs/release-secrets.md` for the runbook.
- **Apple Silicon only on macOS**: `macos-latest` runners are arm64.
  Intel-mac users need an x86_64 build via `macos-13` runner; not
  enabled today to keep matrix size down.
- **Linux runtime libs**: the bundle expects glibc 2.31+ (Ubuntu 22.04
  baseline used by `ubuntu-latest`). Older distros need a build from
  source.

## Auto-update (appcast)

The shipped GUI carries a Help → "Check for updates…" menu entry
backed by `pfc_inductor.updater`. The updater polls a Sparkle-style
appcast at `https://magnadesign.dev/appcast.xml` and offers the
newest release when one is available. Privacy contract:

- **Disabled by default.** First-launch users have to click
  "Check for updates…" manually. The "Automatically check at
  startup" toggle is opt-in and persisted in `QSettings`.
- **Kill switch.** `MAGNADESIGN_DISABLE_TELEMETRY=1` (the same
  env var the crash reporter honours) makes the updater a no-op.
- **No PII.** The HTTP GET sends only
  `magnadesign/<version> <os>/<arch>` as the User-Agent.
- **Signature verification.** Every appcast `<enclosure>` carries
  a `sparkle:edSignature` attribute (Ed25519 over the artefact's
  bytes). The maintainer build pins the public key in
  `pfc_inductor/updater/signature.py::PUBLIC_KEY_BASE64`. A
  tampered appcast can't push a bogus binary.

### Publishing a new appcast

`scripts/generate_appcast.py` produces the XML from the GitHub
Releases API and (optionally) signs each enclosure with the
maintainer's Ed25519 private key. Wire into the release workflow:

```yaml
- name: Generate signed appcast
  if: startsWith(github.ref, 'refs/tags/v')
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    echo "${{ secrets.APPCAST_SIGNING_KEY_BASE64 }}" > /tmp/key
    python scripts/generate_appcast.py \
      --output appcast.xml \
      --signing-key /tmp/key
    rm -f /tmp/key
- name: Publish to gh-pages
  uses: peaceiris/actions-gh-pages@v3
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    publish_branch: gh-pages
    publish_dir: ./
    keep_files: true
```

### Generating the signing keypair

```bash
python -c "
import base64
from cryptography.hazmat.primitives.asymmetric import ed25519
priv = ed25519.Ed25519PrivateKey.generate()
print('PRIVATE (store as APPCAST_SIGNING_KEY_BASE64 secret):')
print(base64.b64encode(priv.private_bytes_raw()).decode())
print()
print('PUBLIC (paste into signature.py::PUBLIC_KEY_BASE64):')
print(base64.b64encode(priv.public_key().public_bytes_raw()).decode())
"
```

Store the private key as a GitHub Actions repo secret; pin the
public key in `signature.py` in the maintainer build (or via a
build-time substitution if you fork). The two keys must match
or every running app will reject the new release with
`SignatureCheckResult.BAD_SIGNATURE`.

### Local testing

```bash
# Generate the appcast against your fork:
python scripts/generate_appcast.py --output appcast.xml \
    --repo lgili/MagnaDesign

# Serve locally and point the running app at it:
python -m http.server 8000  # in the dir containing appcast.xml
MAGNADESIGN_APPCAST_URL=http://localhost:8000/appcast.xml \
    uv run magnadesign
# → Help → Check for updates…
```
