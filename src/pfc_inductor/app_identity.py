"""Single source of truth for app identity + per-OS user paths.

Every place that needs to read or write user data (history database,
catalog overlays, telemetry consent, FEA tool installs, QSettings)
must go through this module instead of calling ``platformdirs``
directly. Centralising the strings keeps the on-disk layout
consistent across:

    macOS   →  ~/Library/Application Support/MagnaDesign/
               ~/Library/Caches/MagnaDesign/
    Linux   →  ~/.local/share/MagnaDesign/        (XDG_DATA_HOME)
               ~/.config/MagnaDesign/             (XDG_CONFIG_HOME)
               ~/.cache/MagnaDesign/              (XDG_CACHE_HOME)
    Windows →  %LOCALAPPDATA%\\MagnaDesign\\MagnaDesign\\
               %LOCALAPPDATA%\\MagnaDesign\\MagnaDesign\\Cache\\

Why ``appname == appauthor == "MagnaDesign"``: on Windows
``platformdirs`` follows Microsoft's convention of nesting under
``<appauthor>\\<appname>``. Calling with ``appauthor=None`` makes
``platformdirs`` substitute ``appname`` for the author slot anyway,
producing the same ``MagnaDesign\\MagnaDesign`` nesting — so we set
them equal explicitly to make the intent visible. On macOS and Linux
the ``appauthor`` slot is dropped from the path entirely, so the
duplication is invisible there.
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import (
    user_cache_dir,
    user_config_dir,
    user_data_dir,
    user_log_dir,
)

APP_NAME: str = "MagnaDesign"
APP_AUTHOR: str = "MagnaDesign"


def app_data_dir(*, ensure: bool = True) -> Path:
    """User-writable data directory (history.db, catalog overlays, FEA workdirs)."""
    p = Path(user_data_dir(APP_NAME, APP_AUTHOR))
    if ensure:
        p.mkdir(parents=True, exist_ok=True)
    return p


def app_config_dir(*, ensure: bool = True) -> Path:
    """User-writable config directory (telemetry consent, app settings JSON).

    On macOS and Windows this resolves to the same place as
    :func:`app_data_dir`; on Linux it follows ``XDG_CONFIG_HOME``
    (``~/.config/MagnaDesign``) so the split between *data* and
    *config* matches the freedesktop convention.
    """
    p = Path(user_config_dir(APP_NAME, APP_AUTHOR))
    if ensure:
        p.mkdir(parents=True, exist_ok=True)
    return p


def app_cache_dir(*, ensure: bool = True) -> Path:
    """User-writable cache directory (thumbnails, compiled artefacts, FEA scratch)."""
    p = Path(user_cache_dir(APP_NAME, APP_AUTHOR))
    if ensure:
        p.mkdir(parents=True, exist_ok=True)
    return p


def app_log_dir(*, ensure: bool = True) -> Path:
    """User-writable log directory."""
    p = Path(user_log_dir(APP_NAME, APP_AUTHOR))
    if ensure:
        p.mkdir(parents=True, exist_ok=True)
    return p


def qsettings_args() -> tuple[str, str]:
    """``(organization, application)`` tuple for :class:`QSettings`.

    ``QSettings("MagnaDesign", "MagnaDesign")`` on Windows writes
    under ``HKCU\\Software\\MagnaDesign\\MagnaDesign``; on macOS it
    becomes ``~/Library/Preferences/com.MagnaDesign.MagnaDesign.plist``;
    on Linux it becomes ``~/.config/MagnaDesign/MagnaDesign.conf``.
    """
    return APP_NAME, APP_NAME


__all__ = [
    "APP_AUTHOR",
    "APP_NAME",
    "app_cache_dir",
    "app_config_dir",
    "app_data_dir",
    "app_log_dir",
    "qsettings_args",
]
