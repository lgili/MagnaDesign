"""macOS / Windows path-with-spaces workaround for FEMMT.

FEMMT 0.5.x calls ``getdp`` via shell strings that don't quote the
package path. When the venv is inside something like
``~/Documents/02 - Trabalho/indutor/.venv``, the space breaks the call
and gmsh receives a truncated argument like ``/Users/.../02.pro``.

The workaround is to relocate the FEMMT package into a no-spaces path
(``$TMPDIR/pfc_femmt_shim`` — kernel-managed on macOS/Linux, ``%TEMP%``
on Windows) and prepend that to ``sys.path`` before ``import femmt``
happens.

On macOS / Linux we use a symlink (cheap, atomic, survives across runs
until reboot). On **Windows** symlink creation requires either admin
rights or Developer Mode — neither of which a regular user is likely
to have — so we fall back to a recursive directory copy. The copy is
slower (~1 s for FEMMT) and uses ~30 MB of disk, but it's a one-time
cost per install / upgrade and it's the only way to dodge the shell
quoting bug without forcing admin rights.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from pfc_inductor.setup_deps.paths import FeaPaths

logger = logging.getLogger(__name__)

# Was hardcoded as ``/tmp/pfc_femmt_shim`` — no ``/tmp`` on Windows.
# ``FeaPaths.shim_dir`` resolves via ``tempfile.gettempdir()`` which
# returns the right thing on every OS (``%TEMP%`` on Windows).
SHIM_DIR = FeaPaths.detect().shim_dir


def _femmt_path() -> Optional[Path]:
    # ``import femmt`` requires ONELAB on ``sys.path``; inject
    # before importing so a fresh install (no ONELAB yet) doesn't
    # take down the GUI with a ``ModuleNotFoundError: No module
    # named 'onelab'`` from FEMMT's own top-level import.
    try:
        from pfc_inductor.setup_deps import ensure_onelab_on_path

        ensure_onelab_on_path()
    except Exception:
        pass
    try:
        import femmt  # type: ignore[import-not-found]
    except (ImportError, ModuleNotFoundError):
        return None
    init = getattr(femmt, "__file__", None)
    return Path(init).resolve() if init else None


def needs_workaround() -> bool:
    """True iff the active FEMMT install lives under a path with spaces."""
    p = _femmt_path()
    return p is not None and " " in str(p)


def _relocate(real: Path, target: Path) -> bool:
    """Place ``real`` at ``target`` using the cheapest mechanism
    that works on the current platform.

    Strategy:

    1. **Symlink** (POSIX). Atomic, free, no disk usage.
    2. **Symlink** (Windows, if Developer Mode / admin is on). Same
       atomic semantics; the call just happens to need privileges.
    3. **Directory copy** (Windows fallback). Slower (~1 s for FEMMT)
       and uses disk, but works for unprivileged users — which is the
       only user we can rely on existing in the wild.

    Returns True on success, False if every strategy failed (the
    caller should surface the failure to the user; we can't FEA
    without it).
    """
    # Step 1/2 — symlink.
    try:
        os.symlink(str(real), str(target), target_is_directory=True)
        return True
    except OSError as e:
        if os.name != "nt":
            # POSIX symlink failure is genuinely unexpected — log
            # before falling back so the cause shows up in support
            # bundles. (We still try the copy below as a last-ditch
            # save; it'll work as long as the disk has space.)
            logger.warning(
                "symlink %s → %s failed on %s: %s; falling back to copy",
                target,
                real,
                os.name,
                e,
            )

    # Step 3 — directory copy. Idempotent: shutil.copytree refuses
    # to overwrite an existing target, so wipe first. We've already
    # confirmed at the call site that ``target`` was either absent
    # or empty before we got here.
    try:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(str(real), str(target), symlinks=False)
        return True
    except OSError as e:
        logger.error(
            "failed to relocate FEMMT to no-spaces path %s: %s "
            "(symlink and copy both failed — FEA will be unavailable "
            "until the install path has no spaces in it)",
            target,
            e,
        )
        return False


def install_path_workaround(*, force: bool = False) -> Optional[Path]:
    """Create the no-spaces shim directory and patch ``sys.path``.

    Returns the shim path on success, ``None`` if no workaround was
    needed (or if relocation failed and FEMMT isn't usable).
    """
    if not force and not needs_workaround():
        return None
    real_init = _femmt_path()
    if real_init is None:
        return None
    real = real_init.parent
    SHIM_DIR.mkdir(parents=True, exist_ok=True)
    target = SHIM_DIR / "femmt"

    # If the target already points at the same real install, reuse it
    # — re-relocating on every launch is wasted I/O (especially the
    # Windows copy path which takes ~1 s).
    if target.is_symlink():
        try:
            if Path(os.readlink(str(target))).resolve() == real.resolve():
                if str(SHIM_DIR) not in sys.path:
                    sys.path.insert(0, str(SHIM_DIR))
                return SHIM_DIR
        except OSError:
            pass
    elif target.is_dir():
        # Copy-installed shim — assume it's still valid if the
        # ``__init__.py`` is there. (We can't compare the full tree
        # cheaply, and if FEMMT itself changed version the user will
        # re-upgrade anyway.)
        if (target / "__init__.py").exists():
            if str(SHIM_DIR) not in sys.path:
                sys.path.insert(0, str(SHIM_DIR))
            return SHIM_DIR

    # Clear any stale shim before relocating fresh.
    if target.is_symlink() or target.exists():
        try:
            if target.is_symlink():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
        except OSError:
            return SHIM_DIR  # best-effort — the existing shim may still work

    if not _relocate(real, target):
        return None

    if str(SHIM_DIR) not in sys.path:
        sys.path.insert(0, str(SHIM_DIR))
    return SHIM_DIR
