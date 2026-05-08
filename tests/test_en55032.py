"""EN 55032 conducted-EMI estimator tests.

Covers contract correctness — limit-lookup table at the band
edges, harmonic enumeration in-band only, dispatcher routing,
report schema. The estimator is documented as a first-order
analytical envelope (±10 dB calibration target) so tests don't
assert absolute pass/fail accuracy; they verify the model
reports the right *direction* and shape.
"""

from __future__ import annotations

import math

import pytest

from pfc_inductor.standards.en55032 import (
    FREQ_BAND_HZ,
    EmiReport,
    HarmonicEnvelopePoint,
    evaluate_emi,
    limit_dbuv,
)


# ---------------------------------------------------------------------------
# Limit lookup table
# ---------------------------------------------------------------------------
def test_limit_at_band_edge_150khz_class_b_qp() -> None:
    """Anchor: 150 kHz Class B QP = 66 dBµV (top of the
    log-decay region per EN 55032:2017 Table A.5)."""
    assert limit_dbuv(150_000, class_="B", detector="QP") == 66.0


def test_limit_at_500khz_class_b_qp_decay_endpoint() -> None:
    """Anchor: 500 kHz Class B QP = 56 dBµV (bottom of the
    150 kHz – 500 kHz log-decay region)."""
    assert limit_dbuv(500_000, class_="B", detector="QP") == pytest.approx(56.0)


def test_limit_class_b_qp_decay_is_log_linear() -> None:
    """Mid-band point ≈ √(150k × 500k) = 274 kHz should sit
    half-way between 66 and 56 dBµV per the log interpolation."""
    midpoint_hz = math.sqrt(150_000 * 500_000)
    expected_db = (66.0 + 56.0) / 2.0
    assert limit_dbuv(midpoint_hz, class_="B", detector="QP") == pytest.approx(
        expected_db,
        abs=0.5,
    )


def test_limit_out_of_band_returns_inf() -> None:
    """Frequencies outside 150 kHz – 30 MHz return +inf so an
    out-of-band harmonic is never flagged as a violation."""
    assert limit_dbuv(50, class_="B") == float("inf")
    assert limit_dbuv(40_000_000, class_="B") == float("inf")


def test_class_a_is_more_permissive_than_class_b() -> None:
    """Industrial (Class A) is 10–13 dB looser than residential
    (Class B) across the band — the standard's headline
    relationship between the two classes."""
    for f in (200_000, 1_000_000, 10_000_000):
        a = limit_dbuv(f, class_="A", detector="QP")
        b = limit_dbuv(f, class_="B", detector="QP")
        assert a > b, f"Class A should be looser at {f} Hz"


def test_av_detector_is_tighter_than_qp() -> None:
    """Average-detector limits are 6–10 dB lower than QP across
    the band (the standard fixes the offset per Table A.5)."""
    for f in (200_000, 1_000_000, 10_000_000):
        qp = limit_dbuv(f, class_="B", detector="QP")
        av = limit_dbuv(f, class_="B", detector="AV")
        assert av < qp


# ---------------------------------------------------------------------------
# Estimator
# ---------------------------------------------------------------------------
def test_evaluate_emi_zero_inputs_return_empty_report() -> None:
    """Zero ripple or zero fsw → no-op pass with an empty point
    list. Used by the dispatcher to short-circuit when the engine
    hasn't computed a ripple yet."""
    r = evaluate_emi(spec_fsw_kHz=0, I_ripple_pk_pk_A=2.0)
    assert r.points == []
    assert r.passes
    r2 = evaluate_emi(spec_fsw_kHz=65, I_ripple_pk_pk_A=0)
    assert r2.points == []


def test_evaluate_emi_enumerates_only_in_band_harmonics() -> None:
    """fsw = 65 kHz, n_harmonics = 5 → only n = 3 (195 kHz) and
    higher land in the 150 kHz – 30 MHz band; n = 1 (65 kHz) and
    n = 2 (130 kHz) are below."""
    r = evaluate_emi(
        spec_fsw_kHz=65,
        I_ripple_pk_pk_A=2.0,
        n_harmonics=5,
    )
    indices = [p.n for p in r.points]
    assert 1 not in indices
    assert 2 not in indices
    assert all(FREQ_BAND_HZ[0] <= p.frequency_Hz <= FREQ_BAND_HZ[1] for p in r.points)


def test_filter_attenuation_lowers_envelope_uniformly() -> None:
    """Doubling the filter attenuation drops every harmonic's
    measured-dBµV by the same amount — the offset is applied
    uniformly post-source-amplitude."""
    r0 = evaluate_emi(
        spec_fsw_kHz=65,
        I_ripple_pk_pk_A=2.0,
        filter_attenuation_dB=20,
    )
    r1 = evaluate_emi(
        spec_fsw_kHz=65,
        I_ripple_pk_pk_A=2.0,
        filter_attenuation_dB=40,
    )
    # Same number of points — same fsw + n_harmonics.
    assert len(r0.points) == len(r1.points)
    # Each harmonic is exactly 20 dB lower in r1.
    for p0, p1 in zip(r0.points, r1.points, strict=True):
        assert p1.measured_dbuv == pytest.approx(p0.measured_dbuv - 20)


def test_higher_ripple_increases_envelope() -> None:
    """Doubling ripple amplitude increases the envelope by 6 dB
    (linear voltage → 20·log10(2) = 6.02 dB)."""
    low = evaluate_emi(spec_fsw_kHz=65, I_ripple_pk_pk_A=1.0)
    high = evaluate_emi(spec_fsw_kHz=65, I_ripple_pk_pk_A=2.0)
    for p_lo, p_hi in zip(low.points, high.points, strict=True):
        assert p_hi.measured_dbuv == pytest.approx(p_lo.measured_dbuv + 6.0, abs=0.1)


def test_evaluate_emi_returns_emi_report_shape() -> None:
    """Schema check — every report carries the headline fields
    consumers need (worst-margin, worst-n, pass flag)."""
    r = evaluate_emi(spec_fsw_kHz=100, I_ripple_pk_pk_A=1.0)
    assert isinstance(r, EmiReport)
    assert isinstance(r.passes, bool)
    assert isinstance(r.worst_margin_dB, float)
    assert r.worst_n is None or isinstance(r.worst_n, int)
    assert all(isinstance(p, HarmonicEnvelopePoint) for p in r.points)


# ---------------------------------------------------------------------------
# Dispatcher integration
# ---------------------------------------------------------------------------
def test_compliance_dispatcher_includes_en55032_for_switching_topology() -> None:
    from pfc_inductor.compliance.dispatcher import applicable_standards
    from pfc_inductor.models import Spec

    spec = Spec(
        topology="boost_ccm",
        Pout_W=600,
        Vin_min_Vrms=85,
        Vin_max_Vrms=265,
        Vout_V=400,
        f_sw_kHz=65,
        ripple_pct=20,
        T_amb_C=40,
    )
    assert "EN 55032" in applicable_standards(spec, "EU")


def test_compliance_dispatcher_excludes_en55032_for_line_reactor() -> None:
    """A 60 Hz line reactor produces no harmonics in the
    150 kHz – 30 MHz band, so EN 55032 doesn't apply."""
    from pfc_inductor.compliance.dispatcher import applicable_standards
    from pfc_inductor.models import Spec

    spec = Spec(
        topology="line_reactor",
        Vin_min_Vrms=85,
        Vin_max_Vrms=265,
        Vin_nom_Vrms=230,
        Pout_W=600,
        n_phases=1,
        L_req_mH=10.0,
        I_rated_Arms=2.6,
        T_amb_C=40,
    )
    assert "EN 55032" not in applicable_standards(spec, "EU")


def test_compliance_evaluate_produces_en55032_standard_result() -> None:
    """End-to-end through the dispatcher — boost-PFC bundle
    carries IEC 61000-3-2 + EN 55032, both with rows."""
    from pfc_inductor.compliance import evaluate
    from pfc_inductor.data_loader import (
        ensure_user_data,
        load_cores,
        load_materials,
        load_wires,
    )
    from pfc_inductor.design import design as run_design
    from pfc_inductor.models import Spec

    ensure_user_data()
    mats = load_materials()
    cores = load_cores()
    wires = load_wires()
    spec = Spec(
        topology="boost_ccm",
        Pout_W=600,
        Vin_min_Vrms=85,
        Vin_max_Vrms=265,
        Vout_V=400,
        f_sw_kHz=65,
        ripple_pct=20,
        T_amb_C=40,
    )
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    result = run_design(spec, core, wire, mat)

    bundle = evaluate(spec, core, wire, mat, result, region="EU")
    standards = {s.standard for s in bundle.standards}
    assert "IEC 61000-3-2" in standards
    assert "EN 55032" in standards
    en = next(s for s in bundle.standards if s.standard == "EN 55032")
    # Schema check — every harmonic row has the standard 5-tuple.
    for label, value, limit, margin, passed in en.rows:
        assert label.startswith("n = ")
        assert "dBµV" in value
        assert "dBµV" in limit
        assert isinstance(margin, float)
        assert isinstance(passed, bool)
    # Notes carry the analytical-envelope disclaimer + LISN
    # measurement requirement.
    notes_text = " ".join(en.notes)
    assert "LISN" in notes_text
    assert "Class B" in notes_text
