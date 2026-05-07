"""Extend the Dongxing EI lamination catalogue.

The MAS bundle ships 3 Dongxing entries (EI28-17 / EI41-17 / EI60-20)
matching the calibration datasheets DX60346/414/415. For 60-Hz line-
reactor design that's too narrow — the engineer covering 200–2000 W
needs 6–10 candidate sizes per spec.

EI silicon-steel laminations follow universal dimensions per JIS
C2535 / DIN 41302 / GB/T 5232 (the three differ by a few tenths of
a mm but are interchangeable for design purposes). Any Chinese
fabricator — Dongxing, Centersky, Jirui, Goldbull — stamps these
exact sheets. We add the missing standard sizes here, paired with
the same three NGO-silicon-steel grades already calibrated:

  - **50H800**   — premium NGO (Bsat 1.65 T, low loss)
  - **50H1300**  — mid-grade  (Bsat 1.55 T)
  - **50CS1300** — economy CS (Bsat 1.55 T)

For each size we emit two stack heights so the optimizer can pick
window-area / volume trade-offs:

  - **square stack** (s = t) — most common, lowest cost
  - **rectangular stack** (s ≈ 1.5 t) — more window area per Ae

AL values are calibrated to μ_eff ≈ 165 (averaged from the existing
3 entries) so the engine's L-vs-N solver gives physically plausible
turn counts. The geometry follows the JIS proportions:

  - tongue width             = ``EI<size>`` ÷ 3 (rounded to standard)
  - window width per side    = tongue / 2
  - window height            = 1.5 × tongue
  - outer leg width          = tongue / 2
  - effective magnetic path  = ~5.85 × tongue
  - mean length of turn      ≈ 2 × (tongue + stack) + π × (tongue + stack) / 2

Mass and cost scale linearly with volume (mass-per-volume of NGO
silicon steel ≈ 7.65 g/cm³; cost ~ $0.17/cm³ retail in 2026).

Run from the repo root:

    python scripts/extend_dongxing_ei.py

Idempotent: re-running on an already-extended catalogue is a no-op
(checks ``x-pfc-inductor.id`` collisions before inserting).
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORES_FILE = REPO_ROOT / "data" / "mas" / "cores.json"

# The data loader reads ``<user_data_dir>/cores.json`` first and only
# falls back to the bundled MAS file if the user copy is missing — so
# when the user has run the app at least once, edits to the bundled
# file alone won't surface. Mirror the additions into the user copy
# too, additively (existing IDs are preserved so manual edits aren't
# lost). The user-data path mirrors ``data_loader.user_data_path``.
def _user_cores_file() -> Path | None:
    try:
        from platformdirs import user_data_dir
    except ImportError:
        return None
    return Path(user_data_dir("PFCInductorDesigner", "indutor")) / "cores.json"

MU0 = 4 * math.pi * 1e-7
MU_EFF_NGO = 165.0          # averaged from EI28-17 / EI41-17 / EI60-20
RHO_SI_STEEL_G_CM3 = 7.65
COST_PER_CM3_USD = 0.17


@dataclass(frozen=True)
class EIBlank:
    """One row of the JIS-standard EI sheet table."""
    size: int                # ``EI<size>`` — overall length in mm
    tongue_mm: float         # centre-leg width (= stack-square reference)
    le_mm: float             # effective magnetic path length


# JIS C2535 standard EI laminations. ``size`` matches the suffix in
# ``EI<size>`` part numbers; ``tongue_mm`` is the centre-leg width.
# ``le_mm`` is the effective path length (cross-checked with the 3
# existing Dongxing entries: EI28→65, EI41→80, EI60→117 — fits le ≈
# 5.85 · tongue with ±5 % deviation).
EI_BLANKS: list[EIBlank] = [
    EIBlank(size=33, tongue_mm=11.0, le_mm=64.0),
    EIBlank(size=48, tongue_mm=16.0, le_mm=94.0),
    EIBlank(size=57, tongue_mm=19.0, le_mm=112.0),
    EIBlank(size=66, tongue_mm=22.0, le_mm=129.0),
    EIBlank(size=76, tongue_mm=25.0, le_mm=147.0),
    EIBlank(size=85, tongue_mm=28.0, le_mm=164.0),
    EIBlank(size=96, tongue_mm=32.0, le_mm=187.0),
]

# Stack ratios per blank — the optimiser benefits from at least two
# choices per size so it can trade window area against effective area.
STACK_RATIOS = [1.0, 1.5]

# Material → bundle-id mapping (the materialName field in MAS records
# must match a ``name`` in materials.json).
MATERIALS = [
    ("50H800",   "dongxing-50h800"),
    ("50H1300",  "dongxing-50h1300"),
    ("50CS1300", "dongxing-50cs1300"),
]


def _ei_geometry(blank: EIBlank, stack_mm: float) -> dict:
    t = blank.tongue_mm
    s = stack_mm
    Ae_mm2 = t * s
    Ve_mm3 = Ae_mm2 * blank.le_mm
    # Window: tongue/2 wide × 1.5·tongue tall. ``Wa`` = single window
    # (the engine's convention — ``Ku = N·A_iso/Wa`` treats Wa as the
    # winding-side area, half of the EI total window).
    window_w = t * 0.5
    window_h = t * 1.5
    Wa_mm2 = window_w * window_h
    # MLT: rectangle around the bobbin (tongue × stack) plus a half-
    # circle at each end of the bobbin = 2·(t + s) + π·(t + s)/2.
    MLT_mm = (2.0 + math.pi / 2.0) * (t + s)
    height_mm = stack_mm + 2 * window_h            # full E + I stack height
    return {
        "effectiveArea": round(Ae_mm2, 1),
        "effectiveMagneticPathLength": round(blank.le_mm, 1),
        "effectiveVolume": round(Ve_mm3, 1),
        "windingWindowArea": round(Wa_mm2, 1),
        "meanLengthTurn": round(MLT_mm, 1),
        "height": round(height_mm, 1),
    }


def _AL_nH(geom: dict) -> float:
    Ae_m2 = geom["effectiveArea"] * 1e-6
    le_m = geom["effectiveMagneticPathLength"] * 1e-3
    AL_H = MU0 * MU_EFF_NGO * Ae_m2 / le_m
    return round(AL_H * 1e9, 1)


def _mass_g(Ve_mm3: float) -> float:
    return round(Ve_mm3 * 1e-3 * RHO_SI_STEEL_G_CM3, 1)


def _cost_usd(Ve_mm3: float) -> float:
    return round(Ve_mm3 * 1e-3 * COST_PER_CM3_USD, 2)


def _build_record(blank: EIBlank, stack_mm: float,
                  material_name: str, material_id: str) -> dict:
    name = f"EI{blank.size}-{int(round(stack_mm))}"
    geom = _ei_geometry(blank, stack_mm)
    mat_short = material_name.lower().replace("/", "")
    pfc_id = f"dongxing-ei{blank.size}{int(round(stack_mm))}-{mat_short}"
    return {
        "name": name,
        "manufacturer": "Dongxing",
        "shape": {"name": name, "family": "EI"},
        "dimensions": geom,
        "materialName": material_id,
        "inductanceFactor": _AL_nH(geom),
        "gapLength": 0.0,
        "notes": (
            "Dongxing harmonic-reactor lamination set, JIS C2535 standard "
            "geometry. AL extrapolated from DX60346/414/415 calibration "
            f"(μ_eff ≈ {MU_EFF_NGO:.0f}); verify against datasheet for "
            "production designs."
        ),
        "x-pfc-inductor": {
            "id": pfc_id,
            "mass_g": _mass_g(geom["effectiveVolume"]),
            "cost_per_piece": _cost_usd(geom["effectiveVolume"]),
        },
    }


def _merge_into(path: Path, new_records: list[dict]) -> tuple[int, int]:
    """Append ``new_records`` into ``path``'s ``cores`` array.

    Skips records whose ``x-pfc-inductor.id`` already exists. Returns
    ``(added, total_after)``. Creates a parent directory and a fresh
    ``{"cores": []}`` document if ``path`` doesn't exist yet.
    """
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"cores": []}
    cores = data.setdefault("cores", [])
    existing_ids = {
        c.get("x-pfc-inductor", {}).get("id")
        for c in cores
        if isinstance(c.get("x-pfc-inductor"), dict)
    }
    added = 0
    for rec in new_records:
        if rec["x-pfc-inductor"]["id"] in existing_ids:
            continue
        cores.append(rec)
        existing_ids.add(rec["x-pfc-inductor"]["id"])
        added += 1
    if added:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return added, len(cores)


def main() -> int:
    if not CORES_FILE.exists():
        print(f"error: {CORES_FILE} not found", file=sys.stderr)
        return 1

    # Build the full set of records once, then merge into both the
    # bundled MAS catalogue (source of truth for new installs) and
    # the user overlay (what a returning user actually reads from).
    new_records: list[dict] = []
    for blank in EI_BLANKS:
        for ratio in STACK_RATIOS:
            stack_mm = round(blank.tongue_mm * ratio)
            for mat_name, mat_id in MATERIALS:
                new_records.append(
                    _build_record(blank, stack_mm, mat_name, mat_id)
                )

    added_bundled, total_bundled = _merge_into(CORES_FILE, new_records)
    print(f"  bundled MAS  {CORES_FILE.relative_to(REPO_ROOT)}: "
          f"+{added_bundled} (total {total_bundled})")

    user_file = _user_cores_file()
    if user_file is not None and user_file.exists():
        added_user, total_user = _merge_into(user_file, new_records)
        print(f"  user overlay {user_file}: "
              f"+{added_user} (total {total_user})")
    elif user_file is not None:
        print(f"  user overlay not found at {user_file} — "
              "will be seeded from bundled on next launch.")
    else:
        print("  platformdirs not importable; skipping user overlay.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
