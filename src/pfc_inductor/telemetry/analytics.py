"""Optional anonymous usage analytics.

A single ``track_event(name, properties=None)`` helper that
posts to a configured analytics endpoint when the user has
opted in for ``analytics`` consent and a backend has been
wired in. Otherwise it's a strict no-op so calling it from a
hot path is free.

Why this is here at all
-----------------------

Knowing which features get used (and which don't) is the
difference between maintaining the app on guesswork and
maintaining it on data. Most opt-in analytics implementations
are built around an external service (PostHog, Plausible,
Amplitude); this module is the *connector*, not the service.
Wire your preferred backend in by overriding the
``_BACKEND`` callable at process start.

Privacy guardrails (enforced here, not at the backend)
-------------------------------------------------------

- No tracking unless ``has_consent("analytics") == True``.
- No tracking when the kill-switch env var is set.
- Properties are scrubbed via :func:`scrub_event` (same path as
  crash reports) so accidental file-paths / emails / blobs
  don't leak.
- A stable, random, opaque ``distinct_id`` is generated on
  first use and persisted in the consent JSON next to the
  flags. Never PII.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Callable, Optional

from pfc_inductor.telemetry.consent import (
    _consent_file,
    has_consent,
    is_telemetry_disabled,
)
from pfc_inductor.telemetry.crashes import scrub_event

# A backend is a callable that receives ``(event_name,
# properties_dict, distinct_id)``. The default is a no-op so
# the module is safe to import everywhere; a maintainer wires
# in PostHog / Plausible / etc. by reassigning ``_BACKEND``.
Backend = Callable[[str, dict[str, Any], str], None]


def _noop_backend(_name: str, _properties: dict[str, Any],
                  _distinct_id: str) -> None:
    """Default backend — drops every event. Replace at startup
    with a real implementation if you want events to leave the
    host."""
    return


_BACKEND: Backend = _noop_backend


def set_backend(backend: Backend) -> None:
    """Override the analytics backend for this process. Useful
    for tests (assert ``track_event`` was called) and for
    plugging in PostHog / Plausible from a maintainer build."""
    global _BACKEND
    _BACKEND = backend


def track_event(
    name: str,
    properties: Optional[dict[str, Any]] = None,
) -> bool:
    """Record an opt-in usage-analytics event.

    Returns ``True`` if the event reached the configured
    backend, ``False`` for any of the consent / kill-switch /
    invalid-input no-op paths. Callers should not branch on the
    return value — the default is "we don't know whether it
    landed", and that's fine for analytics.
    """
    if is_telemetry_disabled() or not has_consent("analytics"):
        return False
    if not isinstance(name, str) or not name.strip():
        return False
    payload: dict[str, Any] = dict(properties or {})
    # Reuse the crash scrubber so the same redaction rules apply.
    payload = scrub_event({"extra": payload}) or {}
    payload = payload.get("extra", {}) if isinstance(payload, dict) else {}

    distinct_id = _distinct_id()
    try:
        _BACKEND(name, payload, distinct_id)
        return True
    except Exception:  # noqa: BLE001 — backend bugs must never crash hot paths
        return False


# ---------------------------------------------------------------------------
# Distinct-ID storage
# ---------------------------------------------------------------------------
def _distinct_id() -> str:
    """Return the persisted random distinct ID, generating it
    on first use. Not PII — opaque UUID4 stored alongside the
    consent flags."""
    path = _consent_file()
    if path.is_file():
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            payload = {}
    else:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    distinct = payload.get("distinct_id")
    if not isinstance(distinct, str) or not distinct:
        distinct = str(uuid.uuid4())
        payload["distinct_id"] = distinct
        try:
            path.write_text(json.dumps(payload, indent=2))
        except OSError:
            pass
    return distinct
