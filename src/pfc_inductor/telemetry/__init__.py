"""Opt-in telemetry — crash reports + usage analytics.

Two subsystems live here, both **disabled by default** and gated
on explicit user consent persisted via QSettings (or a plain
JSON file when Qt isn't available, so the CLI flow works too):

- :mod:`pfc_inductor.telemetry.crashes` — Sentry-SDK glue with
  per-event scrubbing (filesystem paths, email-shaped strings,
  project-file blobs).
- :mod:`pfc_inductor.telemetry.analytics` — minimal opt-in
  ``track_event(name, properties)`` no-op-by-default helper.

Why opt-in
----------

A tool that phones home without asking gets thrown out by every
quality / IT team in industries we care about (compressor OEMs,
PSU manufacturers, automotive Tier 1s). The cost of asking is a
single first-run dialog; the cost of *not* asking is being
banned from the corporate sandbox.

Defensive imports
-----------------

The Sentry SDK is an *optional* dependency (``[telemetry]``
extra). Every public API in this package is a no-op when:

- The SDK isn't installed (``ModuleNotFoundError`` on
  ``import sentry_sdk``).
- The user hasn't consented yet (``has_consent() == False``).
- The DSN isn't configured (``DSN_PLACEHOLDER`` or empty).
- The runtime is in a CI / offscreen / disabled-telemetry env.

The "no-op" path returns ``False`` from :func:`init_crash_reporter`
so the caller can decide whether to log a startup line.
"""
from __future__ import annotations

from pfc_inductor.telemetry.consent import (
    consent_state,
    set_consent,
    has_consent,
    is_telemetry_disabled,
)
from pfc_inductor.telemetry.crashes import (
    init_crash_reporter,
    scrub_event,
)
from pfc_inductor.telemetry.analytics import (
    track_event,
)

__all__ = [
    "consent_state",
    "has_consent",
    "init_crash_reporter",
    "is_telemetry_disabled",
    "scrub_event",
    "set_consent",
    "track_event",
]
