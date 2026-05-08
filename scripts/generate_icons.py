"""Regenerate platform icon artefacts from ``img/icon-source.png``.

Run from the repo root after editing the source mark:

    python scripts/generate_icons.py

Outputs:

- ``img/logo.ico``       — Windows multi-resolution (16/32/48/64/128/256)
- ``img/logo.icns``      — macOS multi-resolution (16…1024)
- ``img/logo-256.png``   — Linux .desktop / Qt window icon (square)
- ``img/logo-512.png``   — high-DPI variant for retina launchers

The PyInstaller spec at ``packaging/pfc-inductor.spec`` already
references ``img/logo.ico`` / ``img/logo.icns`` — once these files
land it picks them up automatically. Qt's ``QApplication.setWindow
Icon`` reads ``img/logo-256.png`` at runtime as a platform-neutral
fallback.

Pillow's ICO encoder takes a list of sizes; ICNS encoder picks the
matching macOS slots automatically. We pre-render PNG variants so
the encoders sample our hand-tuned source instead of doing their
own (possibly worse) downscaling.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "img" / "icon-source.png"
OUT_DIR = REPO_ROOT / "img"

# Sizes Windows / macOS / Linux launchers actually request. ICO ships
# the smaller half; ICNS ships the full ladder.
ICO_SIZES = [16, 32, 48, 64, 128, 256]
ICNS_SIZES = [16, 32, 64, 128, 256, 512, 1024]


def _resample(src: Image.Image, size: int) -> Image.Image:
    """High-quality downscale with LANCZOS — Pillow's best filter."""
    return src.resize((size, size), Image.Resampling.LANCZOS)


def main() -> int:
    if not SRC.exists():
        print(f"error: source not found at {SRC}", file=sys.stderr)
        print("       crop the icon mark from img/logo.png first.")
        return 1

    src = Image.open(SRC).convert("RGBA")
    if src.size[0] != src.size[1]:
        print(f"error: source must be square, got {src.size}", file=sys.stderr)
        return 1

    # 1. .ico — Windows
    ico_imgs = [_resample(src, s) for s in ICO_SIZES]
    ico_path = OUT_DIR / "logo.ico"
    ico_imgs[-1].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=ico_imgs[:-1],
    )
    print(f"  wrote {ico_path.relative_to(REPO_ROOT)} ({', '.join(str(s) for s in ICO_SIZES)})")

    # 2. .icns — macOS
    icns_path = OUT_DIR / "logo.icns"
    # Pillow's ICNS encoder reads the largest source and picks slots
    # automatically; passing append_images is unsupported there.
    src_for_icns = _resample(src, 1024)
    src_for_icns.save(icns_path, format="ICNS")
    print(f"  wrote {icns_path.relative_to(REPO_ROOT)}")

    # 3. Sized PNGs — Linux .desktop + Qt setWindowIcon fallback
    for s in (256, 512):
        p = OUT_DIR / f"logo-{s}.png"
        _resample(src, s).save(p, format="PNG", optimize=True)
        print(f"  wrote {p.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
