AC copper resistance — Dowell
=============================

Above DC, the winding's effective resistance climbs because the
current crowds toward the conductor surface (skin effect) and
adjacent layers force opposite-direction flow into a thin
boundary (proximity effect). MagnaDesign uses the
**Dowell formula** (P. L. Dowell, 1966) for round-wire windings
and the Sullivan extension for Litz.

Implementation: :mod:`pfc_inductor.physics.dowell`.

Skin depth
----------

.. math::

   \\delta(f) = \\sqrt{\\frac{2\\rho_{\\mathrm{Cu}}(T)}{\\omega \\mu_0}}

where ``ρ_Cu(T) = ρ_Cu_20 · (1 + α · (T - 20))`` with α =
0.00393 / K. The temperature dependence couples back into the
thermal solver — see :doc:`thermal`.

Penetration ratio
-----------------

For a round conductor of radius ``r``:

.. math::

   \\Delta = \\frac{r}{\\delta(f)}

Dowell's formula then gives the AC-to-DC resistance ratio per
layer:

.. math::

   F_R = \\Delta \\cdot \\left[
     \\frac{\\sinh 2\\Delta + \\sin 2\\Delta}{\\cosh 2\\Delta - \\cos 2\\Delta}
     + \\frac{2(m^2-1)}{3} \\cdot
     \\frac{\\sinh \\Delta - \\sin \\Delta}{\\cosh \\Delta + \\cos \\Delta}
   \\right]

where ``m`` is the number of layers in the winding. The first
term is the skin contribution; the second is proximity
(quadratic in the layer count, which is why dense multi-layer
windings are dangerous at high fsw).

Where it lives in the code
--------------------------

``pfc_inductor/physics/dowell.py``:

- :func:`pfc_inductor.physics.dowell.skin_depth_m` — δ(f, T).
- :func:`pfc_inductor.physics.dowell.fr_round` — F_R for a
  round conductor with given (Δ, m).
- :func:`pfc_inductor.physics.dowell.fr_litz` — Sullivan-
  extended F_R for Litz with N strands of radius r_s.

Layer count
-----------

The engine derives ``m`` from the bobbin geometry + winding
fill rather than asking the user. The window-height /
wire-OD ratio gives the layer count; the ``Ku_actual`` field
reports the resulting fill so the user can see if they're
hitting the bobbin's window limit.

Calibration
-----------

Dowell's formula is **textbook-exact** for round wires up to
the point where adjacent-layer field interaction breaks down —
typically when the proximity term dominates by 10× or more.
For dense Litz at high I + high fsw the formula under-predicts
by 5-15 % (the Sullivan extension narrows but doesn't close
this gap). The validation thresholds in
``validation/thresholds.yaml`` reflect this: ``copper_loss_pct:
15`` and ``ac_resistance_pct: 25`` are loose enough to
accommodate the residual.

Limits
------

- Round-wire only on the base ``fr_round`` path. Foil + flat
  windings would need a separate Schwartz / Vandelac model
  — not currently in the engine because the catalogue ships
  only round + Litz.
- Above the wire's self-resonant frequency (~1–10 MHz for
  typical PFC chokes) the parasitic Cp shunts the winding and
  the effective resistance no longer follows Dowell. The
  EN 55032 EMI estimator (:doc:`compliance`) takes over in
  that regime.

Code reference
--------------

.. autofunction:: pfc_inductor.physics.dowell.skin_depth_m
.. autofunction:: pfc_inductor.physics.dowell.fr_round
.. autofunction:: pfc_inductor.physics.dowell.fr_litz

Tests
-----

``tests/test_dowell.py`` anchors against the textbook
``F_R(Δ=1, m=4)`` value and against a vendor app-note Litz
case at 100 kHz / 5 strands.

References
----------

- P. L. Dowell, "Effects of eddy currents in transformer
  windings," *Proc. IEE*, vol. 113, no. 8, 1966.
- C. R. Sullivan, "Optimal choice for number of strands in a
  litz-wire transformer winding," *IEEE Trans. Power
  Electron.*, vol. 14, no. 2, 1999.
