Interleaved Boost-PFC
=====================

A multi-phase boost-PFC topology — two or three CCM boost stages
running in parallel on a shared input rail and DC bus, with their
gate signals shifted by ``360° / N`` so the input ripple
components partially cancel before reaching the EMI filter.

Each phase is electrically identical: a textbook boost-CCM
inductor sized for ``P_out / N``. The interleaving is a
controller-side (PWM phase shift) and filter-side (input ripple
cancellation) feature; the magnetics design problem reduces to
designing one phase and ordering ``N`` of them.

When to pick it
---------------

Versus single-phase boost-PFC, interleaving buys:

- **Smaller per-phase magnetics** — ``P_out`` per phase is
  ``P_total / N``, so the per-phase inductor stores roughly
  ``1/N`` of the energy of the equivalent single-phase design.
  Two N=2 cores fit on smaller standard parts than one N=1 core
  rated for the same total power.
- **Higher effective input ripple frequency** — the surviving
  input ripple is at ``N · f_sw``, which lets the EMI filter
  shrink (the filter's first attenuation pole moves up by the
  same factor).
- **Hwu-Yau ripple cancellation** — at the *natural-null* duties
  ``D ∈ {1/N, 2/N, …, (N−1)/N}`` the aggregate input ripple
  approaches zero. Most real PFC stages sweep through these
  duties over the line cycle, so the *RMS* aggregate ripple is
  much smaller than ``ΔI_pp/N`` would naïvely suggest.
- **Thermal redundancy** — with current-sharing control the
  copper loss splits ``1:N`` across N inductors, so the per-part
  ΔT is lower than a single-phase design carrying the same
  total power.

Costs:

- ``N×`` the gate driver and current sensor count.
- Tighter controller — current sharing requires a per-phase
  inner loop to avoid one phase running hot.
- Catalogue uniformity matters: the N inductors should be
  selected from the same vendor lot so their AL_nH spread is
  tight, otherwise asymmetric ripple shows up at the EMI
  filter.

Typical applications: server PSUs (1.5 – 5 kW per converter,
N = 2), residential AC at the same power range, EV chargers
and high-end industrial PSUs (3 – 22 kW, N = 3).

Operating-point math
--------------------

The engine treats interleaved boost-PFC as boost-CCM with a
**per-phase spec** — ``Pout_per_phase = Pout_total / N`` is
substituted, and the rest of the calculation flows through the
boost-CCM model unchanged.

For ``Vin = Vin_min`` (worst-case current) the per-phase RMS
input current is:

.. math::

   I_{\\mathrm{phase,rms}} = \\frac{P_{\\mathrm{out}} / N}
                                 {\\eta \\cdot V_{\\mathrm{in,min}}}

The aggregate input current (sum across all N phases) is then:

.. math::

   I_{\\mathrm{in,rms,total}} = N \\cdot I_{\\mathrm{phase,rms}}
                              = \\frac{P_{\\mathrm{out}}}
                                     {\\eta \\cdot V_{\\mathrm{in,min}}}

i.e. the same as a single-phase design at the same total ``Pout`` —
interleaving does not reduce the line current itself, only the
ripple.

Hwu-Yau ripple cancellation factor
----------------------------------

The closed-form ripple-cancellation ratio of an N-phase boost
PFC versus a single-phase reference at duty cycle ``D`` is
(Hwu and Yau, IEEE PEDS 2009):

.. math::

   \\alpha(D, N) = \\frac{(1 - k \\cdot D) \\cdot (k \\cdot D - k + 1)}
                       {D \\cdot (1 - D)}

where ``k = \\lfloor N \\cdot D \\rfloor + 1``.

Properties:

- ``α(D, N) = 1`` at ``N = 1`` (degenerate — no cancellation).
- ``α(D, N) → 0`` at the natural-null duties
  ``D ∈ {1/N, 2/N, …, (N−1)/N}``.
- Worst-case (smallest cancellation) sits at ``D = 0.5`` for
  N = 2 (full input voltage at low-line, far from any null) and
  at ``D ∈ {1/6, 1/2, 5/6}`` for N = 3.
- Time-averaged across the line cycle, the RMS reduction from
  N = 2 interleaving is typically 6 – 9 dB; N = 3 adds another
  3 – 5 dB.

Use this factor when sizing the input EMI filter — the surviving
ripple at the filter input is approximately
``α(D, N) · ΔI_pp,phase`` per phase, summed at ``N · f_sw``.

Effective input ripple frequency
--------------------------------

PWM signals shifted by ``360° / N`` produce input current
spectral content that doubles (or triples) the dominant ripple
frequency:

.. math::

   f_{\\mathrm{ripple,effective}} = N \\cdot f_{\\mathrm{sw}}

This is the frequency the EMI filter sees, so its first
attenuation pole can move up by ``N×`` versus a single-phase
design at the same per-phase ``f_sw``.

Where it lives in the code
--------------------------

``pfc_inductor/topology/interleaved_boost_pfc.py``:

- :func:`pfc_inductor.topology.interleaved_boost_pfc.per_phase_spec`
  derives the per-phase ``Spec`` from the total spec.
- :func:`pfc_inductor.topology.interleaved_boost_pfc.required_inductance_uH`
  delegates to ``boost_ccm`` after spec substitution.
- :func:`pfc_inductor.topology.interleaved_boost_pfc.ripple_cancellation_factor`
  returns ``α(D, N)`` directly.
- :func:`pfc_inductor.topology.interleaved_boost_pfc.aggregate_input_ripple_pp`
  applies ``α(D, N)`` to a single-phase ripple amplitude.
- :func:`pfc_inductor.topology.interleaved_boost_pfc.effective_input_ripple_frequency_Hz`
  returns ``N · f_sw``.
- :func:`pfc_inductor.topology.interleaved_boost_pfc.estimate_thd_pct`
  scales the boost-CCM THD estimate by ``1 / sqrt(N)``.

The ``InterleavedBoostPFCModel`` adapter in
``interleaved_boost_pfc_model.py`` plugs this set of helpers into
the topology registry — every downstream caller (engine,
optimizer, FEA validator, reports) sees a unified
``ConverterModel`` interface and routes through the boost-CCM
math automatically.

VFD modulation
--------------

When ``Spec.fsw_modulation`` is set, the engine evaluates each
phase at every ``f_sw`` point in the band — same dispatch as
boost-CCM. Interleaving does not change the band sweep itself;
the per-phase magnetics design is identical, only the
controller phase-shift is band-aware.

Compliance regime
-----------------

Interleaved boost-PFC stages produce sinusoidal aggregate line
current by control, so the engine's analytical IEC 61000-3-2
result is again "trivially compliant" — the dispatcher reports
PASS with the same ``"LISN measurement still required"`` caveat
as single-phase boost-CCM.

EN 55032 conducted EMI: the surviving differential-mode ripple
sits at ``N · f_sw`` instead of ``f_sw``, so the input filter
inductance can drop by roughly ``N`` for the same insertion
loss at the new ripple frequency. Common-mode noise is
unaffected by interleaving and still drives the CM choke
selection.

References
----------

- J. Hwu, S.-S. Yau, *An Interleaved Boost Converter With
  Reduced Volume Magnetic Component for PFC Applications*,
  IEEE PEDS 2009.
- L. Huber, B. Irving, M. M. Jovanovic, *Open-Loop Control
  Methods for Interleaved DCM/CCM Boundary Boost PFC
  Converters*, IEEE Trans. Power Electronics, 2008.
- L. Balogh, R. Redl, *Power-Factor Correction with
  Interleaved Boost Converters in Continuous-Inductor-Current
  Mode*, IEEE APEC 1993 (canonical paper that introduced the
  topology).
