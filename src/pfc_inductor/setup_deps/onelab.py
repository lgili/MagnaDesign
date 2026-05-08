"""Download, extract and codesign the ONELAB solver bundle.

ONELAB ships ``getdp`` (the FEM solver), ``gmsh`` (the mesher) and a
helper Python module ``onelab.py``. FEMMT 0.5.x just needs the parent
directory in its ``config.json``.
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

from pfc_inductor.setup_deps.platform_info import PlatformInfo, detect_platform
from pfc_inductor.setup_deps.urls import onelab_archive_url

ProgressCb = Optional[Callable[[str, float], None]]
"""``cb(message, fraction_0_to_1)`` — used by the UI for progress bars."""


def default_onelab_dir() -> Path:
    """Where we install ONELAB by default. Matches the docs at
    ``docs/fea-install.md``.
    """
    return Path.home() / "onelab"


def is_onelab_installed(target_dir: Path) -> bool:
    """ONELAB is "installed" when ``onelab.py`` plus the two binaries are
    present in ``target_dir``.
    """
    if not target_dir.is_dir():
        return False
    has_helper = (target_dir / "onelab.py").is_file()
    has_getdp = (target_dir / "getdp").is_file() or (target_dir / "getdp.exe").is_file()
    has_gmsh = (target_dir / "gmsh").is_file() or (target_dir / "gmsh.exe").is_file()
    return has_helper and has_getdp and has_gmsh


def download_onelab(
    target_dir: Path,
    *,
    plat: Optional[PlatformInfo] = None,
    on_progress: ProgressCb = None,
) -> bool:
    """Idempotent ONELAB download.

    Returns ``True`` if a download happened, ``False`` if the target dir
    was already populated.
    """
    target_dir = Path(target_dir).expanduser()
    if is_onelab_installed(target_dir):
        if on_progress:
            on_progress(f"ONELAB já instalado em {target_dir}", 1.0)
        return False

    plat = plat or detect_platform()
    url = onelab_archive_url(plat)
    target_dir.mkdir(parents=True, exist_ok=True)

    if on_progress:
        on_progress(f"Baixando ONELAB ({plat.onelab_tag}) de onelab.info…", 0.05)

    with tempfile.TemporaryDirectory(prefix="pfc_onelab_") as tmp:
        archive_path = Path(tmp) / f"onelab.{plat.archive_ext}"
        _download_with_progress(url, archive_path, on_progress)

        if on_progress:
            on_progress("Extraindo arquivo…", 0.85)
        _extract_archive(archive_path, target_dir, plat)

    # Some archives nest everything under `onelab-Darwin64/`. Flatten so
    # `target_dir` directly contains the binaries.
    _flatten_single_subdir(target_dir)

    if on_progress:
        on_progress("ONELAB extraído.", 0.95)
    return True


def codesign_macos(target_dir: Path, *, on_progress: ProgressCb = None) -> int:
    """Apply ad-hoc codesign so Gatekeeper doesn't kill ``getdp``/``gmsh``.

    No-op outside macOS. Returns the number of files signed (0 if not on
    macOS).
    """
    plat = detect_platform()
    if not plat.is_macos:
        return 0

    targets: list[Path] = []
    for name in ("getdp", "gmsh"):
        p = target_dir / name
        if p.exists():
            targets.append(p)
    targets.extend(target_dir.glob("*.dylib"))

    signed = 0
    for path in targets:
        if on_progress:
            on_progress(f"Assinando {path.name}…", min(0.99, 0.6 + 0.05 * signed))
        try:
            subprocess.run(
                ["codesign", "--force", "--deep", "--sign", "-", str(path)],
                check=True,
                capture_output=True,
            )
            signed += 1
        except subprocess.CalledProcessError as e:
            # Don't fail the whole install — Gatekeeper might let it run
            # depending on the user's setting; just log via progress.
            if on_progress:
                on_progress(
                    f"  aviso: codesign falhou em {path.name}: "
                    f"{e.stderr.decode(errors='ignore')[:120]}",
                    0.0,
                )
    return signed


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _download_with_progress(
    url: str,
    dest: Path,
    on_progress: ProgressCb,
) -> None:
    """``urllib`` download with a progress callback (0-fraction in 0..1)."""
    req = urllib.request.Request(url, headers={"User-Agent": "pfc-inductor-setup"})
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as out:
        total = int(resp.headers.get("Content-Length", "0") or "0")
        read = 0
        chunk = 1 << 16
        while True:
            buf = resp.read(chunk)
            if not buf:
                break
            out.write(buf)
            read += len(buf)
            if on_progress and total > 0:
                # Reserve 0.05..0.85 of the bar for download.
                frac = 0.05 + 0.80 * (read / total)
                on_progress(
                    f"Baixando ONELAB… {read / 1e6:.1f} / {total / 1e6:.1f} MB",
                    frac,
                )


def _extract_archive(archive: Path, target_dir: Path, plat: PlatformInfo) -> None:
    if plat.archive_ext == "zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(target_dir)
    else:
        with tarfile.open(archive, "r:gz") as t:
            # Python 3.12+ requires an explicit filter argument; "data"
            # strips uid/gid and refuses absolute paths.
            try:
                t.extractall(target_dir, filter="data")
            except TypeError:
                t.extractall(target_dir)


def _flatten_single_subdir(target_dir: Path) -> None:
    """If the archive extracted into ``target/onelab-XXX/``, move the
    contents up one level so ``target_dir/onelab.py`` exists.
    """
    if (target_dir / "onelab.py").exists():
        return
    children = [p for p in target_dir.iterdir() if p.is_dir()]
    if len(children) != 1:
        return
    nested = children[0]
    if not (nested / "onelab.py").exists():
        return
    for item in nested.iterdir():
        dst = target_dir / item.name
        if dst.exists():
            continue
        shutil.move(str(item), str(dst))
    try:
        nested.rmdir()
    except OSError:
        pass


__all__ = [
    "codesign_macos",
    "default_onelab_dir",
    "download_onelab",
    "is_onelab_installed",
]
