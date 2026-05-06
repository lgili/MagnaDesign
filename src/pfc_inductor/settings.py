"""Application-wide ``QSettings`` keys.

Single source of truth for the organisation/application strings used by
``QSettings(SETTINGS_ORG, SETTINGS_APP)``. Previously duplicated in
``__main__.py`` and ``ui/main_window.py``; keeping them in one module
prevents the two from drifting apart and silently splitting user
preferences across two stores.
"""
from __future__ import annotations

SETTINGS_ORG = "indutor"
SETTINGS_APP = "PFCInductorDesigner"

__all__ = ["SETTINGS_APP", "SETTINGS_ORG"]
