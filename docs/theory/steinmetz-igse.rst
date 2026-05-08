Core loss — Steinmetz + iGSE
============================

For non-sinusoidal flux waveforms (every PFC line cycle)
MagnaDesign uses the **improved Generalised Steinmetz Equation
(iGSE)** by Mühlethaler et al. (2012). The implementation is
in :mod:`pfc_inductor.physics.core_loss`.

Anchored Steinmetz form
-----------------------

The vendor-supplied Steinmetz curve is anchored at a reference
operating point ``(f_ref, B_ref, P_v,ref)`` so the user
doesn't have to renormalise per material:

.. math::

   P_v[\\mathrm{mW/cm^3}] = P_{v,\\mathrm{ref}} \\cdot
   \\left(\\frac{f}{f_{\\mathrm{ref}}}\\right)^\\alpha
   \\cdot \\left(\\frac{B}{B_{\\mathrm{ref}}}\\right)^\\beta

Default anchor: ``f_ref = 100 kHz``, ``B_ref = 100 mT``. ``α``
and ``β`` are fit per material from 12 vendor data points
(curated catalogue) or read from the OpenMagnetics MAS catalogue
when absent.

The classic Steinmetz equation only handles sinusoidal flux at
a single frequency. PFC inductors see a non-sinusoidal B(t)
across the line cycle: peak ripple at ``vin = Vout/2``, decreasing
toward the line zeros. The iGSE generalises:

.. math::

   P_v(t) = k_i \\cdot \\left|\\frac{dB}{dt}\\right|^\\alpha
            \\cdot (\\Delta B)^{\\beta - \\alpha}

with

.. math::

   k_i = \\frac{P_{v,\\mathrm{ref}}}{(2\\pi)^{\\alpha-1}
                                     \\cdot
        \\int_0^{2\\pi}
          \\left|\\cos\\theta\\right|^\\alpha\\,d\\theta
        \\cdot B_{\\mathrm{ref}}^{\\beta-\\alpha}}.

Time-averaging over the line cycle gives the per-second core
loss.

Where it lives in the code
--------------------------

``pfc_inductor/physics/core_loss.py``:

- :func:`pfc_inductor.physics.core_loss.steinmetz` — closed-form
  ``P_v(f, B, params)``.
- :func:`pfc_inductor.physics.core_loss.iGSE_line_cycle` — the
  full integral above, integrated numerically over one line
  cycle of the topology's B(t) waveform.
- :func:`pfc_inductor.physics.core_loss.split_into_line_and_ripple`
  — the engine reports core loss split into a
  ``P_core_line_W`` (60 / 50 Hz fundamental) + ``P_core_ripple_W``
  (fsw harmonics) so the user sees which mechanism dominates.

Calibration
-----------

Each curated material's Steinmetz constants are fitted from 12
vendor data points spanning ``20 kHz – 200 kHz × 50 mT –
300 mT``. The residual error sits at ±20 % per material —
documented in the model's docstring and reflected in the
``add-validation-reference-set`` thresholds (``core_loss_pct:
20`` in ``validation/thresholds.yaml``).

The anchored form makes calibration boring: a vendor sheet with
a single data point at any (f, B) feeds straight in via:

.. code-block:: python

   from pfc_inductor.models import SteinmetzParams
   p = SteinmetzParams(
       f_ref=100_000, B_ref=0.1,
       Pv_ref=300,         # mW/cm³ at the anchor
       alpha=1.5, beta=2.6,
   )

Limits
------

- iGSE assumes the flux waveform is **piecewise smooth** over
  the line cycle — discontinuities (saturation transitions)
  break the formula. The engine flags ``saturated`` in the
  result so the user sees the regime shift.
- Below 1 kHz the model degrades — eddy-current losses
  dominate at line frequency and Steinmetz under-predicts.
  The line-reactor topology uses a separate hysteresis-ring
  model documented in :doc:`/topology/line-reactor`.

Code reference
--------------

.. autofunction:: pfc_inductor.physics.core_loss.steinmetz
.. autofunction:: pfc_inductor.physics.core_loss.iGSE_line_cycle

Tests
-----

``tests/test_core_loss.py`` regresses the iGSE against vendor
app-note data points; ``tests/test_iec61000_3_2.py`` and the
``add-validation-reference-set`` notebooks (Phase 2) close the
loop against bench measurements.
