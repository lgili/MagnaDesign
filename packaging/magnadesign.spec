# -*- mode: python -*-
# ruff: noqa: F821
# (Analysis/PYZ/EXE/COLLECT/BUNDLE are injected by PyInstaller's spec
# runner; they're not regular Python imports.)
"""PyInstaller spec for MagnaDesign.

Built once and reused on Linux / macOS / Windows. The release CI
workflow invokes ``pyinstaller packaging/magnadesign.spec`` from the
repo root on a per-platform runner — no per-OS branching is needed
inside this spec because PyInstaller itself emits the right binary
shape for each runtime.

Why **one-folder** and not one-file
-----------------------------------
- ~500 MB unpacked (VTK alone ships 350 MB of native libs). One-file
  re-extracts that on every launch; cold start jumps from ~2 s to
  ~15 s on spinning disks.
- Antivirus engines flag self-extracting one-file binaries far more
  often than plain folders.
- One-folder lets ``data/`` ride alongside the executable with no
  extraction tax; ``data_loader._bundled_data_root`` looks for it
  there when ``sys.frozen`` is set.

Why we **collect_all** pyvista / vtkmodules / matplotlib
-------------------------------------------------------
PyInstaller's static-analysis import graph misses the dynamic loads
that VTK does at runtime (``vtkmodules.<lots>`` discovered via
introspection). Same story for matplotlib backends. ``collect_all``
walks the package and pins every ``.py`` / data file / shared lib
into the bundle so the frozen app actually finds what it needs.

Excluded modules
----------------
- ``femmt`` and its scipy<1.14 / setuptools<70 sub-deps live in the
  optional ``[fea]`` extra; users install them on demand via the
  in-app setup dialog. Bundling would balloon the artifact and
  likely break on platforms where ONELAB binaries aren't bundled.
- ``tkinter`` — matplotlib pulls it in even though we only use the
  Qt backend.
- Test / build / dev modules.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

# PyInstaller 6.x ``exec()``-runs the spec file in a namespace that
# sets ``SPECPATH`` (the spec's directory) but NOT ``__file__`` —
# the previous one-liner ``globals().get("SPECPATH", str(Path(
# __file__).resolve().parent))`` evaluates the default expression
# eagerly and crashed with ``NameError: __file__`` on every release
# build across Linux / macOS / Windows. ``SPECPATH`` is always
# present at runtime, so the dotted access without a fallback is
# the simpler and correct form. The local-dev case (``python
# packaging/magnadesign.spec``) goes through ``__file__`` instead.
try:
    SPECPATH = globals()["SPECPATH"]
except KeyError:
    # Local dev — running the spec module directly (rare; mainly
    # for IDE introspection). ``__file__`` is set in that path.
    SPECPATH = str(Path(__file__).resolve().parent)
REPO_ROOT = Path(SPECPATH).resolve().parent

ENTRY = str(REPO_ROOT / "src" / "pfc_inductor" / "__main__.py")
# User-facing binary name. The Python package on disk stays as
# ``pfc_inductor`` for backwards-compat with import sites, but every
# user-visible artifact (executable, .app bundle, dist folder, asset
# zip) ships under ``magnadesign``.
APP_NAME = "magnadesign"


# ---------------------------------------------------------------------------
# Resolve the build version. Order of preference:
#   1. ``PFC_BUILD_VERSION`` env var (so the release.yml workflow can
#      explicitly pass it at build time without parsing the tag here).
#   2. ``GITHUB_REF_NAME`` minus the leading ``v`` (set by GitHub
#      Actions on tag pushes).
#   3. ``pyproject.toml`` ``[project].version`` parsed by hand to avoid
#      pulling in tomllib at spec-eval time on Python <3.11 paths.
#   4. ``"0.0.0+dev"`` as a last-resort fallback.
# CFBundleVersion accepts only digits + dots, so anything beyond the
# first 3 dotted components or any non-digit gets stripped.
# ---------------------------------------------------------------------------
def _resolve_build_version() -> str:
    env = os.environ.get("PFC_BUILD_VERSION")
    if env:
        return env.lstrip("v")
    ref = os.environ.get("GITHUB_REF_NAME", "")
    if ref.startswith("v") and re.match(r"^v\d", ref):
        return ref.lstrip("v")
    pyproject = REPO_ROOT / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if m:
            return m.group(1)
    return "0.0.0+dev"


def _normalise_cfbundle_version(v: str) -> str:
    # CFBundleVersion is "X.Y.Z" with digits only. Strip any -rcN /
    # +localmeta / build-metadata suffix and pad to 3 components.
    base = re.split(r"[^0-9.]", v, maxsplit=1)[0]
    parts = (base or "0").split(".")
    while len(parts) < 3:
        parts.append("0")
    return ".".join(parts[:3])


BUILD_VERSION = _resolve_build_version()
CFBUNDLE_VERSION = _normalise_cfbundle_version(BUILD_VERSION)

# ---------------------------------------------------------------------------
# Data files riding inside the bundle
# ---------------------------------------------------------------------------
# Tuple shape PyInstaller expects: ``(src_path_on_disk, dest_dir_in_bundle)``.
# Destinations are relative to the bundle root (next to the executable
# in one-folder mode).
datas: list[tuple[str, str]] = []

bundled_data_dir = REPO_ROOT / "data"
if bundled_data_dir.exists():
    # Recurse — ``mas/`` and ``mas/catalog/`` stay nested.
    for p in bundled_data_dir.rglob("*"):
        if p.is_file():
            rel_dir = p.parent.relative_to(REPO_ROOT)
            datas.append((str(p), str(rel_dir)))

# Ship every launcher-icon variant we generated. PyInstaller picks the
# native one (.ico on Windows, .icns on macOS) for the executable
# itself; the PNGs ride along so ``__main__._resolve_icon`` can build
# a multi-resolution ``QIcon`` for the dock / taskbar / about dialog.
for icon_name in (
    "logo.png", "logo-256.png", "logo-512.png",
    "logo.ico", "logo.icns",
):
    p = REPO_ROOT / "img" / icon_name
    if p.exists():
        datas.append((str(p), "img"))

# ---------------------------------------------------------------------------
# collect_all gathers hidden imports + binaries + data for each package.
# We unpack the 3-tuple into accumulators rather than passing them flat.
# ---------------------------------------------------------------------------
hidden: list[str] = []
binaries: list[tuple[str, str]] = []

for pkg in (
    "pyvista",
    "pyvistaqt",
    "vtkmodules",
    "matplotlib",
    "PySide6.QtSvg",
    "PySide6.QtPrintSupport",
):
    try:
        d, b, h = collect_all(pkg)
    except Exception as e:  # pragma: no cover — informational only
        print(f"[spec] collect_all({pkg}) failed: {e}", file=sys.stderr)
        continue
    datas += d
    binaries += b
    hidden += h

# Pydantic v2 ships a Rust core that PyInstaller needs hand-pointed.
hidden += [
    "pydantic",
    "pydantic_core",
    "pydantic._internal",
    "pfc_inductor",
    "pfc_inductor.models",
    "pfc_inductor.physics",
    "pfc_inductor.topology",
    "pfc_inductor.design",
    "pfc_inductor.optimize",
    "pfc_inductor.standards",
    "pfc_inductor.report",
    "pfc_inductor.compare",
    "pfc_inductor.setup_deps",
]

# openpyxl for Excel export, used by the report module.
datas += collect_data_files("openpyxl")

# ---------------------------------------------------------------------------
excluded = [
    "femmt",            # optional [fea] extra; user installs separately
    "onelab",
    "tkinter",
    "_tkinter",
    "Tkinter",
    "test",
    "tests",
    "pytest",
    "mypy",
    "ruff",
    "black",
    "setuptools",       # we only need it at build time
    "pip",
    "wheel",
]

# ---------------------------------------------------------------------------
# Per-platform icon. PyInstaller picks ``.ico`` on Windows and ``.icns``
# on macOS; on Linux the icon is set by .desktop files at install time
# so we just leave it alone.
# ---------------------------------------------------------------------------
icon = None
if sys.platform == "win32":
    candidate = REPO_ROOT / "img" / "logo.ico"
    if candidate.exists():
        icon = str(candidate)
elif sys.platform == "darwin":
    candidate = REPO_ROOT / "img" / "logo.icns"
    if candidate.exists():
        icon = str(candidate)

# ---------------------------------------------------------------------------
block_cipher = None

a = Analysis(
    [ENTRY],
    pathex=[str(REPO_ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                    # UPX confuses some AV scanners + slows VTK
    console=False,                # GUI app — no terminal window on Windows/macOS
    disable_windowed_traceback=False,
    target_arch=None,             # native arch on each runner
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
    # PyInstaller 6.x defaults to ``contents_directory='_internal'``
    # which moves every data file + shared lib under
    # ``dist/<name>/_internal/`` and leaves only the executable next
    # to it. That breaks ``data_loader._bundled_data_root`` (which
    # probes ``Path(sys.executable).parent / data``) and the release
    # workflow's existence check (``test -d dist/<name>/data``). The
    # legacy flat layout (``contents_directory='.'``) is still
    # supported and matches the assumptions encoded in the runtime
    # data-loader and the verify step.
    contents_directory=".",
)

# ---------------------------------------------------------------------------
# macOS only: wrap the COLLECT folder into a .app bundle so users can
# drop it into /Applications. The release workflow further wraps this
# in a .dmg for distribution.
# ---------------------------------------------------------------------------
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="com.indutor.magnadesign",
        info_plist={
            "CFBundleName": "MagnaDesign",
            "CFBundleDisplayName": "MagnaDesign",
            "CFBundleVersion": CFBUNDLE_VERSION,
            "CFBundleShortVersionString": CFBUNDLE_VERSION,
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,  # supports light + dark
        },
    )
