Line reactor (1 φ / 3 φ)
========================

A 50 / 60 Hz rectifier+choke topology — no switching, just a
line-frequency inductor designed for harmonic attenuation on
diode-bridge loads.

Design knob
-----------

Where boost-PFC is "I want this much ripple", the line reactor
is "I want this much impedance":

.. math::

   \\%Z = 100 \\cdot \\frac{\\omega \\cdot L_{\\mathrm{req}}}
                          {Z_{\\mathrm{base}}}

with ``Z_base = V_phase / I_rated``. The ``Spec.L_req_mH`` field
carries the target inductance directly; legacy ``%Z`` inputs
are auto-converted via the back-compat shim in
``models/spec.py``.

Harmonic spectrum
-----------------

The diode-rectifier draws a 6k±1-harmonic spectrum (3 φ) or
2k±1 (1 φ). The engine synthesises the line-current waveform
analytically so the iGSE integration runs over the real B(t):

.. math::

   i(t) = I_{\\mathrm{fund}} \\cdot \\sin(\\omega t) +
          \\sum_{k=1}^{N} I_k \\cdot \\sin(k\\omega t + \\phi_k)

The amplitudes ``I_k`` are functions of the reactor's
%Z — see :func:`pfc_inductor.topology.line_reactor.line_current_waveform`.
Higher %Z attenuates the higher harmonics more (the reactor
is itself a low-pass filter).

IEC 61000-3-2 compliance
------------------------

Line reactors are the canonical IEC 61000-3-2 specimen — the
spectrum has measurable harmonics (h=3, 5, 7, 9, 11, …) so
the dispatcher always produces a populated table. Class D
applies for ≤ 600 W loads with the standard's wave-shape
envelope.

The ``add-line-reactor-topology`` reference design ships at
600 W / 1 φ / 230 V which **fails** Class D at h=5 by 28 % —
this is intentional: it exercises the ``FAIL`` verdict path
for the dispatcher's regression tests.

Where it lives in the code
--------------------------

``pfc_inductor/topology/line_reactor.py``:

- :func:`pfc_inductor.topology.line_reactor.operating_point`
  returns ``(I_line_rms, I_line_pk, %Z_actual)``.
- :func:`pfc_inductor.topology.line_reactor.line_current_waveform`
  synthesises i(t) from the analytic harmonic decomposition.
- :func:`pfc_inductor.topology.line_reactor.harmonic_amplitudes_pct`
  returns the per-harmonic %-of-fundamental table the
  compliance dispatcher feeds to ``evaluate_compliance``.
- :func:`pfc_inductor.topology.line_reactor.harmonic_spectrum`
  — FFT of an arbitrary supplied i(t), for cross-checking
  against scope captures.

UI surface
----------

The Spec drawer's *Line reactor* block is hidden by default;
the topology picker enables it when "Line reactor 1 φ" or
"Line reactor 3 φ" is chosen. The block exposes
``V_line / I_rated / L_req`` directly — the parameters the
power-electronics engineer thinks in.

References
----------

- N. Mohan, T. Undeland, W. Robbins, *Power Electronics*,
  Chap. 5 (rectifier loading + harmonic synthesis).
- IEC 61000-3-2:2018, Tables 1–3 (Class A / D limits).
