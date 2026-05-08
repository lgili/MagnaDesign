"""Topology-aware analytical waveform synthesis for the Análise tab.

The original FormasOndaCard plotted whatever the engine happened to
sample (``DesignResult.waveform_iL_A``) plus an analytically-rendered
source-voltage trace. That worked at a "show me the peak number"
level but the user (Eng. de inversores) called it "muito fraco":
the iL trace had no PWM ripple for boost CCM, no commutation pulses
for line reactors, no diode-bridge signature for passive chokes.

This module synthesises iL(t) waveforms **directly from each
converter's textbook state-space / small-signal model** — no solver
needed, always converges, faithful to the equations a power-stage
engineer recognises by sight. Three motivations:

1. **Realism.** Each topology gets its physically meaningful iL(t)
   shape: PFC-shaped sinusoid with HF ripple for boost CCM,
   double-pulsed at line peaks for the AC line reactor, slow ripple
   on top of DC for the passive choke.

2. **Speed.** Plain numpy ufuncs over ~3 000 samples — well under
   1 ms per call. The Análise card can refresh every recalc without
   adding visible latency.

3. **No solver brittleness.** PulSim transient runs through
   diode-bridge configurations are notoriously hard (multiple diode
   states + sharp commutation transients), and the resulting
   convergence failures would show empty plots. Closed-form
   synthesis sidesteps that.

The synthesis is *not* a replacement for the engine — it's a
visualisation overlay. Numeric metrics (Irms / Ipk / B_pk / losses)
still come from ``DesignResult``. We just give the engineer a more
informative *picture*.

Public API
----------

``synthesize_il_waveform(spec, result, *, n_samples=2400)`` returns
a ``RealisticWaveform`` bundle: ``t_s`` (seconds), ``iL_A`` (amps),
plus a small descriptor (topology, label) the UI surfaces in the
plot legend. Returns ``None`` if the spec is half-configured (no
inductance, no rated current, etc.) so the caller can fall back to
the engine's sampled arrays.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from pfc_inductor.models import DesignResult, Spec


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RealisticWaveform:
    """Bundle of synthesised waveforms for one topology.

    All arrays share the same time axis ``t_s``. ``iL_A`` is the
    headline trace (the inductor designer's diagnostic). When a
    topology has multiple natural traces (e.g. 3-phase reactors
    with three phase currents), ``iL_extra`` contains the additional
    arrays in display order.

    ``label`` is a short, human-readable description of the synthesis
    method — the FormasOndaCard surfaces it as a one-liner so the
    engineer knows whether they're looking at PFC-shaped current
    + ripple, a rectifier pulse train, etc.

    Spectrum / THD fields
    ---------------------
    Filled at construction by :func:`_attach_spectrum`. Two reasons:

    1. The Análise card needs THD for **every** topology, not just
       line_reactor — ``DesignResult.thd_estimate_pct`` is only
       populated by the line-reactor engine path, leaving the THD
       tile blank for boost / passive.
    2. The bottom subplot of FormasOndaCard (was a perpetually-empty
       B(t) axis because the engine doesn't sample ``waveform_B_T``)
       gets repurposed as a harmonic-spectrum bar chart that reads
       the same data the THD number is computed from.

    ``fundamental_Hz`` is the topology's natural fundamental
    (``f_line`` for line reactors, ``2·f_line`` for boost / passive
    where the inductor sees a rectified envelope). ``harmonic_pct``
    is each h-th harmonic's amplitude as a percentage of the
    fundamental peak; ``thd_pct`` follows the IEEE/IEC definition:
    ``√(Σ_{h=2..N} I_h²) / I_1 · 100``.
    """

    topology: str
    n_phases: int
    t_s: np.ndarray
    iL_A: np.ndarray
    iL_extra: tuple[np.ndarray, ...] = ()
    extra_labels: tuple[str, ...] = ()
    label: str = ""
    # ---- Spectrum + THD (filled by ``_attach_spectrum``) -------------
    fundamental_Hz: float = 0.0
    harmonic_h: np.ndarray = None  # type: ignore[assignment]
    harmonic_pct: np.ndarray = None  # type: ignore[assignment]
    thd_pct: float = 0.0

    @property
    def n_traces(self) -> int:
        return 1 + len(self.iL_extra)


# ---------------------------------------------------------------------------
# Spectrum + THD helper
# ---------------------------------------------------------------------------

def _spectrum_at_harmonics(
    t_s: np.ndarray, signal: np.ndarray,
    fundamental_Hz: float, n_harmonics: int = 20,
) -> tuple[np.ndarray, np.ndarray, float]:
    """FFT of ``signal`` sampled at the harmonic bins of ``fundamental_Hz``.

    Returns ``(h_array, mag_pct_of_fundamental, thd_pct)``. THD is the
    canonical IEEE/IEC fraction:
    ``thd = √(Σ_{h=2..N} I_h²) / I_1``.

    The signal's DC component is removed before the FFT so the
    "fundamental" bin isn't shadowed by a large DC offset (passive
    chokes are dominated by their DC level). When the input is too
    short to resolve the fundamental, a zero spectrum + THD = 0 is
    returned so the caller can render a flat bar chart instead of
    erroring.
    """
    h = np.arange(1, n_harmonics + 1)
    if signal.size < 8 or t_s.size != signal.size or fundamental_Hz <= 0:
        return h, np.zeros(n_harmonics), 0.0

    dt = float(t_s[1] - t_s[0])
    if dt <= 0:
        return h, np.zeros(n_harmonics), 0.0

    n = signal.size
    # Strip DC so a passive choke (dominated by I_dc) doesn't pin the
    # spectrum's largest value to bin 0.
    centred = signal - float(np.mean(signal))
    fft = np.fft.rfft(centred)
    freqs = np.fft.rfftfreq(n, d=dt)
    mag = np.abs(fft) * 2.0 / n  # peak amplitude per bin

    # Sample magnitude at each harmonic bin (nearest neighbour). Past
    # the Nyquist limit the harmonic doesn't exist — clamp to 0.
    nyq = 0.5 / dt
    pct = np.zeros(n_harmonics)
    fund_mag = 0.0
    for i, h_n in enumerate(h):
        f_target = float(h_n) * fundamental_Hz
        if f_target > nyq:
            continue
        idx = int(np.argmin(np.abs(freqs - f_target)))
        m = float(mag[idx])
        if h_n == 1:
            fund_mag = m
            pct[i] = 100.0
        else:
            pct[i] = (m / fund_mag * 100.0) if fund_mag > 1e-12 else 0.0

    if fund_mag <= 1e-12:
        return h, np.zeros(n_harmonics), 0.0
    thd_sq = float(np.sum((pct[1:] / 100.0) ** 2))
    thd_pct = math.sqrt(thd_sq) * 100.0
    return h, pct, thd_pct


def _attach_spectrum(
    wf: RealisticWaveform, fundamental_Hz: float,
    n_harmonics: int = 20,
) -> RealisticWaveform:
    """Compute spectrum + THD on ``wf.iL_A`` and return a new bundle.

    For multi-phase topologies the spectrum/THD are computed on phase
    A (the others are the same up to phase shift; the magnitude
    spectrum is invariant under phase rotation).
    """
    h, pct, thd = _spectrum_at_harmonics(
        wf.t_s, wf.iL_A, fundamental_Hz, n_harmonics=n_harmonics,
    )
    return RealisticWaveform(
        topology=wf.topology,
        n_phases=wf.n_phases,
        t_s=wf.t_s,
        iL_A=wf.iL_A,
        iL_extra=wf.iL_extra,
        extra_labels=wf.extra_labels,
        label=wf.label,
        fundamental_Hz=fundamental_Hz,
        harmonic_h=h,
        harmonic_pct=pct,
        thd_pct=thd,
    )


# ---------------------------------------------------------------------------
# Topology-specific synthesisers
# ---------------------------------------------------------------------------

def _boost_ccm(spec: Spec, result: DesignResult,
               n_samples: int) -> RealisticWaveform | None:
    """Boost-CCM iL(t) — sinusoidal PFC envelope + per-cycle HF ripple.

    State-space averaging gives the slow envelope; the HF triangle
    rides on top with an amplitude that varies along the line cycle.

    **Slow envelope (line frequency, sinusoidal current shaping):**

    A boost PFC is designed to draw an ideally sinusoidal input
    current in phase with the rectified line voltage:

        i_in(t) = √2 · I_in_rms · |sin(2πf_line · t)|

    where ``I_in_rms ≈ Pout / (Vin_rms · η)``.

    **HF ripple (instantaneous switching ripple):**

    Per switching cycle, with switch ON for ``D·T_sw`` then OFF for
    ``(1-D)·T_sw``:

        ΔI_pp(t) = v_in(t) · (1 - v_in(t)/V_out) · T_sw / L

    The triangle's centre tracks the slow envelope. We synthesise
    a saw-tooth shape using the modulo of (t / T_sw).

    Both pieces come straight from the textbook small-signal /
    averaged-state-space model of a boost converter — no fudge.
    """
    L_uH = float(result.L_actual_uH)
    if L_uH <= 0:
        return None
    f_line = float(spec.f_line_Hz or 50.0)
    f_sw_kHz = float(spec.f_sw_kHz or 0.0)
    Vin_min = float(spec.Vin_min_Vrms or 0.0)
    Vout = float(spec.Vout_V or 0.0)
    Pout = float(spec.Pout_W or 0.0)
    eta = float(getattr(spec, "eta", 0.95) or 0.95)
    if (f_line <= 0 or f_sw_kHz <= 0 or Vin_min <= 0
            or Vout <= 0 or Pout <= 0):
        return None

    L = L_uH * 1e-6
    T_sw = 1.0 / (f_sw_kHz * 1e3)
    period = 1.0 / f_line  # one full line cycle (seconds)
    omega = 2.0 * math.pi * f_line
    Vin_pk = math.sqrt(2.0) * Vin_min  # worst-case low-line peak
    I_in_rms = Pout / (Vin_min * max(eta, 0.5))
    I_in_pk = math.sqrt(2.0) * I_in_rms

    t = np.linspace(0.0, period, n_samples, endpoint=False)
    v_in = Vin_pk * np.abs(np.sin(omega * t))
    # Slow-frequency PFC envelope: same |sin| shape as v_in.
    i_envelope = I_in_pk * np.abs(np.sin(omega * t))

    # HF ripple amplitude varies with v_in. Avoid division by zero
    # when v_in = 0 — the duty there is meaningless and the boost
    # won't switch (zero-crossing dead-zone). Clamp to ≥ 1 V.
    v_safe = np.maximum(v_in, 1.0)
    duty = np.clip(1.0 - v_safe / Vout, 0.05, 0.95)
    delta_pp = v_safe * duty * T_sw / L

    # Saw-tooth ripple in [-0.5, +0.5] amplitude span. We use
    # ``2·(t/T_sw mod 1) - 1`` for a triangle-from-saw signature
    # — visually reads as the standard "PWM ripple" the engineer
    # expects. Centre of the triangle lies on i_envelope.
    phase = (t / T_sw) % 1.0
    saw = 2.0 * phase - 1.0
    # Mask the deadband near zero crossings: when v_in < 5 % of peak
    # the boost typically loses control and ripple becomes
    # unrepresentative. Fade the ripple amplitude smoothly so the
    # visualisation doesn't show a noisy artifact at the zero crossings.
    fade = np.clip(np.abs(np.sin(omega * t)) / 0.05, 0.0, 1.0)
    ripple = 0.5 * delta_pp * saw * fade

    iL = i_envelope + ripple
    base = RealisticWaveform(
        topology="boost_ccm",
        n_phases=1,
        t_s=t,
        iL_A=iL,
        label=(
            f"Boost CCM @ Vin_min={Vin_min:.0f} Vrms · "
            f"envelope = √2·Pout/(Vin·η) · |sin(ωt)| · "
            f"ripple_pp = Vin·(1-Vin/Vout)·Tsw/L"
        ),
    )
    # Boost-CCM sees a rectified envelope after the bridge — the
    # natural fundamental is at 2·f_line. The PFC line current
    # *before* the bridge would be at f_line, but the spectrum the
    # plot shows is of the inductor current as seen here.
    return _attach_spectrum(base, fundamental_Hz=2.0 * f_line)


def _passive_choke(spec: Spec, result: DesignResult,
                   n_samples: int) -> RealisticWaveform | None:
    """Passive choke iL(t) — DC bus current with line-frequency ripple.

    A passive PFC choke sits between the bridge and the bulk cap.
    The cap holds Vout near constant; the inductor sees a chopped
    rectified voltage. The current is a near-DC level with a slow
    sawtooth at twice the line frequency (full-wave bridge), since
    the cap recharges on each rectified peak.

    Synthesis:

        I_dc = Pout / Vout
        ΔI_pp ≈ V_pk_ripple · T/2 / L
                where T = 1/f_line and V_pk_ripple ≈ V_pk - V_dc

    Approximation: a triangle wave at 2·f_line with peak amplitude
    matching the textbook chopped-rectifier ripple. Faithful to the
    visual signature without a full bridge simulation.
    """
    L_uH = float(result.L_actual_uH)
    if L_uH <= 0:
        return None
    f_line = float(spec.f_line_Hz or 50.0)
    Vin_min = float(spec.Vin_min_Vrms or 0.0)
    Pout = float(spec.Pout_W or 0.0)
    if f_line <= 0 or Vin_min <= 0 or Pout <= 0:
        return None

    L = L_uH * 1e-6
    Vin_pk = math.sqrt(2.0) * Vin_min
    # Crude DC bus voltage estimate for the passive case: ~0.9·Vpk.
    Vbus = 0.9 * Vin_pk
    I_dc = Pout / max(Vbus, 1.0)
    # Half-period of rectified line is T_line / 2.
    half_period = 1.0 / (2.0 * f_line)
    delta_pp_raw = (Vin_pk - Vbus) * half_period / L
    # Clamp the *display* ripple to ≤ 1.5·I_dc so an undersized core
    # (delta_pp_raw → ∞ when L → 0) still produces a readable trace.
    # The label keeps the raw textbook number so the engineer can
    # see whether the chosen L is in spec.
    delta_pp_display = max(min(delta_pp_raw, 1.5 * I_dc), 0.05 * I_dc)

    period = 1.0 / f_line
    t = np.linspace(0.0, 2 * period, n_samples, endpoint=False)
    # Triangle at 2·f_line, centred on I_dc.
    omega2 = 2.0 * math.pi * (2.0 * f_line)
    # ``arcsin(sin(...))`` produces a clean triangle in [-π/2, π/2].
    tri = (2.0 / math.pi) * np.arcsin(np.sin(omega2 * t))
    iL = I_dc + 0.5 * delta_pp_display * tri

    note = ""
    if delta_pp_raw > 1.6 * I_dc:
        note = " · ⚠ L abaixo do recomendado (ripple raw {:.0f} A)".format(
            delta_pp_raw,
        )
    base = RealisticWaveform(
        topology="passive_choke",
        n_phases=1,
        t_s=t,
        iL_A=iL,
        label=(
            f"Choke passivo · I_dc ≈ {I_dc:.2f} A · "
            f"ripple_pp ≈ {delta_pp_display:.2f} A @ 2·f_line"
            f"{note}"
        ),
    )
    # Passive choke ripple lives at 2·f_line — same fundamental as
    # boost CCM since both feed off a full-wave rectifier.
    return _attach_spectrum(base, fundamental_Hz=2.0 * f_line)


def _line_reactor_1ph(spec: Spec, result: DesignResult,
                      n_samples: int) -> RealisticWaveform | None:
    """1φ line-reactor iL(t) — calibrated by the engine, not synthesised.

    The engine's design path for ``line_reactor`` already runs
    :func:`pfc_inductor.topology.line_reactor.line_current_waveform`
    against the design's actual ``pct_impedance_actual`` and IEEE-519-
    fit harmonic table; the result lives in ``result.waveform_iL_A``.
    That waveform is the authoritative shape — synthesising our own
    pulse train from a fudged ``atan2(ωL, R_eq)`` conduction angle
    used to disagree with the engine's THD estimate (the engine said
    ~130 % but we showed 196 %), making engineers wonder whether the
    inductor was being modelled at all.

    Fix: trust the engine. Pull ``waveform_iL_A`` straight in. Only
    fall back to the closed-form pulse train when the engine path
    didn't populate the array (defensive).
    """
    f_line = float(spec.f_line_Hz or 50.0)
    if f_line <= 0:
        return None

    if result.waveform_iL_A and result.waveform_t_s:
        # ---- Engine-calibrated path -----------------------------------
        # The engine path for line_reactor topology populates the
        # waveform from ``line_current_waveform(spec, L_actual_mH,
        # n_cycles=2, n_points=1200)``, which already reflects the
        # design's L_actual_uH via pct_impedance_actual. No further
        # synthesis math needed.
        t = np.array(result.waveform_t_s, dtype=float)
        iL = np.array(result.waveform_iL_A, dtype=float)
        pct_Z = float(result.pct_impedance_actual or 0.0)
        label = (
            f"Reator 1φ · forma calibrada pelo engine · "
            f"pct_Z = {pct_Z:.2f}% · "
            f"I_rms = {result.I_line_rms_A:.2f} A · "
            f"I_pk = {result.I_line_pk_A:.2f} A"
        )
        base = RealisticWaveform(
            topology="line_reactor", n_phases=1,
            t_s=t, iL_A=iL, label=label,
        )
        return _attach_spectrum(base, fundamental_Hz=f_line)

    # ---- Fallback: closed-form pulse train (engine waveform absent) ---
    # Same math as before — kept so half-baked specs (Pout=0 etc.)
    # still get *something* on screen instead of a blank axis.
    L_uH = float(result.L_actual_uH)
    if L_uH <= 0:
        return None
    Vin_min = float(spec.Vin_min_Vrms or 0.0)
    Pout = float(spec.Pout_W or 0.0)
    if Vin_min <= 0 or Pout <= 0:
        return None

    L = L_uH * 1e-6
    Vin_pk = math.sqrt(2.0) * Vin_min
    Vbus = 0.95 * Vin_pk
    I_dc = Pout / max(Vbus, 1.0)
    R_eq = max(Vbus * Vbus / max(Pout, 1.0), 0.1)
    omega = 2.0 * math.pi * f_line
    theta_cond = max(min(math.atan2(omega * L, R_eq), 1.4), 0.4)

    period = 1.0 / f_line
    t = np.linspace(0.0, 2 * period, n_samples, endpoint=False)
    phase = (omega * t) % (2.0 * math.pi)
    pos_pulse = np.cos(0.5 * np.pi * (phase - 0.5 * math.pi)
                       / (0.5 * theta_cond))
    pos_window = (np.abs(phase - 0.5 * math.pi) < 0.5 * theta_cond)
    neg_pulse = np.cos(0.5 * np.pi * (phase - 1.5 * math.pi)
                       / (0.5 * theta_cond))
    neg_window = (np.abs(phase - 1.5 * math.pi) < 0.5 * theta_cond)
    I_pk_raw = 1.2 * math.pi * I_dc / max(theta_cond, 0.1)
    I_pk = min(I_pk_raw, 5.0 * max(I_dc, 0.1))
    iL = np.zeros_like(t)
    iL[pos_window] = I_pk * np.maximum(pos_pulse[pos_window], 0.0)
    iL[neg_window] = -I_pk * np.maximum(neg_pulse[neg_window], 0.0)

    base = RealisticWaveform(
        topology="line_reactor",
        n_phases=1,
        t_s=t,
        iL_A=iL,
        label=(
            f"Reator 1φ (fallback) · I_dc = {I_dc:.2f} A · "
            f"θ_conduction ≈ {math.degrees(theta_cond):.0f}° · "
            f"I_pk ≈ {I_pk:.1f} A"
        ),
    )
    return _attach_spectrum(base, fundamental_Hz=f_line)


def _line_reactor_3ph(spec: Spec, result: DesignResult,
                      n_samples: int) -> RealisticWaveform | None:
    """3φ line-reactor iL_a/b/c(t) — engine-calibrated A + ±120° rotations.

    The engine populates ``result.waveform_iL_A`` for one
    representative phase using the same harmonic-decomposition path
    1φ uses (fed with the 3-phase ``estimate_thd_pct`` ≈ 75/√%Z
    formula). Phase B and C are *not* run independently — they are
    the same waveform shifted by ±T/3 in time, since a balanced 3-
    phase rectifier produces three time-translated copies of the
    same shape.

    Synthesising B and C as ``np.roll(iL_a, ±n_samples/3)`` honours
    that physics exactly and avoids the previous fudge of
    ``np.sin(ωt + φ)·suppress`` which produced an aggressive, square-
    looking waveform that didn't match the engine's THD.
    """
    f_line = float(spec.f_line_Hz or 50.0)
    if f_line <= 0:
        return None

    if result.waveform_iL_A and result.waveform_t_s:
        # ---- Engine-calibrated path -----------------------------------
        t = np.array(result.waveform_t_s, dtype=float)
        iL_a = np.array(result.waveform_iL_A, dtype=float)
        # Time-shift by ±T/3 to recover phases B and C.
        period = 1.0 / f_line
        if t.size >= 2:
            dt = float(t[1] - t[0])
            shift_samples = int(round((period / 3.0) / dt))
        else:
            shift_samples = max(iL_a.size // 6, 1)
        iL_b = np.roll(iL_a, -shift_samples)  # B lags A by 120°
        iL_c = np.roll(iL_a, +shift_samples)  # C leads A by 120°

        pct_Z = float(result.pct_impedance_actual or 0.0)
        label = (
            f"Reator 3φ · forma calibrada pelo engine · "
            f"pct_Z = {pct_Z:.2f}% · "
            f"I_rms = {result.I_line_rms_A:.2f} A · "
            f"3 fases via shift ±T/3"
        )
        base = RealisticWaveform(
            topology="line_reactor", n_phases=3,
            t_s=t, iL_A=iL_a,
            iL_extra=(iL_b, iL_c),
            extra_labels=("iL_b", "iL_c"),
            label=label,
        )
        return _attach_spectrum(base, fundamental_Hz=f_line)

    # ---- Fallback: closed-form windowed sinusoid ---------------------
    L_uH = float(result.L_actual_uH)
    if L_uH <= 0:
        return None
    Vin_min = float(spec.Vin_min_Vrms or 0.0)
    Pout = float(spec.Pout_W or 0.0)
    if Vin_min <= 0 or Pout <= 0:
        return None

    L = L_uH * 1e-6
    Vbus = 1.35 * Vin_min
    I_dc = Pout / max(Vbus, 1.0)
    omega = 2.0 * math.pi * f_line
    theta_cond_total = max(
        min(math.atan2(omega * L, Vbus / max(I_dc, 0.1)), 1.0), 0.4,
    )

    period = 1.0 / f_line
    t = np.linspace(0.0, 2 * period, n_samples, endpoint=False)

    def _phase_current(phi_offset: float) -> np.ndarray:
        env = np.sin(omega * t + phi_offset)
        suppress = np.abs(env) > math.cos(0.5 * theta_cond_total)
        return I_dc * 1.5 * env * suppress

    iL_a = _phase_current(0.0)
    iL_b = _phase_current(-2.0 * math.pi / 3.0)
    iL_c = _phase_current(+2.0 * math.pi / 3.0)

    base = RealisticWaveform(
        topology="line_reactor", n_phases=3, t_s=t, iL_A=iL_a,
        iL_extra=(iL_b, iL_c), extra_labels=("iL_b", "iL_c"),
        label=(
            f"Reator 3φ (fallback) · I_dc ≈ {I_dc:.2f} A · 3 fases a 120°"
        ),
    )
    return _attach_spectrum(base, fundamental_Hz=f_line)


# ---------------------------------------------------------------------------
# Buck CCM synthesiser
# ---------------------------------------------------------------------------

def _buck_ccm(spec: Spec, result: DesignResult,
              n_samples: int) -> RealisticWaveform | None:
    """Buck-CCM iL(t) — pure HF triangle ripple on a DC level.

    State-space averaging: with the high-side switch ON the inductor
    sees ``Vin − Vout`` and ramps up at ``(Vin − Vout) / L``; with the
    switch OFF (low-side conducting) it sees ``−Vout`` and ramps down
    at ``Vout / L``. Volt-seconds balance gives ``D = Vout / Vin``,
    so the ramp-up / ramp-down magnitudes are equal in steady state
    and the resulting iL(t) is a symmetric triangle around ``Iout``.

    No line envelope, no sinusoidal shaping — bucks are DC-DC, the
    waveform is the same triangle on every switching cycle. We
    sample ``n_periods`` cycles at ``Vin_nom`` (worst-case ripple
    happens at ``Vin_max``; we pick nominal so the displayed
    average matches what a scope on the bench would show).

    Returns ``None`` for half-baked specs (no L, no fsw, no Pout).
    """
    # Defer the topology import to avoid a hard cyclic dep at module
    # load (``simulate.realistic_waveforms`` is imported indirectly
    # from many places).
    from pfc_inductor.topology import buck_ccm

    L_uH = float(result.L_actual_uH)
    if L_uH <= 0:
        return None

    Iout = buck_ccm.output_current_A(spec)
    f_sw_kHz = float(spec.f_sw_kHz or 0.0)
    if Iout <= 0 or f_sw_kHz <= 0:
        return None

    Vin_nom = buck_ccm._vin_nom(spec)
    Vin_max = buck_ccm._vin_max(spec)
    Vout = float(spec.Vout_V or 0.0)
    if Vin_nom <= 0 or Vin_max <= 0 or Vout <= 0:
        return None

    f_sw_Hz = f_sw_kHz * 1e3
    T_sw = 1.0 / f_sw_Hz
    D_nom = buck_ccm.duty_cycle(spec, Vin_nom)
    delta_nom = buck_ccm.ripple_pp_at_Vin(spec, L_uH, Vin_nom)
    delta_worst = buck_ccm.worst_case_ripple_pp_A(spec, L_uH)

    # Show 6 switching periods — enough to read the ramp slope and
    # the symmetry of the triangle without crowding the plot.
    n_periods = 6
    t = np.linspace(0.0, n_periods * T_sw, n_samples, endpoint=False)
    phase = (t / T_sw) % 1.0
    on_mask = phase < D_nom

    # Ramp up during D·T_sw from Iout − ΔI/2 to Iout + ΔI/2; ramp
    # down symmetrically during (1 − D)·T_sw.
    on_norm = phase / max(D_nom, 1e-9)
    off_norm = (phase - D_nom) / max(1.0 - D_nom, 1e-9)
    iL = np.where(
        on_mask,
        Iout - 0.5 * delta_nom + delta_nom * on_norm,
        Iout + 0.5 * delta_nom - delta_nom * off_norm,
    )

    label = (
        f"Buck CCM @ Vin_nom={Vin_nom:.1f} V → Vout={Vout:.2f} V · "
        f"D={D_nom:.3f} · I_out={Iout:.2f} A · "
        f"ΔI_pp={delta_nom:.2f} A (nom) / {delta_worst:.2f} A (Vin_max)"
    )
    base = RealisticWaveform(
        topology="buck_ccm",
        n_phases=1,
        t_s=t,
        iL_A=iL,
        label=label,
    )
    # Buck has no line frequency — the inductor's natural fundamental
    # is the switching frequency. The spectrum will show one strong
    # bin at h=1 (= f_sw) and very small higher harmonics from the
    # triangle's odd-harmonic content (1/h² fall-off).
    return _attach_spectrum(base, fundamental_Hz=f_sw_Hz)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def synthesize_il_waveform(
    spec: Spec, result: DesignResult, *, n_samples: int = 2400,
) -> RealisticWaveform | None:
    """Return a topology-aware ``RealisticWaveform`` for the spec.

    Falls through to ``None`` when the spec or result is half-baked
    (Pout = 0, L not yet computed, unknown topology). Callers should
    treat ``None`` as "use the engine's sampled arrays as a backstop".
    """
    topology = getattr(spec, "topology", "boost_ccm")
    n_phases = int(getattr(spec, "n_phases", 1) or 1)

    if topology == "boost_ccm":
        return _boost_ccm(spec, result, n_samples)
    if topology == "passive_choke":
        return _passive_choke(spec, result, n_samples)
    if topology == "buck_ccm":
        return _buck_ccm(spec, result, n_samples)
    if topology == "line_reactor":
        if n_phases == 3:
            return _line_reactor_3ph(spec, result, n_samples)
        return _line_reactor_1ph(spec, result, n_samples)
    return None
