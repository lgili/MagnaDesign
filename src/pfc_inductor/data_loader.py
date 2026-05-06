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
3. **Catalog** — ``data/mas/catalog/{materials,wires}.json`` imported
   from OpenMagnetics MAS (see ``scripts/import_mas_catalog.py``).
4. **Legacy** — ``data/{materials,cores,wires}.json`` (only used when no
   MAS-shaped file exists).

Entries with the same ``id`` collapse: only the highest-precedence copy
is returned. The auto-detect for MAS shape vs legacy is per-file.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Iterable

from platformdirs import user_data_dir

from pfc_inductor.models import Core, Material, Wire

APP_NAME = "PFCInductorDesigner"
APP_AUTHOR = "indutor"

_PACKAGE_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_ROOT.parent.parent
_BUNDLED_DATA = _REPO_ROOT / "data"
_BUNDLED_MAS = _BUNDLED_DATA / "mas"
_BUNDLED_CATALOG = _BUNDLED_MAS / "catalog"


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
    return (
        "manufacturer" in s
        or "permeability" in s
        or "dimensions" in s
        or "conductingArea" in s
    )


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
    """Merge primary + catalog entries with id-based precedence.

    Order, lowest precedence first: catalog -> primary (user/curated/legacy).
    Entries that share an id collapse to the highest-precedence copy. Items
    without an id (legacy data sometimes omitted them) pass through as-is.
    """
    primary_raw = _open_data(file_name).get(key, [])
    primary = list(_decode_entries(primary_raw, kind))
    primary_ids = {getattr(e, "id", None) for e in primary}

    catalog_payload = _open_catalog(file_name) if file_name != "cores.json" else None
    if catalog_payload is None:
        return primary
    catalog_raw = [
        e for e in catalog_payload.get(key, [])
        if _entry_id(e) not in primary_ids
    ]
    catalog = list(_decode_entries(catalog_raw, kind))
    return primary + catalog


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
        if _entry_source(entry) == "openmagnetics":
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


# ---------------------------------------------------------------------------
# Save paths (writes legacy format by default; pass `as_mas=True` for MAS)
# ---------------------------------------------------------------------------
def save_materials(materials: list[Material], *, as_mas: bool = False) -> Path:
    p = user_data_path() / "materials.json"
    if as_mas:
        from pfc_inductor.models.mas import material_to_mas
        items = [
            material_to_mas(m).model_dump(mode="json", by_alias=True,
                                          exclude_none=True)
            for m in materials
        ]
    else:
        items = [m.model_dump(mode="json") for m in materials]
    payload = {
        "_comment": "Edited via PFC Inductor Designer DB editor.",
        "materials": items,
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    return p


def save_cores(cores: list[Core], *, as_mas: bool = False) -> Path:
    p = user_data_path() / "cores.json"
    if as_mas:
        from pfc_inductor.models.mas import core_to_mas
        items = [
            core_to_mas(c).model_dump(mode="json", by_alias=True,
                                      exclude_none=True)
            for c in cores
        ]
    else:
        items = [c.model_dump(mode="json") for c in cores]
    payload = {
        "_comment": "Edited via PFC Inductor Designer DB editor.",
        "cores": items,
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    return p


def save_wires(wires: list[Wire], *, as_mas: bool = False) -> Path:
    p = user_data_path() / "wires.json"
    if as_mas:
        from pfc_inductor.models.mas import wire_to_mas
        items = [
            wire_to_mas(w).model_dump(mode="json", by_alias=True,
                                      exclude_none=True)
            for w in wires
        ]
    else:
        items = [w.model_dump(mode="json") for w in wires]
    payload = {
        "_comment": "Edited via PFC Inductor Designer DB editor.",
        "wires": items,
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    return p
