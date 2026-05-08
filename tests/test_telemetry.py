"""Telemetry — consent + scrubbing + analytics tests.

The telemetry surface is privacy-critical: a regression here
ships data the user didn't authorise. Tests cover:

- The consent state machine (not asked / opted in / opted out
  / kill-switched).
- The scrubber redacts paths, emails, and oversized blobs.
- ``init_crash_reporter`` returns False (no-op) for every
  no-op path documented in the module.
- ``track_event`` honours the consent gate + kill switch +
  hands properties through the same scrubber the crashes
  module uses.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def isolated_consent(tmp_path: Path, monkeypatch):
    """Redirect the consent JSON to a per-test tmp dir so we
    don't read or write the user's real consent state.

    Patches both:
    - ``platformdirs.user_config_dir`` so the JSON-file backend
      lands in the tmp dir.
    - The ``MAGNADESIGN_DISABLE_TELEMETRY`` env var to be cleared
      so the no-op env path doesn't shadow the actual consent
      logic we're testing.
    """
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(
        "pfc_inductor.telemetry.consent._consent_file",
        lambda: config / "consent.json",
    )
    # Patch the QSettings path to a no-op so the test doesn't
    # leak into the real registry / plist.
    monkeypatch.setattr(
        "pfc_inductor.telemetry.consent._read_qsettings",
        lambda: None,
    )
    monkeypatch.setattr(
        "pfc_inductor.telemetry.consent._write_qsettings",
        lambda payload: False,
    )
    monkeypatch.delenv("MAGNADESIGN_DISABLE_TELEMETRY", raising=False)
    yield config / "consent.json"


# ---------------------------------------------------------------------------
# Consent state
# ---------------------------------------------------------------------------
def test_consent_starts_as_not_asked(isolated_consent) -> None:
    from pfc_inductor.telemetry import consent_state

    state = consent_state()
    assert state.crashes is None
    assert state.analytics is None
    assert state.has_been_asked is False


def test_set_consent_persists(isolated_consent) -> None:
    from pfc_inductor.telemetry import consent_state, set_consent

    set_consent(crashes=True, analytics=False)
    state = consent_state()
    assert state.crashes is True
    assert state.analytics is False
    assert state.has_been_asked is True


def test_set_consent_partial_keeps_other_flag(isolated_consent) -> None:
    """Setting only ``crashes`` mustn't clobber a previously
    saved ``analytics`` answer."""
    from pfc_inductor.telemetry import consent_state, set_consent

    set_consent(analytics=True)
    set_consent(crashes=False)
    state = consent_state()
    assert state.crashes is False
    assert state.analytics is True


def test_has_consent_respects_kill_switch(
    isolated_consent, monkeypatch,
) -> None:
    from pfc_inductor.telemetry import has_consent, set_consent

    set_consent(crashes=True, analytics=True)
    monkeypatch.setenv("MAGNADESIGN_DISABLE_TELEMETRY", "1")
    assert has_consent("crashes") is False
    assert has_consent("analytics") is False


def test_is_telemetry_disabled_reads_env(monkeypatch) -> None:
    from pfc_inductor.telemetry import is_telemetry_disabled

    monkeypatch.setenv("MAGNADESIGN_DISABLE_TELEMETRY", "true")
    assert is_telemetry_disabled() is True
    monkeypatch.setenv("MAGNADESIGN_DISABLE_TELEMETRY", "0")
    assert is_telemetry_disabled() is False


# ---------------------------------------------------------------------------
# Scrubber
# ---------------------------------------------------------------------------
def test_scrub_event_redacts_home_paths() -> None:
    from pfc_inductor.telemetry import scrub_event

    home = os.path.expanduser("~")
    event = {
        "exception": {
            "values": [{
                "type": "RuntimeError",
                "value": f"failed at {home}/projects/secret.pfc",
            }],
        },
    }
    out = scrub_event(event)
    msg = out["exception"]["values"][0]["value"]
    assert home not in msg
    assert "~/projects/secret.pfc" in msg


def test_scrub_event_redacts_emails() -> None:
    from pfc_inductor.telemetry import scrub_event

    event = {"message": "user alice@example.com filed a bug"}
    out = scrub_event(event)
    assert "alice@example.com" not in out["message"]
    assert "<redacted-email>" in out["message"]


def test_scrub_event_truncates_long_blobs() -> None:
    """Strings > 200 chars get replaced with the first 60 + …
    so an accidental project-file dump can't leak."""
    from pfc_inductor.telemetry import scrub_event

    blob = "x" * 500
    event = {"extra": {"big": blob}}
    out = scrub_event(event)
    assert len(out["extra"]["big"]) < 200
    assert out["extra"]["big"].endswith("…")


def test_scrub_event_drops_project_file_breadcrumbs() -> None:
    from pfc_inductor.telemetry import scrub_event

    event = {
        "breadcrumbs": {"values": [
            {"category": "ui", "message": "click"},
            {"category": "project_file", "message": "dump"},
            {"category": "engine", "message": "design"},
        ]},
    }
    out = scrub_event(event)
    cats = [bc["category"] for bc in out["breadcrumbs"]["values"]]
    assert "project_file" not in cats
    assert "ui" in cats and "engine" in cats


def test_scrub_event_returns_none_for_non_dict() -> None:
    from pfc_inductor.telemetry import scrub_event

    assert scrub_event("not a dict") is None
    assert scrub_event([1, 2, 3]) is None


# ---------------------------------------------------------------------------
# init_crash_reporter
# ---------------------------------------------------------------------------
def test_init_crash_reporter_is_noop_without_consent(
    isolated_consent,
) -> None:
    from pfc_inductor.telemetry import init_crash_reporter

    assert init_crash_reporter() is False


def test_init_crash_reporter_is_noop_when_disabled(
    isolated_consent, monkeypatch,
) -> None:
    from pfc_inductor.telemetry import init_crash_reporter, set_consent

    set_consent(crashes=True)
    monkeypatch.setenv("MAGNADESIGN_DISABLE_TELEMETRY", "1")
    assert init_crash_reporter() is False


def test_init_crash_reporter_is_noop_without_dsn(
    isolated_consent, monkeypatch,
) -> None:
    """Even with consent + SDK installed, no DSN → no-op."""
    from pfc_inductor.telemetry import init_crash_reporter, set_consent

    set_consent(crashes=True)
    monkeypatch.delenv("MAGNADESIGN_SENTRY_DSN", raising=False)
    assert init_crash_reporter() is False


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
def test_track_event_is_noop_without_consent(isolated_consent) -> None:
    from pfc_inductor.telemetry import track_event

    assert track_event("test_event", {"k": "v"}) is False


def test_track_event_calls_backend_when_consented(
    isolated_consent,
) -> None:
    from pfc_inductor.telemetry import set_consent, track_event
    from pfc_inductor.telemetry.analytics import set_backend

    received: list[tuple[str, dict, str]] = []

    def _capture(name, properties, distinct_id):
        received.append((name, properties, distinct_id))

    set_backend(_capture)
    try:
        set_consent(crashes=False, analytics=True)
        ok = track_event("opened_project",
                         {"topology": "boost_ccm"})
        assert ok is True
        assert len(received) == 1
        name, props, did = received[0]
        assert name == "opened_project"
        assert props == {"topology": "boost_ccm"}
        # distinct_id is a UUID4; just verify it's a non-empty
        # opaque string.
        assert isinstance(did, str)
        assert len(did) >= 32
    finally:
        # Restore the no-op backend so subsequent tests aren't
        # polluted.
        from pfc_inductor.telemetry.analytics import _noop_backend
        set_backend(_noop_backend)


def test_track_event_scrubs_properties(isolated_consent) -> None:
    """Properties get scrubbed via ``scrub_event`` before they
    reach the backend — the user's filesystem must not leak."""
    from pfc_inductor.telemetry import set_consent, track_event
    from pfc_inductor.telemetry.analytics import set_backend

    received: dict = {}

    def _capture(name, properties, distinct_id):
        received["properties"] = properties

    set_backend(_capture)
    try:
        set_consent(analytics=True)
        home = os.path.expanduser("~")
        track_event("opened", {
            "path": f"{home}/secret/foo.pfc",
            "email": "alice@example.com",
        })
        props = received.get("properties", {})
        assert home not in str(props)
        assert "alice@example.com" not in str(props)
    finally:
        from pfc_inductor.telemetry.analytics import _noop_backend
        set_backend(_noop_backend)


def test_track_event_blocks_empty_name(isolated_consent) -> None:
    from pfc_inductor.telemetry import set_consent, track_event

    set_consent(analytics=True)
    assert track_event("") is False
    assert track_event("   ") is False
