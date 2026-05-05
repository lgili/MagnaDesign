"""Platform detection for the cross-platform installer.

Returns a small enum-like dataclass describing the target so the rest of
the setup pipeline doesn't sprinkle ``platform.system()`` checks
everywhere.
"""
from __future__ import annotations
import platform as _pyplatform
from dataclasses import dataclass
from typing import Literal


OS = Literal["darwin", "linux", "windows"]
Arch = Literal["arm64", "x86_64"]


class UnsupportedPlatform(RuntimeError):
    """Raised when the current OS/arch combination is not supported."""


@dataclass(frozen=True)
class PlatformInfo:
    os: OS
    arch: Arch

    @property
    def onelab_tag(self) -> str:
        """ONELAB upstream calls these tags ``Darwin64``, ``Linux64``,
        ``Windows64``. There is no separate arm64 tarball on the official
        site as of upstream 4.x — the macOS build is a fat binary.
        """
        return {
            "darwin": "Darwin64",
            "linux": "Linux64",
            "windows": "Windows64",
        }[self.os]

    @property
    def archive_ext(self) -> str:
        return "zip" if self.os == "windows" else "tgz"

    @property
    def is_macos(self) -> bool:
        return self.os == "darwin"

    @property
    def is_windows(self) -> bool:
        return self.os == "windows"


def detect_platform(
    *,
    system: str | None = None,
    machine: str | None = None,
) -> PlatformInfo:
    """Detect the current platform.

    The optional ``system``/``machine`` args make this trivially testable
    without monkeypatching the ``platform`` module.
    """
    sysname = (system or _pyplatform.system()).lower()
    arch_raw = (machine or _pyplatform.machine()).lower()

    if sysname == "darwin":
        os: OS = "darwin"
    elif sysname == "linux":
        os = "linux"
    elif sysname.startswith("win"):
        os = "windows"
    else:
        raise UnsupportedPlatform(f"Sistema operacional não suportado: {sysname}")

    if arch_raw in ("arm64", "aarch64"):
        arch: Arch = "arm64"
    elif arch_raw in ("x86_64", "amd64", "x64"):
        arch = "x86_64"
    else:
        raise UnsupportedPlatform(f"Arquitetura não suportada: {arch_raw}")

    return PlatformInfo(os=os, arch=arch)
