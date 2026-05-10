"""Cross-platform installer for the FEA backend.

Public entry points:

- ``setup_fea(...)`` — runs every step end-to-end. Idempotent.
- ``check_fea_setup()`` — fast read-only verification used at boot to
  decide whether to surface the setup dialog.
- ``SetupReport`` / ``SetupStep`` — structured progress so the UI dialog
  and the CLI can render the same data.

Importing this module never triggers a download or any network access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from pfc_inductor.setup_deps.femmt_config import (
    read_configured_onelab as read_configured_onelab,
)
from pfc_inductor.setup_deps.femmt_config import (
    write_femmt_config,
)
from pfc_inductor.setup_deps.onelab import (
    codesign_macos,
    default_onelab_dir,
    download_onelab,
)
from pfc_inductor.setup_deps.onelab import (
    is_onelab_installed as is_onelab_installed,
)
from pfc_inductor.setup_deps.platform_info import (
    PlatformInfo,
    UnsupportedPlatform,
    detect_platform,
)
from pfc_inductor.setup_deps.verify import VerifyReport, verify_fea_setup
from pfc_inductor.setup_deps.workaround import install_path_workaround

__all__ = [
    "PlatformInfo",
    "SetupReport",
    "SetupStep",
    "UnsupportedPlatform",
    "VerifyReport",
    "check_fea_setup",
    "ensure_onelab_on_path",
    "setup_fea",
]


def ensure_onelab_on_path() -> Optional[Path]:
    """Add the configured ONELAB folder to ``sys.path`` if needed.

    FEMMT 0.5.x's ``femmt/component.py`` does ``from onelab import
    onelab`` at module load — it expects the ONELAB helper module
    ``onelab.py`` to be importable as a top-level package. ONELAB is
    a binary distribution (gmsh + getdp + a small ``onelab.py``
    Python helper) we install separately into the user's home, so
    Python doesn't find it on ``sys.path`` unless we put it there.

    Without this call, the bundled .app crashes with
    ``ModuleNotFoundError: No module named 'onelab'`` the moment any
    code path touches ``femmt`` — which is exactly the user-reported
    "fala que nao escontra o modulo onelab" symptom.

    Idempotent: returns the path that was added (or already present)
    on success, ``None`` if no configured ONELAB was found. Always
    safe to call multiple times — the second call short-circuits.

    **Important:** this function intentionally bypasses
    ``read_configured_onelab()`` and reads ``~/.femmt_settings.json``
    directly. The full reader probes for ``<femmt>/config.json``
    too, which requires ``import femmt`` — and that's the very
    import this function is supposed to make safe. Calling it
    indirectly here would create the chicken-and-egg crash the
    user reported in v0.4.5: ``ensure_onelab_on_path`` triggers
    ``import femmt`` triggers ``from onelab import onelab``
    BEFORE the path injection has run.
    """
    import json
    import sys

    home_config = Path.home() / ".femmt_settings.json"
    if not home_config.exists():
        return None
    try:
        data = json.loads(home_config.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    raw = data.get("onelab") or data.get("ONELAB")
    if not raw:
        return None
    onelab_dir = Path(raw).expanduser()
    if not (onelab_dir / "onelab.py").exists():
        return None
    onelab_str = str(onelab_dir)
    if onelab_str in sys.path:
        return onelab_dir
    sys.path.insert(0, onelab_str)
    return onelab_dir


@dataclass
class SetupStep:
    name: str
    ok: bool = False
    detail: str = ""


@dataclass
class SetupReport:
    platform: Optional[PlatformInfo] = None
    onelab_dir: Optional[Path] = None
    steps: list[SetupStep] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.steps.append(SetupStep(name=name, ok=ok, detail=detail))


ProgressCb = Optional[Callable[[str, float], None]]


def check_fea_setup() -> VerifyReport:
    """Read-only check used by the main window on boot."""
    return verify_fea_setup()


def setup_fea(
    *,
    onelab_dir: Optional[Path] = None,
    skip_codesign: bool = False,
    on_progress: ProgressCb = None,
) -> SetupReport:
    """Run every setup step end-to-end.

    Each step is recorded in the returned ``SetupReport``. Failures in
    optional steps (codesign, path workaround) are non-fatal and reported
    as ``ok=False`` with a detail message — they don't abort the rest.
    """
    report = SetupReport()
    onelab_dir = Path(onelab_dir).expanduser() if onelab_dir else default_onelab_dir()
    report.onelab_dir = onelab_dir

    # 1. Platform
    try:
        plat = detect_platform()
        report.platform = plat
        report.add("Detectar plataforma", True, f"{plat.os}-{plat.arch} ({plat.onelab_tag})")
    except UnsupportedPlatform as e:
        report.add("Detectar plataforma", False, str(e))
        return report

    # 2. Download + extract
    try:
        downloaded = download_onelab(
            onelab_dir,
            plat=plat,
            on_progress=on_progress,
        )
        if downloaded:
            report.add("Baixar ONELAB", True, f"instalado em {onelab_dir}")
        else:
            report.add("Baixar ONELAB", True, "já presente — pulando")
    except Exception as e:  # network, disk, archive issues
        report.add("Baixar ONELAB", False, f"{type(e).__name__}: {e}")
        return report

    # 3. macOS codesign
    if plat.is_macos and not skip_codesign:
        try:
            n = codesign_macos(onelab_dir, on_progress=on_progress)
            report.add("Assinar binários (macOS)", True, f"{n} arquivo(s)")
        except Exception as e:
            report.add("Assinar binários (macOS)", False, str(e))
    else:
        report.add(
            "Assinar binários (macOS)",
            True,
            "não aplicável" if not plat.is_macos else "pulado por solicitação",
        )

    # 4. Write FEMMT config
    try:
        written = write_femmt_config(onelab_dir)
        report.add(
            "Escrever config da FEMMT",
            True,
            ", ".join(str(p) for p in written) or "nenhum arquivo escrito",
        )
    except Exception as e:
        report.add("Escrever config da FEMMT", False, str(e))

    # 5. Path-with-spaces workaround (macOS only, in practice)
    try:
        shim = install_path_workaround()
        if shim is not None:
            report.add("Workaround path com espaços", True, f"shim em {shim}")
        else:
            report.add("Workaround path com espaços", True, "não necessário")
    except Exception as e:
        report.add("Workaround path com espaços", False, str(e))

    # 6. Verify
    v = verify_fea_setup()
    if v.fea_ready:
        report.add(
            "Verificar instalação", True, f"FEMMT {v.femmt_version or '?'} + ONELAB {v.onelab_dir}"
        )
    else:
        report.add(
            "Verificar instalação",
            False,
            "; ".join(v.notes) or "verificação retornou falha sem detalhes",
        )

    return report
