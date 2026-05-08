"""Integrator (imposed-trajectory) regression tests."""

from __future__ import annotations

import numpy as np
import pytest

from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
)
from pfc_inductor.models import Spec
from pfc_inductor.simulate import (
    NonlinearInductor,
    SimulationConfig,
    simulate_to_steady_state,
)
from pfc_inductor.topology.boost_ccm_model import BoostCCMModel


@pytest.fixture(scope="module")
def db():
    return {
        "materials": load_materials(),
        "cores": load_cores(),
    }


def _spec() -> Spec:
    return Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=220.0,
        Vout_V=400.0,
        Pout_W=800.0,
        eta=0.97,
        f_sw_kHz=65.0,
        ripple_pct=30.0,
        T_amb_C=40.0,
        T_max_C=100.0,
        Ku_max=0.40,
        Bsat_margin=0.20,
    )


def _ref_inductor(db, N: int = 45) -> NonlinearInductor:
    material = find_material(db["materials"], "magnetics-60_highflux")
    core = next(
        c
        for c in db["cores"]
        if c.default_material_id == material.id and 40_000 < c.Ve_mm3 < 100_000
    )
    return NonlinearInductor(core=core, material=material, N=N)


# ─── Waveform shape ─────────────────────────────────────────────


def test_waveform_spans_one_line_cycle(db):
    spec = _spec()
    model = BoostCCMModel(spec)
    inductor = _ref_inductor(db)
    wf = simulate_to_steady_state(model, inductor)

    expected_T = 1.0 / spec.f_line_Hz
    assert wf.duration_s == pytest.approx(expected_T, rel=1e-9)
    assert wf.cycle_stats.converged is True
    # Imposed-trajectory simulator runs a single cycle by construction.
    assert wf.n_line_cycles == 1


def test_waveform_is_rectified_sinusoid_envelope(db):
    """The line-frequency current is `I_pk · |sin(ω·t)|` modulo HF ripple."""
    spec = _spec()
    model = BoostCCMModel(spec)
    inductor = _ref_inductor(db)
    wf = simulate_to_steady_state(model, inductor)

    # Two zero crossings (start, end of half cycle, end of full cycle).
    # At those points the line envelope is zero; HF ripple may add a
    # small offset but the trough must still be near zero.
    i_at_zero = np.abs(wf.i_L_A[0])
    assert i_at_zero < 0.5, f"current at line zero crossing too high: {i_at_zero}"


def test_waveform_peak_exceeds_line_envelope_by_ripple(db):
    """HF ripple should add a few percent to the line-envelope peak."""
    spec = _spec()
    model = BoostCCMModel(spec)
    inductor = _ref_inductor(db)
    wf = simulate_to_steady_state(model, inductor)

    # Topology-supplied peak (no ripple).
    from pfc_inductor.optimize.feasibility import peak_current_A

    I_pk_line = peak_current_A(spec)
    assert wf.i_pk_A > I_pk_line, (
        f"Tier 2 must report a peak > line envelope ({I_pk_line:.2f}); got {wf.i_pk_A:.2f}",
    )
    # And not absurdly higher (e.g. 30% of I_pk default ripple).
    overage = (wf.i_pk_A - I_pk_line) / I_pk_line
    assert 0.0 < overage < 0.5


# ─── Non-linear L(i) actually applied ──────────────────────────


def test_simulator_uses_non_linear_inductance_at_each_sample(db):
    """B is computed with L(i_inst), not constant L."""
    spec = _spec()
    model = BoostCCMModel(spec)
    inductor = _ref_inductor(db)
    wf = simulate_to_steady_state(model, inductor)

    # Recompute B from the captured current using the same inductor —
    # the simulator's stored B must match.
    B_recomputed = inductor.B_T_array(wf.i_L_A)
    np.testing.assert_allclose(wf.B_T, B_recomputed, rtol=1e-12)


# ─── Convergence flag is honest ─────────────────────────────────


def test_cycle_stats_convergence_is_consistent_with_data(db):
    spec = _spec()
    model = BoostCCMModel(spec)
    inductor = _ref_inductor(db)
    wf = simulate_to_steady_state(model, inductor)

    cs = wf.cycle_stats
    # Imposed-trajectory always converges (no ODE error to diverge).
    assert cs.converged is True
    # Per-cycle peak data populated.
    assert cs.i_pk_per_cycle_A.size >= 1
    assert cs.i_pk_per_cycle_A[0] == pytest.approx(wf.i_pk_A, rel=1e-12)


# ─── Sample-rate config is honoured ─────────────────────────────


def test_config_samples_per_line_cycle_minimum_is_floor(db):
    spec = _spec()
    model = BoostCCMModel(spec)
    inductor = _ref_inductor(db)
    cfg = SimulationConfig(samples_per_line_cycle_minimum=400)
    wf = simulate_to_steady_state(model, inductor, config=cfg)
    assert wf.n_samples >= 400


# ─── last_cycle slice ──────────────────────────────────────────


def test_last_cycle_returns_just_one_period(db):
    spec = _spec()
    model = BoostCCMModel(spec)
    inductor = _ref_inductor(db)
    wf = simulate_to_steady_state(model, inductor)

    slice_ = wf.last_cycle()
    # The slice spans (slightly less than) one line period.
    assert slice_.duration_s <= 1.0 / spec.f_line_Hz + 1e-9
    # Peak metric is unchanged.
    assert slice_.i_pk_A == pytest.approx(wf.i_pk_A, rel=1e-9)
