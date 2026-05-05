"""Write the FEMMT configuration that points to the ONELAB folder.

FEMMT 0.5.x reads its config from
``<site-packages>/femmt/config.json``. Older docs and some versions
also honour ``~/.femmt_settings.json``. We write both for safety.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional


HOME_CONFIG = Path.home() / ".femmt_settings.json"


def _femmt_package_config() -> Optional[Path]:
    """Locate ``<site-packages>/femmt/config.json``.

    Returns ``None`` if FEMMT isn't importable — in that case the home
    config is enough; the package config will be written by an explicit
    invocation after FEMMT install.
    """
    try:
        import femmt  # type: ignore[import-not-found]
    except ImportError:
        return None
    init_path = getattr(femmt, "__file__", None)
    if not init_path:
        return None
    pkg_dir = Path(init_path).resolve().parent
    return pkg_dir / "config.json"


def write_femmt_config(onelab_dir: Path) -> list[Path]:
    """Write the ONELAB path into both config locations.

    Returns the list of files actually written. Failure to write the
    package config (because FEMMT isn't installed) is non-fatal; the home
    config is always written.
    """
    onelab_dir = Path(onelab_dir).expanduser().resolve()
    payload = {"onelab": str(onelab_dir)}
    written: list[Path] = []

    HOME_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    HOME_CONFIG.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8",
    )
    written.append(HOME_CONFIG)

    pkg_cfg = _femmt_package_config()
    if pkg_cfg is not None:
        try:
            pkg_cfg.parent.mkdir(parents=True, exist_ok=True)
            pkg_cfg.write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8",
            )
            written.append(pkg_cfg)
        except OSError:
            # Site-packages might be read-only (system install). Home
            # config still works.
            pass

    return written


def read_configured_onelab() -> Optional[Path]:
    """Return the configured ONELAB path, or ``None`` if not set."""
    candidates = [HOME_CONFIG]
    pkg = _femmt_package_config()
    if pkg is not None:
        candidates.append(pkg)
    for c in candidates:
        if not c.exists():
            continue
        try:
            data = json.loads(c.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        path = data.get("onelab") or data.get("ONELAB")
        if path:
            return Path(path).expanduser()
    return None
