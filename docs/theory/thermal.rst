Iterative thermal solver
========================

Copper resistivity is a function of temperature. Core loss is
a function of temperature (via Bsat decay). The winding
temperature is a function of the total loss. These three
couplings make a fixed-point problem:

.. math::

   T &= T_{\\mathrm{amb}} + R_{\\mathrm{th}} \\cdot P_{\\mathrm{total}}(T) \\\\
   P_{\\mathrm{total}}(T) &= P_{\\mathrm{Cu}}(T) + P_{\\mathrm{core}}(T)

The engine iterates this loop until ``T`` stops moving — see
``pfc_inductor/design/engine.py`` for the implementation.

Solver details
--------------

1. **Seed temperature.** Default ``T₀ = T_amb + 30 °C``. Tuning
   knob (``T_init_rise_K_DEFAULT``) — affects iteration count,
   not the converged answer.
2. **Per-iteration:**
   - ``ρ_Cu(T) = ρ_Cu(20°C) · (1 + α·(T - 20))``, ``α = 0.00393/K``.
   - ``Bsat(T)`` linear-interpolated between 25 °C and 100 °C
     vendor sheets.
   - Re-run the full Dowell + iGSE chain at the new T → new
     ``P_total``.
   - Update T = T_amb + R_th · P_total.
3. **Convergence:** ``|ΔT| < 0.5 °C`` or 20 iterations. The
   engine reports ``converged: bool`` so divergent designs
   (typically thermal runaway on undersized cores) surface in
   the result.

Thermal resistance R_th
-----------------------

Currently a closed-form ``R_th = K / (Ae · le)^{0.5}`` with
``K`` calibrated against the validation reference set's
thermal measurements. The validation thresholds in
``validation/thresholds.yaml`` admit a ±10 °C absolute delta
on T_winding — the model's documented residual.

Future iterations could:

- Switch to a per-core measured ``R_th`` from the catalogue
  (the MAS schema carries it).
- Decompose into a CMC + TMC equivalent (cooling-by-convection
  vs. cooling-by-conduction-into-PCB) so a potted vs.
  free-standing inductor are differentiated.

Code reference
--------------

.. autofunction:: pfc_inductor.design.engine.design

Tests
-----

``tests/test_thermal.py`` regresses against three reference
designs at three ambient temperatures each; the residual is
≤ 8 °C across the matrix.
