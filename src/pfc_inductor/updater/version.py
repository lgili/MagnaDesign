"""Semantic-version comparison (PEP 440 subset).

The release pipeline cuts tags like ``v0.7.0`` and
``v0.7.0-rc1``. The updater needs to answer "is the appcast's
latest entry newer than the running build?" without pulling
``packaging`` (which is heavy and not needed elsewhere).

We support:

- ``MAJOR.MINOR.PATCH``  (e.g. ``0.7.2``)
- ``MAJOR.MINOR.PATCH-SUFFIX``  (e.g. ``0.7.2-rc1``,
  ``0.7.2-dev1``, ``0.7.2-alpha.2``)

Suffixed versions are *older* than the same MAJOR.MINOR.PATCH
without a suffix (i.e. ``0.7.2`` > ``0.7.2-rc1``); among
suffixes the lexical compare is "good enough" for our cadence
(``rc1 < rc2 < rc3``). Anything more exotic falls back to
strict equality (returns ``False``).
"""

from __future__ import annotations

import re
from typing import Optional

# Capture: optional leading "v", three numeric components,
# optional non-numeric suffix.
_VERSION_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:[.-](.+))?$",
)


def _parse(value: str) -> Optional[tuple[int, int, int, str]]:
    """Return ``(major, minor, patch, suffix)`` or ``None`` for
    unparseable input. Suffix is the empty string when there is
    no pre-release / dev / build suffix."""
    if not isinstance(value, str):
        return None
    match = _VERSION_RE.match(value.strip())
    if match is None:
        return None
    major, minor, patch, suffix = match.groups()
    return (int(major), int(minor), int(patch), suffix or "")


def is_newer_version(remote: str, current: str) -> bool:
    """Return ``True`` when ``remote`` is strictly newer than
    ``current``.

    Returns ``False`` for any unparseable input — defensive
    against a malformed appcast feeding garbage in. Releasing
    a hot-fix when the comparator can't read the version is
    worse than a missed update notification.
    """
    r = _parse(remote)
    c = _parse(current)
    if r is None or c is None:
        return False
    r_major, r_minor, r_patch, r_suffix = r
    c_major, c_minor, c_patch, c_suffix = c

    # Compare numeric tuple first.
    if (r_major, r_minor, r_patch) > (c_major, c_minor, c_patch):
        return True
    if (r_major, r_minor, r_patch) < (c_major, c_minor, c_patch):
        return False

    # Same numeric — pre-release suffix means *older* (so a
    # remote without a suffix beats a current with one).
    if r_suffix == "" and c_suffix != "":
        return True
    if r_suffix != "" and c_suffix == "":
        return False
    # Both suffixed — lexical compare. Good enough for
    # ``rc1 < rc2`` and ``alpha < beta``. Doesn't fully respect
    # PEP 440 ordering rules; if we ever ship pre-releases that
    # break the ordering, we can swap in ``packaging.version``.
    return r_suffix > c_suffix
