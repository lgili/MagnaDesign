"""Bundled SVG icons (Lucide) usable as ``QIcon``.

Every icon is a 24×24 SVG using ``currentColor`` for stroke so it can be
tinted at runtime to match the active theme. No external dependency: the
SVGs are embedded as Python strings.

Source: Lucide Icons (https://lucide.dev), ISC licence. The full ISC
notice ships with the repository as ``LICENSE-LUCIDE``.

Public API
----------

::

    icon("layout-dashboard", color="#0F172A", size=18) -> QIcon

The function returns a ``QIcon`` whose stroke colour is the requested
hex string. Unknown names raise ``KeyError`` with a message that lists
the available icon names — easier debugging than a silent empty pixmap.
Hyphenated and underscored names are accepted interchangeably so callers
can use the upstream Lucide naming directly (``check-circle``) without
losing back-compat with the v1 names (``check_circle``).
"""
from __future__ import annotations
from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer


# ---------------------------------------------------------------------------
# Icon strings
# ---------------------------------------------------------------------------
# Stripped to single-line stroke/path values; preserve ``currentColor`` so
# the renderer can tint at draw time.

_SVG_ATTRS = (
    'xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"'
)


def _svg(*parts: str) -> str:
    """Compose an SVG document from inline child elements."""
    return f'<svg {_SVG_ATTRS}>' + "".join(parts) + "</svg>"


_ICONS: dict[str, str] = {
    # --- v1 names kept for back-compat ----------------------------------
    "sliders": _svg(
        '<line x1="21" y1="4" x2="14" y2="4"/>',
        '<line x1="10" y1="4" x2="3" y2="4"/>',
        '<line x1="21" y1="12" x2="12" y2="12"/>',
        '<line x1="8" y1="12" x2="3" y2="12"/>',
        '<line x1="21" y1="20" x2="16" y2="20"/>',
        '<line x1="12" y1="20" x2="3" y2="20"/>',
        '<line x1="14" y1="2" x2="14" y2="6"/>',
        '<line x1="8" y1="10" x2="8" y2="14"/>',
        '<line x1="16" y1="18" x2="16" y2="22"/>',
    ),
    "database": _svg(
        '<ellipse cx="12" cy="5" rx="9" ry="3"/>',
        '<path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>',
        '<path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>',
    ),
    "compare": _svg(
        '<rect x="2" y="4" width="8" height="16" rx="1"/>',
        '<rect x="14" y="4" width="8" height="16" rx="1"/>',
    ),
    "search": _svg(
        '<circle cx="11" cy="11" r="7"/>',
        '<line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    ),
    "braid": _svg(
        '<path d="M6 3c0 6 12 6 12 12s-12 6-12 12"/>',
        '<path d="M18 3c0 6-12 6-12 12s12 6 12 12"/>',
    ),
    "cube": _svg(
        '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/>',
        '<polyline points="3.27 6.96 12 12.01 20.73 6.96"/>',
        '<line x1="12" y1="22.08" x2="12" y2="12"/>',
    ),
    "file": _svg(
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>',
        '<polyline points="14 2 14 8 20 8"/>',
        '<line x1="16" y1="13" x2="8" y2="13"/>',
        '<line x1="16" y1="17" x2="8" y2="17"/>',
        '<polyline points="10 9 9 9 8 9"/>',
    ),
    "zap": _svg(
        '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    ),
    "moon": _svg(
        '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    ),
    "sun": _svg(
        '<circle cx="12" cy="12" r="4"/>',
        '<path d="M12 2v2"/><path d="M12 20v2"/>',
        '<path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/>',
        '<path d="M2 12h2"/><path d="M20 12h2"/>',
        '<path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    ),
    "play": _svg(
        '<polygon points="5 3 19 12 5 21 5 3"/>',
    ),
    "download-cloud": _svg(
        '<path d="M20 16.2A4.5 4.5 0 0 0 17.5 8h-1.8A7 7 0 1 0 4 14.9"/>',
        '<polyline points="8 17 12 21 16 17"/>',
        '<line x1="12" y1="12" x2="12" y2="21"/>',
    ),

    # --- v2 additions ----------------------------------------------------
    "layout-dashboard": _svg(
        '<rect x="3" y="3" width="7" height="9" rx="1"/>',
        '<rect x="14" y="3" width="7" height="5" rx="1"/>',
        '<rect x="14" y="12" width="7" height="9" rx="1"/>',
        '<rect x="3" y="16" width="7" height="5" rx="1"/>',
    ),
    "git-branch": _svg(
        '<line x1="6" y1="3" x2="6" y2="15"/>',
        '<circle cx="18" cy="6" r="3"/>',
        '<circle cx="6" cy="18" r="3"/>',
        '<path d="M18 9a9 9 0 0 1-9 9"/>',
    ),
    "cpu": _svg(
        '<rect x="4" y="4" width="16" height="16" rx="2"/>',
        '<rect x="9" y="9" width="6" height="6"/>',
        '<line x1="9" y1="2" x2="9" y2="4"/>',
        '<line x1="15" y1="2" x2="15" y2="4"/>',
        '<line x1="9" y1="20" x2="9" y2="22"/>',
        '<line x1="15" y1="20" x2="15" y2="22"/>',
        '<line x1="20" y1="9" x2="22" y2="9"/>',
        '<line x1="20" y1="14" x2="22" y2="14"/>',
        '<line x1="2" y1="9" x2="4" y2="9"/>',
        '<line x1="2" y1="14" x2="4" y2="14"/>',
    ),
    "gauge": _svg(
        '<path d="m12 14 4-4"/>',
        '<path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    ),
    "activity": _svg(
        '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    ),
    "box": _svg(
        '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/>',
        '<polyline points="3.27 6.96 12 12.01 20.73 6.96"/>',
        '<line x1="12" y1="22.08" x2="12" y2="12"/>',
    ),
    "cog": _svg(
        '<path d="M12 20a1.94 1.94 0 0 0 1.65-.93l.6-1a1.93 1.93 0 0 1 2.07-.91l1.13.18a2 2 0 0 0 2.27-2.65L19.46 13a2 2 0 0 1 0-2l.26-1.66a2 2 0 0 0-2.27-2.65l-1.13.18a1.93 1.93 0 0 1-2.07-.92l-.6-1a2 2 0 0 0-3.3 0l-.6 1a1.93 1.93 0 0 1-2.07.92l-1.14-.18a2 2 0 0 0-2.27 2.65L4.54 11a2 2 0 0 1 0 2l-.26 1.61a2 2 0 0 0 2.27 2.65l1.13-.18a1.93 1.93 0 0 1 2.07.91l.6 1A1.94 1.94 0 0 0 12 20Z"/>',
        '<circle cx="12" cy="12" r="3"/>',
    ),
    "settings-2": _svg(
        '<path d="M20 7h-9"/>',
        '<path d="M14 17H5"/>',
        '<circle cx="17" cy="17" r="3"/>',
        '<circle cx="7" cy="7" r="3"/>',
    ),
    "bell": _svg(
        '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/>',
        '<path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    ),
    "chevron-down": _svg(
        '<polyline points="6 9 12 15 18 9"/>',
    ),
    "chevron-right": _svg(
        '<polyline points="9 18 15 12 9 6"/>',
    ),
    "download": _svg(
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>',
        '<polyline points="7 10 12 15 17 10"/>',
        '<line x1="12" y1="15" x2="12" y2="3"/>',
    ),
    "pause": _svg(
        '<rect x="6" y="4" width="4" height="16"/>',
        '<rect x="14" y="4" width="4" height="16"/>',
    ),
    "pencil": _svg(
        '<path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
    ),
    "check-circle": _svg(
        '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>',
        '<polyline points="22 4 12 14.01 9 11.01"/>',
    ),
    "alert-triangle": _svg(
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>',
        '<line x1="12" y1="9" x2="12" y2="13"/>',
        '<line x1="12" y1="17" x2="12.01" y2="17"/>',
    ),
    "x-circle": _svg(
        '<circle cx="12" cy="12" r="10"/>',
        '<line x1="15" y1="9" x2="9" y2="15"/>',
        '<line x1="9" y1="9" x2="15" y2="15"/>',
    ),
    "info": _svg(
        '<circle cx="12" cy="12" r="10"/>',
        '<line x1="12" y1="16" x2="12" y2="12"/>',
        '<line x1="12" y1="8" x2="12.01" y2="8"/>',
    ),
    "move-3d": _svg(
        '<path d="M5 3v16h16"/>',
        '<path d="m5 19 6-6"/>',
        '<path d="m2 6 3-3 3 3"/>',
        '<path d="m18 16 3 3-3 3"/>',
    ),
    "crop": _svg(
        '<path d="M6 2v14a2 2 0 0 0 2 2h14"/>',
        '<path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
    ),
    "ruler": _svg(
        '<path d="M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4 0L2.7 8.7a2.41 2.41 0 0 1 0-3.4l2.6-2.6a2.41 2.41 0 0 1 3.4 0Z"/>',
        '<path d="m14.5 12.5 2-2"/>',
        '<path d="m11.5 9.5 2-2"/>',
        '<path d="m8.5 6.5 2-2"/>',
        '<path d="m17.5 15.5 2-2"/>',
    ),
    "share": _svg(
        '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/>',
        '<polyline points="16 6 12 2 8 6"/>',
        '<line x1="12" y1="2" x2="12" y2="15"/>',
    ),
    "expand": _svg(
        '<polyline points="15 3 21 3 21 9"/>',
        '<polyline points="9 21 3 21 3 15"/>',
        '<line x1="21" y1="3" x2="14" y2="10"/>',
        '<line x1="3" y1="21" x2="10" y2="14"/>',
    ),
    "image": _svg(
        '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>',
        '<circle cx="9" cy="9" r="2"/>',
        '<path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
    ),
    "eye": _svg(
        '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/>',
        '<circle cx="12" cy="12" r="3"/>',
    ),
    "eye-off": _svg(
        '<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/>',
        '<path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/>',
        '<path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/>',
        '<line x1="2" y1="2" x2="22" y2="22"/>',
    ),
    "filter": _svg(
        '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
    ),
    "plus": _svg(
        '<line x1="12" y1="5" x2="12" y2="19"/>',
        '<line x1="5" y1="12" x2="19" y2="12"/>',
    ),
    "minus": _svg(
        '<line x1="5" y1="12" x2="19" y2="12"/>',
    ),
    "more-horizontal": _svg(
        '<circle cx="12" cy="12" r="1"/>',
        '<circle cx="19" cy="12" r="1"/>',
        '<circle cx="5" cy="12" r="1"/>',
    ),
    "arrow-up-right": _svg(
        '<line x1="7" y1="17" x2="17" y2="7"/>',
        '<polyline points="7 7 17 7 17 17"/>',
    ),
    "circle": _svg(
        '<circle cx="12" cy="12" r="10"/>',
    ),
    "layers": _svg(
        '<polygon points="12 2 2 7 12 12 22 7 12 2"/>',
        '<polyline points="2 17 12 22 22 17"/>',
        '<polyline points="2 12 12 17 22 12"/>',
    ),
    "maximize-2": _svg(
        '<polyline points="15 3 21 3 21 9"/>',
        '<polyline points="9 21 3 21 3 15"/>',
        '<line x1="21" y1="3" x2="14" y2="10"/>',
        '<line x1="3" y1="21" x2="10" y2="14"/>',
    ),
    "file-text": _svg(
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>',
        '<polyline points="14 2 14 8 20 8"/>',
        '<line x1="16" y1="13" x2="8" y2="13"/>',
        '<line x1="16" y1="17" x2="8" y2="17"/>',
        '<polyline points="10 9 9 9 8 9"/>',
    ),
    "clock": _svg(
        '<circle cx="12" cy="12" r="10"/>',
        '<polyline points="12 6 12 12 16 14"/>',
    ),
    "play-circle": _svg(
        '<circle cx="12" cy="12" r="10"/>',
        '<polygon points="10 8 16 12 10 16 10 8"/>',
    ),
    "trending-up": _svg(
        '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>',
        '<polyline points="16 7 22 7 22 13"/>',
    ),
    "trending-down": _svg(
        '<polyline points="22 17 13.5 8.5 8.5 13.5 2 7"/>',
        '<polyline points="16 17 22 17 22 11"/>',
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _normalise(name: str) -> str:
    """Accept both ``check-circle`` and ``check_circle`` spellings."""
    return name.replace("_", "-")


def available_icons() -> list[str]:
    """All icon names known to the registry, sorted alphabetically."""
    return sorted(_ICONS.keys())


def has_icon(name: str) -> bool:
    return _normalise(name) in _ICONS


@lru_cache(maxsize=512)
def _render_pixmap(name_norm: str, color: str, size: int) -> QPixmap:
    svg = _ICONS[name_norm]
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
    """Return a ``QIcon`` for a known name, tinted with the given colour.

    Hyphenated and underscored spellings are accepted interchangeably.
    Raises ``KeyError`` with a helpful suggestion list if the name is
    unknown — silently returning an empty icon hides typos.
    """
    norm = _normalise(name)
    if norm not in _ICONS:
        sample = ", ".join(available_icons()[:8])
        raise KeyError(
            f"Unknown icon name: {name!r}. "
            f"Available (first 8 of {len(_ICONS)}): {sample}, …"
        )
    return QIcon(_render_pixmap(norm, color, size))


def pixmap(name: str, color: str = "#52525B", size: int = 18) -> QPixmap:
    """Lower-level: return a ``QPixmap`` directly. Useful for embedding in
    ``QLabel.setPixmap`` (e.g. the green dot inside the "Salvo" pill)."""
    norm = _normalise(name)
    if norm not in _ICONS:
        raise KeyError(name)
    return _render_pixmap(norm, color, size)
