"""Regression tests for the LoadModulation band sweep.

Mirrors :mod:`tests.test_spec_modulation_roundtrip` for the fsw
band but covers the load-power band path: model validation,
engine wrapper, mutual-exclusion validator, and chart-axis
generalisation.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ────────────────────────────────────────────────────────────────────
# 1. LoadModulation model — bounds + helpers
# ────────────────────────────────────────────────────────────────────


def test_load_modulation_uniform_5_points():
    from pfc_inductor.models import LoadModulation

    mod = LoadModulation(
        pout_min_W=100.0,
        pout_max_W=500.0,
        profile="uniform",
        n_eval_points=5,
    )
    pts = mod.pout_points_W()
    assert len(pts) == 5
    assert pts[0] == 100.0
    assert pts[-1] == 500.0
    # Evenly spaced
    assert pts == [100.0, 200.0, 300.0, 400.0, 500.0]


def test_load_modulation_invalid_band_rejected():
    from pfc_inductor.models import LoadModulation

    with pytest.raises(ValueError, match="must exceed"):
        LoadModulation(pout_min_W=500.0, pout_max_W=100.0)


def test_compressor_swing_requires_nominal():
    from pfc_inductor.models import LoadModulation

    with pytest.raises(ValueError, match="pout_nominal_W"):
        LoadModulation(
            pout_min_W=300.0,
            pout_max_W=780.0,
            profile="compressor_swing",
            # Missing pout_nominal_W
        )


def test_from_compressor_swing_helper():
    from pfc_inductor.models import from_compressor_swing

    mod = from_compressor_swing(600.0, n_eval_points=5)
    assert mod.profile == "compressor_swing"
    assert mod.pout_min_W == 300.0   # 50 % of 600
    assert mod.pout_max_W == 780.0   # 130 % of 600
    assert mod.pout_nominal_W == 600.0


def test_load_modulation_triangular_dither_is_edge_weighted():
    from pfc_inductor.models import LoadModulation

    mod = LoadModulation(
        pout_min_W=100.0,
        pout_max_W=500.0,
        profile="triangular_dither",
    )
    assert mod.is_edge_weighted() is True

    uniform = LoadModulation(pout_min_W=100.0, pout_max_W=500.0)
    assert uniform.is_edge_weighted() is False


# ────────────────────────────────────────────────────────────────────
# 2. Spec mutual exclusion — fsw_modulation XOR load_modulation
# ────────────────────────────────────────────────────────────────────


def test_spec_rejects_both_modulations():
    from pfc_inductor.models import FswModulation, Spec, from_compressor_swing

    with pytest.raises(ValueError, match="mutually exclusive"):
        Spec(
            topology="boost_ccm",
            fsw_modulation=FswModulation(fsw_min_kHz=10.0, fsw_max_kHz=20.0),
            load_modulation=from_compressor_swing(600.0),
        )


def test_spec_accepts_fsw_only():
    from pfc_inductor.models import FswModulation, Spec

    spec = Spec(
        topology="boost_ccm",
        fsw_modulation=FswModulation(fsw_min_kHz=10.0, fsw_max_kHz=20.0),
    )
    assert spec.fsw_modulation is not None
    assert spec.load_modulation is None


def test_spec_accepts_load_only():
    from pfc_inductor.models import Spec, from_compressor_swing

    spec = Spec(
        topology="boost_ccm",
        load_modulation=from_compressor_swing(600.0),
    )
    assert spec.load_modulation is not None
    assert spec.fsw_modulation is None


def test_spec_accepts_neither():
    """The legacy single-point path stays the default."""
    from pfc_inductor.models import Spec

    spec = Spec(topology="boost_ccm")
    assert spec.fsw_modulation is None
    assert spec.load_modulation is None


# ────────────────────────────────────────────────────────────────────
# 3. eval_load_band end-to-end
# ────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def boost_load_band_setup():
    """Real catalog core + material for end-to-end engine call."""
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.models import Spec, from_compressor_swing

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    core = next(c for c in cores if c.id == "tdkepcos-pq-4040-n87")
    mat = next(m for m in mats if m.id == core.default_material_id)
    wire = next(w for w in wires if 1.5 < (getattr(w, "A_cu_mm2", 0) or 0) < 3.0)
    spec = Spec(
        topology="boost_ccm",
        Pout_W=600.0,
        load_modulation=from_compressor_swing(600.0, n_eval_points=5),
    )
    return spec, core, wire, mat


def test_eval_load_band_runs_all_points(boost_load_band_setup):
    from pfc_inductor.modulation import eval_load_band

    spec, core, wire, mat = boost_load_band_setup
    banded = eval_load_band(spec, core, wire, mat)

    assert banded.fsw_count == 5
    assert banded.all_succeeded, (
        f"Expected all 5 points to succeed; "
        f"got {len(banded.flagged_points)} failures"
    )


def test_eval_load_band_points_carry_pout_not_fsw(boost_load_band_setup):
    """``BandPoint.pout_W`` is populated, ``fsw_kHz`` is None."""
    from pfc_inductor.modulation import eval_load_band

    spec, core, wire, mat = boost_load_band_setup
    banded = eval_load_band(spec, core, wire, mat)

    for bp in banded.band:
        assert bp.pout_W is not None
        assert bp.fsw_kHz is None


def test_eval_load_band_raises_without_band(boost_load_band_setup):
    """Calling eval_load_band on a spec without the band raises."""
    from pfc_inductor.models import Spec
    from pfc_inductor.modulation import eval_load_band

    spec, core, wire, mat = boost_load_band_setup
    bare = Spec(topology="boost_ccm", Pout_W=600.0)  # no load_modulation
    with pytest.raises(ValueError, match="load_modulation"):
        eval_load_band(bare, core, wire, mat)


def test_design_or_band_dispatches_to_load_path(boost_load_band_setup):
    """``design_or_band`` picks ``eval_load_band`` when load is set."""
    from pfc_inductor.models.banded_result import BandedDesignResult
    from pfc_inductor.modulation import design_or_band

    spec, core, wire, mat = boost_load_band_setup
    result = design_or_band(spec, core, wire, mat)
    assert isinstance(result, BandedDesignResult)


# ────────────────────────────────────────────────────────────────────
# 4. BandPoint swept_value / axis_label helpers
# ────────────────────────────────────────────────────────────────────


def test_band_point_swept_value_fsw():
    from pfc_inductor.models.banded_result import BandPoint

    bp = BandPoint(fsw_kHz=12.5)
    assert bp.swept_value() == 12.5
    assert bp.swept_axis_label() == "fsw [kHz]"


def test_band_point_swept_value_pout():
    from pfc_inductor.models.banded_result import BandPoint

    bp = BandPoint(pout_W=540.0)
    assert bp.swept_value() == 540.0
    assert bp.swept_axis_label() == "Pout [W]"
