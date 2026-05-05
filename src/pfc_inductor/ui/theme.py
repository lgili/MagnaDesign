"""Design tokens for the PFC Inductor Designer UI.

Two themes (light/dark) sharing the same semantic structure. Every UI module
imports from here — no hard-coded colours elsewhere.

Style direction: Linear/Notion-grade technical app. Subtle borders, generous
padding, monospaced numerics, hierarchical typography.

v2 ("MagnaDesign") additions
-----------------------------

The v2 tokens extend v1 *additively* — every field that existed in v1 keeps
working. New fields are introduced for the dashboard refactor:

- ``Sidebar`` palette: theme-invariant navy chrome (same in light + dark).
- ``Palette.accent_violet`` family: brand secondary used by the workflow
  stepper "active" segment and category pills.
- ``Palette.card_shadow_sm`` / ``card_shadow_md`` / ``card_shadow_focus``:
  structured records (color + blur + dx + dy) consumed by
  ``QGraphicsDropShadowEffect`` so callers do not parse CSS strings.
- ``Radius.card`` (16) / ``Radius.button`` (10) / ``Radius.chip`` (8):
  distinct radii for the three main surface classes. ``Radius.lg`` (8) is
  kept as a back-compat alias.
- ``Spacing.page`` (24) / ``card_pad`` (20) / ``card_gap`` (16) /
  ``section`` (32): dashboard density scale.
- ``Typography.ui_family_brand`` (Inter Variable + system fallback) and
  ``numeric_family`` (mono with ``tnum`` hint).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

ThemeName = Literal["light", "dark"]


# ---------------------------------------------------------------------------
# Sidebar (theme-invariant brand chrome)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Sidebar:
    """Navy chrome that does NOT change between light and dark themes.

    The sidebar is a brand surface, not a neutral surface — toggling the
    theme does not flip it. Every field below resolves to the same byte
    value regardless of which `Palette` is active.
    """
    bg: str = "#0F1729"          # navy 950 — main sidebar fill
    bg_hover: str = "#1A2440"    # navy 800 — hover state on nav items
    bg_active: str = "#243152"   # navy 700 — selected nav item fill
    border: str = "#1A2440"      # subtle 1px separator
    text: str = "#E2E8F0"        # off-white primary text
    text_muted: str = "#94A3B8"  # secondary text, captions
    text_active: str = "#FFFFFF" # selected nav item label
    accent: str = "#A78BFA"      # violet glow used on the brand wordmark


# Module-level singleton so callers can `from theme import SIDEBAR`.
SIDEBAR = Sidebar()


# ---------------------------------------------------------------------------
# Card shadow tokens
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ShadowSpec:
    """Structured drop-shadow descriptor.

    Designed to be unpacked into a ``QGraphicsDropShadowEffect``:

        eff = QGraphicsDropShadowEffect()
        eff.setBlurRadius(spec.blur)
        eff.setOffset(spec.dx, spec.dy)
        eff.setColor(QColor(spec.color))   # ARGB hex string

    The color string uses the ``#AARRGGBB`` form (8 hex digits) so the alpha
    rides along — Qt's ``QColor("#AARRGGBB")`` accepts it directly.
    """
    color: str   # #AARRGGBB
    blur: int    # px
    dx: int = 0
    dy: int = 2


# ---------------------------------------------------------------------------
# Palette (light + dark)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Palette:
    # Surfaces
    bg: str
    surface: str
    surface_elevated: str
    border: str
    border_strong: str

    # Text
    text: str
    text_secondary: str
    text_muted: str
    text_inverse: str

    # Brand / accent (primary, blue family)
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_subtle_bg: str
    accent_subtle_text: str

    # Brand / accent secondary (violet family — workflow stepper, brand glow)
    accent_violet: str
    accent_violet_hover: str
    accent_violet_subtle_bg: str
    accent_violet_subtle_text: str

    # Semantic
    success: str
    success_bg: str
    warning: str
    warning_bg: str
    danger: str
    danger_bg: str
    info: str
    info_bg: str

    # Domain
    copper: str           # used in 3D viewer for windings
    copper_bright: str
    plot_envelope: str
    plot_ripple: str
    plot_static: str

    # Card shadows (3 elevations)
    card_shadow_sm: ShadowSpec
    card_shadow_md: ShadowSpec
    card_shadow_focus: ShadowSpec

    # Misc
    selection_bg: str
    focus_ring: str
    shadow: str           # legacy CSS string — kept for v1 callers


LIGHT = Palette(
    bg="#FAFAFB",
    surface="#FFFFFF",
    surface_elevated="#FFFFFF",
    border="#E4E4E7",
    border_strong="#D4D4D8",

    text="#18181B",
    text_secondary="#52525B",
    text_muted="#A1A1AA",
    text_inverse="#FAFAFA",

    accent="#3B82F6",
    accent_hover="#2563EB",
    accent_pressed="#1D4ED8",
    accent_subtle_bg="#EFF6FF",
    accent_subtle_text="#1D4ED8",

    accent_violet="#7C3AED",
    accent_violet_hover="#6D28D9",
    accent_violet_subtle_bg="#F5F3FF",
    accent_violet_subtle_text="#5B21B6",

    success="#16A34A",
    success_bg="#F0FDF4",
    warning="#D97706",
    warning_bg="#FFFBEB",
    danger="#DC2626",
    danger_bg="#FEF2F2",
    info="#0891B2",
    info_bg="#ECFEFF",

    copper="#C98A4B",
    copper_bright="#E59A5C",
    plot_envelope="#3B82F6",
    plot_ripple="#F59E0B",
    plot_static="#A1A1AA",

    # Light theme: low-alpha black shadow.
    card_shadow_sm=ShadowSpec(color="#14000000", blur=10, dx=0, dy=1),
    card_shadow_md=ShadowSpec(color="#1F000000", blur=24, dx=0, dy=4),
    card_shadow_focus=ShadowSpec(color="#403B82F6", blur=16, dx=0, dy=0),

    selection_bg="#DBEAFE",
    focus_ring="#3B82F6",
    shadow="rgba(0, 0, 0, 0.05)",
)

DARK = Palette(
    bg="#0E1014",
    surface="#16181D",
    surface_elevated="#1C1F26",
    border="#262A33",
    border_strong="#363A44",

    text="#F4F4F5",
    text_secondary="#A1A1AA",
    text_muted="#71717A",
    text_inverse="#0E1014",

    accent="#60A5FA",
    accent_hover="#93C5FD",
    accent_pressed="#3B82F6",
    accent_subtle_bg="#172554",
    accent_subtle_text="#93C5FD",

    accent_violet="#A78BFA",
    accent_violet_hover="#C4B5FD",
    accent_violet_subtle_bg="#2E1065",
    accent_violet_subtle_text="#DDD6FE",

    success="#4ADE80",
    success_bg="#0F2818",
    warning="#FBBF24",
    warning_bg="#2A1F0A",
    danger="#F87171",
    danger_bg="#2A1414",
    info="#22D3EE",
    info_bg="#0E2A2E",

    copper="#E59A5C",
    copper_bright="#FFB070",
    plot_envelope="#60A5FA",
    plot_ripple="#FBBF24",
    plot_static="#52525B",

    # Dark theme: higher alpha so shadows still read on near-black surfaces.
    card_shadow_sm=ShadowSpec(color="#52000000", blur=12, dx=0, dy=1),
    card_shadow_md=ShadowSpec(color="#80000000", blur=28, dx=0, dy=6),
    card_shadow_focus=ShadowSpec(color="#5060A5FA", blur=18, dx=0, dy=0),

    selection_bg="#1E3A8A",
    focus_ring="#60A5FA",
    shadow="rgba(0, 0, 0, 0.4)",
)


# ---------------------------------------------------------------------------
# Spacing / Radius / Typography
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Spacing:
    # v1 ramp (kept for back-compat with existing widgets)
    xs: int = 2
    sm: int = 6
    md: int = 8
    lg: int = 12
    xl: int = 18
    xxl: int = 24

    # v2 dashboard density scale
    page: int = 24       # outer page padding
    card_pad: int = 20   # inside-card padding
    card_gap: int = 16   # between cards on the dashboard grid
    section: int = 32    # between major sections (header → stepper → grid)


@dataclass(frozen=True)
class Radius:
    sm: int = 4
    md: int = 6
    lg: int = 8         # legacy alias; equals chip
    pill: int = 999

    # v2 explicit surface radii
    card: int = 16      # outer card frame
    button: int = 10    # primary / secondary buttons
    chip: int = 8       # small chips and segmented controls


@dataclass(frozen=True)
class Typography:
    # v1 system stack — used by panels not yet migrated to v2.
    ui_family: str = (
        '-apple-system, "SF Pro Display", "Segoe UI Variable", "Segoe UI", '
        '"Inter", "Helvetica Neue", Arial, sans-serif'
    )
    # v1 mono family.
    mono_family: str = (
        '"JetBrains Mono", "SF Mono", "Menlo", "Cascadia Code", '
        '"Consolas", monospace'
    )

    # v2 brand UI face: Inter first when installed locally, complete fallback.
    ui_family_brand: str = (
        '"Inter Variable", "Inter", -apple-system, "SF Pro Display", '
        '"Segoe UI Variable", "Segoe UI", "Helvetica Neue", Arial, sans-serif'
    )
    # v2 numeric family: mono with `tabular-nums` feature hint.
    # Qt6 stylesheets do NOT honour ``font-feature-settings`` directly, but
    # the constant is here so widgets that do their own painting (e.g.
    # MetricCard) can read the hint and pass ``QFont.setFeatures(["tnum"])``
    # to keep digits from jittering on update.
    numeric_family: str = (
        '"JetBrains Mono", "SF Mono", "Menlo", "Cascadia Code", '
        '"Consolas", monospace'
    )

    # Sizes (px) — compact scale tuned for engineering density.
    caption: int = 10
    body: int = 11
    body_md: int = 12
    title_sm: int = 12
    title_md: int = 14
    title_lg: int = 16
    display: int = 22

    # Weights
    regular: int = 400
    medium: int = 500
    semibold: int = 600
    bold: int = 700


# ---------------------------------------------------------------------------
# Theme state singleton
# ---------------------------------------------------------------------------

@dataclass
class ThemeState:
    name: ThemeName = "light"
    palette: Palette = field(default_factory=lambda: LIGHT)
    spacing: Spacing = field(default_factory=Spacing)
    radius: Radius = field(default_factory=Radius)
    type: Typography = field(default_factory=Typography)
    sidebar: Sidebar = field(default_factory=lambda: SIDEBAR)


_state = ThemeState()


def get_theme() -> ThemeState:
    return _state


def set_theme(name: ThemeName) -> ThemeState:
    global _state
    _state = ThemeState(
        name=name,
        palette=LIGHT if name == "light" else DARK,
        spacing=_state.spacing,
        radius=_state.radius,
        type=_state.type,
        sidebar=SIDEBAR,  # invariant
    )
    return _state


def is_dark() -> bool:
    return _state.name == "dark"
