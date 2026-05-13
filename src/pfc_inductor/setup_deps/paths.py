"""Cross-platform path resolution for the FEA toolchain.

One module that owns every disk-and-binary path the FEA setup
pipeline and runtime touch. Callers ask ``FeaPaths`` for what they
need and the class knows the right answer for the active OS — no
scattered ``Path.home() / "..."`` and ``"getdp.exe" if windows
else "getdp"`` checks elsewhere.

Three things motivated extracting this:

1. **Windows breakage.** ``/tmp`` was hardcoded as the path-with-
   spaces shim dir on macOS, but Windows has no ``/tmp``. The
   ONELAB install default (``Path.home() / "onelab"``) lands in
   ``C:\\Users\\<name>\\onelab`` — works, but isn't where Windows
   users expect application state (``%LOCALAPPDATA%`` is).
2. **Binary suffix sprinkling.** ``is_onelab_installed`` checked
   ``getdp`` AND ``getdp.exe`` inline; same for ``gmsh``.
3. **Test surface.** Path logic now testable in isolation by
   passing a ``PlatformInfo`` to ``FeaPaths.for_platform``.

FEMMT compatibility note: ``femmt_settings_json`` stays at
``~/.femmt_settings.json`` on every OS because FEMMT 0.5.x's
package code reads that exact path. We can't relocate it
without forking FEMMT.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pfc_inductor.setup_deps.platform_info import PlatformInfo, detect_platform


def _choose_no_spaces_shim_dir(
    plat: PlatformInfo,
    *,
    tempdir: Path | None = None,
) -> Path:
    """Pick a writable directory whose absolute path contains no spaces.

    FEMMT 0.5.x calls ``getdp`` with an unquoted shell string built
    from the package path. A single space in that path truncates the
    argument and the call dies. The workaround copies / symlinks the
    FEMMT package into the directory this function returns, then
    prepends it to ``sys.path``. The path therefore *must* survive
    the shell string assembly — i.e. contain no spaces.

    Resolution order:

    1. ``tempdir or tempfile.gettempdir()`` — the canonical OS
       tempdir. On macOS this is ``/var/folders/<hash>/T`` (per-user,
       no spaces). On Linux it's ``/tmp``. On Windows it's
       ``%TEMP%`` which is per-user (and inherits any spaces from
       the username).
    2. Per-OS fallback for the corner case where (1) contains a
       space:
       * Windows  → ``C:\\Users\\Public\\magnadesign-femmt-shim``.
         ``%PUBLIC%`` is always present, always writable, and the
         path is space-free regardless of the current user's name.
       * macOS / Linux → ``/var/tmp/pfc_femmt_shim``. Survives
         reboots (unlike ``/tmp``) and is no-spaces on every
         POSIX system the FEA matters on.

    Returns the first candidate that has no spaces. We don't
    probe-write here — that's the caller's job in
    ``install_path_workaround``. If every candidate fails (a
    machine so misconfigured the workaround can't possibly run)
    we return the primary candidate anyway so the user sees a
    consistent path in the eventual error message.
    """
    primary_base = tempdir if tempdir is not None else Path(tempfile.gettempdir())
    primary = primary_base / "pfc_femmt_shim"
    if " " not in str(primary):
        return primary

    if plat.is_windows:
        # ``C:\Users\Public`` exists on every modern Windows install,
        # is writable by all users by default, and contains no
        # spaces — even when ``%LOCALAPPDATA%`` does.
        public = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
        candidate = public / "magnadesign-femmt-shim"
        if " " not in str(candidate):
            return candidate

    # POSIX last-resort: ``/var/tmp`` is system-wide, no-spaces,
    # and persists across reboots so the symlink doesn't need
    # rebuilding every morning.
    posix_fallback = Path("/var/tmp/pfc_femmt_shim")
    if " " not in str(posix_fallback):
        return posix_fallback

    # Truly unrecoverable — return the primary so the user-facing
    # error message in ``install_path_workaround`` points at the
    # actual broken path.
    return primary


@dataclass(frozen=True)
class FeaPaths:
    """Bundle of FEA-related filesystem paths for one platform.

    Construct via :meth:`detect` (auto-detect the running OS) or
    :meth:`for_platform` (testable with a fixed ``PlatformInfo``).
    Instances are frozen — callers can stash them as module-level
    constants safely.
    """

    plat: PlatformInfo
    app_data_dir: Path
    default_onelab_dir: Path
    femmt_settings_json: Path
    shim_dir: Path

    # ── Binary names ────────────────────────────────────────────
    @property
    def getdp_exe_name(self) -> str:
        """``getdp.exe`` on Windows, ``getdp`` elsewhere."""
        return "getdp.exe" if self.plat.is_windows else "getdp"

    @property
    def gmsh_exe_name(self) -> str:
        """``gmsh.exe`` on Windows, ``gmsh`` elsewhere."""
        return "gmsh.exe" if self.plat.is_windows else "gmsh"

    @property
    def onelab_helper_name(self) -> str:
        """Python helper module shipped inside the ONELAB tarball.

        Same name on every OS — ``.py`` is platform-agnostic.
        """
        return "onelab.py"

    # ── Filesystem queries ──────────────────────────────────────
    def is_onelab_installed_at(self, target_dir: Path) -> bool:
        """``True`` when ``target_dir`` contains the three files
        ONELAB ships (``onelab.py`` + ``getdp[.exe]`` + ``gmsh[.exe]``).
        """
        target_dir = Path(target_dir)
        if not target_dir.is_dir():
            return False
        return (
            (target_dir / self.onelab_helper_name).is_file()
            and (target_dir / self.getdp_exe_name).is_file()
            and (target_dir / self.gmsh_exe_name).is_file()
        )

    def onelab_binary_path(self, install_dir: Path, name: str) -> Path:
        """Resolve ``"getdp"`` / ``"gmsh"`` to the actual file path,
        applying the platform's executable suffix.

        Raises ``ValueError`` for unknown names so callers can't
        accidentally pass ``"onelab"`` (which is the Python helper,
        not a binary).
        """
        if name == "getdp":
            return install_dir / self.getdp_exe_name
        if name == "gmsh":
            return install_dir / self.gmsh_exe_name
        raise ValueError(f"unknown ONELAB binary name: {name!r}")

    # ── Constructors ────────────────────────────────────────────
    @classmethod
    def detect(cls) -> FeaPaths:
        """Auto-detect from the running OS."""
        return cls.for_platform(detect_platform())

    @classmethod
    def for_platform(
        cls,
        plat: PlatformInfo,
        *,
        home: Path | None = None,
        appdata_override: str | None = None,
    ) -> FeaPaths:
        """Compute the path set for an arbitrary platform.

        ``home`` and ``appdata_override`` are escape hatches for the
        test suite; production callers use ``detect()``.
        """
        home = home or Path.home()

        # App-state directory — must match
        # :func:`pfc_inductor.app_identity.app_data_dir` exactly so the
        # FEA tooling lives under the same root as the history DB and
        # catalog overlays. We rebuild the path manually here (rather
        # than calling ``app_data_dir()``) so the test suite can pin
        # a fake ``home`` / ``appdata_override`` without monkeypatching
        # ``platformdirs`` globally.
        #
        # Conventions (single source of truth: ``app_identity.py``):
        #   Windows  →  %LOCALAPPDATA%\MagnaDesign\MagnaDesign
        #   macOS    →  ~/Library/Application Support/MagnaDesign
        #   Linux    →  $XDG_DATA_HOME/MagnaDesign  (or ~/.local/share/MagnaDesign)
        from pfc_inductor.app_identity import APP_NAME

        if plat.is_windows:
            if appdata_override is not None:
                base = Path(appdata_override)
            else:
                base = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
            # Windows nests under ``<author>\<name>``; with author == name
            # the convention surfaces as ``MagnaDesign\MagnaDesign``.
            app_data_dir = base / APP_NAME / APP_NAME
        elif plat.is_macos:
            app_data_dir = home / "Library" / "Application Support" / APP_NAME
        else:  # linux
            xdg = os.environ.get("XDG_DATA_HOME")
            base = Path(xdg) if xdg else (home / ".local" / "share")
            app_data_dir = base / APP_NAME

        # ONELAB install default. Windows users expect application
        # binaries under LOCALAPPDATA; macOS/Linux users keep the
        # historical ``~/onelab`` so existing installs aren't
        # invalidated. New installs on Windows land under our app
        # data dir; users with an older ``C:\Users\<name>\onelab``
        # tree keep working because ``femmt_settings.json`` carries
        # the actual configured path (this default only affects
        # the dialog's pre-filled value).
        if plat.is_windows:
            default_onelab_dir = app_data_dir / "onelab"
        else:
            default_onelab_dir = home / "onelab"

        # FEMMT 0.5.x reads ``~/.femmt_settings.json`` regardless
        # of OS. Don't relocate this without auditing the FEMMT
        # source (it hard-codes the read path).
        femmt_settings_json = home / ".femmt_settings.json"

        # Shim directory for the "path-with-spaces" workaround.
        # MUST be a path that contains no spaces (that's the whole
        # point — FEMMT's broken shell quoting needs a clean path).
        # Falls back to a known no-spaces OS-specific location when
        # the tempdir itself happens to contain spaces (typical case:
        # Windows user with a space in their account name, where
        # ``%TEMP% = C:\Users\Luiz Carlos\AppData\Local\Temp``).
        shim_dir = _choose_no_spaces_shim_dir(plat)

        return cls(
            plat=plat,
            app_data_dir=app_data_dir,
            default_onelab_dir=default_onelab_dir,
            femmt_settings_json=femmt_settings_json,
            shim_dir=shim_dir,
        )


__all__ = ["FeaPaths"]
