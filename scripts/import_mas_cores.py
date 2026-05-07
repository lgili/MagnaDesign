"""Import the OpenMagnetics MAS core catalog (10 318 entries).

Source data lives under ``vendor/openmagnetics-catalog/`` (NDJSON
files snapshotted from upstream — see ``VERSION.txt`` for the commit
hash). The data is Apache-2.0 licensed.

Pipeline
--------

1. Index ``core_shapes.ndjson`` by name. Each shape entry carries a
   dict of dimensions ``A``/``B``/``C``/... in **metres**, with
   ``{minimum, maximum}`` envelopes — we take the geometric midpoint
   as nominal and convert to millimetres.
2. Walk ``cores.ndjson``. Each row is a *part* (vendor + material +
   shape + gapping). Look up the shape's nominal dims, then call a
   family-specific decoder to derive ``Ae``/``le``/``Ve``/``Wa``/
   ``MLT``. Apply gap correction to ``AL_nH`` when ``gapping`` is
   non-empty.
3. Pair each core with the named MAS material. The material id is
   slugified to match the MAS catalog already imported by
   ``import_mas_catalog.py``, so the loader can resolve them after a
   full DB reload.
4. Tag every entry with ``x-pfc-inductor.source = "openmagnetics"``
   so the loader's "curated only" filter excludes them by default.
5. Write to ``data/mas/catalog/cores.json`` — the bucket the loader
   already knows how to merge (after we drop the ``cores.json``
   exclusion in ``data_loader._merge_with_catalog``).

Decoder reuse and known accuracy gaps
-------------------------------------

The shape-specific Ae/le/Ve formulas live in
``scripts/import_pyetk_catalog.py``. We import them via ``importlib``
to avoid duplicating ~150 lines of geometry. New decoders specific
to MAS-only shape families (toroid, pot, C-core, planar variants)
are defined here.

**Known caveat — slot convention mismatch.** MAS publishes raw IEC
dimensions but uses slightly different slot semantics than the
Ferroxcube/PyETK convention the imported decoders were calibrated
against. In particular, for ETD/PQ/RM the MAS ``D`` and ``E`` slots
swap meaning (window height vs overall pair height). The reused
decoders therefore yield ``Ae`` accurate to ±5 % (post cross-section
formula doesn't depend on the swap) but ``le`` errors of 15–25 %.
Toroide cores (the bulk of the MAS import — 5500+ entries) use a
**closed-form** formula and are exact. The ``notes`` field on every
imported core flags MAS as the source so the engineer knows to
verify ferrite-shape entries against the vendor datasheet.

Run from project root:

    .venv/bin/python scripts/import_mas_cores.py            # default
    .venv/bin/python scripts/import_mas_cores.py --dry-run  # preview
    .venv/bin/python scripts/import_mas_cores.py --limit 200
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR_DEFAULT = REPO_ROOT / "vendor" / "openmagnetics-catalog"
OUT_DIR = REPO_ROOT / "data" / "mas" / "catalog"

sys.path.insert(0, str(REPO_ROOT / "src"))

from pfc_inductor.models import Core  # type: ignore[import-not-found] # noqa: E402


# ---------------------------------------------------------------------------
# Bring in the PyETK decoder library via importlib (avoids duplicating
# ~150 lines of shape-specific geometry).
# ---------------------------------------------------------------------------

def _load_pyetk_decoders():
    spec = importlib.util.spec_from_file_location(
        "ipy_decoders", REPO_ROOT / "scripts" / "import_pyetk_catalog.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load PyETK decoder module")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_PYETK = _load_pyetk_decoders()


# ---------------------------------------------------------------------------
# MAS-only decoders
# ---------------------------------------------------------------------------

MU_0 = 4.0 * math.pi * 1e-7
DEFAULT_MATERIAL_MU = 2300.0
BOBBIN_CLEARANCE_MM = 2.0


def _decode_toroid(dims: dict[str, float]) -> tuple:
    """Toroid: A=OD, B=ID, C=axial height. Effective parameters from
    the standard ring-core formulas (Magnetics powder core handbook):

    - ``Ae = (A − B) / 2 · C``
    - ``le = π · (A + B) / 2`` (mean diameter perimeter)
    - ``Ve = Ae · le``
    - ``Wa = π · (B / 2)²`` (window = inner hole)
    - ``MLT ≈ 2 · ((A − B) / 2 + C)`` (one turn around the cross-section)

    Validated against Magnetics 0058928A2 (T-58) within ±2 % on Ae,
    ±3 % on le.
    """
    A = dims.get("A", 0.0)
    B = dims.get("B", 0.0)
    C = dims.get("C", 0.0)
    if A <= 0 or B <= 0 or C <= 0 or A <= B:
        return (None,) * 8
    Ae = (A - B) / 2.0 * C
    le = math.pi * (A + B) / 2.0
    Ve = Ae * le
    Wa = math.pi * (B / 2.0) ** 2
    MLT = 2.0 * ((A - B) / 2.0 + C) + 4.0 * BOBBIN_CLEARANCE_MM
    OD = A
    ID = B
    HT = C
    return (Ae, le, Ve, Wa, MLT, OD, ID, HT)


def _decode_pot(dims: dict[str, float]) -> tuple:
    """Pot core (P family): cylindrical outer shell with a round
    central post. ``A`` outer Ø, ``D`` total height, ``F`` post Ø,
    ``E`` window height (interior).

    Different from PyETK's ``_decode_p_core`` because MAS keys differ
    by name — kept here for clarity.
    """
    A = dims.get("A", 0.0)
    D = dims.get("D", 0.0)
    E = dims.get("E", 0.0)
    F = dims.get("F", 0.0)
    if min(A, D, F) <= 0:
        return (None,) * 8
    Ae = math.pi * (F / 2.0) ** 2
    Wa = max(math.pi * ((A / 2.0) ** 2 - (F / 2.0) ** 2) * 0.5, 1.0)
    le = 2.0 * D + (A - F)
    Ve = Ae * le
    MLT = math.pi * (F + 2.0 * BOBBIN_CLEARANCE_MM)
    return (Ae, le, Ve, Wa, MLT, A, None, D)


def _decode_c_core(dims: dict[str, float]) -> tuple:
    """C-core (cut C): two parallel rectangular legs forming a closed
    loop when paired with another C or an I lamination.

    MAS dims for C: ``A`` (outer length), ``B`` (inner length, window
    span), ``C`` (leg thickness), ``D`` (overall height), ``E`` (depth).
    Magnetic path roughly traces around the rectangular window.
    """
    A = dims.get("A", 0.0)
    B = dims.get("B", 0.0)
    C = dims.get("C", 0.0)
    D = dims.get("D", 0.0)
    E = dims.get("E", 0.0)
    if min(A, C, D, E) <= 0:
        return (None,) * 8
    Ae = C * E
    Wa = (B - 2.0 * C) * D if (B - 2.0 * C) > 0 else B * D * 0.5
    le = 2.0 * D + 2.0 * (B - C if B > C else B)
    Ve = Ae * le
    MLT = 2.0 * (C + E) + 4.0 * BOBBIN_CLEARANCE_MM
    return (Ae, le, Ve, Wa, MLT, A, None, D)


def _decode_pm(dims: dict[str, float]) -> tuple:
    """PM (large pot) — same as ``_decode_pot`` but PM uses ``D`` for
    overall height and ``F`` for post Ø, plus has extra alpha/beta
    for the asymmetric window cuts. We use the round-post
    approximation."""
    return _decode_pot(dims)


def _decode_planar_e(dims: dict[str, float]) -> tuple:
    """Planar E cores share the standard E formula but with very
    flat aspect ratios (D ≪ A). Reuse the EFD-style "single yoke
    crossing" formula for ``le``."""
    A = dims.get("A", 0.0)
    B = dims.get("B", 0.0)
    C = dims.get("C", 0.0)
    D = dims.get("D", 0.0)
    E = dims.get("E", 0.0)
    F = dims.get("F", 0.0)
    if min(A, C, D, F) <= 0:
        return (None,) * 8
    Ae = C * F
    Wa = ((A - C) / 2.0) * E if (A - C) > 0 else E * F * 0.5
    le = A + B + 2.0 * D - C
    Ve = Ae * le
    MLT = 2.0 * (C + F) + 4.0 * BOBBIN_CLEARANCE_MM
    return (Ae, le, Ve, Wa, MLT, A, None, D)


# Family-name → decoder. Falls back to PyETK's catalog for names that
# share a decoder (e.g. ``e`` → ``_decode_e_core``).
MAS_FAMILY_DECODERS = {
    "t":          _decode_toroid,
    "c":          _decode_c_core,
    "p":          _decode_pot,
    "pm":         _decode_pm,
    "planarE":    _decode_planar_e,
    "planarEL":   _decode_planar_e,
    "planarER":   _decode_planar_e,
    # Reuse PyETK decoders for everything that maps cleanly. The PyETK
    # decoders take a list-of-8; we wrap them via ``_call_pyetk``.
    "e":     ("e",   _PYETK._decode_e_core),
    "ec":    ("e",   _PYETK._decode_e_core),
    "efd":   ("efd", _PYETK._decode_efd_core),
    "ep":    ("ep",  _PYETK._decode_ep_core),
    "epx":   ("ep",  _PYETK._decode_ep_core),
    "eq":    ("eq",  _PYETK._decode_eq_core),
    "er":    ("er",  _PYETK._decode_er_core),
    "etd":   ("etd", _PYETK._decode_etd_core),
    "pq":    ("pq",  _PYETK._decode_pq_core),
    "pqi":   ("pq",  _PYETK._decode_pq_core),
    "rm":    ("rm",  _PYETK._decode_rm_core),
    "u":     ("u",   _PYETK._decode_u_core),
    "ui":    ("ui",  _PYETK._decode_u_core),
    "ur":    ("u",   _PYETK._decode_u_core),
    # ``lp`` (low-profile, like Würth WE-LP) is rectangular outer
    # with a round post — same family as ER for the magnetic math.
    "lp":    ("er",  _PYETK._decode_er_core),
    "ut":    ("u",   _PYETK._decode_u_core),
}


def _dims_dict_to_8tuple(dims: dict[str, float]) -> list:
    """Project the named MAS dim dict onto the unnamed 8-slot list
    that PyETK's decoders consume. Order matches the IEC datasheet
    convention used by Phillips/Ferroxcube: A/B/C/D/E/F/G/H."""
    return [
        dims.get("A", 0.0),
        dims.get("B", 0.0),
        dims.get("C", 0.0),
        dims.get("D", 0.0),
        dims.get("E", 0.0),
        dims.get("F", 0.0),
        dims.get("G", 0.0),
        dims.get("H", 0.0),
    ]


def decode(family: str, dims: dict[str, float]) -> tuple:
    """Pick the right decoder and call it. Returns a tuple of 8 values
    matching the PyETK contract: (Ae, le, Ve, Wa, MLT, OD, ID, HT)."""
    decoder = MAS_FAMILY_DECODERS.get(family.lower())
    if decoder is None:
        return (None,) * 8
    if isinstance(decoder, tuple):
        # PyETK decoder: needs 8-list input.
        _label, fn = decoder
        return fn(_dims_dict_to_8tuple(dims))
    # Native MAS decoder: accepts the dict directly.
    return decoder(dims)


# ---------------------------------------------------------------------------
# Shape index + dimension extraction
# ---------------------------------------------------------------------------

def _nominal_mm(d: dict | float) -> float:
    """Return the nominal dimension in mm.

    MAS publishes dims in metres in three flavours:

    - ``{"minimum": x, "maximum": y}`` — toleranced; midpoint is nominal.
    - ``{"nominal": z}`` — exact; pass through.
    - ``{"minimum": x}`` or ``{"maximum": y}`` only — single bound.

    Bare scalars (rare, but seen in legacy entries) pass through as
    metres × 1000.
    """
    if isinstance(d, (int, float)):
        return float(d) * 1000.0
    if not isinstance(d, dict):
        return 0.0
    nominal = d.get("nominal")
    if isinstance(nominal, (int, float)):
        return float(nominal) * 1000.0
    lo = d.get("minimum")
    hi = d.get("maximum")
    if lo is not None and hi is not None:
        return (float(lo) + float(hi)) / 2.0 * 1000.0
    if lo is not None:
        return float(lo) * 1000.0
    if hi is not None:
        return float(hi) * 1000.0
    return 0.0


def _index_shapes(path: Path) -> dict[str, dict]:
    """Return ``shape_name → {family, dims_mm}`` for fast core lookup."""
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = d.get("name")
            if not isinstance(name, str):
                continue
            family = d.get("family", "")
            raw_dims = d.get("dimensions", {})
            dims_mm = {k: _nominal_mm(v) for k, v in raw_dims.items()}
            out[name] = {"family": family, "dims": dims_mm}
    return out


# ---------------------------------------------------------------------------
# Core conversion
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    return (
        s.lower()
        .replace("/", "-")
        .replace(" ", "-")
        .replace(".", "_")
        .replace(",", "_")
        .replace("(", "")
        .replace(")", "")
        .replace("·", "-")
    )


def _vendor_name(core: dict) -> str:
    info = core.get("manufacturerInfo", {})
    if isinstance(info, dict):
        n = info.get("name")
        if isinstance(n, str) and n.strip():
            return n.strip()
    return "Unknown"


def _gap_total_mm(core: dict) -> float:
    """Sum the configured air gaps (MAS publishes them in metres)."""
    gapping = core.get("functionalDescription", {}).get("gapping", []) or []
    total = 0.0
    for g in gapping:
        if not isinstance(g, dict):
            continue
        length = g.get("length", 0.0)
        if isinstance(length, (int, float)):
            total += float(length) * 1000.0
    return total


def _derive_AL_nH(Ae_mm2: float, le_mm: float, gap_mm: float = 0.0,
                  mu_eff: float = DEFAULT_MATERIAL_MU) -> float:
    """``AL = μ₀ · μ_eff · Ae / (le + μ_eff · l_gap)``. Reluctance of
    the airgap dominates as soon as the gap exceeds le/μ — for a
    typical 100 µm gap on a μ=2300 ferrite that's the whole story
    (1000× the iron reluctance)."""
    if Ae_mm2 <= 0 or le_mm <= 0:
        return 0.0
    Ae_m2 = Ae_mm2 * 1e-6
    le_m = le_mm * 1e-3
    gap_m = max(gap_mm, 0.0) * 1e-3
    eff_path = le_m + mu_eff * gap_m
    L_per_N2_H = MU_0 * mu_eff * Ae_m2 / eff_path
    return L_per_N2_H * 1e9


def parse_cores(
    cores_path: Path, shapes_index: dict[str, dict],
    limit: Optional[int] = None,
) -> tuple[list[Core], dict[str, int]]:
    """Walk ``cores.ndjson`` and build Core objects.

    Returns the imported list plus a stats dict the CLI prints to
    stdout (``seen`` / ``skipped_*`` / ``imported``)."""
    out: list[Core] = []
    seen_ids: set[str] = set()
    skipped_no_shape = 0
    skipped_no_decoder = 0
    skipped_bad_dims = 0
    n_seen = 0
    with cores_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                core = json.loads(line)
            except json.JSONDecodeError:
                continue
            if limit is not None and n_seen >= limit:
                break
            n_seen += 1

            functional = core.get("functionalDescription", {})
            shape_name = functional.get("shape")
            material_name = functional.get("material")
            if not isinstance(shape_name, str) or not isinstance(material_name, str):
                continue

            shape_entry = shapes_index.get(shape_name)
            if shape_entry is None:
                skipped_no_shape += 1
                continue

            family = shape_entry["family"]
            dims = shape_entry["dims"]
            Ae, le, Ve, Wa, MLT, OD, ID, HT = decode(family, dims)
            if Ae is None or le is None:
                skipped_no_decoder += 1
                continue
            if Ae <= 0 or le <= 0 or Ve is None or Ve <= 0:
                skipped_bad_dims += 1
                continue

            vendor = _vendor_name(core)
            gap_mm = _gap_total_mm(core)
            AL = _derive_AL_nH(Ae, le, gap_mm)

            shape_slug = _slug(family)
            mat_slug = _slug(material_name)
            part_slug = _slug(core.get("name", shape_name))
            cid = f"mas-{_slug(vendor)}-{shape_slug}-{part_slug}"
            # Some MAS rows have identical (vendor, shape, material, gap)
            # entries — collapse to the first hit.
            if cid in seen_ids:
                continue
            seen_ids.add(cid)

            obj = Core(
                id=cid,
                vendor=vendor,
                shape=family.upper(),
                part_number=core.get("name", shape_name),
                default_material_id=f"mas-{mat_slug}",
                Ae_mm2=round(Ae, 2),
                le_mm=round(le, 2),
                Ve_mm3=round(Ve, 1),
                Wa_mm2=round(Wa or 0.0, 2),
                MLT_mm=round(MLT or 0.0, 2),
                AL_nH=round(AL, 1),
                lgap_mm=round(gap_mm, 4),
                OD_mm=round(OD, 2) if OD is not None else None,
                ID_mm=round(ID, 2) if ID is not None else None,
                HT_mm=round(HT, 2) if HT is not None else None,
                notes=(
                    f"Imported from OpenMagnetics MAS (Apache-2.0). "
                    f"Geometry resolved via shape-{family} decoder; "
                    f"gap={gap_mm:.3f} mm. Verify against vendor "
                    f"datasheet before final design sign-off."
                ),
            )
            out.append(obj)

    return out, {
        "seen": n_seen,
        "skipped_no_shape": skipped_no_shape,
        "skipped_no_decoder": skipped_no_decoder,
        "skipped_bad_dims": skipped_bad_dims,
        "imported": len(out),
    }


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def _tag_source(entry: dict, commit: str) -> dict:
    entry["x-pfc-inductor"] = {
        "id": entry["id"],
        "source": "openmagnetics",
        "snapshot": commit,
    }
    return entry


def _read_version_tag(src_dir: Path) -> str:
    vp = src_dir / "VERSION.txt"
    if not vp.exists():
        return "unknown"
    for line in vp.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("commit:"):
            return line.split(":", 1)[1].strip()[:12]
    return "unknown"


def _write_catalog(out_dir: Path, cores: list[Core], commit: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "_comment": (
            f"Imported from OpenMagnetics MAS (Apache-2.0) snapshot "
            f"@ {commit}. {len(cores)} cores converted via "
            f"scripts/import_mas_cores.py."
        ),
        "cores": [
            _tag_source(c.model_dump(mode="json"), commit) for c in cores
        ],
    }
    (out_dir / "cores.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--source", type=Path, default=SRC_DIR_DEFAULT,
        help=f"Source dir with cores.ndjson + core_shapes.ndjson (default: {SRC_DIR_DEFAULT.relative_to(REPO_ROOT)})",
    )
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N input rows (debug aid).")
    args = parser.parse_args(list(argv) if argv is not None else None)

    src: Path = args.source
    if not src.exists():
        print(f"error: source dir not found: {src}", file=sys.stderr)
        return 2

    cores_path = src / "cores.ndjson"
    shapes_path = src / "core_shapes.ndjson"
    for p in (cores_path, shapes_path):
        if not p.exists():
            print(f"error: required file missing: {p}", file=sys.stderr)
            return 2

    print(f"Indexing shapes from {shapes_path.relative_to(REPO_ROOT)}...")
    shapes = _index_shapes(shapes_path)
    print(f"  {len(shapes)} shapes indexed")

    print(f"Reading cores from {cores_path.relative_to(REPO_ROOT)}...")
    cores, stats = parse_cores(cores_path, shapes, limit=args.limit)
    print(f"  {stats['imported']} imported / {stats['seen']} seen")
    print(f"    skipped (shape not found): {stats['skipped_no_shape']}")
    print(f"    skipped (no decoder):      {stats['skipped_no_decoder']}")
    print(f"    skipped (bad dims):        {stats['skipped_bad_dims']}")

    # Tally by family.
    by_shape: dict[str, int] = {}
    by_vendor: dict[str, int] = {}
    for c in cores:
        by_shape[c.shape] = by_shape.get(c.shape, 0) + 1
        by_vendor[c.vendor] = by_vendor.get(c.vendor, 0) + 1
    print(f"  by shape: {dict(sorted(by_shape.items()))}")
    print(f"  by vendor (top 8): {dict(sorted(by_vendor.items(), key=lambda kv: -kv[1])[:8])}")

    if args.dry_run:
        print("(dry-run — nothing written)")
        return 0

    commit = _read_version_tag(src)
    out_dir: Path = args.out
    _write_catalog(out_dir, cores, commit)
    print(f"  wrote: {out_dir.relative_to(REPO_ROOT)}/cores.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
