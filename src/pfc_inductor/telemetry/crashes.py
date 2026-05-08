"""Sentry crash-reporter glue.

Every public entry point is **opt-in** and **defensive**:

- :func:`init_crash_reporter` is a no-op unless the user has
  consented (``has_consent("crashes")``), the SDK is installed,
  and a DSN has been configured.
- :func:`scrub_event` is the ``before_send`` hook — strips
  filesystem paths, email-shaped strings, and project-file
  blobs before the event leaves the host.

Configuring the DSN
-------------------

The DSN is the only piece a maintainer needs to plug in.
Possible sources, checked in order:

1. ``MAGNADESIGN_SENTRY_DSN`` environment variable.
2. A maintainer-provided ``_dsn.py`` shipped in this package
   (gitignored — never bake a real DSN into the public repo).
3. ``None`` → the reporter stays a no-op.

DSNs are non-secret by design (Sentry's threat model treats
them as public), but committing one to a public repo invites
abuse from random GitHub crawlers, so the env-var path is
preferred for downstream forks.
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional

from pfc_inductor.telemetry.consent import has_consent, is_telemetry_disabled

# A DSN looks like ``https://<key>@<host>/<project_id>``. Empty
# string disables the reporter; that's the shipped default.
DSN_PLACEHOLDER = ""

# Regex used to redact email addresses from breadcrumbs / message
# bodies. Conservative: matches ``foo@bar.tld`` shapes.
_EMAIL_RE = re.compile(
    r"[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}",
)
# Long opaque blobs (base64-ish dumps) get redacted past this
# length. Catches most accidental "the whole project file
# survived to the breadcrumb" cases.
_MAX_STRING_LEN = 200


def init_crash_reporter(
    *,
    dsn: Optional[str] = None,
    env: str = "prod",
) -> bool:
    """Initialise Sentry. Returns ``True`` if it actually
    initialised, ``False`` for any of the no-op paths.

    The no-op paths are intentional — see the module docstring.
    Callers should not branch on the return value beyond an
    optional "telemetry: enabled" startup line.
    """
    if is_telemetry_disabled() or not has_consent("crashes"):
        return False
    dsn = dsn or os.environ.get("MAGNADESIGN_SENTRY_DSN") or DSN_PLACEHOLDER
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=env,
        # Heavy events stay off — we only want crashes + their
        # tracebacks, not transaction traces.
        traces_sample_rate=0.0,
        # Before-send hook runs scrubbing on every event.
        before_send=scrub_event,
        # Auto-detected versions land as tags below.
        send_default_pii=False,
        attach_stacktrace=True,
        max_breadcrumbs=20,
    )
    _set_release_tags(sentry_sdk)
    return True


def scrub_event(
    event: dict[str, Any],
    _hint: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """``before_send`` hook — return the event after redacting
    sensitive fields, or ``None`` to drop it entirely.

    Behaviour:

    - Replace any path under ``$HOME`` with ``~/...``.
    - Replace any email-shaped string with ``<redacted-email>``.
    - Replace strings longer than ``_MAX_STRING_LEN`` with the
      first 60 chars + ``…`` so a stray project-file dump can't
      leave the host intact.
    - Drop breadcrumbs whose ``category == "project_file"``.
    """
    if not isinstance(event, dict):
        return None
    home = str(os.path.expanduser("~"))
    _walk_and_scrub(event, home)
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        values = breadcrumbs.get("values")
        if isinstance(values, list):
            breadcrumbs["values"] = [
                bc
                for bc in values
                if not (isinstance(bc, dict) and bc.get("category") == "project_file")
            ]
    return event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _walk_and_scrub(node: Any, home: str) -> None:
    """Recursively scrub a nested dict/list in place."""
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if isinstance(value, str):
                node[key] = _scrub_string(value, home)
            else:
                _walk_and_scrub(value, home)
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            if isinstance(value, str):
                node[idx] = _scrub_string(value, home)
            else:
                _walk_and_scrub(value, home)


def _scrub_string(value: str, home: str) -> str:
    """Apply the three string-level scrubs."""
    if not value:
        return value
    if home and home in value:
        value = value.replace(home, "~")
    value = _EMAIL_RE.sub("<redacted-email>", value)
    if len(value) > _MAX_STRING_LEN:
        value = value[:60] + "…"
    return value


def _set_release_tags(sentry_sdk) -> None:
    """Attach the canonical release / OS / Qt tags so events are
    bucketed by version + platform without further wiring."""
    import platform

    try:
        from importlib.metadata import version as _v

        release = _v("magnadesign")
    except Exception:
        release = "unknown"

    try:
        from PySide6 import __version__ as qt_version
    except ImportError:
        qt_version = "no-qt"

    sentry_sdk.set_tag("app_version", release)
    sentry_sdk.set_tag("python_version", platform.python_version())
    sentry_sdk.set_tag("os", platform.system().lower())
    sentry_sdk.set_tag("arch", platform.machine().lower())
    sentry_sdk.set_tag("qt_version", str(qt_version))
