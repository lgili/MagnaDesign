"""Consent state — crash reports + analytics flags.

Persisted in ``QSettings`` when Qt is available; falls back to a
JSON file under ``platformdirs.user_config_dir("MagnaDesign")``
so the CLI path works without a Qt application.

State shape::

    {
        "version": 1,
        "crashes": <bool|None>,
        "analytics": <bool|None>,
        "asked_at": "<ISO date>"
    }

``None`` means "user hasn't been asked yet" — the consent dialog
should fire on next GUI launch. ``True`` / ``False`` are
explicit answers and are honoured forever (the user can always
flip the toggle in Settings → Privacy).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

# Disable-everything escape hatch — set this env var in CI or in
# any pipeline that absolutely must not phone home. Bypasses the
# user's saved consent if it's somehow True.
TELEMETRY_DISABLED_ENV = "MAGNADESIGN_DISABLE_TELEMETRY"


@dataclass(frozen=True)
class ConsentState:
    """Frozen snapshot of the user's consent answers."""

    crashes: Optional[bool]
    analytics: Optional[bool]
    asked_at: Optional[str] = None

    @property
    def has_been_asked(self) -> bool:
        """``True`` if the user has answered the dialog at least
        once. The first-run dialog should fire when this is
        ``False``."""
        return self.crashes is not None or self.analytics is not None


def consent_state() -> ConsentState:
    """Return the current persisted consent state.

    Reads from QSettings when Qt is available; otherwise reads
    from ``platformdirs.user_config_dir / consent.json``.
    Missing / malformed state returns the "not asked" default.
    """
    payload = _read_qsettings() or _read_json_file() or {}
    if not isinstance(payload, dict):
        payload = {}
    return _coerce(payload)


def set_consent(
    *,
    crashes: Optional[bool] = None,
    analytics: Optional[bool] = None,
) -> ConsentState:
    """Update the consent state. Pass either flag or both — the
    other field is left at its current value.

    Returns the new :class:`ConsentState`. Persists to QSettings
    when available, otherwise to the JSON file.
    """
    current = consent_state()
    payload = {
        "version": 1,
        "crashes": _coerce_bool(
            crashes if crashes is not None else current.crashes,
        ),
        "analytics": _coerce_bool(
            analytics if analytics is not None else current.analytics,
        ),
        "asked_at": datetime.now(UTC).date().isoformat(),
    }
    if not _write_qsettings(payload):
        _write_json_file(payload)
    return _coerce(payload)


def has_consent(kind: str) -> bool:
    """Convenience: returns ``True`` only when the user has
    explicitly opted in for ``kind`` and the disable-everything
    env var isn't set."""
    if is_telemetry_disabled():
        return False
    state = consent_state()
    if kind == "crashes":
        return state.crashes is True
    if kind == "analytics":
        return state.analytics is True
    return False


def is_telemetry_disabled() -> bool:
    """Hard kill switch — set ``MAGNADESIGN_DISABLE_TELEMETRY=1``
    in CI / offscreen / corporate sandbox environments. Wins
    over saved consent."""
    val = os.environ.get(TELEMETRY_DISABLED_ENV, "").strip().lower()
    return val in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Storage backends
# ---------------------------------------------------------------------------
def _read_qsettings() -> Optional[dict]:
    try:
        from PySide6.QtCore import QSettings
    except ImportError:
        return None
    settings = QSettings("MagnaDesign", "MagnaDesign")
    raw = settings.value("telemetry/consent", None)
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    if isinstance(raw, dict):
        return raw
    return None


def _write_qsettings(payload: dict) -> bool:
    """Write to QSettings; returns False when Qt isn't available
    so the caller falls back to the JSON file."""
    try:
        from PySide6.QtCore import QSettings
    except ImportError:
        return False
    settings = QSettings("MagnaDesign", "MagnaDesign")
    settings.setValue("telemetry/consent", json.dumps(payload))
    settings.sync()
    return True


def _consent_file() -> Path:
    try:
        from platformdirs import user_config_dir

        base = Path(user_config_dir("MagnaDesign"))
    except ImportError:
        base = Path.home() / ".config" / "MagnaDesign"
    base.mkdir(parents=True, exist_ok=True)
    return base / "consent.json"


def _read_json_file() -> Optional[dict]:
    path = _consent_file()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_json_file(payload: dict) -> None:
    path = _consent_file()
    path.write_text(json.dumps(payload, indent=2))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _coerce(payload: dict) -> ConsentState:
    return ConsentState(
        crashes=_coerce_bool(payload.get("crashes")),
        analytics=_coerce_bool(payload.get("analytics")),
        asked_at=str(payload["asked_at"])
        if payload.get("asked_at")
        else None,
    )


def _coerce_bool(value) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"true", "1", "yes", "on"}:
            return True
        if s in {"false", "0", "no", "off"}:
            return False
    return None
