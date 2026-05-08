API reference
=============

Auto-generated from the source via Sphinx ``autosummary``.
Every public module is type-hinted; the docstrings here
mirror the `pyproject.toml`-mypy "strict on the domain layer"
contract.

Domain models
-------------

.. autosummary::
   :toctree: generated/
   :template: module.rst

   pfc_inductor.models
   pfc_inductor.models.spec
   pfc_inductor.models.core
   pfc_inductor.models.material
   pfc_inductor.models.wire
   pfc_inductor.models.result
   pfc_inductor.models.banded_result
   pfc_inductor.models.modulation

Physics modules
---------------

.. autosummary::
   :toctree: generated/

   pfc_inductor.physics.core_loss
   pfc_inductor.physics.dowell
   pfc_inductor.physics.rolloff

Engine + topologies
-------------------

.. autosummary::
   :toctree: generated/

   pfc_inductor.design
   pfc_inductor.topology
   pfc_inductor.modulation

Optimisation
------------

.. autosummary::
   :toctree: generated/

   pfc_inductor.optimize
   pfc_inductor.optimize.sweep
   pfc_inductor.optimize.cascade
   pfc_inductor.worst_case
   pfc_inductor.worst_case.engine
   pfc_inductor.worst_case.monte_carlo
   pfc_inductor.worst_case.tolerances

Standards / compliance
----------------------

.. autosummary::
   :toctree: generated/

   pfc_inductor.standards
   pfc_inductor.standards.iec61000_3_2
   pfc_inductor.standards.en55032
   pfc_inductor.standards.ul1411
   pfc_inductor.compliance
   pfc_inductor.compliance.dispatcher

Acoustic
--------

.. autosummary::
   :toctree: generated/

   pfc_inductor.acoustic
   pfc_inductor.acoustic.model

Reporting
---------

.. autosummary::
   :toctree: generated/

   pfc_inductor.report

CLI
---

.. autosummary::
   :toctree: generated/

   pfc_inductor.cli
   pfc_inductor.cli.exit_codes
