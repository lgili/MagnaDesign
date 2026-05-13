"""Tests for the cross-platform FEA installer.

Network calls and ``codesign`` invocations are not exercised here — those
need a real macOS machine and bandwidth, and we cover them manually as
part of the release checklist.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pfc_inductor.setup_deps import femmt_config, workaround
from pfc_inductor.setup_deps.onelab import is_onelab_installed
from pfc_inductor.setup_deps.platform_info import (
    PlatformInfo,
    UnsupportedPlatform,
    detect_platform,
)
from pfc_inductor.setup_deps.urls import onelab_archive_url


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "system,machine,expected",
    [
        ("Darwin", "arm64", PlatformInfo("darwin", "arm64")),
        ("Darwin", "x86_64", PlatformInfo("darwin", "x86_64")),
        ("Linux", "x86_64", PlatformInfo("linux", "x86_64")),
        ("Linux", "aarch64", PlatformInfo("linux", "arm64")),
        ("Windows", "AMD64", PlatformInfo("windows", "x86_64")),
    ],
)
def test_detect_platform_known(system, machine, expected):
    assert detect_platform(system=system, machine=machine) == expected


@pytest.mark.parametrize(
    "system,machine",
    [
        ("FreeBSD", "x86_64"),
        ("Linux", "ppc64le"),
    ],
)
def test_detect_platform_unsupported(system, machine):
    with pytest.raises(UnsupportedPlatform):
        detect_platform(system=system, machine=machine)


def test_onelab_archive_url_per_platform():
    p_mac = PlatformInfo("darwin", "arm64")
    p_linux = PlatformInfo("linux", "x86_64")
    p_win = PlatformInfo("windows", "x86_64")
    assert onelab_archive_url(p_mac).endswith("Darwin64.tgz")
    assert onelab_archive_url(p_linux).endswith("Linux64.tgz")
    assert onelab_archive_url(p_win).endswith("Windows64.zip")


# ---------------------------------------------------------------------------
# is_onelab_installed
# ---------------------------------------------------------------------------
def test_is_onelab_installed_true_when_files_present(tmp_path):
    (tmp_path / "onelab.py").write_text("# stub")
    (tmp_path / "getdp").write_bytes(b"binary")
    (tmp_path / "gmsh").write_bytes(b"binary")
    assert is_onelab_installed(tmp_path) is True


def test_is_onelab_installed_false_when_missing(tmp_path):
    (tmp_path / "onelab.py").write_text("# stub")
    # gmsh missing
    (tmp_path / "getdp").write_bytes(b"binary")
    assert is_onelab_installed(tmp_path) is False


def test_is_onelab_installed_handles_windows_exes(tmp_path, monkeypatch):
    """On Windows the binary names carry ``.exe`` — the platform-
    strict installation check (``FeaPaths.is_onelab_installed_at``)
    only accepts the suffix that matches the running OS, so we
    have to fake the OS detection here to exercise the Windows
    branch from a unix-y test host.

    The pre-refactor code accepted either suffix unconditionally
    (a Mac install with ``.exe`` files reported "installed"),
    which was wrong — it hid the case where a download landed
    with the wrong binary set.
    """
    from pfc_inductor.setup_deps.paths import FeaPaths
    from pfc_inductor.setup_deps.platform_info import PlatformInfo

    win = PlatformInfo(os="windows", arch="x86_64")
    win_paths = FeaPaths.for_platform(win, home=tmp_path)
    monkeypatch.setattr(FeaPaths, "detect", classmethod(lambda cls: win_paths))

    (tmp_path / "onelab.py").write_text("# stub")
    (tmp_path / "getdp.exe").write_bytes(b"binary")
    (tmp_path / "gmsh.exe").write_bytes(b"binary")
    assert is_onelab_installed(tmp_path) is True

    # Same directory with Unix-suffix binaries instead is NOT
    # a Windows install — the previous either-suffix code would
    # have wrongly accepted this.
    (tmp_path / "getdp.exe").unlink()
    (tmp_path / "gmsh.exe").unlink()
    (tmp_path / "getdp").write_bytes(b"binary")
    (tmp_path / "gmsh").write_bytes(b"binary")
    assert is_onelab_installed(tmp_path) is False


# ---------------------------------------------------------------------------
# femmt_config: writes home + (optional) package config
# ---------------------------------------------------------------------------
def test_write_femmt_config_uses_home(tmp_path, monkeypatch):
    home_cfg = tmp_path / "home.json"
    monkeypatch.setattr(femmt_config, "HOME_CONFIG", home_cfg)
    monkeypatch.setattr(femmt_config, "_femmt_package_config", lambda: None)

    onelab_dir = tmp_path / "onelab"
    onelab_dir.mkdir()
    written = femmt_config.write_femmt_config(onelab_dir)

    assert home_cfg in written
    payload = json.loads(home_cfg.read_text())
    assert Path(payload["onelab"]) == onelab_dir.resolve()


def test_write_femmt_config_writes_both_when_pkg_present(tmp_path, monkeypatch):
    home_cfg = tmp_path / "home.json"
    pkg_cfg = tmp_path / "pkg" / "config.json"
    pkg_cfg.parent.mkdir()
    monkeypatch.setattr(femmt_config, "HOME_CONFIG", home_cfg)
    monkeypatch.setattr(femmt_config, "_femmt_package_config", lambda: pkg_cfg)

    onelab_dir = tmp_path / "onelab"
    onelab_dir.mkdir()
    written = femmt_config.write_femmt_config(onelab_dir)

    assert home_cfg in written
    assert pkg_cfg in written
    assert json.loads(pkg_cfg.read_text())["onelab"] == str(onelab_dir.resolve())


def test_read_configured_onelab_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(femmt_config, "HOME_CONFIG", tmp_path / "missing.json")
    monkeypatch.setattr(femmt_config, "_femmt_package_config", lambda: None)
    assert femmt_config.read_configured_onelab() is None


# ---------------------------------------------------------------------------
# Path-with-spaces workaround detection
# ---------------------------------------------------------------------------
class _FakeFemmt:
    def __init__(self, file_path: str):
        self.__file__ = file_path


def test_needs_workaround_true_when_path_has_spaces(monkeypatch):
    fake = _FakeFemmt("/Users/foo/Some Path/site-packages/femmt/__init__.py")
    monkeypatch.setitem(sys.modules, "femmt", fake)
    assert workaround.needs_workaround() is True


def test_needs_workaround_false_when_no_spaces(monkeypatch):
    fake = _FakeFemmt("/usr/local/lib/python3.12/site-packages/femmt/__init__.py")
    monkeypatch.setitem(sys.modules, "femmt", fake)
    assert workaround.needs_workaround() is False


# ── _relocate: symlink + copy fallback paths ─────────────────────
def test_relocate_uses_symlink_on_posix(tmp_path: Path):
    """POSIX path: ``os.symlink`` works without privileges, so the
    shim points at the real FEMMT install via a symlink (zero disk
    cost). This is the fast path on macOS and Linux."""
    if sys.platform == "win32":
        pytest.skip("POSIX symlink behavior")
    real = tmp_path / "real_femmt"
    real.mkdir()
    (real / "__init__.py").write_text("# real")
    target = tmp_path / "shim" / "femmt"
    target.parent.mkdir()

    assert workaround._relocate(real, target) is True
    assert target.is_symlink()
    assert (target / "__init__.py").read_text() == "# real"


def test_relocate_falls_back_to_copy_when_symlink_fails(monkeypatch, tmp_path: Path):
    """Windows path: ``os.symlink`` raises ``OSError`` without admin /
    Developer Mode. The function must transparently fall back to a
    directory copy so the unprivileged Windows user still gets a
    working FEMMT install."""
    real = tmp_path / "real_femmt"
    real.mkdir()
    (real / "__init__.py").write_text("# real")
    (real / "submodule.py").write_text("x = 1")
    target = tmp_path / "shim" / "femmt"
    target.parent.mkdir()

    def _fail_symlink(*args, **kwargs):
        raise OSError("symlink not permitted")

    monkeypatch.setattr(workaround.os, "symlink", _fail_symlink)

    assert workaround._relocate(real, target) is True
    assert target.is_dir() and not target.is_symlink()
    assert (target / "__init__.py").read_text() == "# real"
    assert (target / "submodule.py").read_text() == "x = 1"


def test_relocate_returns_false_when_both_strategies_fail(monkeypatch, tmp_path: Path):
    """Pathological case (read-only target, full disk, ...) — both
    symlink and copy fail. ``_relocate`` returns False so the caller
    can surface a clear error to the user instead of silently
    pretending the workaround succeeded."""
    real = tmp_path / "real_femmt"
    real.mkdir()
    target = tmp_path / "shim" / "femmt"
    target.parent.mkdir()

    monkeypatch.setattr(
        workaround.os, "symlink", lambda *a, **k: (_ for _ in ()).throw(OSError("nope"))
    )
    monkeypatch.setattr(
        workaround.shutil,
        "copytree",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )

    assert workaround._relocate(real, target) is False


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------
def test_cli_check_returns_zero_when_ready(monkeypatch, capsys):
    """``--check`` should exit 0 when the verifier reports ``fea_ready``."""
    from pfc_inductor.setup_deps import cli as cli_mod
    from pfc_inductor.setup_deps.verify import VerifyReport

    rep = VerifyReport(
        femmt_importable=True,
        femmt_version="0.5.4",
        onelab_dir=Path("/tmp/onelab"),
        onelab_binaries_present=True,
        config_consistent=True,
    )
    monkeypatch.setattr(cli_mod, "check_fea_setup", lambda: rep)
    code = cli_mod.main(["--check", "--no-color"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Pronto para usar  : sim" in out


def test_cli_check_returns_one_when_missing(monkeypatch):
    from pfc_inductor.setup_deps import cli as cli_mod
    from pfc_inductor.setup_deps.verify import VerifyReport

    rep = VerifyReport(femmt_importable=False, notes=["femmt não importável"])
    monkeypatch.setattr(cli_mod, "check_fea_setup", lambda: rep)
    code = cli_mod.main(["--check", "--no-color"])
    assert code == 1
