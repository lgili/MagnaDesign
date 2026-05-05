"""Detect available FEM backends (FEMMT preferred; FEMM/xfemm legacy)."""
from __future__ import annotations
import importlib
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Literal, Optional


Backend = Literal["femmt", "femm", "none"]


# ---- FEMM (legacy) ---------------------------------------------------------
_FEMM_BINARIES = ("xfemm", "femm", "fkn-femm")
_MAC_PATHS = [
    Path("/Applications/FEMM/femm.app/Contents/MacOS/femm"),
    Path("/Applications/FEMM.app/Contents/MacOS/femm"),
    Path.home() / "Applications/FEMM.app/Contents/MacOS/femm",
]
_WIN_PATHS = [
    Path("C:/femm42/bin/femm.exe"),
    Path("C:/Program Files/femm42/bin/femm.exe"),
    Path("C:/Program Files (x86)/femm42/bin/femm.exe"),
]


def find_femm_binary() -> Optional[str]:
    for name in _FEMM_BINARIES:
        p = shutil.which(name)
        if p:
            return p
    sysname = platform.system().lower()
    if sysname == "darwin":
        for p in _MAC_PATHS:
            if p.exists():
                return str(p)
    elif sysname == "windows":
        for p in _WIN_PATHS:
            if p.exists():
                return str(p)
    return None


def is_femm_available() -> bool:
    return find_femm_binary() is not None


def femm_version() -> Optional[str]:
    binary = find_femm_binary()
    if binary is None:
        return None
    try:
        r = subprocess.run([binary, "--version"], capture_output=True,
                           text=True, timeout=4)
        out = (r.stdout or r.stderr).strip()
        return out or "unknown"
    except Exception:
        return "unknown"


# ---- FEMMT (preferred) -----------------------------------------------------
def is_femmt_available() -> bool:
    """`import femmt` works (ONELAB config checked separately at solve time)."""
    try:
        importlib.import_module("femmt")
        return True
    except Exception:
        return False


def is_femmt_onelab_configured() -> bool:
    """Check FEMMT's `config.json` (inside the installed package) for an
    ONELAB folder path that contains `onelab.py`.

    FEMMT 0.5.x reads `<site-packages>/femmt/config.json`. Older docs
    sometimes refer to `~/.femmt_settings.json`; we check both for safety.
    """
    candidates = []
    try:
        import femmt
        candidates.append(Path(femmt.__file__).parent / "config.json")
    except Exception:
        pass
    candidates += [
        Path.home() / ".femmt_settings.json",
        Path.home() / "femmt_settings.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                import json
                data = json.loads(p.read_text())
                onelab = data.get("onelab") or data.get("ONELAB")
                if not onelab:
                    continue
                onelab_dir = Path(onelab)
                # FEMMT requires `onelab.py` in this directory.
                if (onelab_dir / "onelab.py").exists():
                    return True
            except Exception:
                pass
    return False


def femmt_config_path() -> Optional[Path]:
    """Return the path FEMMT reads its ONELAB config from."""
    try:
        import femmt
        return Path(femmt.__file__).parent / "config.json"
    except Exception:
        return None


def femmt_version() -> Optional[str]:
    try:
        m = importlib.import_module("femmt")
        return getattr(m, "__version__", "unknown")
    except Exception:
        return None


# ---- Dispatcher ------------------------------------------------------------
def active_backend() -> Backend:
    """Pick the FEA backend without considering the design's shape.

    Precedence:
      1. ``PFC_FEA_BACKEND`` env var (`femmt` | `femm`) — testing/CI.
      2. FEMMT if importable (preferred).
      3. FEMM if a binary is detected.
      4. ``"none"`` otherwise.
    """
    forced = os.environ.get("PFC_FEA_BACKEND", "").strip().lower()
    if forced == "femmt":
        return "femmt" if is_femmt_available() else "none"
    if forced == "femm":
        return "femm" if is_femm_available() else "none"
    if is_femmt_available():
        return "femmt"
    if is_femm_available():
        return "femm"
    return "none"


def select_backend_for_shape(shape_kind: str) -> Backend:
    """Pick the **best** backend for a specific core shape.

    FEMMT 0.5.x lacks a native toroid primitive (only `Single`/`Stacked`
    PQ-style cores). For toroides we therefore prefer FEMM (true
    axisymmetric solve) when available; FEMMT is used only as fallback.

    For EE/ETD/PQ we prefer FEMMT — its `Single` core type matches
    those geometries exactly.

    Honours `PFC_FEA_BACKEND` to force a backend regardless.
    """
    forced = os.environ.get("PFC_FEA_BACKEND", "").strip().lower()
    if forced == "femmt":
        return "femmt" if is_femmt_available() else "none"
    if forced == "femm":
        return "femm" if is_femm_available() else "none"

    is_toroid = (shape_kind == "toroid")
    if is_toroid:
        if is_femm_available():
            return "femm"
        if is_femmt_available():
            return "femmt"
    else:
        if is_femmt_available():
            return "femmt"
        if is_femm_available():
            return "femm"
    return "none"


def backend_fidelity(shape_kind: str, backend: Backend) -> Literal["high", "approx", "none"]:
    """Subjective fidelity rating of a (shape, backend) pair.

    - High: backend models the geometry exactly (FEMM toroid axissymmetric;
      FEMMT EE/ETD/PQ).
    - Approx: backend models a different but related geometry (FEMMT for
      toroide via PQ-equivalent).
    - None: no backend.
    """
    if backend == "none":
        return "none"
    if shape_kind == "toroid":
        return "high" if backend == "femm" else "approx"
    if shape_kind in ("ee", "etd", "pq"):
        return "high" if backend == "femmt" else "approx"
    return "approx"


def install_hint() -> str:
    """Platform-aware install hint for whichever backend is missing."""
    sys = platform.system().lower()
    backend = active_backend()
    if backend != "none":
        return ""

    # No backend at all — recommend FEMMT first, FEMM as fallback.
    base = (
        "Nenhum backend FEA detectado. Recomendado: FEMMT "
        "(`pip install pfc-inductor-designer[fea]`).\n"
        "FEMMT requer Python 3.12 e um pin de scipy<1.14 — veja "
        "docs/fea-install.md.\n"
        "Alternativa legada (FEMM): "
    )
    if sys == "darwin":
        base += (
            "no macOS, `brew install xfemm` ou rode FEMM original via "
            "Wine/CrossOver."
        )
    elif sys == "linux":
        base += (
            "no Linux, `apt install xfemm` ou compile do fonte "
            "(https://femm.foster-miller.net/wiki/HomePage)."
        )
    elif sys == "windows":
        base += (
            "no Windows, baixe o instalador FEMM 4.2 em "
            "https://www.femm.info."
        )
    return base
