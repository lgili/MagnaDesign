"""Step-2 RK4 PWM-resolved transient simulator tests.

These regressions cover the ODE driver as a complement to Step 1
(`simulate_to_steady_state`). They compare the two simulators
against each other in CCM steady state, exercise the diode clamp
in DCM, and confirm the topology guard / DCM behaviour the
docstring promises.
"""

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
    simulate_transient,
)
from pfc_inductor.topology.boost_ccm_model import BoostCCMModel
from pfc_inductor.topology.passive_choke_model import PassiveChokeModel


@pytest.fixture(scope="module")
def db():
    return {
        "materials": load_materials(),
        "cores": load_cores(),
    }


def _ref_inductor(db, *, N: int = 45) -> NonlinearInductor:
    material = find_material(db["materials"], "magnetics-60_highflux")
    core = next(
        c
        for c in db["cores"]
        if c.default_material_id == material.id and 40_000 < c.Ve_mm3 < 100_000
    )
    return NonlinearInductor(core=core, material=material, N=N)


def _spec_at_pout(Pout_W: float = 800.0) -> Spec:
    return Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=220.0,
        Vout_V=400.0,
        Pout_W=Pout_W,
        eta=0.97,
        f_sw_kHz=65.0,
        ripple_pct=30.0,
        T_amb_C=40.0,
        T_max_C=100.0,
        Ku_max=0.40,
        Bsat_margin=0.20,
    )


# ─── Topology guard ────────────────────────────────────────────────


def test_simulate_transient_passive_topologies_delegate_to_step1(db):
    """Phase B Step 3: passive topologies use the imposed-trajectory
    answer (Step 1) — `simulate_transient` for them returns a
    `Waveform` shaped exactly like `simulate_to_steady_state`'s
    output, with no PWM ripple of its own to add."""
    spec = _spec_at_pout(Pout_W=400.0).model_copy(
        update={"topology": "passive_choke"},
    )
    model = PassiveChokeModel(spec)
    inductor = _ref_inductor(db)

    wf_step1 = simulate_to_steady_state(model, inductor)
    wf_step2 = simulate_transient(model, inductor)

    assert wf_step1.i_pk_A == pytest.approx(wf_step2.i_pk_A, rel=1e-9)
    assert wf_step1.B_pk_T == pytest.approx(wf_step2.B_pk_T, rel=1e-9)
    assert wf_step1.t_s.shape == wf_step2.t_s.shape


# ─── CCM steady-state agreement with Step 1 ───────────────────────


def test_step2_agrees_with_step1_on_ccm_peak(db):
    """In CCM steady state, Step 2's mean trailing-cycle peak must
    agree with Step 1's analytical peak.

    The non-integer ratio f_sw / f_line creates a slow beat in the
    PWM-resolved trajectory: some line cycles peak a few percent
    higher than the mean and others a bit lower. Comparing the
    *mean* of the trailing window against Step 1 averages out the
    beat; comparing the worst cycle would be flaky.
    """
    spec = _spec_at_pout(Pout_W=800.0)
    model = BoostCCMModel(spec)
    inductor = _ref_inductor(db, N=45)

    wf_step1 = simulate_to_steady_state(model, inductor)
    wf_step2 = simulate_transient(model, inductor, n_line_cycles=8)

    # Mean of the trailing 4 cycles — robust to the f_sw/f_line beat.
    trailing = wf_step2.cycle_stats.i_pk_per_cycle_A[-4:]
    mean_pk = float(np.mean(trailing))
    rel_err_i = abs(mean_pk - wf_step1.i_pk_A) / wf_step1.i_pk_A
    assert rel_err_i < 0.15, f"Step 2 / Step 1 mean i_pk disagreement {100 * rel_err_i:.1f}% > 15 %"


def test_step2_returns_well_formed_waveform(db):
    """Sanity: Step 2's waveform shape matches the Step 1 contract
    (`Waveform` with `cycle_stats`, `last_cycle`, peak metrics)."""
    spec = _spec_at_pout()
    model = BoostCCMModel(spec)
    inductor = _ref_inductor(db)
    wf = simulate_transient(model, inductor, n_line_cycles=3)

    assert wf.t_s.size > 0
    assert wf.i_L_A.shape == wf.t_s.shape
    assert wf.B_T.shape == wf.t_s.shape
    assert wf.i_pk_A > 0
    assert wf.cycle_stats.i_pk_per_cycle_A.size == 3
    assert wf.cycle_stats.B_pk_per_cycle_T.size == 3
    # Last-cycle slice must contain ~one line period.
    last = wf.last_cycle()
    assert last.duration_s == pytest.approx(1.0 / spec.f_line_Hz, rel=0.05)


# ─── Diode clamp / DCM behaviour ──────────────────────────────────


def test_step2_diode_clamp_prevents_negative_current(db):
    """Force DCM with a deeply under-loaded spec (Pout 5 W on a
    big inductor at 65 kHz). The current must never go below zero
    even though, with no clamp, the OFF phase would drive it
    negative."""
    spec = _spec_at_pout(Pout_W=5.0)
    model = BoostCCMModel(spec)
    inductor = _ref_inductor(db, N=45)

    wf = simulate_transient(model, inductor, n_line_cycles=2)

    assert (wf.i_L_A >= -1e-12).all(), f"diode clamp violated: min i_L = {wf.i_L_A.min():.3e}"


def test_step2_diode_clamp_engages_on_high_Kp(db):
    """An aggressive controller that overshoots can drive the
    plant equation into the regime where the natural OFF-phase
    di/dt would push current negative. The diode clamp must keep
    `i_L >= 0` over the entire trace.

    A proper DCM-aware regression (controller naturally enters
    DCM at light load) is deferred to Phase B Step 3 alongside a
    DCM-aware feedforward — the current controller's pure CCM
    feedforward fights the natural pulsed current shape, masking
    DCM in the simulation result.
    """
    spec = _spec_at_pout(Pout_W=800.0)
    model = BoostCCMModel(spec)
    inductor = _ref_inductor(db, N=45)
    # Very high Kp to provoke aggressive duty modulation that, sans
    # the clamp, would drive the integrator into negative current.
    wf = simulate_transient(model, inductor, Kp=2.0, n_line_cycles=2)
    assert (wf.i_L_A >= 0.0).all(), f"diode clamp violated: min i_L = {wf.i_L_A.min():.6e}"


# ─── Auto-tuned Kp ────────────────────────────────────────────────


def test_step2_default_Kp_produces_stable_result(db):
    """Auto-tuned Kp should always produce a finite, monotone-bounded
    waveform — no NaN, no runaway. A bad Kp would explode within a
    cycle or two."""
    spec = _spec_at_pout()
    model = BoostCCMModel(spec)
    inductor = _ref_inductor(db)
    wf = simulate_transient(model, inductor, n_line_cycles=4)
    assert np.isfinite(wf.i_L_A).all()
    assert wf.i_pk_A < 100.0  # generous; far below any runaway scale


def test_step2_explicit_Kp_overrides_auto_tune(db):
    """Passing `Kp=` overrides the auto-tune; verify the override
    actually reaches the controller by comparing two very different
    gains and confirming the output differs."""
    spec = _spec_at_pout()
    model = BoostCCMModel(spec)
    inductor = _ref_inductor(db)
    wf_low = simulate_transient(model, inductor, Kp=1e-4, n_line_cycles=2)
    wf_high = simulate_transient(model, inductor, Kp=0.1, n_line_cycles=2)
    # With Kp two orders of magnitude apart the trajectories must
    # differ visibly. Compare peaks.
    assert wf_low.i_pk_A != pytest.approx(wf_high.i_pk_A, rel=1e-3)


# ─── SimulationConfig knobs apply ─────────────────────────────────


def test_step2_honours_steps_per_switching_period(db):
    """Bumping `steps_per_switching_period` increases the trace length."""
    spec = _spec_at_pout()
    model = BoostCCMModel(spec)
    inductor = _ref_inductor(db)
    cfg_low = SimulationConfig(steps_per_switching_period=10)
    cfg_high = SimulationConfig(steps_per_switching_period=40)
    wf_low = simulate_transient(model, inductor, config=cfg_low, n_line_cycles=1)
    wf_high = simulate_transient(model, inductor, config=cfg_high, n_line_cycles=1)
    assert wf_high.n_samples > wf_low.n_samples
