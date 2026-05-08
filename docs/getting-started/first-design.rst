First design
============

A 5-minute walkthrough from "fresh checkout" to "datasheet
PDF on disk".

1. Open the example project
---------------------------

The repo ships two example projects under ``examples/``:

- ``examples/600W_boost_reference.pfc`` — feasible boost-PFC,
  passes worst-case + UL 1411 + IEC 61000-3-2.
- ``examples/line_reactor_600W.pfc`` — 1 φ line reactor; FAILS
  IEC 61000-3-2 Class D at h=5, useful for seeing the
  compliance dispatcher in action.

.. code-block:: console

   $ magnadesign design examples/600W_boost_reference.pfc --pretty
   project      600W boost reference
   topology     boost_ccm
   material     60_HighFlux
   core         C058777A2
   wire         AWG14
   L_target_uH  747.45
   L_actual_uH  762.81
   N_turns      61
   B_pk_mT      269.2
   B_sat_pct    27.1
   T_winding_C  103.4
   T_rise_C     63.4
   P_total_W    3.36
   ...

2. Sweep the catalogue
----------------------

.. code-block:: console

   $ magnadesign sweep examples/600W_boost_reference.pfc \\
        --top 10 --rank loss --csv top10.csv

   sweeping boost_ccm (1 materials × 10193 cores × 1433 wires) ...
   swept 64485 candidates (2045 feasible) → keeping top 10
   CSV → top10.csv

The first line on stderr reads ``materials × cores × wires`` —
the cardinality the cascade Tier 0 prunes through. The CSV is
ready for spreadsheet review.

3. Run the worst-case envelope
------------------------------

.. code-block:: console

   $ magnadesign worst-case examples/600W_boost_reference.pfc --pretty
   corner DOE: 7 tolerances, running...
     → 143 corners, 0 engine failures
   Monte-Carlo: 1000 samples, seed=0
   project       600W boost reference
   topology      boost_ccm
   tolerances    default-ipc-iec-vendor
   corners       143  (failed: 0)
   ...
   yield         100.00 % (1000 samples, seed-reproducible)
   verdict       ✓ PASS

Exits with code 0. Try
``--yield-threshold 99.999`` to see the ``WORST_CASE_FAIL``
exit-code-3 path.

4. Generate the compliance report
---------------------------------

.. code-block:: console

   $ magnadesign compliance examples/line_reactor_600W.pfc \\
        --region EU --out compl.pdf
   PDF → compl.pdf
   ... (FAIL — h=5 exceeds the limit by 28.4 %)

The PDF carries the verdict per standard, the per-harmonic
table, the methodology notes, and a per-page footer with the
project + git SHA so an auditor can match the document to an
exact build.

5. Open the GUI for the visual loop
-----------------------------------

.. code-block:: console

   $ magnadesign

The desktop app loads the same ``.pfc`` files; the *Project*
workspace tabs (Core / Analysis / Validate / Worst-case /
Compliance / Export) reproduce every CLI surface plus the
interactive bits (3-D viewer, B-H loop, Pareto chart) that
don't fit on stdout.

Where to go next
----------------

- :doc:`cli` — the full subcommand cheat sheet.
- :doc:`/theory/overview` — the engine pipeline + per-physics-
  module derivations.
- :doc:`/topology/boost-ccm` — design notes for the active PFC
  topology that drives most of the catalogue.
