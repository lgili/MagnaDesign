"""Compare module + HTML/CSV export tests."""
import csv
import tempfile
from pathlib import Path

import pytest

from pfc_inductor.compare import METRICS, CompareSlot, categorize
from pfc_inductor.compare.diff import _DIRECTION_BY_KEY
from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.design import design
from pfc_inductor.models import Spec


@pytest.fixture(scope="module")
def two_slots():
    mats, cores, wires = load_materials(), load_cores(), load_wires()
    spec = Spec(Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
                Vout_V=400.0, Pout_W=800.0, eta=0.97,
                f_sw_kHz=65.0, ripple_pct=30.0)
    mat_a = find_material(mats, "magnetics-60_highflux")
    mat_b = find_material(mats, "magnetics-60_xflux")
    core_a = next(
        c for c in cores
        if c.default_material_id == "magnetics-60_highflux"
        and 40000 < c.Ve_mm3 < 100000
    )
    core_b = next(
        c for c in cores
        if c.default_material_id == "magnetics-60_xflux"
        and 40000 < c.Ve_mm3 < 100000
    )
    w = next(w for w in wires if w.id == "AWG14")
    r_a = design(spec, core_a, w, mat_a)
    r_b = design(spec, core_b, w, mat_b)
    return [
        CompareSlot(spec=spec, core=core_a, wire=w, material=mat_a, result=r_a),
        CompareSlot(spec=spec, core=core_b, wire=w, material=mat_b, result=r_b),
    ]


def test_categorize_lower_is_better():
    assert categorize("P_total_W", 10.0, 8.0) == "better"
    assert categorize("P_total_W", 10.0, 12.0) == "worse"
    assert categorize("P_total_W", 10.0, 10.0) == "neutral"


def test_categorize_higher_is_better():
    assert categorize("sat_margin_pct", 30.0, 50.0) == "better"
    assert categorize("sat_margin_pct", 30.0, 10.0) == "worse"


def test_categorize_neutral_metric():
    """Line current is determined by spec, not design — should be neutral."""
    assert categorize("I_line_pk_A", 14.0, 10.0) == "neutral"


def test_metric_value_extraction(two_slots):
    """Every defined metric must yield a finite number for a real slot."""
    for metric in METRICS:
        v = metric.value_of(two_slots[0])
        assert isinstance(v, float)
        assert v == v  # not NaN


def test_metric_format_returns_str(two_slots):
    for metric in METRICS:
        s = metric.format(two_slots[0])
        assert isinstance(s, str) and len(s) > 0


def test_directions_table_covers_all_metrics():
    for m in METRICS:
        assert m.key in _DIRECTION_BY_KEY


def test_compare_slot_label(two_slots):
    s = two_slots[0]
    assert s.material.name in s.label
    assert s.core.part_number in s.label
    assert s.wire.id in s.label


def test_html_compare_self_contained(two_slots):
    from pfc_inductor.report import generate_compare_html
    with tempfile.TemporaryDirectory() as td:
        out = generate_compare_html(two_slots, Path(td) / "cmp.html")
        text = out.read_text(encoding="utf-8")
        assert "Comparação" in text
        for slot in two_slots:
            # short_label has '\n', that's split in HTML; check parts.
            assert slot.material.name in text
            assert slot.core.part_number in text
        # Diff colours present
        assert "#dff5e3" in text or "#fbe2e2" in text


def test_csv_export_format(two_slots, tmp_path):
    """Replicate the dialog's CSV write logic and verify shape."""
    out = tmp_path / "cmp.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        header = ["Métrica", "Unidade"] + [s.label for s in two_slots]
        w.writerow(header)
        for metric in METRICS:
            row = [metric.label, metric.unit] + [
                metric.format(s) for s in two_slots
            ]
            w.writerow(row)
    rows = list(csv.reader(out.open(encoding="utf-8")))
    assert len(rows) == 1 + len(METRICS)
    assert len(rows[0]) == 2 + len(two_slots)
