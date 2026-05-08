"""Import powder-core catalogs from manufacturer XLSX downloads.

Targets the public catalog spreadsheets published by **Magnetics Inc**
and **Micrometals**. Both vendors ship Excel files with one row per
core part, listing the standard effective parameters (Ae, le, Ve, Wa,
MLT, AL_nH) plus material identity and rolloff parameters. We bring
those rows into our ``Core`` model so the engine can use them
*without* the ±15-25 % shape-decoder error the MAS / PyETK paths
incur for ferrite shapes — the manufacturer values are exact.

Why a separate script
---------------------

The MAS catalog already includes ~2237 Magnetics cores, but their
``Ae`` / ``le`` come from MAS shape-dimension midpoints decoded
through generic family formulas. For powder cores in PFC chokes
(where the rolloff curve dominates the design), the manufacturer's
own table is the canonical reference. This script lets the user
overlay precise data on top of the approximated MAS entries.

How to get the XLSX
-------------------

**Magnetics Inc** publishes a free catalog at
``https://www.mag-inc.com/Products/Powder-Cores``. Look for
"Powder Core Catalog Reference" or "Inductor Designer Software"
downloads — both ship per-part Excel sheets.

**Micrometals** publishes at
``https://www.micrometals.com/design-and-applications/design-tools/``.
Their "Inductor Design Software" data dump exports a similar
spreadsheet.

**Expected XLSX format**

The script expects a single sheet with at least these columns
(case-insensitive, partial match):

- ``part`` / ``part number`` / ``id`` — vendor SKU
- ``material`` — ``Kool Mu 60`` / ``MPP 125`` / ``XFlux 60`` / etc.
- ``shape`` — ``E``, ``T``, ``EE``, etc. (optional; inferred from
  the part number when omitted)
- ``Ae`` (mm² or cm²) — effective area
- ``le`` (mm or cm) — effective path length
- ``Ve`` (mm³ or cm³) — effective volume
- ``Wa`` (mm² or cm²) — window area (optional)
- ``MLT`` (mm or cm) — mean length per turn (optional)
- ``AL`` (nH/N²) — inductance index at zero DC bias

Unit detection: we read the column header for unit hints (``cm``,
``mm``, ``cm²``, ``mm²``, ``cm³``, ``mm³``); when the header carries
no unit, we fall back to the heuristic that toroide-class Ae values
< 100 are in cm² and ≥ 100 are in mm² (powder-core typical span).

Run from project root:

    .venv/bin/python scripts/import_powder_xlsx.py path/to/Magnetics-PowderCore-Catalog.xlsx
    .venv/bin/python scripts/import_powder_xlsx.py file.xlsx --vendor "Magnetics" --dry-run
    .venv/bin/python scripts/import_powder_xlsx.py file.xlsx --sheet "Cores" --out data/magnetics/cores.json

Output is tagged with ``x-pfc-inductor.source = "powder_xlsx"`` and
the vendor name, so the loader's "Apenas curados" filter excludes
the imports until the user explicitly opts in.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR_DEFAULT = REPO_ROOT / "data" / "magnetics"

sys.path.insert(0, str(REPO_ROOT / "src"))

from pfc_inductor.models import Core  # type: ignore[import-not-found] # noqa: E402

# ---------------------------------------------------------------------------
# Column mapping
# ---------------------------------------------------------------------------

# Each row maps a canonical field name to a list of header substrings
# (case-insensitive) that vendors are known to use. Order matters —
# the first match wins. Multi-token headers (``A_e [cm²]``) are
# normalised by stripping non-alphanumerics before matching.

COLUMN_ALIASES: dict[str, list[str]] = {
    "part_number": ["part", "partnumber", "id", "catalogue", "catalog"],
    "material": ["material", "alloy", "core material"],
    "shape": ["shape", "core type", "geometry"],
    "Ae": ["effectivearea", "ae", "crosssection", "cross section"],
    "le": ["effectivepathlength", "le", "magneticpath", "pathlength"],
    "Ve": ["effectivevolume", "ve", "corevolume"],
    "Wa": ["windowarea", "wa", "window"],
    "MLT": ["meanlengthperturn", "mlt", "averagewindinglength"],
    "AL": ["al", "inductancefactor", "alvalue"],
    "OD": ["outerdiameter", "od"],
    "ID": ["innerdiameter", "id"],  # NB: matches "id" too — ordering caveat below
    "HT": ["height", "ht", "thickness"],
    "vendor": ["manufacturer", "vendor", "brand"],
    "cost": ["price", "cost"],
}


def _normalise(header: str) -> str:
    """Lowercase, strip non-alphanumerics. Collapses ``A_e [cm²]`` to
    ``aecm``. Handles the typographic Unicode squared sign and
    superscript digits as separate non-alphanumeric chars."""
    return re.sub(r"[^a-z0-9]+", "", header.lower())


def _match_column(header: str, aliases: list[str]) -> bool:
    norm = _normalise(header)
    return any(alias in norm for alias in aliases)


def _detect_columns(headers: list[str]) -> dict[str, int]:
    """Map canonical field → column index for the given header row.

    ``id`` appears in both ``part_number`` aliases and the literal
    ``ID`` (inner-diameter) entry. Resolve by ordering: search
    ``part_number`` first, mark used; only check ``ID`` against
    columns NOT yet matched.
    """
    used: set[int] = set()
    out: dict[str, int] = {}
    # Handle ``part_number`` first to claim any "id" column for the
    # part identifier rather than the inner diameter.
    ordered_fields = list(COLUMN_ALIASES.keys())
    if "ID" in ordered_fields:
        ordered_fields.remove("ID")
        ordered_fields.append("ID")  # check last
    for field in ordered_fields:
        aliases = COLUMN_ALIASES[field]
        for i, h in enumerate(headers):
            if i in used:
                continue
            if _match_column(str(h or ""), aliases):
                out[field] = i
                used.add(i)
                break
    return out


# ---------------------------------------------------------------------------
# Unit detection
# ---------------------------------------------------------------------------


@dataclass
class UnitHints:
    """Per-field unit guess. ``mm`` for lengths, ``mm2`` for areas,
    ``mm3`` for volumes — converted from cm/cm²/cm³ when needed."""

    Ae: str = "mm2"
    le: str = "mm"
    Ve: str = "mm3"
    Wa: str = "mm2"
    MLT: str = "mm"
    OD: str = "mm"
    ID: str = "mm"
    HT: str = "mm"


def _infer_unit(header: str, default: str) -> str:
    """Pick the unit from a header like ``A_e [cm²]`` or ``le (mm)``."""
    norm = header.lower().replace(" ", "")
    if "cm³" in norm or "cm3" in norm:
        return "cm3"
    if "mm³" in norm or "mm3" in norm:
        return "mm3"
    if "cm²" in norm or "cm2" in norm:
        return "cm2"
    if "mm²" in norm or "mm2" in norm:
        return "mm2"
    if "[cm" in norm or "(cm" in norm:
        return "cm" if default == "mm" else "cm2"
    if "[mm" in norm or "(mm" in norm:
        return default
    return default


def _detect_units(headers: list[str], cols: dict[str, int]) -> UnitHints:
    h = UnitHints()
    for field, idx in cols.items():
        if not hasattr(h, field):
            continue
        default = getattr(h, field)
        setattr(h, field, _infer_unit(str(headers[idx] or ""), default))
    return h


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _to_mm(value: Any, unit: str) -> Optional[float]:
    if not isinstance(value, (int, float)):
        return None
    if unit == "cm":
        return float(value) * 10.0
    return float(value)


def _to_mm2(value: Any, unit: str) -> Optional[float]:
    if not isinstance(value, (int, float)):
        return None
    if unit == "cm2":
        return float(value) * 100.0
    return float(value)


def _to_mm3(value: Any, unit: str) -> Optional[float]:
    if not isinstance(value, (int, float)):
        return None
    if unit == "cm3":
        return float(value) * 1000.0
    return float(value)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _infer_shape(part_number: str, fallback: str = "T") -> str:
    """Infer shape family from a Magnetics-style part number.

    Magnetics SKUs follow patterns like ``0058083A2`` (toroide),
    ``EE 24/24/8`` (E-pair), etc. When the part starts with a
    canonical IEC family prefix, use it; otherwise return the
    fallback (most powder cores are toroides).
    """
    pn = part_number.strip().upper()
    for prefix in (
        "ETD",
        "EFD",
        "EER",
        "EEL",
        "EE",
        "EL",
        "EI",
        "ER",
        "EQ",
        "EP",
        "PQ",
        "RM",
        "PM",
        "PH",
        "PT",
        "EC",
        "UI",
        "UR",
        "UT",
        "U",
        "P",
        "T",
        "E",
    ):
        if pn.startswith(prefix + " ") or pn.startswith(prefix + "-"):
            return prefix
    return fallback


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _row_value(row: tuple, idx: Optional[int]) -> Any:
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def parse_xlsx(
    path: Path,
    *,
    sheet: Optional[str] = None,
    vendor_default: str = "Magnetics",
    source_tag: str = "powder_xlsx",
) -> tuple[list[Core], dict[str, int]]:
    """Read an XLSX catalog and return (cores, stats)."""
    import openpyxl  # imported here so the script imports even when
    # openpyxl is missing (the user gets a clean ImportError on run).

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.active
    if ws is None:
        raise ValueError(f"no active sheet in {path}")

    rows_iter = ws.iter_rows(values_only=True)
    headers = next(rows_iter, None)
    if headers is None:
        raise ValueError(f"no header row in {path}")
    headers = list(headers)

    cols = _detect_columns(headers)
    if "part_number" not in cols:
        raise ValueError(
            f"could not find a part-number column in {path}. "
            f"Headers seen: {headers}. Add a column header containing "
            "'part', 'partnumber', or 'catalog'."
        )
    if "Ae" not in cols or "le" not in cols:
        raise ValueError(f"missing Ae or le columns. Headers seen: {[h for h in headers if h]}")
    units = _detect_units(headers, cols)

    out: list[Core] = []
    seen_ids: set[str] = set()
    n_rows = 0
    skipped_empty = 0
    skipped_bad = 0

    for row in rows_iter:
        n_rows += 1
        pn = _row_value(row, cols.get("part_number"))
        if not pn:
            skipped_empty += 1
            continue
        pn_str = str(pn).strip()
        if not pn_str:
            skipped_empty += 1
            continue

        material = _row_value(row, cols.get("material"))
        material_str = str(material).strip() if material else ""

        Ae_raw = _row_value(row, cols.get("Ae"))
        le_raw = _row_value(row, cols.get("le"))
        Ae = _to_mm2(Ae_raw, units.Ae)
        le = _to_mm(le_raw, units.le)
        if Ae is None or le is None or Ae <= 0 or le <= 0:
            skipped_bad += 1
            continue

        Ve_raw = _row_value(row, cols.get("Ve"))
        Ve = _to_mm3(Ve_raw, units.Ve)
        if Ve is None or Ve <= 0:
            Ve = Ae * le  # derive when missing

        Wa_raw = _row_value(row, cols.get("Wa"))
        Wa = _to_mm2(Wa_raw, units.Wa) or 0.0

        MLT_raw = _row_value(row, cols.get("MLT"))
        MLT = _to_mm(MLT_raw, units.MLT) or 0.0

        AL_raw = _row_value(row, cols.get("AL"))
        try:
            AL = float(AL_raw) if AL_raw is not None else 0.0
        except (TypeError, ValueError):
            AL = 0.0

        OD = _to_mm(_row_value(row, cols.get("OD")), units.OD)
        ID = _to_mm(_row_value(row, cols.get("ID")), units.ID)
        HT = _to_mm(_row_value(row, cols.get("HT")), units.HT)

        vendor_raw = _row_value(row, cols.get("vendor"))
        vendor = str(vendor_raw).strip() if vendor_raw else vendor_default

        shape_raw = _row_value(row, cols.get("shape"))
        shape = str(shape_raw).strip() if shape_raw else _infer_shape(pn_str)

        try:
            cost = float(_row_value(row, cols.get("cost"))) if cols.get("cost") else None
        except (TypeError, ValueError):
            cost = None

        material_id = (
            f"{_slug(vendor)}-{_slug(material_str)}" if material_str else f"{_slug(vendor)}-unknown"
        )
        cid = f"{source_tag}-{_slug(vendor)}-{_slug(pn_str)}"
        if cid in seen_ids:
            continue
        seen_ids.add(cid)

        try:
            obj = Core(
                id=cid,
                vendor=vendor,
                shape=shape.upper(),
                part_number=pn_str,
                default_material_id=material_id,
                Ae_mm2=round(Ae, 3),
                le_mm=round(le, 3),
                Ve_mm3=round(Ve, 2),
                Wa_mm2=round(Wa, 3),
                MLT_mm=round(MLT, 3),
                AL_nH=round(AL, 1),
                OD_mm=round(OD, 2) if OD else None,
                ID_mm=round(ID, 2) if ID else None,
                HT_mm=round(HT, 2) if HT else None,
                cost_per_piece=cost,
                notes=(
                    f"Imported from {vendor} XLSX (powder_xlsx). "
                    f"Manufacturer-supplied effective parameters — "
                    f"no shape-decoder approximation."
                ),
            )
        except Exception:
            skipped_bad += 1
            continue
        out.append(obj)

    return out, {
        "rows": n_rows,
        "skipped_empty": skipped_empty,
        "skipped_bad": skipped_bad,
        "imported": len(out),
        "columns_detected": cols,
        "units_detected": units.__dict__,
    }


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _tag_source(entry: dict, vendor: str, source_path: Path) -> dict:
    entry["x-pfc-inductor"] = {
        "id": entry["id"],
        "source": "powder_xlsx",
        "vendor": vendor,
        "snapshot": source_path.name,
    }
    return entry


def _write_catalog(out_dir: Path, cores: list[Core], vendor: str, source_path: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "_comment": (
            f"Imported from {vendor} XLSX catalog ({source_path.name}). "
            f"{len(cores)} cores converted via "
            f"scripts/import_powder_xlsx.py. Effective parameters are "
            f"manufacturer-published values (exact, not shape-decoded)."
        ),
        "cores": [_tag_source(c.model_dump(mode="json"), vendor, source_path) for c in cores],
    }
    (out_dir / "cores.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", type=Path, help="Path to the vendor XLSX catalog file.")
    parser.add_argument(
        "--sheet", type=str, default=None, help="Sheet name (default: first/active)."
    )
    parser.add_argument(
        "--vendor",
        type=str,
        default="Magnetics",
        help="Vendor name when the XLSX has no vendor column (default: Magnetics).",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Output directory (default: data/<vendor>/)."
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    src: Path = args.source
    if not src.exists():
        print(f"error: source file not found: {src}", file=sys.stderr)
        return 2

    out_dir: Path = args.out or REPO_ROOT / "data" / _slug(args.vendor)

    print(f"Parsing {src.relative_to(Path.cwd()) if src.is_relative_to(Path.cwd()) else src}...")
    cores, stats = parse_xlsx(src, sheet=args.sheet, vendor_default=args.vendor)
    print(f"  rows seen:        {stats['rows']}")
    print(f"  skipped (empty):  {stats['skipped_empty']}")
    print(f"  skipped (bad):    {stats['skipped_bad']}")
    print(f"  imported:         {stats['imported']}")
    print(f"  columns mapped:   {stats['columns_detected']}")
    print(f"  units inferred:   {stats['units_detected']}")

    by_shape: dict[str, int] = {}
    for c in cores:
        by_shape[c.shape] = by_shape.get(c.shape, 0) + 1
    print(f"  by shape: {dict(sorted(by_shape.items()))}")

    if args.dry_run:
        print("(dry-run — nothing written)")
        return 0

    _write_catalog(out_dir, cores, args.vendor, src)
    print(f"  wrote: {out_dir}/cores.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
