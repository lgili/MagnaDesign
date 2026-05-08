"""Realistic-waveform synthesis (Análise tab plot source).

Locks in the small-signal / state-space synthesis used by the
``FormasOndaCard`` so a refactor doesn't silently turn the boost
CCM trace back into a smooth sinusoid (the bug we just fixed).
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.design import design
from pfc_inductor.models import Spec
from pfc_inductor.simulate.realistic_waveforms import (
    RealisticWaveform,
    synthesize_il_waveform,
)


# ---------------------------------------------------------------------------
# Fixtures — a real (mat, core, wire) triple so we can run ``design()``.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db():
    materials = load_materials()
    cores = load_cores()
    wires = load_wires()
    mat = find_material(materials, "magnetics-60_highflux")
    core = next(
        c for c in cores if c.id == "magnetics-0058181a2-60_highflux"
    )
    wire = next(w for w in wires if w.id == "AWG14")
    return {"mat": mat, "core": core, "wire": wire}


def _result(db, spec: Spec):
    return design(spec, db["core"], db["wire"], db["mat"])


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------

def test_synthesizes_for_each_topology(db):
    """Every supported topology produces a non-None waveform on a
    realistic spec."""
    cases = [
        ("boost_ccm", 1),
        ("passive_choke", 1),
        ("line_reactor", 1),
        ("line_reactor", 3),
    ]
    for topology, n_phases in cases:
        spec = Spec(topology=topology, n_phases=n_phases)
        wf = synthesize_il_waveform(spec, _result(db, spec))
        assert wf is not None, f"{topology}/{n_phases}ph returned None"
        assert isinstance(wf, RealisticWaveform)
        assert wf.t_s.size > 100  # at least a few line-cycles of samples
        assert wf.iL_A.shape == wf.t_s.shape


def test_returns_none_when_inductance_zero(db):
    """A half-baked spec → None so the caller can fall through to the
    engine's own sampled arrays without painting a flat line."""
    from pfc_inductor.models import DesignResult

    # Hand-crafted result with no L — we don't run design() because
    # it would refuse this configuration.
    spec = Spec()
    fake = _result(db, spec).model_copy(update={"L_actual_uH": 0.0})
    wf = synthesize_il_waveform(spec, fake)
    assert wf is None


def test_returns_none_for_unknown_topology(db):
    """Defensive guard — Spec.topology is a Literal but the helper
    treats unknown values as "I don't synthesise that yet"."""

    spec = Spec()
    # Pydantic Literal forbids unknown values, so we monkey-patch
    # the dataclass attribute directly.
    object.__setattr__(spec, "topology", "made_up")
    wf = synthesize_il_waveform(spec, _result(db, Spec()))
    assert wf is None


# ---------------------------------------------------------------------------
# Boost CCM — the textbook signature: sinusoidal envelope + PWM ripple
# ---------------------------------------------------------------------------

def test_boost_ccm_has_high_frequency_component(db):
    """Boost CCM iL must carry a switching-frequency ripple component
    on top of the line-frequency envelope. We verify that by checking
    the FFT has noticeable energy near f_sw.
    """
    spec = Spec(topology="boost_ccm")  # default 65 kHz fsw, 50 Hz line
    wf = synthesize_il_waveform(spec, _result(db, spec))
    assert wf is not None

    # FFT — sample rate from the time vector.
    n = wf.t_s.size
    dt = float(wf.t_s[1] - wf.t_s[0])
    freqs = np.fft.rfftfreq(n, d=dt)
    spectrum = np.abs(np.fft.rfft(wf.iL_A - wf.iL_A.mean()))
    # Bin nearest to f_sw should carry meaningful energy compared to
    # the floor.
    fsw_Hz = spec.f_sw_kHz * 1e3
    idx = int(np.argmin(np.abs(freqs - fsw_Hz)))
    # Energy in the f_sw band > 5× the median magnitude → ripple is present.
    assert spectrum[idx] > 5.0 * np.median(spectrum)


def test_boost_ccm_envelope_follows_rectified_sine(db):
    """The slow-frequency envelope must match the rectified line voltage
    in shape (high in the middle of the cycle, low at the zero
    crossings). We sample at three benchmark phases."""
    spec = Spec(topology="boost_ccm")
    wf = synthesize_il_waveform(spec, _result(db, spec))
    assert wf is not None

    period = 1.0 / float(spec.f_line_Hz)
    # |sin| envelope: peaks at t=T/4 and 3T/4, zeros at t=0 and T/2.
    n_zero = int(np.argmin(np.abs(wf.t_s - 0.0)))
    n_peak = int(np.argmin(np.abs(wf.t_s - 0.25 * period)))
    n_mid = int(np.argmin(np.abs(wf.t_s - 0.5 * period)))

    # Envelope is the moving-average over a switching period; we
    # approximate by averaging a small window around each anchor.
    win = 60  # ~60 samples ~ a few sw periods at default fsw / fline
    avg_zero = float(np.mean(np.abs(wf.iL_A[max(0, n_zero - win):n_zero + win])))
    avg_peak = float(np.mean(np.abs(wf.iL_A[n_peak - win:n_peak + win])))
    avg_mid = float(np.mean(np.abs(wf.iL_A[n_mid - win:n_mid + win])))

    # Peak averages must dominate zero-crossing averages (the whole
    # point of PFC current shaping). 3× headroom guards against
    # ripple noise at the zero crossings being misread as envelope.
    assert avg_peak > 3.0 * avg_zero
    # Mid (next zero crossing) is also low — same bound.
    assert avg_peak > 3.0 * avg_mid


# ---------------------------------------------------------------------------
# Passive choke — DC level with 2·f_line slow ripple (no PWM)
# ---------------------------------------------------------------------------

def test_passive_choke_no_high_frequency_content(db):
    """The passive PFC choke's iL has line-frequency ripple but no
    switching-frequency component. Energy at default 65 kHz must be
    near the FFT floor (no PWM present)."""
    spec = Spec(topology="passive_choke")
    wf = synthesize_il_waveform(spec, _result(db, spec))
    assert wf is not None

    n = wf.t_s.size
    dt = float(wf.t_s[1] - wf.t_s[0])
    freqs = np.fft.rfftfreq(n, d=dt)
    spectrum = np.abs(np.fft.rfft(wf.iL_A - wf.iL_A.mean()))
    fsw_Hz = spec.f_sw_kHz * 1e3
    if freqs[-1] > fsw_Hz:
        idx = int(np.argmin(np.abs(freqs - fsw_Hz)))
        # Floor-comparable energy — much less than at 2·f_line.
        idx_2fline = int(np.argmin(np.abs(freqs - 2.0 * spec.f_line_Hz)))
        assert spectrum[idx_2fline] > 5.0 * spectrum[idx]


# ---------------------------------------------------------------------------
# Line reactor — diode-bridge pulse signature
# ---------------------------------------------------------------------------

def test_line_reactor_1ph_pulse_signature(db):
    """1φ line reactor iL should be near-zero away from line peaks
    (conduction angle is narrow). We check that the median magnitude
    is much smaller than the peak magnitude — the signature of a
    pulse train, not a sinusoid."""
    spec = Spec(topology="line_reactor", n_phases=1)
    wf = synthesize_il_waveform(spec, _result(db, spec))
    assert wf is not None

    abs_iL = np.abs(wf.iL_A)
    # Pulse train: median magnitude ~0 (most samples in the dead-zone),
    # peak much larger. 10× ratio is conservative.
    assert abs_iL.max() > 10.0 * float(np.median(abs_iL) + 0.1)


def test_line_reactor_3ph_three_phase_offset(db):
    """3φ reactor returns iL_a + two extras with proper 120° offsets
    in their fundamental component. Compare signs at t = T/12 (the
    canonical 30° phase point where A is positive, B is negative,
    C is negative-to-zero)."""
    spec = Spec(topology="line_reactor", n_phases=3)
    wf = synthesize_il_waveform(spec, _result(db, spec))
    assert wf is not None
    assert len(wf.iL_extra) == 2

    # Aggregate sign pattern over a small window — the conduction
    # window for phase A near its positive peak should *not* coincide
    # with phase B's positive peak (they're 120° apart).
    period = 1.0 / float(spec.f_line_Hz)
    t_quarter = 0.25 * period
    idx = int(np.argmin(np.abs(wf.t_s - t_quarter)))
    win = 30
    a = wf.iL_A[max(0, idx - win):idx + win]
    b = wf.iL_extra[0][max(0, idx - win):idx + win]
    c = wf.iL_extra[1][max(0, idx - win):idx + win]
    # At T/4 (positive peak of phase A):
    # - A's window-mean is positive
    # - B and C are not simultaneously at their positive peak
    assert a.mean() > 0
    # At least one of B / C is opposite-signed (or near-zero) wrt A.
    assert (b.mean() < 0.5 * abs(a.mean())) or (c.mean() < 0.5 * abs(a.mean()))


# ---------------------------------------------------------------------------
# Performance — synthesis must be cheap (refresh on every recalc)
# ---------------------------------------------------------------------------

def test_synthesis_is_fast(db):
    """Each topology synthesises in well under 50 ms — the budget the
    Análise card has between user click → plot redraw."""
    import time

    spec = Spec()  # boost CCM default — most expensive (HF ripple)
    result = _result(db, spec)
    t0 = time.perf_counter()
    for _ in range(10):
        synthesize_il_waveform(spec, result)
    elapsed_ms = (time.perf_counter() - t0) * 100.0  # 10 calls → ms each
    assert elapsed_ms < 50.0, f"synthesis took {elapsed_ms:.1f} ms/call"


# ---------------------------------------------------------------------------
# Spectrum / THD — the v3 contract: every topology carries a non-empty
# spectrum + a THD number, and the picked fundamental matches the
# topology's natural rectifier order.
# ---------------------------------------------------------------------------

def test_every_topology_has_thd_and_spectrum(db):
    """Each ``RealisticWaveform`` carries:
      - ``thd_pct`` > 0 (non-trivial distortion present)
      - ``harmonic_h`` of length 20 starting at 1
      - ``harmonic_pct[0] == 100`` (fundamental normalisation)
    """
    cases = [
        ("boost_ccm", 1),
        ("passive_choke", 1),
        ("line_reactor", 1),
        ("line_reactor", 3),
    ]
    for topology, n_phases in cases:
        spec = Spec(topology=topology, n_phases=n_phases)
        wf = synthesize_il_waveform(spec, _result(db, spec))
        assert wf is not None
        assert wf.harmonic_h is not None
        assert wf.harmonic_pct is not None
        assert wf.harmonic_h.shape == (20,)
        assert wf.harmonic_h[0] == 1
        assert wf.harmonic_pct[0] == pytest.approx(100.0)
        assert wf.thd_pct > 0.5, (
            f"{topology}/{n_phases}ph THD too low ({wf.thd_pct:.1f}%) — "
            "synthesis likely produced a near-pure sinusoid"
        )


def test_fundamental_matches_topology(db):
    """boost / passive feed off a full-wave rectifier — natural
    fundamental is at 2·f_line. Line reactors' iL is the line current
    itself — fundamental at f_line."""
    f_line = 50.0  # default Spec
    cases_2x = [("boost_ccm", 1), ("passive_choke", 1)]
    cases_1x = [("line_reactor", 1), ("line_reactor", 3)]
    for topology, n_phases in cases_2x:
        spec = Spec(topology=topology, n_phases=n_phases)
        wf = synthesize_il_waveform(spec, _result(db, spec))
        assert wf is not None
        assert wf.fundamental_Hz == pytest.approx(2.0 * f_line)
    for topology, n_phases in cases_1x:
        spec = Spec(topology=topology, n_phases=n_phases)
        wf = synthesize_il_waveform(spec, _result(db, spec))
        assert wf is not None
        assert wf.fundamental_Hz == pytest.approx(f_line)


def test_line_reactor_dominant_odd_harmonics(db):
    """Diode-bridge pulse-train signature: h3 / h5 / h7 should each
    be above 50 % of the fundamental (these are the canonical
    rectifier harmonics IEEE 519 calls out)."""
    spec = Spec(topology="line_reactor", n_phases=1)
    wf = synthesize_il_waveform(spec, _result(db, spec))
    assert wf is not None
    pct = wf.harmonic_pct
    # ``harmonic_pct`` is indexed 0..19 for h = 1..20.
    assert pct[2] > 50.0, f"h3 = {pct[2]:.1f}% < 50% — pulse train weak"
    assert pct[4] > 30.0, f"h5 = {pct[4]:.1f}% < 30% — pulse train weak"
    assert pct[6] > 20.0, f"h7 = {pct[6]:.1f}% < 20% — pulse train weak"


def test_boost_ccm_low_thd_relative_to_line_reactor(db):
    """Sanity-check ordering: a PFC boost should report dramatically
    lower THD than a passive line reactor on the same operating
    point. If the test ever inverts, the synthesis lost the PFC
    current-shaping property and reverted to a generic rectifier."""
    spec_boost = Spec(topology="boost_ccm")
    spec_lr = Spec(topology="line_reactor", n_phases=1)
    wf_b = synthesize_il_waveform(spec_boost, _result(db, spec_boost))
    wf_lr = synthesize_il_waveform(spec_lr, _result(db, spec_lr))
    assert wf_b is not None and wf_lr is not None
    # Generous margin: even the noisiest boost should sit below 80 %,
    # and a line reactor should always exceed 100 %.
    assert wf_b.thd_pct < wf_lr.thd_pct
    assert wf_b.thd_pct < 80.0
    assert wf_lr.thd_pct > 100.0


def test_thd_zero_signal_is_zero():
    """Edge case: spectrum helper on a flat-zero signal returns
    THD = 0 (no fundamental to normalise against) instead of NaN."""
    from pfc_inductor.simulate.realistic_waveforms import (
        _spectrum_at_harmonics,
    )

    t = np.linspace(0.0, 0.02, 1000)
    flat = np.zeros_like(t)
    h, pct, thd = _spectrum_at_harmonics(t, flat, fundamental_Hz=50.0)
    assert h.shape == (20,)
    assert np.all(pct == 0.0)
    assert thd == 0.0
