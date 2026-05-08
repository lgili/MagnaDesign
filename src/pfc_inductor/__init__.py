"""MagnaDesign — topology-aware desktop suite for inductor design.

Originally shipped as ``pfc-inductor-designer`` and scoped to active
boost-CCM PFC chokes; the app now covers active boost-CCM, passive
PFC chokes, and 1φ / 3φ line reactors with calibrated physics + FEA
validation in a single workflow. The Python package name was kept as
``pfc_inductor`` to avoid mass-renaming every import site — see
``pyproject.toml`` for the renamed distribution + ``magnadesign``
CLI entry points.
"""

__version__ = "0.1.0"
