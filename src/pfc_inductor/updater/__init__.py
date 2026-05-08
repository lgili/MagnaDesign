"""Auto-update — opt-in appcast polling + Ed25519 signature verify.

Sparkle's appcast format is the de-facto standard for desktop
auto-update on macOS, and Windows / Linux ports (Squirrel,
WinSparkle) speak the same XML schema. We keep the format
canonical so a single ``appcast.xml`` published to GitHub Pages
serves all three platforms.

Public API
----------

- :func:`check_for_updates` — top-level entry point. Returns a
  :class:`UpdateInfo` describing the latest release, or
  ``None`` when no update is available, the user opted out, or
  the network call failed.
- :func:`parse_appcast` — pure parser of the XML payload
  (testable without network).
- :func:`verify_signature` — Ed25519 verification using
  ``cryptography``. Falls back gracefully when the dep isn't
  installed (degrades to "no verification" with an explicit
  warning).
- :class:`AppcastEntry` / :class:`UpdateInfo` — typed payload.

Privacy + opt-in
----------------

The updater **does not poll on its own**. The only entry point
is :func:`check_for_updates`, which:

1. Honours the ``MAGNADESIGN_DISABLE_TELEMETRY`` env-var hard
   kill switch (matches the crash reporter's contract).
2. Returns ``None`` for any error path — never raises into the
   GUI thread.
3. Sends only the user-agent string ``magnadesign/<version>
   <os>/<arch>`` with the request — no PII, no project data.

The GUI's "Check for updates…" menu item calls this function on
demand. The "Auto-check at startup" toggle is persisted in
``QSettings`` and gates a one-shot call after MainWindow
initialisation.
"""

from __future__ import annotations

from pfc_inductor.updater.appcast import (
    AppcastEntry,
    parse_appcast,
)
from pfc_inductor.updater.client import (
    UpdateInfo,
    check_for_updates,
)
from pfc_inductor.updater.signature import (
    SignatureCheckResult,
    verify_signature,
)
from pfc_inductor.updater.version import (
    is_newer_version,
)

__all__ = [
    "AppcastEntry",
    "SignatureCheckResult",
    "UpdateInfo",
    "check_for_updates",
    "is_newer_version",
    "parse_appcast",
    "verify_signature",
]
