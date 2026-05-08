"""Sparkle-style appcast XML parser.

Sparkle's appcast format is an RSS 2.0 feed with a
``sparkle:`` extension namespace. We accept the canonical
shape and ignore unknown elements:

.. code-block:: xml

    <?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"
         xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
      <channel>
        <title>MagnaDesign updates</title>
        <link>https://magnadesign.dev/appcast.xml</link>
        <description>Stable releases of MagnaDesign.</description>
        <item>
          <title>v0.7.0</title>
          <pubDate>Thu, 08 May 2026 12:00:00 +0000</pubDate>
          <sparkle:version>0.7.0</sparkle:version>
          <sparkle:shortVersionString>0.7.0</sparkle:shortVersionString>
          <sparkle:minimumSystemVersion>11.0</sparkle:minimumSystemVersion>
          <description>...release notes html...</description>
          <enclosure
              url="https://github.com/.../MagnaDesign-0.7.0-arm64.dmg"
              length="289345234"
              type="application/octet-stream"
              sparkle:edSignature="<base64-ed25519>"/>
        </item>
        <!-- more <item> entries ... -->
      </channel>
    </rss>

Parser is **defensive**: malformed XML, missing namespace
declarations, or out-of-order elements all degrade to "no
update available" rather than raising — surfacing a network
error to the user is helpful; surfacing an XML parse error is
not.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

# Sparkle XML namespace — items use ``sparkle:version`` etc.
_NS = {"sparkle": "http://www.andymatuschak.org/xml-namespaces/sparkle"}


@dataclass(frozen=True)
class AppcastEntry:
    """One entry in the appcast — typically one per release tag.

    All fields are optional except ``version``; consumers that
    care about a specific field check for ``None`` first.
    """

    version: str
    """Canonical semantic version (``"0.7.0"`` / ``"0.7.0-rc1"``)."""

    title: Optional[str] = None
    """Release title (typically the tag name)."""

    pub_date: Optional[str] = None
    """RFC-822 publish date."""

    minimum_system_version: Optional[str] = None
    """Minimum OS version required (Sparkle's ``minimumSystemVersion``)."""

    description_html: Optional[str] = None
    """Release notes — HTML or plain text."""

    download_url: Optional[str] = None
    """Direct URL to the platform-specific artefact (``.dmg``,
    ``.msi``, etc.)."""

    download_size_bytes: Optional[int] = None
    """``length`` attribute on the ``enclosure`` tag."""

    signature_b64: Optional[str] = None
    """Base64-encoded Ed25519 signature
    (``sparkle:edSignature``). ``None`` for unsigned releases —
    the verifier degrades to a warning when this is missing."""

    short_version_string: Optional[str] = None
    """Sparkle's user-facing version string (often the same as
    ``version``)."""


def parse_appcast(xml_text: str) -> list[AppcastEntry]:
    """Parse the appcast XML and return every entry, newest-first.

    Returns an empty list for any malformed-XML / missing-channel
    / no-items path — a defensive parser is more useful than a
    raising one in the auto-update hot path.
    """
    if not isinstance(xml_text, str) or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    entries: list[AppcastEntry] = []
    for item in channel.findall("item"):
        entry = _parse_item(item)
        if entry is not None:
            entries.append(entry)
    return entries


def _parse_item(item: ET.Element) -> Optional[AppcastEntry]:
    """Convert one ``<item>`` to an :class:`AppcastEntry`. Returns
    ``None`` when the item lacks a parseable version — the only
    field we treat as required."""
    version = _findtext(item, "sparkle:version")
    if not version:
        # Some feeds put the canonical version in
        # ``shortVersionString`` instead. Fall back gracefully.
        version = _findtext(item, "sparkle:shortVersionString")
    if not version:
        return None

    enclosure = item.find("enclosure")
    download_url: Optional[str] = None
    download_size: Optional[int] = None
    signature_b64: Optional[str] = None
    if enclosure is not None:
        download_url = enclosure.get("url") or None
        size_str = enclosure.get("length")
        if size_str and size_str.isdigit():
            download_size = int(size_str)
        # Sparkle's signature attribute name; fall back to the
        # legacy DSA attribute too.
        signature_b64 = (
            enclosure.get(f"{{{_NS['sparkle']}}}edSignature")
            or enclosure.get(f"{{{_NS['sparkle']}}}dsaSignature")
            or None
        )

    return AppcastEntry(
        version=version.strip(),
        title=_findtext(item, "title"),
        pub_date=_findtext(item, "pubDate"),
        minimum_system_version=_findtext(item, "sparkle:minimumSystemVersion"),
        description_html=_findtext(item, "description"),
        download_url=download_url,
        download_size_bytes=download_size,
        signature_b64=signature_b64,
        short_version_string=_findtext(item, "sparkle:shortVersionString"),
    )


def _findtext(item: ET.Element, tag: str) -> Optional[str]:
    """``element.findtext`` with namespace expansion + an empty-
    string→None coercion."""
    if ":" in tag:
        prefix, local = tag.split(":", 1)
        ns = _NS.get(prefix)
        if ns is None:
            return None
        text = item.findtext(f"{{{ns}}}{local}")
    else:
        text = item.findtext(tag)
    if text is None:
        return None
    text = text.strip()
    return text or None
