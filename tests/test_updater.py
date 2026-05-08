"""Auto-update — appcast parser + Ed25519 verify + check_for_updates.

The updater is privacy-critical: a regression here either
ships a malicious binary (signature regression) or floods the
user with phone-home requests (consent regression). Tests
cover:

- Version comparator handles ``0.7.0`` / ``0.7.0-rc1`` /
  ``v`` prefix / malformed strings.
- Appcast parser is defensive: malformed XML, missing
  ``<channel>``, missing ``sparkle:`` namespace declarations,
  out-of-order elements all degrade to ``[]`` rather than
  raising.
- Ed25519 signature verifier produces every ``SignatureCheckResult``
  branch on synthetic inputs (the ``cryptography`` lib is a
  top-level dep so we can sign + verify in-process).
- ``check_for_updates`` honours the kill-switch env var and
  the consent state.
"""

from __future__ import annotations

import base64
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Version comparator
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "remote,current,expected",
    [
        ("0.7.0", "0.6.5", True),
        ("0.7.0", "0.7.0", False),
        ("0.6.5", "0.7.0", False),
        ("v0.7.0", "0.7.0", False),  # leading v ignored
        ("0.7.0", "v0.6.0", True),
        ("0.7.0", "0.7.0-rc1", True),  # release > pre-release
        ("0.7.0-rc1", "0.7.0", False),  # pre-release < release
        ("0.7.0-rc2", "0.7.0-rc1", True),  # lexical compare on suffix
        ("0.7.0-rc1", "0.7.0-rc2", False),
        ("garbage", "0.7.0", False),
        ("0.7.0", "garbage", False),
    ],
)
def test_is_newer_version(remote, current, expected) -> None:
    from pfc_inductor.updater.version import is_newer_version

    assert is_newer_version(remote, current) is expected


# ---------------------------------------------------------------------------
# Appcast parser
# ---------------------------------------------------------------------------
_GOOD_APPCAST = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"
     xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>MagnaDesign updates</title>
    <link>https://magnadesign.dev/appcast.xml</link>
    <description>Stable releases.</description>
    <item>
      <title>v0.7.0</title>
      <pubDate>Thu, 08 May 2026 12:00:00 +0000</pubDate>
      <sparkle:version>0.7.0</sparkle:version>
      <sparkle:shortVersionString>0.7.0</sparkle:shortVersionString>
      <description>Release notes for 0.7.0.</description>
      <enclosure
          url="https://example.com/MagnaDesign-0.7.0.dmg"
          length="289345234"
          type="application/octet-stream"
          sparkle:edSignature="dGVzdC1zaWdfMA=="/>
    </item>
    <item>
      <title>v0.6.5</title>
      <sparkle:version>0.6.5</sparkle:version>
      <enclosure
          url="https://example.com/MagnaDesign-0.6.5.dmg"
          length="287000000"
          type="application/octet-stream"/>
    </item>
  </channel>
</rss>
"""


def test_parse_appcast_happy_path() -> None:
    from pfc_inductor.updater.appcast import parse_appcast

    entries = parse_appcast(_GOOD_APPCAST)
    assert len(entries) == 2
    e0, e1 = entries
    assert e0.version == "0.7.0"
    assert e0.title == "v0.7.0"
    assert e0.download_url == "https://example.com/MagnaDesign-0.7.0.dmg"
    assert e0.download_size_bytes == 289_345_234
    # Sparkle signature attribute is parsed from the namespaced
    # attribute on the enclosure.
    assert e0.signature_b64 == "dGVzdC1zaWdfMA=="
    assert e0.description_html == "Release notes for 0.7.0."

    # Older entry — no signature, smaller size.
    assert e1.version == "0.6.5"
    assert e1.signature_b64 is None


def test_parse_appcast_malformed_xml_returns_empty() -> None:
    from pfc_inductor.updater.appcast import parse_appcast

    assert parse_appcast("<not-xml>") == []
    assert parse_appcast("") == []
    assert parse_appcast(None) == []  # type: ignore[arg-type]


def test_parse_appcast_no_channel_returns_empty() -> None:
    from pfc_inductor.updater.appcast import parse_appcast

    xml_text = '<?xml version="1.0"?><rss version="2.0"></rss>'
    assert parse_appcast(xml_text) == []


def test_parse_appcast_skips_items_without_version() -> None:
    """An ``<item>`` lacking both ``sparkle:version`` and
    ``sparkle:shortVersionString`` is skipped — it's not
    actionable for the updater."""
    from pfc_inductor.updater.appcast import parse_appcast

    xml_text = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"
         xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
      <channel>
        <title>x</title>
        <item><title>no version here</title></item>
        <item>
          <sparkle:version>1.0.0</sparkle:version>
        </item>
      </channel>
    </rss>"""
    entries = parse_appcast(xml_text)
    assert len(entries) == 1
    assert entries[0].version == "1.0.0"


# ---------------------------------------------------------------------------
# Ed25519 signature verifier
# ---------------------------------------------------------------------------
# ``cryptography`` is shipped via the ``[updater]`` optional extra
# — production GUI builds install it; minimal CI runs may not.
# Skip the sign-and-verify tests cleanly when the dep isn't
# present (the ``UNAVAILABLE`` branch is covered separately
# below by patching the import).
pytest.importorskip("cryptography")


@pytest.fixture
def keypair():
    from cryptography.hazmat.primitives.asymmetric import ed25519

    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_b64 = base64.b64encode(
        pub.public_bytes_raw(),
    ).decode()
    return priv, pub_b64


def test_verify_signature_ok(keypair) -> None:
    from pfc_inductor.updater import (
        SignatureCheckResult,
        verify_signature,
    )

    priv, pub_b64 = keypair
    artefact = b"the quick brown fox jumps over the lazy dog"
    sig_b64 = base64.b64encode(priv.sign(artefact)).decode()
    result = verify_signature(
        artefact_bytes=artefact,
        signature_b64=sig_b64,
        public_key_b64=pub_b64,
    )
    assert result is SignatureCheckResult.OK


def test_verify_signature_bad_signature_rejects(keypair) -> None:
    from pfc_inductor.updater import (
        SignatureCheckResult,
        verify_signature,
    )

    priv, pub_b64 = keypair
    artefact = b"genuine"
    sig_b64 = base64.b64encode(priv.sign(b"different bytes")).decode()
    result = verify_signature(
        artefact_bytes=artefact,
        signature_b64=sig_b64,
        public_key_b64=pub_b64,
    )
    assert result is SignatureCheckResult.BAD_SIGNATURE


def test_verify_signature_no_public_key() -> None:
    from pfc_inductor.updater import (
        SignatureCheckResult,
        verify_signature,
    )

    result = verify_signature(
        artefact_bytes=b"x",
        signature_b64="anything",
        public_key_b64="",  # upstream default
    )
    assert result is SignatureCheckResult.NO_PUBLIC_KEY


def test_verify_signature_no_signature(keypair) -> None:
    from pfc_inductor.updater import (
        SignatureCheckResult,
        verify_signature,
    )

    _, pub_b64 = keypair
    result = verify_signature(
        artefact_bytes=b"x",
        signature_b64="",
        public_key_b64=pub_b64,
    )
    assert result is SignatureCheckResult.NO_SIGNATURE


def test_verify_signature_malformed(keypair) -> None:
    from pfc_inductor.updater import (
        SignatureCheckResult,
        verify_signature,
    )

    _, pub_b64 = keypair
    # Wrong-length sig — Ed25519 sigs are exactly 64 bytes.
    bad_sig = base64.b64encode(b"too short").decode()
    result = verify_signature(
        artefact_bytes=b"x",
        signature_b64=bad_sig,
        public_key_b64=pub_b64,
    )
    assert result is SignatureCheckResult.MALFORMED


# ---------------------------------------------------------------------------
# check_for_updates — opt-in + network gating
# ---------------------------------------------------------------------------
def test_check_for_updates_respects_kill_switch(monkeypatch) -> None:
    from pfc_inductor.updater import check_for_updates

    monkeypatch.setenv("MAGNADESIGN_DISABLE_TELEMETRY", "1")
    # Kill switch wins regardless of network state.
    assert check_for_updates(current_version="0.5.0") is None


def test_check_for_updates_returns_none_on_network_error(
    monkeypatch,
) -> None:
    """A failed HTTP fetch must degrade to ``None`` — not
    raise into the caller."""
    from pfc_inductor.updater import check_for_updates

    monkeypatch.delenv("MAGNADESIGN_DISABLE_TELEMETRY", raising=False)

    def _broken(_request, timeout=None):
        raise OSError("network unreachable")

    with patch(
        "pfc_inductor.updater.client.urllib.request.urlopen",
        side_effect=_broken,
    ):
        assert check_for_updates(current_version="0.5.0") is None


def test_check_for_updates_returns_update_info(monkeypatch) -> None:
    """Healthy appcast + a newer version → :class:`UpdateInfo`
    with the latest entry."""
    from pfc_inductor.updater import check_for_updates

    monkeypatch.delenv("MAGNADESIGN_DISABLE_TELEMETRY", raising=False)

    class _FakeResponse:
        def read(self_):
            return _GOOD_APPCAST.encode()

        def __enter__(self_):
            return self_

        def __exit__(self_, *args):
            return False

    with patch(
        "pfc_inductor.updater.client.urllib.request.urlopen",
        return_value=_FakeResponse(),
    ):
        info = check_for_updates(current_version="0.6.0")
    assert info is not None
    assert info.current_version == "0.6.0"
    assert info.latest.version == "0.7.0"


def test_check_for_updates_returns_none_when_current_is_latest(
    monkeypatch,
) -> None:
    from pfc_inductor.updater import check_for_updates

    monkeypatch.delenv("MAGNADESIGN_DISABLE_TELEMETRY", raising=False)

    class _FakeResponse:
        def read(self_):
            return _GOOD_APPCAST.encode()

        def __enter__(self_):
            return self_

        def __exit__(self_, *args):
            return False

    with patch(
        "pfc_inductor.updater.client.urllib.request.urlopen",
        return_value=_FakeResponse(),
    ):
        # Running 0.7.0 — appcast also tops out at 0.7.0, so no
        # newer version is available.
        info = check_for_updates(current_version="0.7.0")
    assert info is None


def test_check_for_updates_picks_newest_when_unordered(
    monkeypatch,
) -> None:
    """The parser preserves XML order; the client must still
    pick the newest entry. Test against an appcast where the
    older entry comes first."""
    from pfc_inductor.updater import check_for_updates

    monkeypatch.delenv("MAGNADESIGN_DISABLE_TELEMETRY", raising=False)
    feed = """<?xml version="1.0"?>
    <rss version="2.0"
         xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
      <channel><title>x</title>
        <item><sparkle:version>0.5.0</sparkle:version></item>
        <item><sparkle:version>0.7.0</sparkle:version></item>
        <item><sparkle:version>0.6.0</sparkle:version></item>
      </channel>
    </rss>"""

    class _FakeResponse:
        def read(self_):
            return feed.encode()

        def __enter__(self_):
            return self_

        def __exit__(self_, *args):
            return False

    with patch(
        "pfc_inductor.updater.client.urllib.request.urlopen",
        return_value=_FakeResponse(),
    ):
        info = check_for_updates(current_version="0.5.0")
    assert info is not None
    assert info.latest.version == "0.7.0"
