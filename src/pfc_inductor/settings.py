"""Application-wide ``QSettings`` keys.

Thin re-export of the ``(organization, application)`` pair from
:mod:`pfc_inductor.app_identity`. The two names are kept as
module-level constants for backward compatibility with existing
``from pfc_inductor.settings import SETTINGS_ORG, SETTINGS_APP``
imports — new code should call
:func:`pfc_inductor.app_identity.qsettings_args` directly.
"""

from __future__ import annotations

from pfc_inductor.app_identity import APP_NAME

# Both slots resolve to ``"MagnaDesign"``. Older code may still
# read them as separate names, so we expose them explicitly.
SETTINGS_ORG: str = APP_NAME
SETTINGS_APP: str = APP_NAME

__all__ = ["SETTINGS_APP", "SETTINGS_ORG"]
