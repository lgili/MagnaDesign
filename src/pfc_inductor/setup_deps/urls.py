"""Upstream ONELAB download URLs.

The official binaries live at ``https://onelab.info/files/`` and are
versioned by year (no semver). We pin the tag so re-installing on a
different machine pulls the same build.
"""

from __future__ import annotations

from pfc_inductor.setup_deps.platform_info import PlatformInfo

# Pinned to the build we tested against. Bump when upstream releases a
# new gmsh/getdp combo and we re-validate.
ONELAB_VERSION = "4.13.0"

_BASE = "https://onelab.info/files"


def onelab_archive_url(plat: PlatformInfo) -> str:
    """Return the URL of the ONELAB archive for the given platform."""
    return f"{_BASE}/onelab-{plat.onelab_tag}.{plat.archive_ext}"
