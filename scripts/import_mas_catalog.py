"""Import the OpenMagnetics MAS catalog into our local database.

Source data lives under ``vendor/openmagnetics-catalog/`` (NDJSON files
fetched at release time — see ``vendor/openmagnetics-catalog/VERSION.txt``).

The script:

1. parses ``core_materials.ndjson`` and ``wires.ndjson`` (cores not
   supported in v1 — upstream cores reference shapes without effective
   dimensions);
2. converts each entry into our internal ``Material`` / ``Wire`` models,
   tagging it with ``x-pfc-inductor.source = "openmagnetics"`` and the
   vendored catalog tag;
3. merges with shipped curated data and the user-data overlay, never
   overwriting either:
     - id seen in user overlay -> skipped
     - id seen in shipped curated -> skipped (we calibrated those)
     - else -> added to the catalog file
4. writes ``data/mas/catalog/{materials,wires}.json`` (separate from the
   curated set so a re-import is non-destructive).

Run from project root:

    .venv/bin/python scripts/import_mas_catalog.py            # default source
    .venv/bin/python scripts/import_mas_catalog.py --source /tmp/mas/data
    .venv/bin/python scripts/import_mas_catalog.py --dry-run

Exit code is 0 even when zero new entries are added; the merge summary
is printed on stdout. ``--dry-run`` skips the write step.
"""
from __future__ import annotations
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR_DEFAULT = REPO_ROOT / "vendor" / "openmagnetics-catalog"
OUT_DIR = REPO_ROOT / "data" / "mas" / "catalog"

# Make `pfc_inductor` importable when the script is run from a checkout
# without the package being installed. Pyright can't follow the runtime
# sys.path edit, so the imports below carry an explicit ignore.
sys.path.insert(0, str(REPO_ROOT / "src"))

from pfc_inductor.models import (  # type: ignore[import-not-found] # noqa: E402
    Material, SteinmetzParams, Wire,
)
from pfc_inductor.models.mas import (  # type: ignore[import-not-found] # noqa: E402
    material_to_mas, wire_to_mas,
)
from pfc_inductor.models.mas.adapters import _slug  # type: ignore[import-not-found] # noqa: E402


# ---------------------------------------------------------------------------
# Source loading (NDJSON: one JSON object per non-empty line)
# ---------------------------------------------------------------------------
def _iter_ndjson(path: Path) -> Iterable[dict]:
    with path.open(encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            s = line.strip()
            if not s:
                continue
            try:
                yield json.loads(s)
            except json.JSONDecodeError as e:
                print(
                    f"  warn: {path.name}:{ln} skipped (invalid JSON: {e})",
                    file=sys.stderr,
                )


def _read_version_tag(src_dir: Path) -> str:
    vp = src_dir / "VERSION.txt"
    if vp.exists():
        for line in vp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.lower().startswith("commit:"):
                return line.split(":", 1)[1].strip()[:12]
    return "unknown"


# ---------------------------------------------------------------------------
# OpenMagnetics → internal Material
# ---------------------------------------------------------------------------
def _initial_permeability(perm: dict) -> Optional[float]:
    """Pull a representative initial permeability from the MAS doc.

    OpenMagnetics stores ``permeability.initial`` as either a scalar or a
    list of ``{value, temperature}`` rows; ``permeability.complex.real``
    holds frequency-dependent data with ``{frequency, value}`` rows. We
    prefer ``initial`` at 25 °C; otherwise the lowest-frequency real
    value; otherwise None.
    """
    if not isinstance(perm, dict):
        return None

    init = perm.get("initial")
    if isinstance(init, (int, float)):
        return float(init)
    if isinstance(init, dict) and "value" in init:
        return float(init["value"])
    if isinstance(init, list) and init:
        for row in init:
            if isinstance(row, dict) and abs(row.get("temperature", 25) - 25) < 5:
                return float(row.get("value", 0.0))
        first = init[0]
        if isinstance(first, dict) and "value" in first:
            return float(first["value"])

    cx = perm.get("complex") or {}
    real = cx.get("real")
    if isinstance(real, list) and real:
        rows = sorted(
            (r for r in real if isinstance(r, dict)),
            key=lambda r: r.get("frequency", float("inf")),
        )
        if rows:
            return float(rows[0].get("value", 0.0))

    return None


def _bsat_at_temperature(saturation: list[dict], target_C: float) -> Optional[float]:
    if not isinstance(saturation, list):
        return None
    rows = [
        r for r in saturation
        if isinstance(r, dict) and "magneticFluxDensity" in r
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: abs(r.get("temperature", target_C) - target_C))
    return float(rows[0]["magneticFluxDensity"])


def _steinmetz_from_volumetric(losses: list[dict]) -> Optional[SteinmetzParams]:
    """Extract a Steinmetz fit from MAS ``volumetricLosses`` if present.

    OpenMagnetics keeps several methods per material; we accept the first
    ``steinmetz``-flavoured entry that ships ``k``, ``alpha``, ``beta``.
    """
    if not isinstance(losses, list):
        return None
    for entry in losses:
        if not isinstance(entry, dict):
            continue
        coeffs = entry.get("coefficients") or entry.get("steinmetzCoefficients")
        method = (entry.get("method") or "").lower()
        if not isinstance(coeffs, dict):
            continue
        if "steinmetz" not in method and "k" not in coeffs:
            continue
        k_raw = coeffs.get("k", coeffs.get("kc"))
        alpha_raw = coeffs.get("alpha")
        beta_raw = coeffs.get("beta")
        if not (isinstance(k_raw, (int, float))
                and isinstance(alpha_raw, (int, float))
                and isinstance(beta_raw, (int, float))):
            continue
        f_ref = float(entry.get("referenceFrequency", 100_000.0))
        b_ref = float(entry.get("referenceMagneticFluxDensity",
                                entry.get("referenceFluxDensity", 0.1)))
        return SteinmetzParams(
            Pv_ref_mWcm3=float(k_raw),
            f_ref_kHz=f_ref / 1000.0,
            B_ref_mT=b_ref * 1000.0,
            alpha=float(alpha_raw),
            beta=float(beta_raw),
            f_min_kHz=1.0,
            f_max_kHz=500.0,
        )
    return None


def _material_from_mas_doc(doc: dict, *, version_tag: str) -> Optional[Material]:
    """OpenMagnetics MAS material document -> internal ``Material``.

    Returns ``None`` for entries that lack the minimum data we need
    (permeability + saturation), so the caller can count skipped rows.
    """
    name = doc.get("name")
    if not name:
        return None

    mfg = (doc.get("manufacturerInfo") or {}).get("name", "Unknown")
    family = doc.get("family", "") or ""
    mat_kind = doc.get("material", "ferrite")

    mu = _initial_permeability(doc.get("permeability") or {})
    if mu is None:
        return None

    sat_rows = doc.get("saturation") or []
    bsat25 = _bsat_at_temperature(sat_rows, 25.0)
    bsat100 = _bsat_at_temperature(sat_rows, 100.0)
    if bsat25 is None:
        # Some entries store coercive force only — make a best-effort
        # estimate from material kind so the entry remains usable.
        bsat25 = 0.40 if mat_kind == "ferrite" else 1.00
    if bsat100 is None:
        bsat100 = bsat25 * 0.85

    density = doc.get("density")
    rho = float(density) if isinstance(density, (int, float)) else 5000.0

    steinmetz = _steinmetz_from_volumetric(doc.get("volumetricLosses") or [])
    if steinmetz is None:
        # Conservative ferrite default — better to flag in notes than to
        # leave an entry without any loss model at all.
        steinmetz = SteinmetzParams(
            Pv_ref_mWcm3=200.0, f_ref_kHz=100.0, B_ref_mT=100.0,
            alpha=1.4, beta=2.5, f_min_kHz=1.0, f_max_kHz=500.0,
        )
        notes = (
            f"Imported from OpenMagnetics MAS @ {version_tag}. "
            "No Steinmetz fit shipped — using generic ferrite defaults; "
            "calibrate before relying on loss numbers."
        )
    else:
        notes = (
            f"Imported from OpenMagnetics MAS @ {version_tag}. "
            "Steinmetz coefficients lifted from upstream volumetricLosses."
        )

    mat_id = f"{_slug(mfg)}-{_slug(name)}"
    return Material(
        id=mat_id,
        vendor=mfg,
        family=family,
        name=name,
        type=mat_kind,
        mu_initial=mu,
        Bsat_25C_T=bsat25,
        Bsat_100C_T=bsat100,
        rho_kg_m3=rho,
        steinmetz=steinmetz,
        rolloff=None,
        loss_datapoints=[],
        cost_per_kg=None,
        cost_currency="USD",
        notes=notes,
    )


# ---------------------------------------------------------------------------
# OpenMagnetics → internal Wire
# ---------------------------------------------------------------------------
def _dim_nominal(d: Any) -> Optional[float]:
    """Pull a nominal value out of an MAS ``DimensionWithTolerance`` field.

    Accepts ``{nominal: x}``, ``{minimum, maximum}`` (averaged), or a
    raw scalar.
    """
    if isinstance(d, (int, float)):
        return float(d)
    if not isinstance(d, dict):
        return None
    if "nominal" in d:
        try:
            return float(d["nominal"])
        except (TypeError, ValueError):
            return None
    lo = d.get("minimum")
    hi = d.get("maximum")
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
        return (float(lo) + float(hi)) / 2.0
    if isinstance(hi, (int, float)):
        return float(hi)
    if isinstance(lo, (int, float)):
        return float(lo)
    return None


def _wire_from_mas_doc(doc: dict, *, version_tag: str) -> Optional[Wire]:
    """OpenMagnetics MAS wire document -> internal ``Wire`` (round only).

    Litz / rectangular / foil / planar are skipped: those types either
    reference an external strand-by-name (litz) or use width/height
    rather than diameter (the rest), neither of which our internal
    schema handles. Round Elektrisola entries (~1390) cover the common
    PFC choke wire range from 0.01 mm up to ~5 mm.
    """
    name = doc.get("name")
    wtype = (doc.get("type") or "round").lower()
    if not name or wtype != "round":
        return None

    # OpenMagnetics stores diameters in metres; we use millimetres.
    d_cu_m = _dim_nominal(doc.get("conductingDiameter"))
    d_iso_m = _dim_nominal(doc.get("outerDiameter"))
    if d_cu_m is None:
        return None

    d_cu_mm = d_cu_m * 1000.0
    d_iso_mm = d_iso_m * 1000.0 if d_iso_m is not None else None

    a_cu_doc = _dim_nominal(doc.get("conductingArea"))
    if a_cu_doc is not None:
        # MAS conductingArea is in m^2 -> mm^2 = *1e6
        A_cu_mm2 = float(a_cu_doc) * 1e6
    else:
        import math
        A_cu_mm2 = math.pi * (d_cu_mm / 2.0) ** 2

    wid = _slug(name)
    return Wire(
        id=wid,
        type="round",
        awg=None,
        d_cu_mm=d_cu_mm,
        d_iso_mm=d_iso_mm,
        A_cu_mm2=A_cu_mm2,
        awg_strand=None,
        d_strand_mm=None,
        n_strands=None,
        d_bundle_mm=None,
        cost_per_meter=None,
        mass_per_meter_g=None,
        notes=f"Imported from OpenMagnetics MAS @ {version_tag}.",
    )


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------
@dataclass
class MergeReport:
    added: int = 0
    kept_curated: int = 0
    skipped_user: int = 0
    skipped_unsupported: int = 0

    def line(self, kind: str) -> str:
        return (
            f"{kind}: +{self.added} added, "
            f"{self.kept_curated} kept (curated), "
            f"{self.skipped_user} kept (user-edited), "
            f"{self.skipped_unsupported} skipped (unsupported)"
        )


def _existing_ids(path: Path, key: str) -> set[str]:
    """Read ids from a curated/overlay JSON file, if it exists."""
    if not path.exists():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    ids: set[str] = set()
    for entry in raw.get(key, []):
        if not isinstance(entry, dict):
            continue
        ext = entry.get("x-pfc-inductor") or {}
        eid = ext.get("id") if isinstance(ext, dict) else None
        if eid:
            ids.add(str(eid))
    return ids


def _user_data_dir() -> Optional[Path]:
    try:
        from platformdirs import user_data_dir
    except ImportError:
        return None
    return Path(user_data_dir("PFCInductorDesigner", "indutor"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _import_materials(
    src: Path, *, version_tag: str, curated_ids: set[str], user_ids: set[str],
) -> tuple[list[Material], MergeReport]:
    rep = MergeReport()
    out: list[Material] = []
    seen: set[str] = set()
    for doc in _iter_ndjson(src):
        m = _material_from_mas_doc(doc, version_tag=version_tag)
        if m is None:
            rep.skipped_unsupported += 1
            continue
        if m.id in user_ids:
            rep.skipped_user += 1
            continue
        if m.id in curated_ids:
            rep.kept_curated += 1
            continue
        if m.id in seen:
            # OpenMagnetics ships a few near-duplicates (e.g. minor revs);
            # collapse on slug.
            continue
        seen.add(m.id)
        out.append(m)
        rep.added += 1
    return out, rep


def _import_wires(
    src: Path, *, version_tag: str, curated_ids: set[str], user_ids: set[str],
) -> tuple[list[Wire], MergeReport]:
    rep = MergeReport()
    out: list[Wire] = []
    seen: set[str] = set()
    for doc in _iter_ndjson(src):
        w = _wire_from_mas_doc(doc, version_tag=version_tag)
        if w is None:
            rep.skipped_unsupported += 1
            continue
        if w.id in user_ids:
            rep.skipped_user += 1
            continue
        if w.id in curated_ids:
            rep.kept_curated += 1
            continue
        if w.id in seen:
            continue
        seen.add(w.id)
        out.append(w)
        rep.added += 1
    return out, rep


def _write_payload(
    out_path: Path, key: str, items: list[dict], *, version_tag: str,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_comment": (
            f"Imported from OpenMagnetics MAS catalog @ {version_tag} "
            f"by scripts/import_mas_catalog.py. Do not edit by hand — "
            f"user edits belong in the user-data overlay."
        ),
        "_source": "openmagnetics",
        "_catalog_version": version_tag,
        key: items,
    }
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8",
    )


def run_import(src_dir: Path, *, dry_run: bool = False) -> int:
    """Programmatic entry point — returns a process-style exit code (0 ok)."""
    if not src_dir.exists():
        print(f"error: source dir not found: {src_dir}", file=sys.stderr)
        return 2

    version_tag = _read_version_tag(src_dir)
    print(f"OpenMagnetics MAS catalog @ {version_tag}")
    print(f"  source: {src_dir}")

    bundled_dir = REPO_ROOT / "data" / "mas"
    user_dir = _user_data_dir()

    mats_path = src_dir / "core_materials.ndjson"
    wires_path = src_dir / "wires.ndjson"

    materials_out: list[Material] = []
    wires_out: list[Wire] = []
    reports: list[str] = []

    if mats_path.exists():
        curated = _existing_ids(bundled_dir / "materials.json", "materials")
        user = _existing_ids(user_dir / "materials.json", "materials") if user_dir else set()
        materials_out, mrep = _import_materials(
            mats_path, version_tag=version_tag,
            curated_ids=curated, user_ids=user,
        )
        reports.append(mrep.line("materials"))
    else:
        print(f"  skip: {mats_path.name} not found", file=sys.stderr)

    if wires_path.exists():
        curated = _existing_ids(bundled_dir / "wires.json", "wires")
        user = _existing_ids(user_dir / "wires.json", "wires") if user_dir else set()
        wires_out, wrep = _import_wires(
            wires_path, version_tag=version_tag,
            curated_ids=curated, user_ids=user,
        )
        reports.append(wrep.line("wires"))
    else:
        print(f"  skip: {wires_path.name} not found", file=sys.stderr)

    if dry_run:
        print("\nDry run — nothing written.")
        for line in reports:
            print(f"  {line}")
        return 0

    if materials_out:
        items = []
        for m in materials_out:
            mas = material_to_mas(m).model_dump(
                mode="json", by_alias=True, exclude_none=True,
            )
            ext = mas.setdefault("x-pfc-inductor", {})
            ext["source"] = "openmagnetics"
            ext["catalog_version"] = version_tag
            items.append(mas)
        _write_payload(
            OUT_DIR / "materials.json", "materials", items,
            version_tag=version_tag,
        )

    if wires_out:
        items = []
        for w in wires_out:
            mas = wire_to_mas(w).model_dump(
                mode="json", by_alias=True, exclude_none=True,
            )
            ext = mas.setdefault("x-pfc-inductor", {})
            ext["source"] = "openmagnetics"
            ext["catalog_version"] = version_tag
            items.append(mas)
        _write_payload(
            OUT_DIR / "wires.json", "wires", items,
            version_tag=version_tag,
        )

    print(f"\nWrote catalog to {OUT_DIR}")
    for line in reports:
        print(f"  {line}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Import the OpenMagnetics MAS catalog into data/mas/catalog/.",
    )
    p.add_argument(
        "--source",
        type=Path,
        default=SRC_DIR_DEFAULT,
        help=f"Path to the vendored MAS catalog dir (default: {SRC_DIR_DEFAULT})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report without writing data/mas/catalog/.",
    )
    args = p.parse_args(argv)
    return run_import(args.source, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
