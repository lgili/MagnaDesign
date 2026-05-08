Engine pipeline overview
========================

MagnaDesign's design engine is a deterministic functional
pipeline: every output is computed from the spec + selected
component triple, no hidden state, no randomness, no caches.
The orchestrator lives at
:func:`pfc_inductor.design.design`.

.. mermaid::

   graph LR
     A[Spec] --> B[Topology adapter]
     B --> C[Operating-point<br>currents + ripple]
     C --> D[Turn-count solver<br>L_required → N]
     D --> E[Flux density B_pk<br>vs Bsat margin]
     E --> F[Loss model<br>Steinmetz + iGSE + Dowell]
     F --> G[Iterative thermal<br>solver]
     G --> H[DesignResult]

Every block in the diagram has a dedicated chapter:

- :doc:`steinmetz-igse` — core loss under non-sinusoidal flux.
- :doc:`dowell` — AC copper resistance with proximity effect.
- :doc:`rolloff` — DC-bias permeability decay (powder cores).
- :doc:`thermal` — coupled ρ\ :sub:`Cu`\ (T) + iGSE(T) loop.
- :doc:`feasibility` — Tier-0 envelope check used by the
  cascade optimiser.
- :doc:`compliance` — IEC 61000-3-2 + EN 55032 + UL 1411
  derivations.

.. note::
   The pipeline is purely functional. ``design()`` is safe to
   call from worker threads, process pools, and CLI scripts —
   no global state, no surprise mutation. The optimiser's
   process pool relies on this contract.

When the spec carries an ``fsw_modulation`` band, the dispatch
function :func:`pfc_inductor.modulation.design_or_band` fans
out to one ``design()`` call per fsw point and aggregates the
results into a :class:`pfc_inductor.models.banded_result.BandedDesignResult`.
The single-point and banded paths share the same physics
modules — see :doc:`/topology/boost-ccm` for an example of how
the modulation envelope folds back into per-topology adapters.

Inputs
------

The four arguments to ``design`` are typed Pydantic models:

- :class:`pfc_inductor.models.Spec` — spec sheet (topology,
  V/I/P/η/fsw/T_amb/Ku_max/Bsat_margin, optional VFD
  modulation band).
- :class:`pfc_inductor.models.Core` — core geometry (AL, Ae,
  le, Wa, Bsat curve, dimensions).
- :class:`pfc_inductor.models.Wire` — winding spec (gauge,
  insulation, optionally Litz strand count + diameter).
- :class:`pfc_inductor.models.Material` — magnetic material
  (vendor, family, μ_initial, Bsat vs T, Steinmetz constants,
  rolloff curve, optional λ\ :sub:`s` for acoustic prediction).

Outputs
-------

Single :class:`pfc_inductor.models.DesignResult` carrying:

- ``L_required_uH`` / ``L_actual_uH`` — target vs. delivered
  inductance.
- ``N_turns``, ``B_pk_T``, ``Bsat_limit_T``.
- ``T_winding_C``, ``T_rise_C``, ``H_dc_peak_Oe``.
- ``losses.P_cu_dc_W``, ``P_cu_ac_W``, ``P_core_*_W``,
  ``P_total_W``.
- ``Ku_actual``, ``mu_pct_at_peak``.
- Topology-specific extras: ``pct_impedance_actual`` (line
  reactor), ``Pi_W`` + efficiency (boost-PFC), THD estimate.

Conventions
-----------

- **SI units inside the engine.** UI shows engineering units
  (mT, Oe, mm, A, W, °C, kHz). Conversions only happen at the
  boundary.
- **Worst-case operating point** = low line + peak ripple at
  ``vin = Vout/2`` (or line peak when ``Vin_pk < Vout/2``).
- **Stateless physics modules.** Orchestration lives in
  ``design.engine``.
- **Every regression** has a hand-calc anchor in
  ``tests/`` against a textbook or vendor app-note datapoint.
