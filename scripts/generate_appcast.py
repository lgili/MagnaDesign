"""Generate ``appcast.xml`` for the auto-updater.

Reads release metadata from the GitHub Releases API (via
``gh release list --json …`` to avoid pulling a real HTTP
client into the bundle) and emits a Sparkle-style appcast XML
file. Each ``<item>`` carries the version, release notes,
download URL, size, and (optionally) the Ed25519 signature
produced by Sparkle's ``sign_update`` tool.

Invocation
----------

::

    python scripts/generate_appcast.py \
        --output appcast.xml \
        --signing-key path/to/ed25519.priv \
        --base-url https://github.com/lgili/MagnaDesign/releases

The CI workflow runs this on a tag push and copies the result
to ``gh-pages/appcast.xml`` so the production URL is
``https://magnadesign.dev/appcast.xml``.

Signing key format
------------------

The ``--signing-key`` file is a **raw 32-byte Ed25519 private
key**, base64-encoded, on a single line. Generate one with::

    python -c "
    from cryptography.hazmat.primitives.asymmetric import ed25519
    import base64
    k = ed25519.Ed25519PrivateKey.generate()
    raw = k.private_bytes_raw()
    print(base64.b64encode(raw).decode())
    "

Store the resulting string as a GitHub Actions secret
(``APPCAST_SIGNING_KEY_BASE64``). The matching public key gets
pinned in ``pfc_inductor/updater/signature.py::PUBLIC_KEY_BASE64``
in the maintainer build — never commit either to source.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

# Sparkle namespace registered globally so ElementTree emits
# the prefixed attributes / elements with the expected names.
ET.register_namespace(
    "sparkle",
    "http://www.andymatuschak.org/xml-namespaces/sparkle",
)
_SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--output",
        "-o",
        default="appcast.xml",
        help="Path to write the appcast XML to.",
    )
    parser.add_argument(
        "--signing-key",
        default=None,
        help="Path to an Ed25519 private key (32-byte raw, "
        "base64-encoded on a single line). When omitted, "
        "items are emitted without the sparkle:edSignature "
        "attribute and the updater warns 'verification "
        "skipped'.",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", "lgili/MagnaDesign"),
        help="``owner/repo`` slug. Defaults to ``GITHUB_REPOSITORY`` (set by GitHub Actions).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max number of releases to include (newest-first).",
    )
    parser.add_argument(
        "--include-prerelease",
        action="store_true",
        help="Include pre-release tags (those with a hyphen, e.g. ``v0.7.0-rc1``). Off by default.",
    )
    args = parser.parse_args(argv)

    releases = _fetch_releases(args.repo, args.limit, args.include_prerelease)
    signing_key = _load_signing_key(args.signing_key)

    xml_bytes = _build_appcast(
        releases,
        repo=args.repo,
        signing_key=signing_key,
    )
    Path(args.output).write_bytes(xml_bytes)
    print(
        f"wrote {args.output} ({len(releases)} entries, signed={signing_key is not None})",
        file=sys.stderr,
    )
    return 0


# ---------------------------------------------------------------------------
# GitHub Releases API (via gh CLI)
# ---------------------------------------------------------------------------
def _fetch_releases(
    repo: str,
    limit: int,
    include_prerelease: bool,
) -> list[dict]:
    """Pull the latest releases via ``gh release list --json``.

    The ``gh`` CLI is pre-installed on every GitHub-hosted
    runner; using it instead of the REST API avoids the
    ``requests`` dep and the rate-limit dance.
    """
    cmd = [
        "gh",
        "release",
        "list",
        "--repo",
        repo,
        "--limit",
        str(limit),
        "--json",
        "tagName,name,publishedAt,body,isDraft,isPrerelease,assets",
    ]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"gh release list failed: {exc.stderr}", file=sys.stderr)
        sys.exit(2)
    payload = json.loads(result.stdout)

    out: list[dict] = []
    for r in payload:
        if r.get("isDraft"):
            continue
        if r.get("isPrerelease") and not include_prerelease:
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------
def _load_signing_key(path: Optional[str]):
    """Return an Ed25519PrivateKey or ``None`` if unsigned."""
    if not path:
        return None
    raw_b64 = Path(path).read_text().strip()
    raw = base64.b64decode(raw_b64, validate=True)
    if len(raw) != 32:
        raise SystemExit(
            "signing key must be a base64-encoded 32-byte Ed25519 raw private key",
        )
    from cryptography.hazmat.primitives.asymmetric import ed25519

    return ed25519.Ed25519PrivateKey.from_private_bytes(raw)


def _sign_asset(asset_url: str, signing_key) -> Optional[str]:
    """Download the asset, sign its bytes, return the base64
    signature.

    The download happens inside the CI step so the runner has
    network. For sub-MB CI runs we keep the asset in memory;
    for ~300 MB binaries we'd switch to a streaming hash, but
    Ed25519's batch verify works on a single contiguous buffer
    so streaming would force a hash-then-sign indirection. The
    in-memory path is fine for the binaries we ship.
    """
    if signing_key is None:
        return None
    import urllib.request

    try:
        with urllib.request.urlopen(asset_url, timeout=120) as response:
            data = response.read()
    except Exception as exc:
        print(f"download failed for {asset_url}: {exc}", file=sys.stderr)
        return None
    sig = signing_key.sign(data)
    return base64.b64encode(sig).decode()


# ---------------------------------------------------------------------------
# XML emission
# ---------------------------------------------------------------------------
def _build_appcast(
    releases: list[dict],
    *,
    repo: str,
    signing_key,
) -> bytes:
    """Serialise the appcast XML."""
    rss = ET.Element(
        "rss",
        attrib={
            "version": "2.0",
            "xmlns:sparkle": _SPARKLE_NS,
        },
    )
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "MagnaDesign updates"
    ET.SubElement(channel, "link").text = f"https://github.com/{repo}/releases"
    ET.SubElement(
        channel, "description"
    ).text = "Stable releases of MagnaDesign — code-signed installers + release notes."
    ET.SubElement(channel, "language").text = "en"

    for r in releases:
        item = ET.SubElement(channel, "item")
        version = (r.get("tagName") or "").lstrip("v")
        ET.SubElement(item, "title").text = r.get("name") or version
        pub = _format_pub_date(r.get("publishedAt"))
        if pub:
            ET.SubElement(item, "pubDate").text = pub
        ET.SubElement(
            item,
            f"{{{_SPARKLE_NS}}}version",
        ).text = version
        ET.SubElement(
            item,
            f"{{{_SPARKLE_NS}}}shortVersionString",
        ).text = version
        body = r.get("body") or ""
        ET.SubElement(item, "description").text = body
        # Pick the platform-canonical asset for the enclosure —
        # convention: the first ``.dmg`` for macOS, fall back to
        # the first ``.zip`` for cross-platform downloads.
        asset = _pick_primary_asset(r.get("assets") or [])
        if asset is not None:
            enclosure_attrs = {
                "url": asset["url"],
                "length": str(asset.get("size", 0)),
                "type": asset.get(
                    "contentType",
                    "application/octet-stream",
                ),
            }
            sig_b64 = _sign_asset(asset["url"], signing_key)
            if sig_b64:
                enclosure_attrs[f"{{{_SPARKLE_NS}}}edSignature"] = sig_b64
            ET.SubElement(item, "enclosure", attrib=enclosure_attrs)

    # Pretty-print: ElementTree doesn't ship one; manual indent
    # is fine for a release artefact and keeps the dependency
    # surface zero.
    _indent(rss)
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def _pick_primary_asset(assets: list[dict]) -> Optional[dict]:
    """Pick the appcast's primary download — prefer ``.dmg``,
    fall back to ``.zip`` / ``.tar.gz`` / ``.msi``."""
    by_priority = {
        ".dmg": 0,
        ".msi": 1,
        ".zip": 2,
        ".tar.gz": 3,
        ".AppImage": 4,
    }
    candidates: list[tuple[int, dict]] = []
    for a in assets:
        name = (a.get("name") or "").lower()
        for ext, prio in by_priority.items():
            if name.endswith(ext):
                # Normalise the asset shape — gh API returns a
                # different field name for the download URL.
                normalized = {
                    "url": a.get("url") or a.get("apiUrl") or "",
                    "size": int(a.get("size") or 0),
                    "contentType": a.get("contentType") or "application/octet-stream",
                    "name": name,
                }
                candidates.append((prio, normalized))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda kv: kv[0])
    return candidates[0][1]


def _format_pub_date(value: Optional[str]) -> Optional[str]:
    """Convert GitHub's ISO-8601 publishedAt to RFC-822 (the
    format Sparkle expects)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC).strftime(
        "%a, %d %b %Y %H:%M:%S +0000",
    )


def _indent(element: ET.Element, level: int = 0) -> None:
    """In-place pretty-print via the ``ET.indent``-equivalent
    pre-3.9 trick. (We can drop this once we hard-pin Python
    3.9+, which we already do — kept defensive for users on
    weird ports.)"""
    indent = "\n" + level * "  "
    if len(element):
        if not element.text or not element.text.strip():
            element.text = indent + "  "
        for child in element:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    if level and (not element.tail or not element.tail.strip()):
        element.tail = indent


if __name__ == "__main__":
    sys.exit(main())
