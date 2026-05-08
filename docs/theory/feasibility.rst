Tier-0 feasibility envelope
============================

The cascade optimiser pre-prunes its candidate space with a
fast geometric / saturation check before invoking the full
analytical engine. The check lives in
:mod:`pfc_inductor.optimize.feasibility`.

What gets checked
-----------------

For every (core, material, wire, N) tuple the Tier-0 path
verifies:

- **Window fit** — ``Ku_predicted ≤ Ku_max`` per the spec.
  Predicted Ku is closed-form from
  ``N · A_w / (Wa · k_fill_for_kind)``.
- **Saturation envelope** — ``B_pk_predicted ≤ B_sat ·
  (1 - margin)`` using a closed-form B(I, AL_at_H_peak)
  estimate that doesn't iterate.
- **AL plausibility** — the chosen N gives an L within ``5 ×
  L_required`` (an order-of-magnitude sanity check that
  catches obvious mismatches).
- **Wire current density** — ``J = I_rms / A_w ≤ J_max``.
  Default ``J_max = 8 A/mm²``; tightens to 5 A/mm² for
  Litz designs (proximity-effect overhead).

Tier-0 runs at **~5 µs per candidate**, so a 6 G theoretical
catalogue × candidate space prunes to ~140 k feasible tuples
in under a second. The orchestrator then hands the survivors
to Tier 1 (full analytical engine, ~1 ms each).

Where it lives in the code
--------------------------

``pfc_inductor/optimize/feasibility.py``:

- :func:`pfc_inductor.optimize.feasibility.core_quick_check` —
  the per-tuple gate. Returns
  :class:`pfc_inductor.models.FeasibilityEnvelope` with
  ``feasible`` flag + ``reasons`` list when False.
- :func:`pfc_inductor.optimize.feasibility.viable_wires_for_spec`
  — pre-narrows the wire catalogue to candidates whose AC
  current density lands in the J_min..J_max band. Cuts the
  full 1 400-wire catalogue to ~10 viable gauges per spec.

Why have it separate from the engine?
-------------------------------------

The full engine takes ~1 ms per candidate even on fast
hardware. With 6 G theoretical candidates that's 1.6 weeks of
CPU. Tier-0's 5 µs pre-filter is the bottleneck reduction
that makes the cascade tractable: it does the cheap
"obviously-impossible" rejections first so the expensive
``design()`` only runs on tuples that have a chance.

The same envelope check is exposed to the simple optimiser
via the ``feasible`` flag on each ``SweepResult``, but the
sweep doesn't *gate* on it — the user can opt to see infeasible
candidates with the GUI's "Hide infeasible designs"
checkbox.

Code reference
--------------

.. autofunction:: pfc_inductor.optimize.feasibility.core_quick_check

Tests
-----

``tests/test_feasibility.py`` regresses against hand-built
edge cases: a known-feasible design must pass; a known-saturated
core (B_pk > Bsat × (1 - margin)) must fail with the
``"saturates"`` reason; an over-wound bobbin must fail with
``"window_overflow"``.
