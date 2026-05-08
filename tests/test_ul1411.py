"""UL 1411 envelope tests."""
from __future__ import annotations

import pytest

from pfc_inductor.standards.ul1411 import (
    UlReport,
    evaluate,
    hipot_test_voltage,
    temperature_rise_limit_C,
)


def test_class_a_temperature_limit() -> None:
    """Class A magnet wire (105 °C absolute @ 40 °C ambient)
    → 65 °C rise."""
    assert temperature_rise_limit_C("A") == 65.0


def test_class_h_temperature_limit() -> None:
    """Class H is the highest spec — 180 °C absolute → 140 °C rise."""
    assert temperature_rise_limit_C("H") == 140.0


def test_temperature_classes_strictly_increasing() -> None:
    """A < B < F < H — adding rated heat tolerance step by step."""
    levels = [temperature_rise_limit_C(c) for c in ("A", "B", "F", "H")]
    assert levels == sorted(levels)


def test_hipot_formula() -> None:
    """UL 1411 §40: ``2 × V_work + 1000``. Anchor checks at
    230 V (mains) and 800 V (DC bus + safety margin)."""
    assert hipot_test_voltage(230.0) == pytest.approx(1460.0)
    assert hipot_test_voltage(800.0) == pytest.approx(2600.0)


def test_evaluate_passes_when_rise_below_limit() -> None:
    """50 °C rise on Class B (90 °C limit) → PASS with 40 °C
    margin."""
    rep = evaluate(
        insulation_class="B",
        temperature_rise_C=50.0,
        working_voltage_Vrms=230.0,
    )
    assert rep.passes_temperature
    assert rep.margin_to_temperature_limit_C == pytest.approx(40.0)


def test_evaluate_fails_when_rise_exceeds_limit() -> None:
    """100 °C rise on Class B (90 °C limit) → FAIL by 10 °C."""
    rep = evaluate(
        insulation_class="B",
        temperature_rise_C=100.0,
        working_voltage_Vrms=230.0,
    )
    assert not rep.passes_temperature
    assert rep.margin_to_temperature_limit_C == pytest.approx(-10.0)


def test_evaluate_low_voltage_skips_required_hipot() -> None:
    """Working voltage ≤ 30 V → hi-pot is typically waived; the
    flag goes False so a build script can branch on it."""
    rep = evaluate(
        insulation_class="B",
        temperature_rise_C=50.0,
        working_voltage_Vrms=12.0,
    )
    assert not rep.passes_hipot_required
    assert any("waived" in n for n in rep.notes)


def test_evaluate_high_voltage_requires_hipot() -> None:
    """230 Vrms working → hi-pot is a release-gate requirement."""
    rep = evaluate(
        insulation_class="B",
        temperature_rise_C=50.0,
        working_voltage_Vrms=230.0,
    )
    assert rep.passes_hipot_required
    # Hi-pot voltage in the notes for the lab to read.
    assert any("Hi-pot test voltage" in n for n in rep.notes)


def test_evaluate_class_step_up_on_failure() -> None:
    """When a design fails Class A, stepping up to Class B
    (or F, H) typically clears the limit. Same rise ⇒ pass on
    higher class."""
    rep_a = evaluate(
        insulation_class="A",
        temperature_rise_C=80.0,
        working_voltage_Vrms=230.0,
    )
    rep_f = evaluate(
        insulation_class="F",
        temperature_rise_C=80.0,
        working_voltage_Vrms=230.0,
    )
    assert not rep_a.passes_temperature  # 80 > 65 limit
    assert rep_f.passes_temperature       # 80 < 115 limit


# ---------------------------------------------------------------------------
# Dispatcher integration
# ---------------------------------------------------------------------------
def test_dispatcher_applies_ul1411_for_us_region() -> None:
    from pfc_inductor.compliance.dispatcher import applicable_standards
    from pfc_inductor.models import Spec

    spec = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=65, ripple_pct=20, T_amb_C=40,
    )
    assert "UL 1411" in applicable_standards(spec, "US")


def test_dispatcher_applies_ul1411_for_worldwide_region() -> None:
    from pfc_inductor.compliance.dispatcher import applicable_standards
    from pfc_inductor.models import Spec

    spec = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=65, ripple_pct=20, T_amb_C=40,
    )
    assert "UL 1411" in applicable_standards(spec, "Worldwide")


def test_dispatcher_skips_ul1411_for_eu_only() -> None:
    """EU-only projects don't get UL 1411 — keeps the bundle
    focused on the relevant regulatory regime."""
    from pfc_inductor.compliance.dispatcher import applicable_standards
    from pfc_inductor.models import Spec

    spec = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=65, ripple_pct=20, T_amb_C=40,
    )
    assert "UL 1411" not in applicable_standards(spec, "EU")


def test_full_evaluate_includes_ul1411_for_us_region() -> None:
    """End-to-end through the dispatcher — US-region bundle
    carries UL 1411 with the temperature-rise row + hi-pot row."""
    from pfc_inductor.compliance import evaluate as bundle_evaluate
    from pfc_inductor.data_loader import (
        ensure_user_data, load_cores, load_materials, load_wires,
    )
    from pfc_inductor.design import design as run_design
    from pfc_inductor.models import Spec

    ensure_user_data()
    mats = load_materials()
    cores = load_cores()
    wires = load_wires()
    spec = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=65, ripple_pct=20, T_amb_C=40,
    )
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores
                if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    result = run_design(spec, core, wire, mat)

    bundle = bundle_evaluate(spec, core, wire, mat, result, region="US")
    standards = {s.standard: s for s in bundle.standards}
    assert "UL 1411" in standards
    ul = standards["UL 1411"]
    # Two rows minimum: temperature rise + hi-pot.
    assert len(ul.rows) >= 2
    # First row is the temperature rise — label fixed by dispatcher.
    label, _value, _limit, _margin, _passed = ul.rows[0]
    assert label == "Temperature rise"
