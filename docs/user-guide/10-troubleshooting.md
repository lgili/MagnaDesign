# 10. Troubleshooting

Symptoms in the field, diagnostics, and fixes. Each entry is a
real failure mode users have hit; the fix at the end of each
points at the underlying root cause so you can confirm before
applying it.

## 10.1 The app closed during FEA validation

**Symptom**: clicked **Validate**, the dialog showed gmsh
output for ~10–60 s, then the entire desktop app vanished
silently.

**Root cause**: native crash (SIGSEGV) inside gmsh's mesher
or getdp's solver. The most common trigger is **a winding with
≥ 80 turns** — each turn becomes a separate geometric primitive
("curve loop") in the FE input file, and gmsh's mesher chokes
on dense coils.

**Fix**: nothing on your side. The app is now hardened against
this — FEMMT runs in a subprocess, and the crash dies in the
child while the parent stays alive. Retry the validation. If
the design has N > 80 turns, the runner short-circuits with a
polite "FEA skipped — N exceeds the safe gmsh ceiling" message
instead of even spawning gmsh.

If you absolutely need FEA on a high-N design:

- **Reduce N** by picking a higher-AL core in the Core tab.
- **Switch backend to legacy FEMM** if the core is a toroid —
  FEMM's Lua geometry models the winding as a bulk current
  region rather than per-turn primitives.

## 10.2 FEA reports L_FEA wildly off (e.g. + 678 %)

**Symptom**: the Validate dialog reports an inductance error
of several hundred percent. Same factor on B<sub>pk</sub>.

**Root cause**: air-gap mismatch between the analytic engine
and the FE model. The catalogue's `AL_nH` already encodes some
effective gap (real or distributed). FEMMT models the core
with explicit `µ_r_abs` + `lgap`, so passing a hard-coded gap
disconnects the FE geometry from the analytic.

**Fix**: nothing on your side. The runner now back-solves the
gap from the catalogue's AL on every run:
``lgap = µ₀·Ae/AL − le/µ_initial``.

Confirm in the Notes line of the FEA result — it should read
something like ``gap=0.292 mm (back-solved from AL_nH)``.

## 10.3 "FEMMT is installed but ONELAB is not yet configured"

**Symptom**: amber backend status with this exact message.

**Root cause**: FEMMT's ``site-packages/femmt/config.json``
either doesn't exist, has no ``onelab`` key, or points at a
folder that's missing ``onelab.py`` / ``getdp`` / ``gmsh``.

**Fix**:

1. Download ONELAB from <https://onelab.info/> for your platform.
2. Extract anywhere — say ``~/onelab``.
3. Verify the folder contains ``onelab.py``, ``getdp`` (or
   ``getdp.exe`` on Windows), and ``gmsh`` (or ``gmsh.exe``).
4. Edit ``site-packages/femmt/config.json``:

   ```json
   {"onelab": "/Users/yourname/onelab"}
   ```

5. Restart the desktop app.

The diagnostic in ``pfc_inductor.fea.femmt_runner`` checks for
all three binaries — it'll tell you exactly which one is
missing in the error message.

## 10.4 "module 'femmt' has no attribute 'MagneticComponent'"

**Symptom**: FEA dialog raises this exact error.

**Root cause**: the FEMMT install is **incomplete** — Python
treats it as a PEP 420 namespace package because the
``__init__.py`` is missing or corrupted. ``import femmt``
succeeds but every top-level export is unavailable.

**Fix**:

```console
$ uv pip install --reinstall femmt
$ uv pip install "setuptools<70"
```

The setuptools pin is also needed because FEMMT 0.5.x imports
``pkg_resources``, which setuptools ≥ 70 removed.

The runner's integrity check now catches this case up-front
with a clear message:

> FEMMT module at /…/femmt is missing required top-level
> attributes: MagneticComponent, CoreType, … (Python is
> treating `femmt` as a namespace package — the install
> probably lost its `__init__.py`).

## 10.5 Optimizer marks every candidate FEA-skipped

**Symptom**: every row of the Optimizer's results table has
the FEA column empty and the Status column reads "FEA-skipped".

**Possible causes**:

1. **No FEA backend installed.** Install with
   ``uv pip install -e ".[fea]"``.
2. **Every candidate exceeds N = 80 turns.** Look at the
   `N_turns` column — if all values are ≥ 80, the cascade is
   correctly refusing FEA on each one.
3. **ONELAB misconfigured.** Open the workspace's Validate tab
   manually to read the backend status; fix ONELAB per
   chapter 7.

The cascade tier 3 / tier 4 is silent on individual FEA
errors — they're logged to the run's JSON but not surfaced in
the table. Read ``--save-run`` JSON for per-candidate failure
reasons:

```console
$ magnadesign cascade my-spec.pfc --fea --output sweep.json
$ jq '.candidates[] | {core, fea_status, fea_error}' sweep.json
```

## 10.6 PDF datasheet has missing fonts (Helvetica fallback)

**Symptom**: the generated PDF uses generic Helvetica instead
of the bundled Inter font.

**Root cause**: ``pip install --no-binary`` or other packaging
quirks can strip non-Python data files (the ``report/fonts/``
directory ships ``Inter-{Regular,Medium,SemiBold,Bold}.ttf``).
Without the fonts, ``_register_fonts`` falls back to
Helvetica.

**Fix**:

```console
$ uv pip install --reinstall --no-cache-dir magnadesign
```

Verify the fonts directory exists:

```console
$ ls "$(python -c 'import pfc_inductor; print(pfc_inductor.__path__[0])')/report/fonts"
Inter-Bold.ttf  Inter-Medium.ttf  Inter-Regular.ttf  Inter-SemiBold.ttf  LICENSE-Inter.txt
```

## 10.7 Equations look bad in the project report PDF

**Symptom**: the project report renders, but equations look
like screenshots of plain ASCII text rather than typeset math.

**Root cause**: matplotlib's mathtext backend failed to find
the Computer Modern font. Default behaviour on a fresh
matplotlib install on minimal containers.

**Fix**: matplotlib bundles Computer Modern but doesn't always
register it. Refresh the matplotlib font cache:

```console
$ python -c "import matplotlib; matplotlib.font_manager._load_fontmanager(try_read_cache=False)"
```

If that doesn't work, install ``cm-super`` system-side:

```console
$ apt-get install cm-super       # Debian / Ubuntu
$ brew install --cask mactex     # macOS
```

## 10.8 Comparison drag-and-drop has weird side effects

**Symptom**: dragging a column to a new position seems to
work but the colour coding refreshes oddly.

**Root cause**: this is the expected behaviour. When the
leftmost column changes, every other column's colour coding
recomputes against the new REF. So columns that were green
suddenly turn red, etc.

**Confirmation**: look at the leftmost column header — it
should now carry the **REF** badge for the column you just
promoted.

## 10.9 The app is slow to start

**Symptom**: 5+ seconds from double-click to the splash screen.

**Root causes & fixes**:

| Cause | Fix |
|---|---|
| **Cold catalogue load** (first launch since boot). | Subsequent launches reuse the OS file cache and are sub-second. |
| **FEMMT eagerly imported.** | We lazy-import; if you see this on cold launches, file an issue. |
| **PyVista 3D viewer initialising VTK on import.** | Toggle the 3D Viz off in Settings if you don't use it. |
| **Old PySide6 < 6.7.** | The icon system pre-loads SVG sprites; older Qt versions take longer. Upgrade. |

## 10.10 macOS — app immediately quits or shows "is damaged"

**Symptom**: double-clicking `magnadesign.app` either:

- Bounces in the Dock for a moment then disappears, or
- Shows _"magnadesign.app is damaged and can't be opened. You should
  move it to the Trash."_, or
- Shows _"cannot be opened because Apple cannot check it for malicious
  software."_

**Root causes (two layers stack here)**:

1. **Gatekeeper quarantine.** Safari / Chrome tag every download with
   the `com.apple.quarantine` extended attribute. Combined with the
   ad-hoc-signed binary the release workflow ships (no Apple Developer
   ID), Gatekeeper refuses to launch the app. This is the "damaged" /
   "cannot verify" message.
2. **Build defect in v0.4.0 only.** The PyInstaller spec missed
   `collect_all` for numpy / scipy / pandas, so numpy 2.x's
   `numpy._core` submodules (`_exceptions`, `multiarray`, …) are
   absent from the bundle. The app launches past Gatekeeper, then
   crashes immediately with
   `ModuleNotFoundError: No module named 'numpy._core._exceptions'`.

**Fix**:

- **Use v0.4.1 or newer** — the spec fix is in
  [`packaging/magnadesign.spec`](https://github.com/lgili/MagnaDesign/blob/main/packaging/magnadesign.spec).
  Re-download from the GitHub Releases page.
- **Then strip the quarantine flag** so Gatekeeper lets the unsigned
  app run:

  ```console
  $ xattr -dr com.apple.quarantine ~/Downloads/magnadesign.app
  ```

  Equivalent right-click recipe: hold _Control_, click the app,
  pick _Open_, then _Open_ again in the dialog. macOS records the
  approval and double-click works after that.

**Confirming the fix worked**: launch the binary directly from
Terminal to see the real error:

```console
$ ~/Downloads/magnadesign.app/Contents/MacOS/magnadesign
```

A working bundle prints the splash banner and the GUI comes up. A
broken (v0.4.0-class) bundle prints a Python traceback ending in
`numpy._core._exceptions` or a similar `ModuleNotFoundError`.

## 10.11 Where do I file bugs?

GitHub issues at <https://github.com/lgili/MagnaDesign/issues>.
Include:

- The desktop app version (Help → About).
- The ``.pfc`` file the issue reproduces against.
- The exact stack trace from the workspace's status bar (or
  the CLI's output).
- The output of ``magnadesign --version`` and
  ``uv pip list | grep -E "(femmt|scipy|setuptools|pyside6)"``.

The maintainers triage issues weekly.
