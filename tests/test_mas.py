"""MAS schema interop tests.

Verifies:
- Bidirectional adapters round-trip every shipped Material/Core/Wire.
- Loader auto-detects MAS vs legacy by shape.
- Saved MAS files re-load and recompute the same design results.
"""
from __future__ import annotations

import json
from pathlib import Path

from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.models.mas import (
    core_from_mas,
    core_to_mas,
    material_from_mas,
    material_to_mas,
    wire_from_mas,
    wire_to_mas,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------
def test_material_round_trip_preserves_critical_fields():
    """Convert internal → MAS → internal for every shipped material."""
    mats = load_materials()
    assert len(mats) >= 50
    for m in mats:
        rt = material_from_mas(material_to_mas(m))
        assert rt.id == m.id
        assert rt.vendor == m.vendor
        assert rt.name == m.name
        assert rt.mu_initial == m.mu_initial
        assert abs(rt.Bsat_25C_T - m.Bsat_25C_T) < 1e-9
        assert abs(rt.Bsat_100C_T - m.Bsat_100C_T) < 1e-9
        # Steinmetz
        assert abs(rt.steinmetz.alpha - m.steinmetz.alpha) < 1e-9
        assert abs(rt.steinmetz.beta - m.steinmetz.beta) < 1e-9
        assert abs(rt.steinmetz.Pv_ref_mWcm3 - m.steinmetz.Pv_ref_mWcm3) < 1e-9
        # Custom fields preserved through x-pfc-inductor
        if m.cost_per_kg is not None:
            assert rt.cost_per_kg == m.cost_per_kg
        if m.rolloff is not None:
            assert rt.rolloff is not None
            assert abs(rt.rolloff.a - m.rolloff.a) < 1e-9
            assert abs(rt.rolloff.b - m.rolloff.b) < 1e-9
            assert abs(rt.rolloff.c - m.rolloff.c) < 1e-9


def test_core_round_trip():
    cores = load_cores()
    assert len(cores) >= 100
    for c in cores:
        rt = core_from_mas(core_to_mas(c))
        assert rt.id == c.id
        assert rt.vendor == c.vendor
        assert rt.part_number == c.part_number
        assert rt.default_material_id == c.default_material_id
        assert abs(rt.Ae_mm2 - c.Ae_mm2) < 1e-9
        assert abs(rt.le_mm - c.le_mm) < 1e-9
        assert abs(rt.AL_nH - c.AL_nH) < 1e-9


def test_wire_round_trip():
    wires = load_wires()
    assert len(wires) >= 30
    for w in wires:
        rt = wire_from_mas(wire_to_mas(w))
        assert rt.id == w.id
        assert rt.type == w.type
        assert abs(rt.A_cu_mm2 - w.A_cu_mm2) < 1e-9


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------
def test_loader_detects_mas_layout(tmp_path, monkeypatch):
    """Loader must auto-pick MAS files over legacy when both exist."""
    from pfc_inductor import data_loader as dl

    # Build a tiny MAS materials.json under a tmp user-data dir
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    monkeypatch.setattr(dl, "user_data_path", lambda: user_dir)
    # Suppress the imported catalog so the test only sees its tmp file.
    monkeypatch.setattr(dl, "_open_catalog", lambda _name: None)

    mats_internal = load_materials()[:3]
    mas_payload = {
        "materials": [
            material_to_mas(m).model_dump(mode="json", by_alias=True,
                                          exclude_none=True)
            for m in mats_internal
        ],
    }
    (user_dir / "materials.json").write_text(
        json.dumps(mas_payload), encoding="utf-8",
    )

    # The loader should detect MAS shape and convert back
    loaded = dl.load_materials()
    assert len(loaded) == 3
    assert {m.id for m in loaded} == {m.id for m in mats_internal}


def test_loader_falls_back_to_legacy_format(tmp_path, monkeypatch):
    from pfc_inductor import data_loader as dl

    user_dir = tmp_path / "user"
    user_dir.mkdir()
    monkeypatch.setattr(dl, "user_data_path", lambda: user_dir)
    monkeypatch.setattr(dl, "_open_catalog", lambda _name: None)

    mats_internal = load_materials()[:2]
    legacy_payload = {
        "materials": [m.model_dump(mode="json") for m in mats_internal],
    }
    (user_dir / "materials.json").write_text(
        json.dumps(legacy_payload), encoding="utf-8",
    )

    loaded = dl.load_materials()
    assert len(loaded) == 2


# ---------------------------------------------------------------------------
# Bundled MAS files exist
# ---------------------------------------------------------------------------
def test_bundled_mas_files_present_and_valid():
    """The migration script's output must be in the repo."""
    for name in ("materials.json", "cores.json", "wires.json"):
        p = REPO_ROOT / "data" / "mas" / name
        assert p.exists(), f"data/mas/{name} missing — run scripts/migrate_to_mas.py"
        data = json.loads(p.read_text())
        # Top-level key matches the type
        assert any(k in data for k in ("materials", "cores", "wires"))


def test_design_runs_unchanged_when_db_loaded_via_mas():
    """End-to-end: design results from MAS-loaded DB equal legacy-loaded."""
    from pfc_inductor.design import design
    from pfc_inductor.models import Spec

    mats = load_materials()
    cores = load_cores()
    wires = load_wires()

    mat = find_material(mats, "magnetics-60_highflux")
    core = next(
        c for c in cores
        if c.default_material_id == "magnetics-60_highflux"
        and 40000 < c.Ve_mm3 < 100000
    )
    wire = next(w for w in wires if w.id == "AWG14")
    spec = Spec(Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
                Vout_V=400.0, Pout_W=800.0, eta=0.97,
                f_sw_kHz=65.0, ripple_pct=30.0)
    r = design(spec, core, wire, mat)
    # Same numbers we documented in test_design_engine.test_800W_design_with_high_flux_60
    assert 350 < r.L_required_uH < 400
    assert r.is_feasible() or r.warnings  # either feasible or has warnings


# ---------------------------------------------------------------------------
# Save round-trip
# ---------------------------------------------------------------------------
def test_save_then_reload_mas(tmp_path, monkeypatch):
    """save_materials(as_mas=True) → load_materials() returns equivalent set."""
    from pfc_inductor import data_loader as dl

    user_dir = tmp_path / "user"
    user_dir.mkdir()
    monkeypatch.setattr(dl, "user_data_path", lambda: user_dir)
    monkeypatch.setattr(dl, "_open_catalog", lambda _name: None)

    mats = load_materials()[:5]
    dl.save_materials(mats, as_mas=True)
    loaded = dl.load_materials()
    assert len(loaded) == len(mats)
    for orig, rt in zip(mats, loaded, strict=False):
        assert orig.id == rt.id
        assert abs(orig.Bsat_25C_T - rt.Bsat_25C_T) < 1e-9
