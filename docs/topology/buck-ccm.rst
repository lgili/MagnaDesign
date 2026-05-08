Buck-CCM (DC-DC step-down)
==========================

Synchronous-buck DC-DC inductor — first DC-input topology in
the catalogue. Used in POL converters, automotive 12 → 5 V,
telecom 48 → 12 V, and as the secondary-side filter of a
phase-shifted full-bridge.

Operating-point math
--------------------

For a buck operating in CCM at duty ratio ``D = Vout / Vin``:

.. math::

   \\Delta i_L = \\frac{V_{\\mathrm{out}} \\cdot (1 - D)}{f_{\\mathrm{sw}} \\cdot L}

The required inductance hits the user's ``ripple_ratio = ΔI_pp /
I_out`` target:

.. math::

   L_{\\mathrm{required}} = \\frac{V_{\\mathrm{out}} \\cdot (1 - D)}
                          {f_{\\mathrm{sw}} \\cdot \\mathrm{ripple\\_ratio} \\cdot I_{\\mathrm{out}}}

A ``ripple_ratio`` of 0.30 is the textbook optimum (Erickson
§5.2) — lower values give bigger inductors; higher values
shrink L at the cost of larger output capacitance.

Spec model extensions
---------------------

Buck adds three DC-input fields to ``Spec``:

- ``Vin_dc_V`` — nominal DC input voltage.
- ``Vin_dc_min_V`` — worst-case (high-current) operating point.
- ``Vin_dc_max_V`` — worst-case (high-ripple) operating point.

Plus the ``ripple_ratio`` knob that replaces the AC-spec's
``ripple_pct`` (a *ratio* of I_out for buck vs. a *percent* of
I_pk for AC).

When the spec is migrated from a boost project (or built fresh
without the DC fields), the engine falls back to ``Vin_min_Vrms``
to populate ``v_in`` so the validator doesn't trip on missing
data — the migration shim is documented inline in
``models/spec.py``.

Where it lives in the code
--------------------------

``pfc_inductor/topology/buck_ccm.py`` (parallel agent's
parallel-topology track):

- ``operating_point()`` returns ``(I_out, I_pk, ΔI_pp, D_max)``.
- ``required_inductance(spec, ripple_ratio)`` computes
  ``L_required`` from the worst-case (V_in_max, full I_out,
  ripple_ratio) corner.

UI integration
--------------

The Spec drawer's converter block sets ``Vout / Pout / fsw /
ripple_pct`` plus a DC-input block (``Vin_dc / Vin_dc_min /
Vin_dc_max``) that's hidden by default and revealed when the
topology picker selects "Buck CCM". The line-reactor block
hides and the AC-input block ports its values into the DC
defaults so a user iterating between topologies doesn't lose
context.

References
----------

- R. W. Erickson, D. Maksimović, *Fundamentals of Power
  Electronics*, 2nd ed., Chap. 5 (CCM analysis).
