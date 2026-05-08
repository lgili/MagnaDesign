"""VFD modulation workflow tests.

Covers:

- ``FswModulation`` model — constructor validation + RPM-band
  helper + JSON round-trip.
- ``Spec.fsw_modulation`` extension — backward-compat (every
  legacy `.pfc` round-trips identically) + new-feature
  serialisation.
- ``BandedDesignResult`` aggregation — worst-per-metric picks
  the right point, edge-weighted profile honours the dither
  semantics, missing measurements degrade cleanly.
- ``eval_band`` engine wrapper — runs through the engine on a
  feasible reference design without raising; failure absorption
  works when the band pushes a point into a corner.
"""
from __future__ import annotations

import json

import pytest

from pfc_inductor.data_loader import (
    ensure_user_data,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.models import (
    FswModulation,
    Spec,
    from_rpm_band,
    rpm_to_fsw,
)
from pfc_inductor.models.banded_result import (
    BandedDesignResult,
    BandPoint,
    aggregate_band,
    unwrap_for_kpi,
)
from pfc_inductor.modulation import design_or_band, eval_band


# ---------------------------------------------------------------------------
# Model — FswModulation construction + validation
# ---------------------------------------------------------------------------
def test_fsw_modulation_uniform_band_validates() -> None:
    m = FswModulation(fsw_min_kHz=4, fsw_max_kHz=25, n_eval_points=5)
    points = m.fsw_points_kHz()
    assert len(points) == 5
    assert points[0] == 4.0
    assert points[-1] == 25.0
    # Linear sweep — each step is the same.
    diffs = {round(points[i + 1] - points[i], 6)
             for i in range(len(points) - 1)}
    assert len(diffs) == 1


def test_fsw_modulation_rejects_inverted_band() -> None:
    with pytest.raises(ValueError, match="fsw_max_kHz"):
        FswModulation(fsw_min_kHz=25, fsw_max_kHz=4)


def test_fsw_modulation_rpm_band_requires_extra_fields() -> None:
    with pytest.raises(ValueError, match="rpm_band.*requires"):
        FswModulation(
            fsw_min_kHz=4, fsw_max_kHz=25, profile="rpm_band",
        )


def test_fsw_modulation_n_points_capped_at_extremes() -> None:
    """Two points → just min + max; 50 points stays within the
    declared limit."""
    m = FswModulation(fsw_min_kHz=4, fsw_max_kHz=25, n_eval_points=2)
    assert m.fsw_points_kHz() == [4.0, 25.0]
    with pytest.raises(ValueError):
        FswModulation(fsw_min_kHz=4, fsw_max_kHz=25, n_eval_points=51)


def test_fsw_modulation_edge_weighted_only_for_dither() -> None:
    uniform = FswModulation(fsw_min_kHz=4, fsw_max_kHz=25)
    dither = FswModulation(
        fsw_min_kHz=4, fsw_max_kHz=25, profile="triangular_dither",
    )
    assert not uniform.is_edge_weighted()
    assert dither.is_edge_weighted()


def test_rpm_to_fsw_returns_zero_for_zero_inputs() -> None:
    assert rpm_to_fsw(0, 2) == 0.0
    assert rpm_to_fsw(1500, 0) == 0.0


def test_from_rpm_band_derives_fsw_from_rpm() -> None:
    """Reasonable compressor band: 1500–4500 RPM at 2 pole pairs
    → 10–30 kHz fsw using the bundled K_CARRIER_RATIO=200."""
    m = from_rpm_band(rpm_min=1500, rpm_max=4500, pole_pairs=2)
    assert m.fsw_min_kHz == pytest.approx(10.0)
    assert m.fsw_max_kHz == pytest.approx(30.0)
    assert m.profile == "rpm_band"
    assert m.rpm_min == 1500
    assert m.pole_pairs == 2


def test_from_rpm_band_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        from_rpm_band(rpm_min=0, rpm_max=4500, pole_pairs=2)
    with pytest.raises(ValueError):
        from_rpm_band(rpm_min=4500, rpm_max=1500, pole_pairs=2)
    with pytest.raises(ValueError):
        from_rpm_band(rpm_min=1500, rpm_max=4500, pole_pairs=0)


# ---------------------------------------------------------------------------
# Spec round-trip — backward-compat + new feature
# ---------------------------------------------------------------------------
def test_legacy_spec_roundtrips_unchanged() -> None:
    """A spec without ``fsw_modulation`` round-trips identically
    through JSON — every existing `.pfc` file keeps working."""
    spec = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=65, ripple_pct=20, T_amb_C=40,
    )
    rt = Spec.model_validate_json(spec.model_dump_json())
    assert rt.fsw_modulation is None
    # Whole-spec equality (Pydantic v2 model equality is field-wise).
    assert rt == spec


def test_spec_with_modulation_roundtrips() -> None:
    """A new-feature spec preserves every field of the band."""
    band = FswModulation(
        fsw_min_kHz=4, fsw_max_kHz=25,
        profile="triangular_dither", n_eval_points=7,
    )
    spec = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=10, ripple_pct=20, T_amb_C=40,
        fsw_modulation=band,
    )
    rt = Spec.model_validate_json(spec.model_dump_json())
    assert rt.fsw_modulation is not None
    assert rt.fsw_modulation.fsw_min_kHz == 4.0
    assert rt.fsw_modulation.fsw_max_kHz == 25.0
    assert rt.fsw_modulation.profile == "triangular_dither"
    assert rt.fsw_modulation.n_eval_points == 7


# ---------------------------------------------------------------------------
# BandedDesignResult aggregation
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def reference_inputs():
    """Feasible 600 W boost-PFC — bundled C058777A2 toroid +
    Magnetics 60 µ HighFlux + AWG14."""
    ensure_user_data()
    mats = load_materials()
    cores = load_cores()
    wires = load_wires()
    spec = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=10, ripple_pct=20, T_amb_C=40,
    )
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores
                if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    return spec, core, wire, mat


def test_eval_band_runs_engine_per_point(reference_inputs) -> None:
    """End-to-end: a 5-point band against a feasible reference
    design produces a fully-populated ``BandedDesignResult`` with
    no engine failures."""
    spec, core, wire, mat = reference_inputs
    spec = spec.model_copy(update={
        "fsw_modulation": FswModulation(
            fsw_min_kHz=4, fsw_max_kHz=25, n_eval_points=5,
        ),
    })
    banded = eval_band(spec, core, wire, mat)
    assert isinstance(banded, BandedDesignResult)
    assert banded.fsw_count == 5
    assert banded.all_succeeded
    assert banded.flagged_points == ()
    # Worst-per-metric covers the four standard metrics.
    for metric in ("T_winding_C", "B_pk_T", "P_total_W", "T_rise_C"):
        assert metric in banded.worst_per_metric


def test_eval_band_low_fsw_is_thermal_worst_case(
    reference_inputs,
) -> None:
    """Engineering anchor: in a boost-PFC, low fsw drives core
    loss (longer volt-second integration per cycle) and so
    typically wins the thermal worst case. The test asserts
    the property — flexibly to "≤ band midpoint" — to survive
    minor engine recalibrations without breaking."""
    spec, core, wire, mat = reference_inputs
    spec = spec.model_copy(update={
        "fsw_modulation": FswModulation(
            fsw_min_kHz=4, fsw_max_kHz=25, n_eval_points=5,
        ),
    })
    banded = eval_band(spec, core, wire, mat)
    worst = banded.worst_per_metric.get("T_winding_C")
    assert worst is not None
    midband = (4 + 25) / 2
    assert worst.fsw_kHz <= midband, (
        f"thermal worst case at fsw={worst.fsw_kHz} kHz, "
        f"expected ≤ {midband} kHz"
    )


def test_design_or_band_routes_legacy_specs_through_design(
    reference_inputs,
) -> None:
    """Spec without ``fsw_modulation`` short-circuits to the
    plain single-point ``DesignResult`` — backward-compat for
    callers that haven't migrated to the banded shape."""
    from pfc_inductor.models.result import DesignResult

    spec, core, wire, mat = reference_inputs
    result = design_or_band(spec, core, wire, mat)
    assert isinstance(result, DesignResult)


def test_design_or_band_routes_banded_specs_through_eval_band(
    reference_inputs,
) -> None:
    spec, core, wire, mat = reference_inputs
    spec = spec.model_copy(update={
        "fsw_modulation": FswModulation(
            fsw_min_kHz=4, fsw_max_kHz=25, n_eval_points=3,
        ),
    })
    result = design_or_band(spec, core, wire, mat)
    assert isinstance(result, BandedDesignResult)
    assert result.fsw_count == 3


# ---------------------------------------------------------------------------
# Aggregation logic — synthetic inputs
# ---------------------------------------------------------------------------
def test_aggregate_band_picks_worst_per_metric(reference_inputs) -> None:
    """Hand-built band with 3 points where each metric is worst
    at a different point — the aggregator must bucket them
    correctly without conflating into one "worst point"."""
    spec, core, wire, mat = reference_inputs
    from pfc_inductor.design import design as run_design
    # Build three independent results by eval-ing at different fsw.
    points: list[BandPoint] = []
    for fsw in (5.0, 12.0, 25.0):
        s = spec.model_copy(update={"f_sw_kHz": fsw})
        points.append(BandPoint(
            fsw_kHz=fsw, result=run_design(s, core, wire, mat),
        ))
    banded = aggregate_band(spec, points)
    assert banded.fsw_count == 3
    # Centre point should be the nominal.
    assert banded.nominal is not None
    # Every worst-per-metric pick is one of the three input fsw values.
    fsw_vals = {p.fsw_kHz for p in points}
    for metric, bp in banded.worst_per_metric.items():
        assert bp.fsw_kHz in fsw_vals, (
            f"worst[{metric}] picked fsw={bp.fsw_kHz} not in {fsw_vals}"
        )


def test_aggregate_band_handles_engine_failures(
    reference_inputs,
) -> None:
    """A band with one failed point still aggregates, and the
    failure shows up in ``flagged_points`` not in
    ``worst_per_metric``."""
    spec, core, wire, mat = reference_inputs
    from pfc_inductor.design import design as run_design
    good = run_design(
        spec.model_copy(update={"f_sw_kHz": 10}), core, wire, mat,
    )
    points = [
        BandPoint(fsw_kHz=4.0, result=None,
                  failure_reason="synthetic"),
        BandPoint(fsw_kHz=10.0, result=good),
        BandPoint(fsw_kHz=25.0, result=good),
    ]
    banded = aggregate_band(spec, points)
    assert len(banded.flagged_points) == 1
    assert banded.flagged_points[0].fsw_kHz == 4.0
    # Worst-per-metric never returns a failed point.
    for bp in banded.worst_per_metric.values():
        assert bp.result is not None


def test_unwrap_for_kpi_returns_design_result_in_both_shapes(
    reference_inputs,
) -> None:
    spec, core, wire, mat = reference_inputs
    from pfc_inductor.design import design as run_design
    from pfc_inductor.models.result import DesignResult

    plain = run_design(spec, core, wire, mat)
    assert isinstance(unwrap_for_kpi(plain), DesignResult)

    spec_b = spec.model_copy(update={
        "fsw_modulation": FswModulation(
            fsw_min_kHz=4, fsw_max_kHz=25, n_eval_points=3,
        ),
    })
    banded = eval_band(spec_b, core, wire, mat)
    unwrapped = unwrap_for_kpi(banded)
    assert isinstance(unwrapped, DesignResult)


def test_aggregate_band_edge_weighted_picks_extremes(
    reference_inputs,
) -> None:
    """When the dither profile is active, the worst-case search
    is restricted to the band edges — even if a centre point's
    metric is technically higher, only the extremes count."""
    spec, core, wire, mat = reference_inputs
    from pfc_inductor.design import design as run_design

    edge_low = run_design(
        spec.model_copy(update={"f_sw_kHz": 4.0}), core, wire, mat,
    )
    edge_high = run_design(
        spec.model_copy(update={"f_sw_kHz": 25.0}), core, wire, mat,
    )
    centre = run_design(
        spec.model_copy(update={"f_sw_kHz": 14.0}), core, wire, mat,
    )
    points = [
        BandPoint(fsw_kHz=4.0,  result=edge_low),
        BandPoint(fsw_kHz=14.0, result=centre),
        BandPoint(fsw_kHz=25.0, result=edge_high),
    ]
    banded = aggregate_band(spec, points, edge_weighted=True)
    # Worst-per-metric entries must be drawn from the two edges
    # only — the centre point is excluded.
    for bp in banded.worst_per_metric.values():
        assert bp.fsw_kHz in (4.0, 25.0), (
            f"edge-weighted aggregator picked centre fsw={bp.fsw_kHz}"
        )
