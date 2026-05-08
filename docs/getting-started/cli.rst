Headless CLI
============

``magnadesign`` is the headless entry point — every GUI surface
has a CLI sibling so CI pipelines, batch scripts, and vendor-
quoting integrations can drive the engine without a display.

Subcommand cheat sheet
----------------------

.. code-block:: console

   $ magnadesign --help
   Usage: magnadesign [OPTIONS] COMMAND [ARGS]...
     MagnaDesign headless CLI — drive the design engine from
     scripts and CI pipelines.
   Commands:
     design       Run the engine on PROJECT_FILE and print headline KPIs.
     sweep        Run the simple Pareto sweep on PROJECT_FILE.
     worst-case   Run the corner DOE + Monte-Carlo on PROJECT_FILE.
     compliance   Run regulatory checks on PROJECT_FILE.
     cascade      Run the multi-tier cascade on PROJECT_FILE.

Bare ``magnadesign`` (no args) and ``magnadesign gui`` launch
the desktop app — backward-compatible with every existing
entry-point launcher and Windows shortcut.

Exit codes
----------

==  ===========================  ============================================
 0  ``OK``                       Successful execution.
 1  ``GENERIC_ERROR``            Bug, I/O, engine raise.
 2  ``COMPLIANCE_FAIL``          Design fails at least one applicable
                                 regulatory check.
 3  ``WORST_CASE_FAIL``          Design fails at least one tolerance corner
                                 OR yield falls below ``--yield-threshold``.
 4  ``USAGE_ERROR``              Bad invocation (missing argument, malformed
                                 ``.pfc``, unresolved selection).
==  ===========================  ============================================

CI scripts can branch:

.. code-block:: bash

   if magnadesign compliance project.pfc --region EU; then
       echo "Regulatory: PASS"
   elif [ $? -eq 2 ]; then
       echo "Regulatory: FAIL — design needs work"
   else
       echo "Pipeline error"
       exit 1
   fi

Common workflows
----------------

**Validate a release candidate**

.. code-block:: bash

   magnadesign design        rc.pfc --json | tee rc-summary.json
   magnadesign worst-case    rc.pfc --pretty
   magnadesign compliance    rc.pfc --region Worldwide --out rc-compl.pdf
   magnadesign cascade       rc.pfc --top 5 --rank loss

**Batch sweep over a directory**

.. code-block:: bash

   for pfc in projects/*.pfc; do
       magnadesign sweep "$pfc" --top 10 --csv "${pfc%.pfc}-top10.csv"
   done

**Vendor-quoting pipeline (manufacturing-spec follow-up)**

.. code-block:: bash

   magnadesign design     project.pfc --json > kpis.json
   magnadesign mfg-spec   project.pfc --out factory.pdf  # add-mfg-spec
   magnadesign compliance project.pfc --region US --out factory-ul.pdf

JSON output schema
------------------

Every subcommand emits machine-readable JSON to stdout by
default; ``--pretty`` flips to a human-readable key-value table.
The JSON schema per subcommand is stable from 0.1 onward — see
the per-subcommand source files in
``src/pfc_inductor/cli/`` for the exact key set.

For deeper integration the same Python API the CLI wraps is
available directly:

.. code-block:: python

   from pfc_inductor.cli.utils import load_session
   from pfc_inductor.design import design

   loaded = load_session("project.pfc")
   result = design(
       loaded.spec,
       loaded.selected_core,
       loaded.selected_wire,
       loaded.selected_material,
   )
