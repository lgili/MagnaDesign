DC-bias permeability rolloff
============================

Powder cores (Kool Mµ, MPP, HighFlux, XFlux) lose effective
permeability under DC bias — the AL value falls as the H field
saturates the distributed gap. Ferrite cores show a similar
but much weaker dependence; line-frequency laminations are
nearly bias-invariant.

MagnaDesign uses a calibrated power-law model:

.. math::

   \\mu_{\\mathrm{frac}}(H) =
     \\frac{1}{a + b \\cdot H[\\mathrm{Oe}]^c}

where ``μ_frac = μ_eff / μ_initial`` and ``a, b, c`` are
fitted per (vendor, family, μ_initial) tuple. At ``H = 0`` the
formula reduces to ``μ_frac = 1/a`` (which is by construction
1.0 — i.e. ``a = 1``); the engine reports ``mu_pct_at_peak``
in the result so the user sees the actual rolloff at their
operating H.

Calibration data
----------------

Each curated material's ``a, b, c`` are fitted from the vendor's
50 % rolloff datapoint plus the high-bias asymptote shown in
their datasheet. Sources currently calibrated:

- **Magnetics Inc.** — Kool Mµ 26/40/60/75/90/125 µ; MPP 14
  → 200 µ; HighFlux 26/60/125; XFlux 60/125. 12 datapoints
  per material spanning ``5 → 250 Oe``.
- **Magmattec** (Brazilian) — same families.
- **Micrometals** — sendust + iron-powder grades. -52, -2,
  -8 cores.
- **CSC** — Megaflux + HiFlux variants.

Implementation: :mod:`pfc_inductor.physics.rolloff`.

Where it lives in the code
--------------------------

``pfc_inductor/physics/rolloff.py``:

- :func:`pfc_inductor.physics.rolloff.mu_frac_at_H` —
  closed-form rolloff lookup. Falls back to ``μ_frac = 1`` if
  the material lacks a calibrated curve (line-frequency
  laminations) so the engine never crashes on missing data.
- :func:`pfc_inductor.physics.rolloff.fit_rolloff_to_data` —
  least-squares fit used by the catalogue-import pipeline.

How rolloff feeds the engine
----------------------------

The turn-count solver iterates:

1. Start with ``L_required`` and the AL at H = 0.
2. Guess N → compute peak H → look up ``μ_frac(H)`` →
   recompute AL_eff → recompute L for that N.
3. If ``L < L_required`` increase N; loop until converged or
   the bobbin saturates (Ku > Ku_max) or N hits the 500-turn
   safety cap.

The iterations are typically 3–5 for powder cores and 1 for
ferrite. Convergence is reported in
``DesignResult.converged`` so a divergent design surfaces in
the report rather than silently shipping bad numbers.

Limits
------

- Above the saturation knee the power-law extrapolates badly.
  The engine clamps to the ``Bsat × (1 - margin)`` limit and
  reports the design as infeasible if N can't satisfy
  ``L_required`` without crossing it.
- Temperature dependence isn't in the rolloff curve — it's
  captured separately in the material's ``Bsat_25C_T`` /
  ``Bsat_100C_T`` pair, which the engine interpolates linearly
  at the operating-point temperature.

Code reference
--------------

.. autofunction:: pfc_inductor.physics.rolloff.mu_frac_at_H

Tests
-----

``tests/test_rolloff.py`` regresses against the Magnetics
2017 catalog's published 50 % rolloff datapoints for every
curated material; the residual is < 5 % per data point.
