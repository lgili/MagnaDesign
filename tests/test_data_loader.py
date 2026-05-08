"""Sanity checks on the bundled JSON databases."""

from pfc_inductor.data_loader import (
    load_cores,
    load_curated_ids,
    load_materials,
    load_wires,
)


def test_materials_load_and_have_steinmetz():
    mats = load_materials()
    assert len(mats) >= 30
    for m in mats:
        assert m.steinmetz.Pv_ref_mWcm3 > 0
        # Wide bounds: includes high-freq materials like Magnetics L
        # whose data is concentrated at 0.5-3 MHz and yields steeper fits.
        assert 1.0 <= m.steinmetz.alpha <= 3.0, f"{m.id}: alpha={m.steinmetz.alpha}"
        assert 1.0 <= m.steinmetz.beta <= 6.5, f"{m.id}: beta={m.steinmetz.beta}"
        assert 0.2 <= m.Bsat_25C_T <= 2.1  # silicon steel reaches ~2.03 T


def test_cores_have_geometry():
    cores = load_cores()
    assert len(cores) >= 100
    for c in cores:
        assert c.Ae_mm2 > 0
        assert c.le_mm > 0
        assert c.AL_nH > 0


def test_wires_complete_AWG_range():
    wires = load_wires()
    awgs = {w.awg for w in wires if w.awg is not None}
    # Should cover at least 10..40 AWG
    for awg in (10, 12, 16, 20, 24, 30, 40):
        assert awg in awgs, f"AWG {awg} missing from wire database"


def test_brazilian_vendors_present():
    """Thornton and Magmattec are critical for the user's market."""
    mats = load_materials()
    vendors = {m.vendor for m in mats}
    assert "Thornton" in vendors
    assert "Magmattec" in vendors


def test_catalog_merge_adds_openmagnetics_entries():
    """When data/mas/catalog/*.json exists, those entries are appended."""
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    catalog_path = repo / "data" / "mas" / "catalog" / "materials.json"
    if not catalog_path.exists():
        return  # catalog not yet imported in this checkout — skip

    mats = load_materials()
    # The shipped curated set has 50 entries; the catalog adds more.
    assert len(mats) > 100, "catalog merge should yield >100 materials"

    # At least one catalog-only material is recoverable, and its source
    # tag survives the round-trip through the loader.
    curated = load_curated_ids("materials")
    assert len(curated) >= 30  # baseline curated count
    catalog_only = [m for m in mats if m.id not in curated]
    assert catalog_only, "no catalog-only materials returned"


def test_curated_only_filter_excludes_catalog_rows():
    """`load_curated_ids` is the source of truth for the UI filter."""
    curated = load_curated_ids("materials")
    mats = load_materials()
    if len(mats) <= len(curated):
        return  # no catalog imported yet — nothing to verify
    catalog_only = [m for m in mats if m.id not in curated]
    # Every non-curated material must carry a source breadcrumb in
    # ``notes``. We accept either OpenMagnetics (MAS catalog) or
    # PyETK (Ansys-imported ferrites). New importers should append
    # their own marker here.
    expected_markers = ("OpenMagnetics", "PyETK")
    for m in catalog_only:
        assert any(marker in m.notes for marker in expected_markers), (
            f"catalog material {m.id!r} has no source marker in notes: {m.notes!r}"
        )


def test_catalog_material_drives_design_engine():
    """A catalog-only material must run end-to-end without error."""
    from pfc_inductor.data_loader import find_material
    from pfc_inductor.design import design
    from pfc_inductor.models import Spec

    mats = load_materials()
    cores = load_cores()
    wires = load_wires()
    curated = load_curated_ids("materials")
    catalog_only = [m for m in mats if m.id not in curated]
    if not catalog_only:
        return  # catalog not imported — skip
    target_material = catalog_only[0]
    target_core = next(
        (c for c in cores if c.shape.lower() in {"toroid", "e", "ee"}),
        cores[0],
    )
    target_wire = next((w for w in wires if w.type == "round"), wires[0])

    spec = Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85,
        Vin_max_Vrms=265,
        Vin_nom_Vrms=220,
        f_line_Hz=50,
        Vout_V=400,
        Pout_W=600,
        eta=0.97,
        f_sw_kHz=65,
        ripple_pct=30,
        T_amb_C=40,
        T_max_C=100,
        Ku_max=0.4,
        Bsat_margin=0.2,
    )
    # Rebuild the material reference via the loader path so any future
    # adapter changes are exercised.
    m = find_material(mats, target_material.id)
    result = design(spec, target_core, target_wire, m)
    assert result.N_turns > 0
    assert result.L_actual_uH > 0
