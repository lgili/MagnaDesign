"""HTML report generation tests."""

import tempfile
from pathlib import Path

from pfc_inductor.data_loader import find_material, load_cores, load_materials, load_wires
from pfc_inductor.design import design
from pfc_inductor.models import Spec
from pfc_inductor.report import generate_html_report


def test_report_generates_self_contained_html():
    mats, cores, wires = load_materials(), load_cores(), load_wires()
    spec = Spec(
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=220.0,
        Vout_V=400.0,
        Pout_W=800.0,
        eta=0.97,
        f_sw_kHz=65.0,
        ripple_pct=30.0,
    )
    mat = find_material(mats, "magnetics-60_highflux")
    core = next(
        c
        for c in cores
        if c.default_material_id == "magnetics-60_highflux" and 40000 < c.Ve_mm3 < 100000
    )
    wire = next(w for w in wires if w.id == "AWG14")
    r = design(spec, core, wire, mat)

    with tempfile.TemporaryDirectory() as td:
        out = generate_html_report(spec, core, mat, wire, r, Path(td) / "report.html")
        assert out.exists()
        text = out.read_text()
        # Must contain embedded base64 images, not external file refs
        assert "data:image/png;base64," in text
        # Key sections must be present
        for section in (
            "Design specifications",
            "Selection",
            "Electrical / magnetic results",
            "Inductor current waveform",
            "Loss breakdown",
        ):
            assert section in text
