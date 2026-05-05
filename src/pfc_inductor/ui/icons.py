"""Bundled SVG icons (Lucide-style monoline) usable as QIcon.

Each icon is a 24×24 SVG using `currentColor` for stroke so it can be tinted
at runtime to match the active theme. No external dependency: the SVGs are
embedded as Python strings.

Public API:
    icon("sliders", color="#0F172A", size=18) -> QIcon
"""
from __future__ import annotations
from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer


# --- Source: Lucide Icons (https://lucide.dev) — ISC licence ---------------
# Stripped to single-line stroke/path values; preserve `currentColor`.

_ICONS: dict[str, str] = {
    "sliders": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<line x1="21" y1="4" x2="14" y2="4"/>'
        '<line x1="10" y1="4" x2="3" y2="4"/>'
        '<line x1="21" y1="12" x2="12" y2="12"/>'
        '<line x1="8" y1="12" x2="3" y2="12"/>'
        '<line x1="21" y1="20" x2="16" y2="20"/>'
        '<line x1="12" y1="20" x2="3" y2="20"/>'
        '<line x1="14" y1="2" x2="14" y2="6"/>'
        '<line x1="8" y1="10" x2="8" y2="14"/>'
        '<line x1="16" y1="18" x2="16" y2="22"/>'
        '</svg>'
    ),
    "database": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<ellipse cx="12" cy="5" rx="9" ry="3"/>'
        '<path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>'
        '<path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>'
        '</svg>'
    ),
    "compare": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="2" y="4" width="8" height="16" rx="1"/>'
        '<rect x="14" y="4" width="8" height="16" rx="1"/>'
        '</svg>'
    ),
    "search": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="11" cy="11" r="7"/>'
        '<line x1="21" y1="21" x2="16.65" y2="16.65"/>'
        '</svg>'
    ),
    "braid": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M6 3c0 6 12 6 12 12s-12 6-12 12"/>'
        '<path d="M18 3c0 6-12 6-12 12s12 6 12 12"/>'
        '</svg>'
    ),
    "cube": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/>'
        '<polyline points="3.27 6.96 12 12.01 20.73 6.96"/>'
        '<line x1="12" y1="22.08" x2="12" y2="12"/>'
        '</svg>'
    ),
    "file": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/>'
        '<line x1="16" y1="13" x2="8" y2="13"/>'
        '<line x1="16" y1="17" x2="8" y2="17"/>'
        '<polyline points="10 9 9 9 8 9"/>'
        '</svg>'
    ),
    "zap": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>'
        '</svg>'
    ),
    "moon": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>'
        '</svg>'
    ),
    "sun": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="4"/>'
        '<path d="M12 2v2"/><path d="M12 20v2"/>'
        '<path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/>'
        '<path d="M2 12h2"/><path d="M20 12h2"/>'
        '<path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>'
        '</svg>'
    ),
    "check_circle": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>'
        '<polyline points="22 4 12 14.01 9 11.01"/>'
        '</svg>'
    ),
    "alert_triangle": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>'
        '<line x1="12" y1="9" x2="12" y2="13"/>'
        '<line x1="12" y1="17" x2="12.01" y2="17"/>'
        '</svg>'
    ),
    "x_circle": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="10"/>'
        '<line x1="15" y1="9" x2="9" y2="15"/>'
        '<line x1="9" y1="9" x2="15" y2="15"/>'
        '</svg>'
    ),
    "play": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<polygon points="5 3 19 12 5 21 5 3"/>'
        '</svg>'
    ),
    "download_cloud": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M20 16.2A4.5 4.5 0 0 0 17.5 8h-1.8A7 7 0 1 0 4 14.9"/>'
        '<polyline points="8 17 12 21 16 17"/>'
        '<line x1="12" y1="12" x2="12" y2="21"/>'
        '</svg>'
    ),
}


@lru_cache(maxsize=256)
def _render_pixmap(name: str, color: str, size: int) -> QPixmap:
    svg = _ICONS.get(name)
    if svg is None:
        # Fallback: empty icon.
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        return pix
    src = svg.replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(src.encode("utf-8")))
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(p)
    p.end()
    return pix


def icon(name: str, color: str = "#52525B", size: int = 18) -> QIcon:
    """Return a `QIcon` for a known name, tinted with the given colour."""
    return QIcon(_render_pixmap(name, color, size))


def available_icons() -> list[str]:
    return sorted(_ICONS.keys())
