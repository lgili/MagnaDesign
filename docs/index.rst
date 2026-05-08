MagnaDesign — topology-aware inductor design suite
====================================================

MagnaDesign is a desktop + headless tool for designing PFC
inductors, line reactors, passive chokes, and DC-DC magnetics
(buck-CCM, flyback, …) with calibrated physics, multi-tier
optimisation, and FEA validation.

The project sits in the gap between vendor calculators
(Magnetics, Micrometals — single-material, single-topology) and
heavy commercial FEA suites (ANSYS PEmag, Cedrat Flux). It
specialises vertically: PFC topology-aware maths, in-tool cost
model, Litz optimiser, multi-design comparison, B–H loop
visualisation, polished bilingual UI, Brazilian + global supply
chain.

.. toctree::
   :maxdepth: 1
   :caption: Getting started

   getting-started/install
   getting-started/first-design
   getting-started/cli

.. toctree::
   :maxdepth: 2
   :caption: Theory of operation

   theory/overview
   theory/steinmetz-igse
   theory/dowell
   theory/rolloff
   theory/thermal
   theory/feasibility
   theory/compliance

.. toctree::
   :maxdepth: 1
   :caption: Topology

   topology/boost-ccm
   topology/line-reactor
   topology/passive-choke
   topology/buck-ccm

.. toctree::
   :maxdepth: 1
   :caption: Project / governance

   adr/0001-positioning
   ../docs/POSITIONING.md
   ../docs/RELEASE.md

.. toctree::
   :maxdepth: 1
   :caption: API reference

   reference/index


Why this exists
---------------

The open-source magnetics-design landscape (FEMMT, OpenMagnetics
MAS, AI-mag) is strong on FEM and generic schemas, but does not
serve **the PFC engineer who has to ship inverters worldwide
with cost-aware decisions and a Brazilian supply chain**. This
project specialises *vertically*: PFC topology-aware maths, in-
tool cost model, Litz optimiser, multi-design compare, B–H loop
visualisation, polished bilingual UI, Brazilian vendors.

When in doubt about scope or trade-offs, see
:doc:`adr/0001-positioning`.


Indices
-------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
