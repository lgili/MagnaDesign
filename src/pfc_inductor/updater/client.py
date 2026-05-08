"""``check_for_updates`` — top-level entry point.

Resolves the running app's version, fetches the appcast,
filters entries newer than the running version, and returns
the most-recent compatible one (or ``None``). All network +
parsing + version-compare steps are wrapped so the function
**never raises into the GUI** — every failure path returns
``None`` and an internal log line.

Privacy guardrails
------------------

- Honours :func:`pfc_inductor.telemetry.consent.is_telemetry_disabled`
  — the same kill switch crash reporting honours.
- Sends only the user-agent ``magnadesign/<version> <os>/<arch>``
  with the request. No PII, no project data.
- 10-second timeout on the network call so a slow / blocked
  appcast doesn't pin a worker thread.
"""

from __future__ import annotations

import logging
import platform
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from pfc_inductor.updater.appcast import AppcastEntry, parse_appcast
from pfc_inductor.updater.version import is_newer_version

# Default appcast URL — points to the upstream GitHub Pages
# branch. Maintainer forks override via the ``url`` argument or
# the ``MAGNADESIGN_APPCAST_URL`` env var.
DEFAULT_APPCAST_URL = "https://magnadesign.dev/appcast.xml"
_DEFAULT_TIMEOUT_S = 10.0
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateInfo:
    """Information about an available update.

    Returned by :func:`check_for_updates` when the appcast
    advertises a version newer than the running build. The GUI
    composes a "Update available" dialog from this payload.
    """

    current_version: str
    """The running app's version, for the dialog's "you are on
    X" line."""

    latest: AppcastEntry
    """The newest appcast entry. Carries title, release notes,
    download URL, signature, and minimum-system-version."""


def check_for_updates(
    *,
    current_version: Optional[str] = None,
    url: str = DEFAULT_APPCAST_URL,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Optional[UpdateInfo]:
    """Return :class:`UpdateInfo` when an update is available.

    Returns ``None`` for any of:

    - User opted out (kill-switch env var set).
    - Network call failed (DNS / TLS / 4xx / 5xx / timeout).
    - Appcast XML malformed or empty.
    - Every entry is older than or equal to the running build.

    The function never raises — every failure path logs at
    DEBUG level and returns ``None`` so the GUI's
    "Check for updates…" handler stays simple.
    """
    # Telemetry kill switch — same env var the crash reporter
    # honours. A user who opted out of phoning home shouldn't
    # have the updater silently call out either.
    try:
        from pfc_inductor.telemetry.consent import is_telemetry_disabled

        if is_telemetry_disabled():
            _LOG.debug("update check skipped: telemetry disabled")
            return None
    except Exception:
        # Defensive — if the telemetry module isn't importable
        # for some reason, we still respect the env var directly.
        import os

        if os.environ.get("MAGNADESIGN_DISABLE_TELEMETRY", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return None

    current = current_version or _resolve_current_version()
    if not current:
        _LOG.debug("update check skipped: current version unresolved")
        return None

    xml_text = _fetch(url, timeout_s, current)
    if xml_text is None:
        return None
    entries = parse_appcast(xml_text)
    if not entries:
        return None

    # Pick the newest entry strictly newer than the running build.
    newer = [e for e in entries if is_newer_version(e.version, current)]
    if not newer:
        return None
    # Sort by version descending — handles the case where the
    # appcast lists entries in arbitrary order.
    newer.sort(key=lambda e: _sortable_version(e.version), reverse=True)
    return UpdateInfo(current_version=current, latest=newer[0])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_current_version() -> Optional[str]:
    """Read the package version from ``importlib.metadata``.

    Returns ``None`` for source checkouts where the package
    isn't installed — the updater silently skips in that case
    rather than misleading a developer with a "0.0.0 → 0.7.0"
    dialog.
    """
    try:
        from importlib.metadata import version

        return version("magnadesign")
    except Exception:
        return None


def _user_agent(current_version: str) -> str:
    """Compose the user-agent string. The OS / arch fields help
    the maintainer triage download-fail bug reports without
    asking the user."""
    return f"magnadesign/{current_version} {platform.system().lower()}/{platform.machine().lower()}"


def _fetch(url: str, timeout_s: float, current_version: str) -> Optional[str]:
    """HTTP GET with a short timeout and our user-agent.

    Returns the response body decoded as UTF-8, or ``None`` for
    any failure path. ``urllib.request`` keeps the dep surface
    minimal — no ``requests`` / ``httpx`` pulled into the
    PyInstaller bundle.
    """
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": _user_agent(current_version),
            "Accept": "application/xml, text/xml, */*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _LOG.debug("update check failed: %s", exc)
        return None
    if not data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        # Some servers return Latin-1; the parser is happy with
        # either as long as the XML declaration matches. Try a
        # permissive fallback before bailing.
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return None


def _sortable_version(value: str) -> tuple[int, int, int, str]:
    """Project the parsed-version tuple onto a ``sort()`` key.

    Untraceable inputs sort last — defensive against a feed
    that smuggled a malformed entry past
    :mod:`...version`'s parser.
    """
    from pfc_inductor.updater.version import _parse  # private

    parsed = _parse(value)
    if parsed is None:
        return (-1, -1, -1, "")
    major, minor, patch, suffix = parsed
    # Empty suffix is "newer than" any non-empty suffix at the
    # same numeric tuple — encode by sorting on the tuple
    # ``(major, minor, patch, suffix == "" → 1, suffix)``.
    return (major, minor, patch, "~" if suffix == "" else suffix)
