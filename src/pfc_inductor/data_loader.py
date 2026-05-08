"""Load core/material/wire databases from JSON, with user-data dir overlay.

Supports two on-disk layouts:

- **MAS (preferred)**: files under `data/mas/{materials,cores,wires}.json`
  shaped per `pfc_inductor.models.mas.types` (subset of OpenMagnetics MAS).
- **Legacy**: files under `data/{materials,cores,wires}.json` shaped per
  our internal pydantic models (the original format).

Source precedence, highest first:

1. **User overlay** — ``<user_data_dir>/{materials,cores,wires}.json``
   (whatever the user edited via the DB editor).
2. **Curated** — ``data/mas/{materials,cores,wires}.json`` shipped with
   the app, hand-tuned (rolloff/Steinmetz calibrations).
3. **MAS catalog** — ``data/mas/catalog/{materials,wires}.json`` imported
   from OpenMagnetics MAS (see ``scripts/import_mas_catalog.py``).
4. **PyETK catalog** — ``data/pyetk/{materials,cores}.json`` imported
   from ansys/ansys-pyetk (see ``scripts/import_pyetk_catalog.py``).
   Tagged with ``x-pfc-inductor.source = "pyetk"`` so the
   "Apenas curados" filter excludes them by default.
5. **Legacy** — ``data/{materials,cores,wires}.json`` (only used when no
   MAS-shaped file exists).

Entries with the same ``id`` collapse: only the highest-precedence copy
is returned. The auto-detect for MAS shape vs legacy is per-file.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable

from platformdirs import user_data_dir

from pfc_inductor.models import Core, Material, Wire

APP_NAME = "PFCInductorDesigner"
APP_AUTHOR = "indutor"

_PACKAGE_ROOT = Path(__file__).resolve().parent


def _bundled_data_root() -> Path:
    """Locate the bundled ``data/`` directory across all run modes.

    Three deployment shapes are supported and probed in order:

    1. **PyInstaller frozen build** — ``sys._MEIPASS`` (one-file mode)
       or ``sys.executable``'s parent (one-folder mode). The release
       workflow ships ``data/`` next to the binary so we look there
       first when ``sys.frozen`` is set.
    2. **Editable install from a checkout** — ``data/`` lives at
       ``<repo>/data/`` (one level above ``src/pfc_inductor/``).
    3. **Pip-installed wheel** — ``data/`` was copied into the package
       itself via ``[tool.setuptools.package-data]``; resolves to
       ``<site-packages>/pfc_inductor/data/``.

    The first existing directory wins. ``PFC_INDUCTOR_DATA_DIR`` env
    var overrides everything for power users / packagers.
    """
    override = os.environ.get("PFC_INDUCTOR_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if getattr(sys, "frozen", False):
        # PyInstaller one-file extracts to ``sys._MEIPASS``.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate = Path(meipass) / "data"
            if candidate.exists():
                return candidate
        # PyInstaller one-folder: ``data/`` ships alongside the
        # executable in ``<dist>/pfc-inductor/``.
        exe_dir = Path(sys.executable).resolve().parent
        candidate = exe_dir / "data"
        if candidate.exists():
            return candidate

    # Editable / source checkout: ``<repo>/data``.
    repo_data = _PACKAGE_ROOT.parent.parent / "data"
    if repo_data.exists():
        return repo_data

    # Wheel install: ``<site-packages>/pfc_inductor/data``.
    return _PACKAGE_ROOT / "data"


_BUNDLED_DATA = _bundled_data_root()
_BUNDLED_MAS = _BUNDLED_DATA / "mas"
_BUNDLED_CATALOG = _BUNDLED_MAS / "catalog"
_BUNDLED_PYETK = _BUNDLED_DATA / "pyetk"


def user_data_path() -> Path:
    p = Path(user_data_dir(APP_NAME, APP_AUTHOR))
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_user_data() -> Path:
    """Copy bundled JSONs into the user-data dir on first launch (non-destructive).

    Prefers the MAS layout; falls back to legacy if MAS files are missing
    from the bundle.
    """
    target = user_data_path()
    for name in ("materials.json", "cores.json", "wires.json"):
        dst = target / name
        if not dst.exists():
            src_mas = _BUNDLED_MAS / name
            src_legacy = _BUNDLED_DATA / name
            src = src_mas if src_mas.exists() else src_legacy
            if src.exists():
                shutil.copy2(src, dst)
    return target


def _open_data(name: str) -> dict:
    """Read the user-data overlay if present, else MAS-bundled, else legacy."""
    user_path = user_data_path() / name
    if user_path.exists():
        return json.loads(user_path.read_text(encoding="utf-8"))
    mas_path = _BUNDLED_MAS / name
    if mas_path.exists():
        return json.loads(mas_path.read_text(encoding="utf-8"))
    legacy = _BUNDLED_DATA / name
    return json.loads(legacy.read_text(encoding="utf-8"))


def _open_catalog(name: str) -> dict | None:
    """Read the imported catalog file under data/mas/catalog/, if present."""
    p = _BUNDLED_CATALOG / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _open_pyetk(name: str) -> dict | None:
    """Read the imported PyETK catalog file under ``data/pyetk/``.

    The PyETK importer (``scripts/import_pyetk_catalog.py``) writes
    legacy-shaped JSON into this directory tagged with
    ``x-pfc-inductor.source = "pyetk"``. Returning ``None`` when the
    file is missing keeps the loader silent for users who never ran
    the import script.
    """
    p = _BUNDLED_PYETK / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _entry_id(entry: dict) -> str | None:
    """Pull the ``id`` from a JSON entry in either MAS or legacy shape."""
    if not isinstance(entry, dict):
        return None
    if "id" in entry and isinstance(entry["id"], str):
        return entry["id"]
    ext = entry.get("x-pfc-inductor")
    if isinstance(ext, dict):
        eid = ext.get("id")
        if isinstance(eid, str):
            return eid
    return None


def _entry_source(entry: dict) -> str:
    """Read ``x-pfc-inductor.source`` (``openmagnetics`` for catalog rows)."""
    if not isinstance(entry, dict):
        return "curated"
    ext = entry.get("x-pfc-inductor")
    if isinstance(ext, dict):
        s = ext.get("source")
        if isinstance(s, str):
            return s
    return "curated"


def _is_mas_payload(items: list[dict]) -> bool:
    """Detect MAS layout by sampling the first item.

    MAS materials use ``manufacturer``+``permeability``; cores use ``shape``
    plus ``dimensions``; wires use ``conductingArea`` (or our adapter alias).
    Legacy layouts use ``vendor`` and friends.
    """
    if not items:
        return False
    s = items[0]
    if not isinstance(s, dict):
        return False
    return "manufacturer" in s or "permeability" in s or "dimensions" in s or "conductingArea" in s


def _decode_entries(items: list[dict], kind: str) -> list:
    """Convert a list of MAS-or-legacy raw dicts into our internal models."""
    if not items:
        return []
    if _is_mas_payload(items):
        if kind == "materials":
            from pfc_inductor.models.mas import MasMaterial, material_from_mas

            return [material_from_mas(MasMaterial(**m)) for m in items]
        if kind == "cores":
            from pfc_inductor.models.mas import MasCore, core_from_mas

            return [core_from_mas(MasCore(**c)) for c in items]
        from pfc_inductor.models.mas import MasWire, wire_from_mas

        return [wire_from_mas(MasWire(**w)) for w in items]
    if kind == "materials":
        return [Material(**m) for m in items]
    if kind == "cores":
        return [Core(**c) for c in items]
    return [Wire(**w) for w in items]


def _merge_with_catalog(file_name: str, key: str, kind: str) -> list:
    """Merge primary + MAS catalog + PyETK catalog with id-based precedence.

    Order, lowest precedence first: PyETK → MAS catalog → primary
    (user/curated/legacy). Entries that share an id collapse to the
    highest-precedence copy. Items without an id (legacy data sometimes
    omitted them) pass through as-is.

    The MAS catalog is consulted only for ``materials.json`` /
    ``wires.json`` (the upstream MAS dataset has no curated cores
    layer); the PyETK catalog covers ``materials.json`` and
    ``cores.json`` because that's what the import script generates.
    """
    primary_raw = _open_data(file_name).get(key, [])
    primary = list(_decode_entries(primary_raw, kind))
    seen_ids: set[str | None] = {getattr(e, "id", None) for e in primary}

    extras: list = []

    # Layer 1: MAS catalog. ``materials.json`` and ``wires.json`` are
    # produced by ``import_mas_catalog.py``; ``cores.json`` is now
    # produced by ``import_mas_cores.py`` (so the previous "exclude
    # cores" carve-out has been dropped).
    mas_payload = _open_catalog(file_name)
    if mas_payload is not None:
        mas_raw = [e for e in mas_payload.get(key, []) if _entry_id(e) not in seen_ids]
        mas_entries = _decode_entries(mas_raw, kind)
        extras.extend(mas_entries)
        seen_ids.update(getattr(e, "id", None) for e in mas_entries)

    # Layer 2: PyETK catalog (covers both materials and cores).
    pyetk_payload = _open_pyetk(file_name)
    if pyetk_payload is not None:
        pyetk_raw = [e for e in pyetk_payload.get(key, []) if _entry_id(e) not in seen_ids]
        pyetk_entries = _decode_entries(pyetk_raw, kind)
        extras.extend(pyetk_entries)

    return primary + extras


def load_materials() -> list[Material]:
    return _merge_with_catalog("materials.json", "materials", "materials")


def load_cores() -> list[Core]:
    # Catalog cores are not yet generated by import_mas_catalog.py — see
    # scripts/import_mas_catalog.py module docstring for rationale.
    return _merge_with_catalog("cores.json", "cores", "cores")


def load_wires() -> list[Wire]:
    return _merge_with_catalog("wires.json", "wires", "wires")


def load_curated_ids(kind: str) -> set[str]:
    """Ids that come from the curated/user source, not the imported catalog.

    Used by the UI to offer a "show curated only" filter.
    """
    file_name = {
        "materials": "materials.json",
        "cores": "cores.json",
        "wires": "wires.json",
    }[kind]
    key = kind
    items = _open_data(file_name).get(key, [])
    out: set[str] = set()
    for entry in items:
        if not isinstance(entry, dict):
            continue
        # Anything from an imported catalog (MAS or PyETK) is *not*
        # curated, even if it lives in the primary file (the user
        # could have copied an imported entry into their overlay).
        if _entry_source(entry) in ("openmagnetics", "pyetk"):
            continue
        eid = _entry_id(entry)
        if eid:
            out.add(eid)
    return out


def find_material(materials: Iterable[Material], material_id: str) -> Material:
    for m in materials:
        if m.id == material_id:
            return m
    raise KeyError(f"Material '{material_id}' not found in database")


def _resolved_source_path(file_name: str) -> Path:
    """Resolve the file `_open_data` would actually read for the given name.

    Mirrors the precedence in `_open_data`: user overlay → bundled MAS →
    bundled legacy. Returns the first path that exists.
    """
    user_path = user_data_path() / file_name
    if user_path.exists():
        return user_path
    mas_path = _BUNDLED_MAS / file_name
    if mas_path.exists():
        return mas_path
    return _BUNDLED_DATA / file_name


def current_db_versions() -> dict[str, str]:
    """SHA-256 content hashes of the active material/core/wire JSON files.

    Used by the cascade `RunStore` so two runs with the same spec hash
    but different DB content are treated as distinct — and a resume
    attempt against a changed catalog is rejected.

    Hashes only the primary source for each kind (the file
    `_open_data` would read). The optional OpenMagnetics catalog
    overlay is intentionally excluded: it is large, slow to hash, and
    its contents change rarely; if a Phase ever cares about it, the
    function can be extended without changing the dict shape.
    """
    versions: dict[str, str] = {}
    for kind, file_name in (
        ("materials", "materials.json"),
        ("cores", "cores.json"),
        ("wires", "wires.json"),
    ):
        path = _resolved_source_path(file_name)
        h = hashlib.sha256()
        if path.exists():
            h.update(path.read_bytes())
        versions[kind] = h.hexdigest()
    return versions


# ---------------------------------------------------------------------------
# Save paths (writes legacy format by default; pass `as_mas=True` for MAS)
# ---------------------------------------------------------------------------
def save_materials(materials: list[Material], *, as_mas: bool = False) -> Path:
    p = user_data_path() / "materials.json"
    if as_mas:
        from pfc_inductor.models.mas import material_to_mas

        items = [
            material_to_mas(m).model_dump(mode="json", by_alias=True, exclude_none=True)
            for m in materials
        ]
    else:
        items = [m.model_dump(mode="json") for m in materials]
    payload = {
        "_comment": "Edited via MagnaDesign DB editor.",
        "materials": items,
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def save_cores(cores: list[Core], *, as_mas: bool = False) -> Path:
    p = user_data_path() / "cores.json"
    if as_mas:
        from pfc_inductor.models.mas import core_to_mas

        items = [
            core_to_mas(c).model_dump(mode="json", by_alias=True, exclude_none=True) for c in cores
        ]
    else:
        items = [c.model_dump(mode="json") for c in cores]
    payload = {
        "_comment": "Edited via MagnaDesign DB editor.",
        "cores": items,
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def save_wires(wires: list[Wire], *, as_mas: bool = False) -> Path:
    p = user_data_path() / "wires.json"
    if as_mas:
        from pfc_inductor.models.mas import wire_to_mas

        items = [
            wire_to_mas(w).model_dump(mode="json", by_alias=True, exclude_none=True) for w in wires
        ]
    else:
        items = [w.model_dump(mode="json") for w in wires]
    payload = {
        "_comment": "Edited via MagnaDesign DB editor.",
        "wires": items,
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p
