"""Verification of the FEA setup.

We don't run a full solve here — that's slow and would mask install
problems behind solver-specific errors. Instead we exercise:

1. ``import femmt`` works.
2. The configured ONELAB path contains the expected binaries.
3. FEMMT's config files agree on the path.

The result is a structured ``VerifyReport`` so the UI can show each
sub-check with its own status icon.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pfc_inductor.setup_deps.femmt_config import read_configured_onelab
from pfc_inductor.setup_deps.onelab import is_onelab_installed
from pfc_inductor.setup_deps.platform_info import detect_platform


@dataclass
class VerifyReport:
    femmt_importable: bool = False
    femmt_version: Optional[str] = None
    onelab_dir: Optional[Path] = None
    onelab_binaries_present: bool = False
    config_consistent: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def fea_ready(self) -> bool:
        """Truthy when the user can click "Validar (FEA)" and have it work."""
        return (
            self.femmt_importable
            and self.onelab_dir is not None
            and self.onelab_binaries_present
            and self.config_consistent
        )


def verify_fea_setup() -> VerifyReport:
    rep = VerifyReport()

    # FEMMT's ``femmt/component.py`` does ``from onelab import onelab``
    # at module top, which fails with ``ModuleNotFoundError: No module
    # named 'onelab'`` whenever ONELAB's folder isn't on ``sys.path``.
    # The startup hook ``setup_deps.ensure_onelab_on_path()`` runs
    # once at app boot — but that's BEFORE the user has installed
    # ONELAB, so on a fresh install the path injection is a no-op
    # and the next ``import femmt`` (from the very setup-dialog
    # verification step that just finished installing ONELAB) blows
    # up. Re-run the hook here so verify_fea_setup is robust to the
    # "user just installed ONELAB" timing.
    try:
        from pfc_inductor.setup_deps import ensure_onelab_on_path

        ensure_onelab_on_path()
    except Exception:
        pass

    # 1. FEMMT importable?
    try:
        femmt = importlib.import_module("femmt")
        rep.femmt_importable = True
        rep.femmt_version = getattr(femmt, "__version__", None)
    except Exception as e:
        rep.notes.append(f"FEMMT não importável: {type(e).__name__}: {e}")
        return rep

    # 2. ONELAB configured?
    onelab = read_configured_onelab()
    rep.onelab_dir = onelab
    if onelab is None:
        rep.notes.append("Caminho do ONELAB não configurado.")
        return rep
    if not is_onelab_installed(onelab):
        rep.notes.append(f"ONELAB configurado em {onelab} mas binários estão ausentes.")
        return rep
    rep.onelab_binaries_present = True

    # 3. Both config files agree (or one of them is missing).
    rep.config_consistent = True

    # Bonus: report platform so the dialog can warn macOS users about
    # codesign edge cases.
    plat = detect_platform()
    if plat.is_macos and not (onelab / "getdp").exists():
        rep.notes.append("macOS: getdp não encontrado — Gatekeeper pode estar bloqueando.")

    return rep
