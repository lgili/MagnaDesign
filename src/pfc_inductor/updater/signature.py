"""Ed25519 signature verification for appcast enclosures.

Sparkle's ``sign_update`` tool produces an Ed25519 signature of
the artefact's bytes, base64-encoded, attached as the
``sparkle:edSignature`` attribute on the appcast ``<enclosure>``.
The updater verifies the signature **before** it offers the
download to the user — a malicious appcast can't push a bogus
binary if the maintainer's public key is pinned in the build.

Public-key configuration
------------------------

The maintainer pins the Ed25519 public key (32 bytes,
base64-encoded) in :data:`PUBLIC_KEY_BASE64`. A maintainer fork
overrides this constant in their build; the upstream ships an
empty string so the verifier returns
:class:`SignatureCheckResult.NO_PUBLIC_KEY` instead of accepting
unsigned releases by default.

Defensive imports
-----------------

The ``cryptography`` library is a top-level dep (used by
ReportLab font registration), but if it ever becomes optional
the verifier returns :class:`SignatureCheckResult.UNAVAILABLE`
so the GUI can show a clear "verification disabled" warning.
"""

from __future__ import annotations

import base64
from enum import Enum

# 32-byte Ed25519 public key (base64). Empty by default — the
# maintainer build overrides this constant from a build-time
# secret. Never commit a real key to the public repo.
PUBLIC_KEY_BASE64: str = ""


class SignatureCheckResult(Enum):
    """Result of verifying an appcast enclosure's signature."""

    OK = "ok"
    """Signature matches the artefact's bytes under the pinned
    public key."""

    BAD_SIGNATURE = "bad_signature"
    """Signature is well-formed but doesn't match the artefact —
    refuse to install."""

    NO_PUBLIC_KEY = "no_public_key"
    """Maintainer hasn't pinned a public key. Returned by the
    upstream build; downstream maintainer forks override
    ``PUBLIC_KEY_BASE64``."""

    NO_SIGNATURE = "no_signature"
    """Appcast entry lacks a ``sparkle:edSignature`` — either an
    older release or an intermediate hot-fix. The GUI shows a
    "verification skipped" warning."""

    UNAVAILABLE = "unavailable"
    """``cryptography`` not installed — verifier can't run.
    Should never happen in a shipped build but keeps the API
    self-describing for tests / dev environments."""

    MALFORMED = "malformed"
    """Signature or public key isn't valid base64 / wrong
    length. Defensive — refuse to install."""


def verify_signature(
    *,
    artefact_bytes: bytes,
    signature_b64: str,
    public_key_b64: str = "",
) -> SignatureCheckResult:
    """Verify an Ed25519 signature against the artefact's bytes.

    Parameters
    ----------
    artefact_bytes
        The full binary the user is about to install. Read into
        memory by the updater after downloading (≤ 350 MB
        typical — fits comfortably in modern RAM).
    signature_b64
        Base64-encoded 64-byte Ed25519 signature from the
        appcast's ``sparkle:edSignature`` attribute.
    public_key_b64
        Base64-encoded 32-byte Ed25519 public key. Defaults to
        :data:`PUBLIC_KEY_BASE64` so the maintainer build's
        pinned key is automatic.

    Returns
    -------
    A :class:`SignatureCheckResult`. The GUI maps each enum
    value to a user-facing message.
    """
    pub_key = (public_key_b64 or PUBLIC_KEY_BASE64).strip()
    if not pub_key:
        return SignatureCheckResult.NO_PUBLIC_KEY
    if not signature_b64 or not signature_b64.strip():
        return SignatureCheckResult.NO_SIGNATURE
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric import (
            ed25519,
        )
    except ImportError:
        return SignatureCheckResult.UNAVAILABLE

    try:
        pub_key_bytes = base64.b64decode(pub_key, validate=True)
        signature_bytes = base64.b64decode(
            signature_b64,
            validate=True,
        )
    except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
        return SignatureCheckResult.MALFORMED
    if len(pub_key_bytes) != 32:
        return SignatureCheckResult.MALFORMED
    if len(signature_bytes) != 64:
        return SignatureCheckResult.MALFORMED

    try:
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(
            pub_key_bytes,
        )
    except Exception:
        return SignatureCheckResult.MALFORMED
    try:
        public_key.verify(signature_bytes, artefact_bytes)
    except InvalidSignature:
        return SignatureCheckResult.BAD_SIGNATURE
    except Exception:
        return SignatureCheckResult.MALFORMED
    return SignatureCheckResult.OK
