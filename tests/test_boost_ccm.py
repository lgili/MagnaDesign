"""Boost PFC CCM topology calculations."""
import math
import pytest

from pfc_inductor.models import Spec
from pfc_inductor.topology import boost_ccm


@pytest.fixture
def spec_800W():
    return Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
        Vout_V=400.0, Pout_W=800.0, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
    )


def test_peak_current_at_low_line(spec_800W):
    """At low line (worst case): I_pk = sqrt(2)*P/(eta*V) = sqrt(2)*800/(0.97*85) = 13.72 A."""
    I_pk = boost_ccm.line_peak_current_A(spec_800W, 85.0)
    assert abs(I_pk - 13.72) < 0.05


def test_required_inductance_drops_with_higher_fsw(spec_800W):
    L_low = boost_ccm.required_inductance_uH(spec_800W, 85.0)
    spec_800W.f_sw_kHz = 130.0
    L_high = boost_ccm.required_inductance_uH(spec_800W, 85.0)
    assert L_high < L_low / 1.9, "Doubling fsw should roughly halve required L"


def test_required_inductance_formula(spec_800W):
    """L_min = Vout / (4 * fsw * I_pk * ripple_fraction)."""
    L_uH = boost_ccm.required_inductance_uH(spec_800W, 85.0)
    fsw_Hz = spec_800W.f_sw_kHz * 1000.0
    I_pk = boost_ccm.line_peak_current_A(spec_800W, 85.0)
    expected_H = spec_800W.Vout_V / (4 * fsw_Hz * I_pk * (spec_800W.ripple_pct / 100.0))
    assert abs(L_uH * 1e-6 - expected_H) / expected_H < 1e-6


def test_waveforms_have_expected_shape(spec_800W):
    L_uH = boost_ccm.required_inductance_uH(spec_800W, 85.0)
    wf = boost_ccm.waveforms(spec_800W, 85.0, L_uH, n_points_per_half_cycle=200)
    assert wf["t_s"][0] == 0.0
    # Half period at 50 Hz = 10 ms
    assert abs(wf["t_s"][-1] - 0.01) < 1e-3
    # iL_avg should be |sin| envelope: peaks near middle
    iL_avg = wf["iL_avg_A"]
    mid = len(iL_avg) // 2
    assert iL_avg[mid] > iL_avg[0] * 100  # peak much greater than zero crossing


def test_max_ripple_at_half_vout():
    """Max delta_iL at vin_inst = Vout/2 (where d(1-d) is maximized)."""
    spec = Spec(
        Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=200.0,
        Vout_V=400.0, Pout_W=800.0, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
    )
    L_uH = 400.0
    wf = boost_ccm.waveforms(spec, 200.0, L_uH, n_points_per_half_cycle=400)
    delta = wf["delta_iL_pp_A"]
    vin = wf["vin_inst_V"]
    idx_max = int(delta.argmax())
    # At argmax, vin_inst should be near Vout/2 = 200V
    assert abs(vin[idx_max] - 200.0) < 30.0
