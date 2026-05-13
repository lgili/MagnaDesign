"""Load core/material/wire databases from JSON, with user-data dir overlay.

Supports two on-disk layouts:

- **MAS (preferred)**: files under `data/mas/{materials,cores,wires}.json`
  shaped per `pfc_inductor.models.mas.types` (subset of OpenMagnetics MAS).
- **Legacy**: files under `data/{materials,cores,wires}.json` shaped per
  our internal pydantic models (the original format).

Source precedence, highest first:

1. **User overlay (curated)** — ``<user_data_dir>/{materials,cores,wires}.json``
   (the small hand-tuned set the user can edit via the DB editor).
2. **MAS catalog (user)** — ``<user_data_dir>/mas/catalog/{materials,cores,wires}.json``
   (the full OpenMagnetics MAS import, copied to the user dir on first
   launch by :func:`ensure_user_data` and editable thereafter).
3. **PyETK catalog (user)** — ``<user_data_dir>/pyetk/{materials,cores}.json``
   (Ansys-imported ferrites, same copy-on-first-launch pattern).
4. **Bundle fallbacks** — when any of the user-dir files above is
   missing :func:`_open_catalog` / :func:`_open_pyetk` fall back to
   the same path under ``data/`` inside the installed package. New
   installs always have all three trees populated; the fallbacks
   exist for the case where a user deletes a file by hand.

Entries with the same ``id`` collapse: only the highest-precedence copy
is returned. The auto-detect for MAS shape vs legacy is per-file.

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

from pfc_inductor.app_identity import app_data_dir
from pfc_inductor.models import Core, Material, Wire

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
        # PyInstaller one-folder. Two layouts exist depending on the
        # PyInstaller version that produced the bundle:
        #
        # - Legacy / pinned ``contents_directory='.'`` (what the
        #   release spec ships): ``<dist>/magnadesign/data/``.
        # - PyInstaller 6.x default ``contents_directory='_internal'``:
        #   ``<dist>/magnadesign/_internal/data/`` (the executable
        #   stays directly under ``<dist>/magnadesign/``).
        #
        # We probe legacy first because the spec opts back into it,
        # then fall through to ``_internal/data`` so a build that
        # forgot to override the default still works.
        exe_dir = Path(sys.executable).resolve().parent
        for sub in ("", "_internal"):
            candidate = exe_dir / sub / "data" if sub else exe_dir / "data"
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
    return app_data_dir()


def ensure_user_data() -> Path:
    """Copy every bundled JSON into the user-data dir on first launch.

    Three source trees are mirrored verbatim so the engineer can
    edit / extend each catalogue independently:

    1. **Primary (curated)** — small hand-picked set in
       ``<user>/materials.json``, ``<user>/cores.json``,
       ``<user>/wires.json``. Sourced from ``data/mas/*.json`` when
       available, falling back to the legacy ``data/*.json``.

    2. **MAS catalog** — the full OpenMagnetics MAS import, kept in
       ``<user>/mas/catalog/{materials,cores,wires}.json``. Mirrors
       the bundle's ``data/mas/catalog/`` layout so the path-based
       extensions the user files in (``my-cores.json`` siblings,
       e.g.) survive launches.

    3. **PyETK** — Ansys-imported ferrites in
       ``<user>/pyetk/{materials,cores}.json``. Mirrors the bundle's
       ``data/pyetk/`` layout for the same reason.

    Copy is **non-destructive**: a file that already exists in the
    user dir is never overwritten, so the engineer can mutate any
    catalogue without fear of losing edits across upgrades.
    """
    target = user_data_path()

    # Layer 1 — primary/curated triplet at the user dir root.
    for name in ("materials.json", "cores.json", "wires.json"):
        dst = target / name
        if dst.exists():
            continue
        src_mas = _BUNDLED_MAS / name
        src_legacy = _BUNDLED_DATA / name
        src = src_mas if src_mas.exists() else src_legacy
        if src.exists():
            shutil.copy2(src, dst)

    # Layer 2 — full MAS catalog mirrored under ``<user>/mas/catalog/``.
    if _BUNDLED_CATALOG.is_dir():
        user_catalog_dir = target / "mas" / "catalog"
        user_catalog_dir.mkdir(parents=True, exist_ok=True)
        for name in ("materials.json", "cores.json", "wires.json"):
            dst = user_catalog_dir / name
            src = _BUNDLED_CATALOG / name
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)

    # Layer 3 — PyETK mirrored under ``<user>/pyetk/``.
    if _BUNDLED_PYETK.is_dir():
        user_pyetk_dir = target / "pyetk"
        user_pyetk_dir.mkdir(parents=True, exist_ok=True)
        for name in ("materials.json", "cores.json"):
            dst = user_pyetk_dir / name
            src = _BUNDLED_PYETK / name
            if src.exists() and not dst.exists():
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
    """Read the MAS catalog file, preferring the user overlay.

    Look-up order:

    1. ``<user_data>/mas/catalog/<name>`` — copied by
       :func:`ensure_user_data` on first launch and editable by the
       engineer afterwards. Lets a custom MAS-shaped JSON survive
       app upgrades without merge-magic on our side.
    2. ``<bundle>/data/mas/catalog/<name>`` — the read-only ship-time
       catalog. Used until the user dir is populated and as the
       fallback when the overlay file is missing.
    """
    user = user_data_path() / "mas" / "catalog" / name
    src = user if user.exists() else _BUNDLED_CATALOG / name
    if not src.exists():
        return None
    try:
        return json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _open_pyetk(name: str) -> dict | None:
    """Read the PyETK catalog file, preferring the user overlay.

    The PyETK importer (``scripts/import_pyetk_catalog.py``) writes
    legacy-shaped JSON tagged with ``x-pfc-inductor.source = "pyetk"``.
    Returning ``None`` when both overlay and bundle are missing keeps
    the loader silent for users who never ran the import script.

    Look-up order mirrors :func:`_open_catalog`: user overlay first,
    bundle as fallback.
    """
    user = user_data_path() / "pyetk" / name
    src = user if user.exists() else _BUNDLED_PYETK / name
    if not src.exists():
        return None
    try:
        return json.loads(src.read_text(encoding="utf-8"))
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
    cores = _merge_with_catalog("cores.json", "cores", "cores")
    # Normalize the per-core ``default_material_id`` to the
    # canonical material id the materials catalog actually uses.
    # The MAS import emits cores with a legacy ``mas-{name-slug}``
    # form (e.g. ``mas-kool-mµ-26``) but the materials carry their
    # canonical ``{vendor-slug}-{name-slug}`` form (e.g.
    # ``magnetics-kool-mµ-26``). Without this fix-up, code that
    # falls back to the core's default material — including the
    # spec drawer when a project's stored material id has been
    # invalidated — looks up an id that never resolves.
    return _normalize_core_material_refs(cores)


def _normalize_core_material_refs(cores: list[Core]) -> list[Core]:
    """Rewrite each core's ``default_material_id`` to the
    canonical id used by ``load_materials``.

    The mapping is built from the loaded materials: every
    canonical id ``{vendor-slug}-{name-slug}`` is also registered
    under the legacy alias ``mas-{name-slug}`` so the cross-
    reference resolves both forms. Ambiguity (two materials
    sharing the same name slug across vendors) is broken by
    matching against the core's own vendor.
    """
    materials = load_materials()
    canonical_ids = {m.id for m in materials}
    # Build the alias index using the material's ``name`` field
    # rather than splitting the id on dashes — vendors like
    # ``Fair-Rite`` and ``TDK/EPCOS`` make a positional split
    # unreliable (``fair-rite-98`` would split into ``fair`` /
    # ``rite-98``, missing the ``mas-98`` legacy alias the core
    # uses).
    legacy_to_canon: dict[str, str] = {}
    by_vendor_name: dict[tuple[str, str], str] = {}
    for m in materials:
        name_slug = _slugify(m.name)
        if not name_slug:
            continue
        legacy_to_canon.setdefault(f"mas-{name_slug}", m.id)
        by_vendor_name[(_slugify(m.vendor), name_slug)] = m.id

    fixed: list[Core] = []
    for c in cores:
        if c.default_material_id in canonical_ids:
            fixed.append(c)
            continue
        # Always prefer the (core_vendor, material_name) lookup
        # when the legacy id is ambiguous across vendors. Falling
        # back to the first-write-wins ``legacy_to_canon`` would
        # mis-route, e.g., a TDK core's ``mas-n97`` to TDK/EPCOS's
        # ``tdkepcos-n97`` simply because that material was loaded
        # earlier. Drop the ``mas-`` prefix and look up
        # ``(vendor_slug, name_slug)`` first; only fall back to
        # the unique-suffix index when the core is from a vendor
        # we don't have any matching material for.
        canon = None
        if c.default_material_id.startswith("mas-"):
            name_slug = c.default_material_id.removeprefix("mas-")
            canon = by_vendor_name.get((_slugify(c.vendor), name_slug))
        if canon is None:
            canon = legacy_to_canon.get(c.default_material_id)
        if canon is None:
            # Couldn't normalise — leave as-is. Downstream
            # ``find_material`` will raise a clean error.
            fixed.append(c)
            continue
        # Pydantic models are immutable by default; rebuild via
        # ``model_copy`` so the rest of the catalog stays the
        # original objects.
        fixed.append(c.model_copy(update={"default_material_id": canon}))
    return fixed


def _slugify(s: str) -> str:
    """Match the slug rule the MAS adapter uses for material ids
    so the legacy → canonical mapping stays in sync."""
    return (s or "").lower().replace(" ", "-")


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
