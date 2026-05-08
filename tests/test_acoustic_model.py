"""Acoustic-noise estimator tests.

Covers contract correctness (schema, A-weighting, mechanism
selection, threshold reporting) and engineering anchors that
match published vendor data within the model's documented
±3 dB(A) calibration target.
"""
from __future__ import annotations

import math

import pytest

from pfc_inductor.acoustic.model import (
    DEFAULT_QUIET_THRESHOLD_DBA,
    NoiseEstimate,
    _a_weighting_dB,
    _spl_magnetostriction_dba,
    _spl_winding_lorentz_dba,
    estimate_noise,
    magnetostrictive_lambda_s_ppm,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def reference_inputs():
    """600 W boost-PFC on the bundled reference toroid."""
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
    return spec, core, wire, mat, result


# ---------------------------------------------------------------------------
# A-weighting curve
# ---------------------------------------------------------------------------
def test_a_weighting_at_1khz_is_zero() -> None:
    """1 kHz is the reference frequency — A-weighting offset
    should be approximately 0 dB."""
    assert abs(_a_weighting_dB(1000.0)) < 1.5


def test_a_weighting_attenuates_low_frequencies() -> None:
    """Low frequencies (50 Hz, 100 Hz) get tens of dB cut."""
    assert _a_weighting_dB(50.0) < -25.0
    assert _a_weighting_dB(100.0) < -15.0


def test_a_weighting_attenuates_ultrasonic() -> None:
    """Frequencies above 20 kHz get cut so the loudness
    perception correctly drops to ~0 even for raw-pressure
    sources at those frequencies."""
    assert _a_weighting_dB(50_000) < -10.0
    assert _a_weighting_dB(130_000) < -20.0


# ---------------------------------------------------------------------------
# magnetostrictive_lambda_s_ppm helper
# ---------------------------------------------------------------------------
def test_lambda_s_returns_high_value_for_nizn() -> None:
    """NiZn ferrites famously hum — λ_s should be high."""
    from pfc_inductor.models import Material

    # Build a minimal material with type='nizn' to exercise the
    # name-based fallback path. Real catalogue entries don't
    # always carry an explicit type field.
    class _M:
        type = "nizn"
        name = "test"
        id = "t"
        magnetostrictive_lambda_s_ppm = None

    val = magnetostrictive_lambda_s_ppm(_M())  # type: ignore[arg-type]
    assert val >= 20.0


def test_lambda_s_explicit_field_wins(reference_inputs) -> None:
    """When the catalogue entry has a real measured λ_s value,
    it overrides the family-default fallback."""
    _, _, _, mat, _ = reference_inputs

    # Stash an explicit value on the material via Pydantic.
    explicit = mat.model_copy(update={
        "magnetostrictive_lambda_s_ppm": 42.0,
    }) if hasattr(mat.__class__, "model_copy") else None
    if explicit is None:
        pytest.skip("Material model doesn't support extra fields yet")
    val = magnetostrictive_lambda_s_ppm(explicit)
    assert val == 42.0


def test_lambda_s_kool_mu_is_quietest() -> None:
    """Kool Mµ is the quietest powder family — the helper should
    return a small λ_s."""
    class _M:
        type = "powder"
        name = "Kool Mu"
        id = "t"
        magnetostrictive_lambda_s_ppm = None

    val = magnetostrictive_lambda_s_ppm(_M())  # type: ignore[arg-type]
    assert val < 1.0


# ---------------------------------------------------------------------------
# Mechanism estimators
# ---------------------------------------------------------------------------
def test_magnetostriction_zero_inputs_return_minus_inf() -> None:
    """Zero λ_s / B / fsw → no contribution, -inf dB(A)."""
    db, _ = _spl_magnetostriction_dba(0, 0.3, 65_000, 5e-5)
    assert db == float("-inf")


def test_magnetostriction_dominant_freq_is_2x_fsw() -> None:
    """B² nonlinearity → vibration at twice the switching
    frequency. Engineering anchor: rectified-magnetostriction."""
    _, freq = _spl_magnetostriction_dba(1.0, 0.3, 65_000, 5e-5)
    assert freq == pytest.approx(130_000)


def test_magnetostriction_higher_b_is_louder() -> None:
    """Doubling B should increase SPL by ~12 dB (B² → +6 dB
    per doubling, then +6 dB more from velocity scaling)."""
    db_low, _ = _spl_magnetostriction_dba(1.0, 0.1, 65_000, 5e-5)
    db_high, _ = _spl_magnetostriction_dba(1.0, 0.2, 65_000, 5e-5)
    # +12 dB per B-doubling — the strain quadratic plus velocity
    # ω·displacement scaling.
    delta = db_high - db_low
    assert delta == pytest.approx(12.0, abs=1.0)


def test_winding_lorentz_zero_for_single_layer() -> None:
    """Single-layer windings have no inter-layer pairs → no
    Lorentz contribution."""
    db, _ = _spl_winding_lorentz_dba(2.0, 65_000, n_layers=1)
    assert db == float("-inf")


# ---------------------------------------------------------------------------
# Public estimate_noise()
# ---------------------------------------------------------------------------
def test_estimate_noise_returns_full_schema(reference_inputs) -> None:
    spec, core, wire, mat, result = reference_inputs
    est = estimate_noise(spec, core, wire, mat, result)
    assert isinstance(est, NoiseEstimate)
    assert isinstance(est.dB_a_at_1m, float)
    assert math.isfinite(est.dB_a_at_1m)
    assert est.dominant_mechanism in (
        "magnetostriction", "winding_lorentz",
        "bobbin_resonance", "none",
    )
    assert isinstance(est.contributors_dba, dict)


def test_low_fsw_design_is_louder_than_high_fsw(
    reference_inputs,
) -> None:
    """Engineering anchor: a VFD low-fsw point (8 kHz) should
    sound louder than a mid-band 65 kHz point because the
    A-weighting curve attenuates the 130 kHz harmonic of the
    65 kHz design more aggressively than the 16 kHz harmonic
    of the 8 kHz design."""
    from pfc_inductor.design import design as run_design

    spec, core, wire, mat, _ = reference_inputs
    spec_low = spec.model_copy(update={"f_sw_kHz": 8})
    spec_high = spec
    result_low = run_design(spec_low, core, wire, mat)
    result_high = run_design(spec_high, core, wire, mat)

    est_low = estimate_noise(spec_low, core, wire, mat, result_low)
    est_high = estimate_noise(spec_high, core, wire, mat, result_high)

    assert est_low.dB_a_at_1m > est_high.dB_a_at_1m


def test_estimate_noise_threshold_drives_headroom(
    reference_inputs,
) -> None:
    """Headroom = threshold - SPL. Doubling the threshold should
    increase the headroom by exactly the same amount."""
    spec, core, wire, mat, result = reference_inputs
    base = estimate_noise(spec, core, wire, mat, result,
                          quiet_threshold_dba=30.0)
    relaxed = estimate_noise(spec, core, wire, mat, result,
                             quiet_threshold_dba=45.0)
    assert relaxed.headroom_to_threshold_dB - base.headroom_to_threshold_dB \
        == pytest.approx(15.0)


def test_estimate_noise_default_threshold_is_quiet_appliance(
    reference_inputs,
) -> None:
    spec, core, wire, mat, result = reference_inputs
    est = estimate_noise(spec, core, wire, mat, result)
    # Headroom = threshold - SPL → threshold = SPL + headroom.
    threshold = est.dB_a_at_1m + est.headroom_to_threshold_dB
    assert threshold == pytest.approx(DEFAULT_QUIET_THRESHOLD_DBA)


def test_estimate_noise_zero_b_returns_no_mechanism(
    reference_inputs,
) -> None:
    """A design where the engine reports B_pk = 0 (degenerate /
    unfeasible spec) should fall through to ``mechanism='none'``
    with SPL=0."""
    spec, core, wire, mat, _ = reference_inputs

    class _ZeroResult:
        B_pk_T = 0.0
        I_ripple_pk_pk_A = 0.0
        n_layers = 1

    est = estimate_noise(
        spec, core, wire, mat, _ZeroResult(),  # type: ignore[arg-type]
    )
    assert est.dominant_mechanism == "none"
    assert est.dB_a_at_1m == 0.0
