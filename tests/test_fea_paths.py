"""Cross-platform FEA path resolution.

``FeaPaths`` is the single source of truth for every disk path the
FEA setup pipeline touches. These tests pin the per-OS resolution
so a future refactor can't silently move the ONELAB install
directory or break the Windows binary-suffix lookup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pfc_inductor.setup_deps.paths import FeaPaths
from pfc_inductor.setup_deps.platform_info import PlatformInfo


# Helpers ---------------------------------------------------------
def _plat(os_name: str) -> PlatformInfo:
    return PlatformInfo(os=os_name, arch="x86_64")  # type: ignore[arg-type]


# ── Binary names ────────────────────────────────────────────────
def test_binary_names_windows_appends_exe():
    paths = FeaPaths.for_platform(_plat("windows"), home=Path("C:/Users/test"))
    assert paths.getdp_exe_name == "getdp.exe"
    assert paths.gmsh_exe_name == "gmsh.exe"
    assert paths.onelab_helper_name == "onelab.py"


def test_binary_names_macos_no_suffix():
    paths = FeaPaths.for_platform(_plat("darwin"), home=Path("/Users/test"))
    assert paths.getdp_exe_name == "getdp"
    assert paths.gmsh_exe_name == "gmsh"


def test_binary_names_linux_no_suffix():
    paths = FeaPaths.for_platform(_plat("linux"), home=Path("/home/test"))
    assert paths.getdp_exe_name == "getdp"
    assert paths.gmsh_exe_name == "gmsh"


# ── App data dir ────────────────────────────────────────────────
def test_app_data_dir_windows_uses_localappdata(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")
    paths = FeaPaths.for_platform(_plat("windows"), home=Path(r"C:\Users\test"))
    assert paths.app_data_dir == Path(r"C:\Users\test\AppData\Local") / "MagnaDesign"


def test_app_data_dir_windows_fallback_when_localappdata_unset(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    paths = FeaPaths.for_platform(_plat("windows"), home=Path(r"C:\Users\test"))
    assert paths.app_data_dir == (Path(r"C:\Users\test") / "AppData" / "Local" / "MagnaDesign")


def test_app_data_dir_macos_uses_library_application_support():
    paths = FeaPaths.for_platform(_plat("darwin"), home=Path("/Users/test"))
    assert paths.app_data_dir == Path("/Users/test/Library/Application Support/MagnaDesign")


def test_app_data_dir_linux_xdg(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_DATA_HOME", "/home/test/.share")
    paths = FeaPaths.for_platform(_plat("linux"), home=Path("/home/test"))
    assert paths.app_data_dir == Path("/home/test/.share/magnadesign")


def test_app_data_dir_linux_default_when_xdg_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    paths = FeaPaths.for_platform(_plat("linux"), home=Path("/home/test"))
    assert paths.app_data_dir == Path("/home/test/.local/share/magnadesign")


# ── Default ONELAB install dir ──────────────────────────────────
def test_default_onelab_dir_windows_under_app_data(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")
    paths = FeaPaths.for_platform(_plat("windows"), home=Path(r"C:\Users\test"))
    # Windows users expect application binaries under LOCALAPPDATA,
    # not in their home folder root.
    assert paths.default_onelab_dir == (
        Path(r"C:\Users\test\AppData\Local") / "MagnaDesign" / "onelab"
    )


def test_default_onelab_dir_macos_legacy_home():
    # Historical install location; keeping it so existing users'
    # ``~/onelab`` trees don't get orphaned by a re-default.
    paths = FeaPaths.for_platform(_plat("darwin"), home=Path("/Users/test"))
    assert paths.default_onelab_dir == Path("/Users/test/onelab")


def test_default_onelab_dir_linux_legacy_home():
    paths = FeaPaths.for_platform(_plat("linux"), home=Path("/home/test"))
    assert paths.default_onelab_dir == Path("/home/test/onelab")


# ── FEMMT config path ───────────────────────────────────────────
def test_femmt_settings_json_always_home_dotfile():
    """FEMMT 0.5.x hard-codes ``~/.femmt_settings.json``; we can't
    relocate it without forking FEMMT."""
    for os_name, home in (
        ("windows", Path(r"C:\Users\test")),
        ("darwin", Path("/Users/test")),
        ("linux", Path("/home/test")),
    ):
        paths = FeaPaths.for_platform(_plat(os_name), home=home)
        assert paths.femmt_settings_json == home / ".femmt_settings.json", os_name


# ── Shim dir (path-with-spaces workaround) ──────────────────────
def test_shim_dir_uses_tempfile_gettempdir():
    """Was hardcoded ``/tmp/pfc_femmt_shim`` — no ``/tmp`` on Windows."""
    paths = FeaPaths.for_platform(_plat("windows"), home=Path(r"C:\Users\test"))
    import tempfile

    expected = Path(tempfile.gettempdir()) / "pfc_femmt_shim"
    assert paths.shim_dir == expected


# ── is_onelab_installed_at ──────────────────────────────────────
def test_is_onelab_installed_at_finds_unix_binaries(tmp_path: Path):
    paths = FeaPaths.for_platform(_plat("linux"), home=Path("/home/test"))
    install = tmp_path / "onelab"
    install.mkdir()
    (install / "onelab.py").write_text("# helper")
    (install / "getdp").write_text("#!/bin/bash")
    (install / "gmsh").write_text("#!/bin/bash")
    assert paths.is_onelab_installed_at(install) is True


def test_is_onelab_installed_at_requires_exe_on_windows(tmp_path: Path):
    paths = FeaPaths.for_platform(_plat("windows"), home=Path(r"C:\Users\test"))
    install = tmp_path / "onelab"
    install.mkdir()
    (install / "onelab.py").write_text("# helper")
    # Without .exe suffix the check fails on Windows.
    (install / "getdp").write_text("not the exe")
    (install / "gmsh").write_text("not the exe")
    assert paths.is_onelab_installed_at(install) is False
    # Adding the .exe versions makes it pass.
    (install / "getdp.exe").write_text("real exe")
    (install / "gmsh.exe").write_text("real exe")
    assert paths.is_onelab_installed_at(install) is True


def test_is_onelab_installed_at_missing_helper_fails(tmp_path: Path):
    paths = FeaPaths.for_platform(_plat("linux"), home=Path("/home/test"))
    install = tmp_path / "onelab"
    install.mkdir()
    (install / "getdp").write_text("#!/bin/bash")
    (install / "gmsh").write_text("#!/bin/bash")
    # onelab.py missing → not installed.
    assert paths.is_onelab_installed_at(install) is False


def test_is_onelab_installed_at_returns_false_for_nonexistent_dir(tmp_path: Path):
    paths = FeaPaths.for_platform(_plat("linux"), home=Path("/home/test"))
    assert paths.is_onelab_installed_at(tmp_path / "does-not-exist") is False


# ── onelab_binary_path ──────────────────────────────────────────
def test_onelab_binary_path_resolves_with_suffix():
    paths_w = FeaPaths.for_platform(_plat("windows"), home=Path(r"C:\Users\test"))
    install = Path(r"C:\Onelab")
    assert paths_w.onelab_binary_path(install, "getdp") == install / "getdp.exe"
    assert paths_w.onelab_binary_path(install, "gmsh") == install / "gmsh.exe"

    paths_m = FeaPaths.for_platform(_plat("darwin"), home=Path("/Users/test"))
    assert paths_m.onelab_binary_path(install, "getdp") == install / "getdp"


def test_onelab_binary_path_rejects_unknown_name():
    paths = FeaPaths.for_platform(_plat("linux"), home=Path("/home/test"))
    with pytest.raises(ValueError, match="unknown ONELAB binary name"):
        paths.onelab_binary_path(Path("/tmp"), "onelab")  # onelab is the .py helper


# ── Detect roundtrip ────────────────────────────────────────────
def test_detect_uses_current_os():
    """Smoke: ``detect()`` should return a sensible answer on the
    host running the test suite."""
    paths = FeaPaths.detect()
    # Whichever OS we're on, the binary names should be self-consistent.
    if paths.plat.is_windows:
        assert paths.getdp_exe_name.endswith(".exe")
        assert paths.gmsh_exe_name.endswith(".exe")
    else:
        assert paths.getdp_exe_name == "getdp"
        assert paths.gmsh_exe_name == "gmsh"
