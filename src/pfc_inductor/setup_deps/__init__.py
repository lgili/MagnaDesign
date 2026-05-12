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
    """Make ``from onelab import onelab`` resolvable for FEMMT.

    FEMMT 0.5.x's ``femmt/component.py`` does

        from onelab import onelab

    at module load. That's the ``from <package> import <submodule>``
    pattern: Python expects ``onelab`` to be a *package* (a folder
    importable as a module), and ``onelab.onelab`` to be the
    submodule inside it (the actual ``onelab.py`` file). The
    upstream ONELAB binary distribution we install for the user
    ships ``onelab.py`` as a flat file in ``~/onelab/`` — no
    ``__init__.py``. Python 3's implicit namespace packages make
    that folder importable AS A PACKAGE as long as its **parent**
    is on ``sys.path`` (not the folder itself).

    Old (v0.4.x) versions of this function added the onelab folder
    itself to ``sys.path``, which made the folder look like a
    plain module directory. ``import onelab`` then resolved to
    ``/Users/.../onelab/onelab.py`` (the FILE) and
    ``from onelab import onelab`` blew up with
    ``ImportError: cannot import name 'onelab' from 'onelab'`` —
    the file doesn't export an ``onelab`` attribute, it exports
    ``client``, ``path``, ``extract``, etc.

    The fix is to add the **parent** of the configured onelab
    folder to ``sys.path``. Then:

      - ``import onelab`` finds ``~/onelab/`` as a namespace
        package.
      - ``from onelab import onelab`` finds
        ``~/onelab/onelab.py`` as the submodule.
      - ``onelab.client(__file__)`` (which is what FEMMT actually
        wants) resolves to the class inside the submodule.

    Idempotent: returns the parent path on success, ``None`` if
    no configured ONELAB was found. Safe to call multiple times.

    Reads ``~/.femmt_settings.json`` directly with stdlib JSON;
    deliberately avoids ``read_configured_onelab`` because the
    full reader probes ``<femmt>/config.json`` which requires
    ``import femmt`` — the chicken-and-egg this helper exists
    to make safe.
    """
    import json
    import sys

    from pfc_inductor.setup_deps.paths import FeaPaths

    home_config = FeaPaths.detect().femmt_settings_json
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
    # Inject the PARENT so the folder is importable as a namespace
    # package and ``from onelab import onelab`` finds the submodule.
    parent = onelab_dir.parent
    parent_str = str(parent)
    if parent_str not in sys.path:
        sys.path.insert(0, parent_str)
    # Drop any stale injection of the onelab folder itself — leaving
    # it on ``sys.path`` would shadow the namespace-package lookup
    # because Python prefers a flat ``onelab.py`` over an implicit
    # ``onelab/`` package when both match.
    folder_str = str(onelab_dir)
    while folder_str in sys.path:
        sys.path.remove(folder_str)
    return parent


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

    # Step 0: Path-with-spaces workaround. This MUST run first, as
    # subsequent steps may trigger a `femmt` import, which would
    # fail with a SyntaxError if the patching hasn't run yet.
    try:
        shim = install_path_workaround()
        if shim is not None:
            report.add("Workaround path com espaços", True, f"shim em {shim}")
        else:
            report.add("Workaround path com espaços", True, "não necessário")
    except Exception as e:
        report.add("Workaround path com espaços", False, str(e))
        # This step is critical for fixing syntax errors, so we abort if it fails.
        return report

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

    # 5. Verify
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
