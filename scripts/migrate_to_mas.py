"""Generate MAS-shaped JSON files from the legacy layout.

Reads `data/{materials,cores,wires}.json` (legacy) and writes the
MAS-shaped equivalents under `data/mas/`. The loader will prefer those
on next launch; legacy files are kept untouched.

Run from the project root:

    .venv/bin/python scripts/migrate_to_mas.py
"""
from __future__ import annotations
import json
from pathlib import Path

from pfc_inductor.data_loader import load_materials, load_cores, load_wires
from pfc_inductor.models.mas import (
    material_to_mas, core_to_mas, wire_to_mas,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "mas"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Writing MAS-shaped data under {OUT_DIR}")

    mats = load_materials()
    payload = {
        "_comment": (
            "MAS-shaped materials. Auto-generated from data/materials.json by "
            "scripts/migrate_to_mas.py. Custom fields under x-pfc-inductor."
        ),
        "materials": [
            material_to_mas(m).model_dump(mode="json", by_alias=True,
                                          exclude_none=True)
            for m in mats
        ],
    }
    (OUT_DIR / "materials.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(f"  materials.json — {len(mats)} entries")

    cores = load_cores()
    payload = {
        "_comment": (
            "MAS-shaped cores. Auto-generated from data/cores.json by "
            "scripts/migrate_to_mas.py."
        ),
        "cores": [
            core_to_mas(c).model_dump(mode="json", by_alias=True,
                                      exclude_none=True)
            for c in cores
        ],
    }
    (OUT_DIR / "cores.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(f"  cores.json     — {len(cores)} entries")

    wires = load_wires()
    payload = {
        "_comment": (
            "MAS-shaped wires. Auto-generated from data/wires.json by "
            "scripts/migrate_to_mas.py."
        ),
        "wires": [
            wire_to_mas(w).model_dump(mode="json", by_alias=True,
                                      exclude_none=True)
            for w in wires
        ],
    }
    (OUT_DIR / "wires.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(f"  wires.json     — {len(wires)} entries")
    print("Done. Loader will prefer MAS layout on next launch.")


if __name__ == "__main__":
    main()
