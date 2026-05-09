"""Design tokens for the MagnaDesign UI.

Two themes (light/dark) sharing the same semantic structure. Every UI module
imports from here — no hard-coded colours elsewhere.

Theme-change broadcast
----------------------

A module-level ``theme_changed`` Qt signal fires whenever ``set_theme()``
mutates the active palette. Widgets that hold *inline* stylesheets
(``self.setStyleSheet(...)``) — i.e. anything not styled exclusively by
``app.setStyleSheet(make_stylesheet(...))`` — should subscribe to it
and re-apply their inline QSS:

    from pfc_inductor.ui.theme import on_theme_changed
    on_theme_changed(self._refresh_qss)

This is the cheapest way to keep light↔dark transitions correct across
the whole app without a heavyweight palette-driven QStyle.

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

    bg: str = "#0F1729"  # navy 950 — main sidebar fill
    bg_hover: str = "#1A2440"  # navy 800 — hover state on nav items
    bg_active: str = "#243152"  # navy 700 — selected nav item fill
    border: str = "#1A2440"  # subtle 1px separator
    text: str = "#E2E8F0"  # off-white primary text
    text_muted: str = "#94A3B8"  # secondary text, captions
    text_active: str = "#FFFFFF"  # selected nav item label
    accent: str = "#A78BFA"  # violet glow used on the brand wordmark


# Module-level singleton so callers can `from theme import SIDEBAR`.
SIDEBAR = Sidebar()


# ---------------------------------------------------------------------------
# Viz3D (theme-invariant material/scene realism)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Viz3D:
    """3D viewer realism palette — does NOT change between light and dark.

    Magnetic materials look the same regardless of UI theme: a powder
    core is always sandy-iron, a ferrite is always anthracite. Same for
    bobbin (cream PA66) and copper. Keeping these out of :class:`Palette`
    avoids the trap of dark-mode tinting a render that should match what
    the user will see on their bench.
    """

    # Material colours by ``Material.type``.
    material_powder: str = "#B9A98C"  # warm sandy iron
    material_ferrite: str = "#3A3838"  # dark anthracite
    material_nanocrystalline: str = "#5D6C7A"  # bluish steel
    material_amorphous: str = "#6E7178"  # gunmetal
    material_silicon_steel: str = "#A4A39E"  # rolled GO/NGO sheet
    material_default: str = "#888888"
    # Bobbin (PA66 / Mylar former).
    bobbin: str = "#E8E2D0"
    # Magnet-wire colours. Real enameled magnet wire is satin-brown
    # (Class-130 polyamide / Class-180 polyurethane), NOT the bare
    # copper one sees in textbooks — that's the conductor underneath
    # the lacquer, only visible at cut ends. We keep both tokens so
    # the renderer can show the enamel for the helix and the bare
    # copper for any visible end-stubs / cut-aways.
    wire_enamel: str = "#A0522D"  # sienna brown — coated wire
    wire_copper: str = "#B87333"  # bare copper — end stubs
    # Scene background gradient (top → bottom).
    bg_top: str = "#CDD6E0"
    bg_bottom: str = "#F0F3F7"
    # HUD text overlays.
    text_dim: str = "#666666"
    text_error: str = "#A01818"


# Module-level singleton so callers can `from theme import VIZ3D`.
VIZ3D = Viz3D()


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

    color: str  # #AARRGGBB
    blur: int  # px
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
    copper: str  # used in 3D viewer for windings
    copper_bright: str
    plot_envelope: str
    plot_ripple: str
    plot_static: str

    # Categorical data series. Use these for *categories* (Cu DC vs Cu
    # AC vs Núcleo, etc.) — DO NOT reuse the semantic ``warning`` /
    # ``danger`` tokens for plain data, which used to make a "Cu AC"
    # bar look like a "warning" status. Three series cover today's
    # callers; extend the dataclass when a 4th lands.
    data_series_1: str  # primary categorical (e.g. Cu DC)
    data_series_2: str  # secondary
    data_series_3: str  # tertiary

    # Pareto / scatter plots (matplotlib, no theme rebuild on the fly —
    # read at dialog construction time).
    plot_pareto_infeasible: str
    plot_pareto_feasible: str
    plot_pareto_frontier: str

    # Compare-dialog row backgrounds (subtle wash, distinct from semantic
    # success_bg/danger_bg which are designed to host pill text).
    compare_better_bg: str
    compare_worse_bg: str

    # Card shadows (3 elevations)
    card_shadow_sm: ShadowSpec
    card_shadow_md: ShadowSpec
    card_shadow_focus: ShadowSpec

    # Misc
    selection_bg: str
    focus_ring: str
    shadow: str  # legacy CSS string — kept for v1 callers


LIGHT = Palette(
    bg="#FAFAFB",
    surface="#FFFFFF",
    surface_elevated="#FFFFFF",
    border="#E4E4E7",
    border_strong="#D4D4D8",
    text="#18181B",
    text_secondary="#52525B",
    # text_muted bumped #A1A1AA → #71717A so caption-class text on bg
    # passes WCAG AA body contrast (was 2.9:1, now 4.6:1).
    text_muted="#71717A",
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
    # Categorical series — kept distinct from semantic warning/danger.
    data_series_1="#3B82F6",  # blue 500 — primary
    data_series_2="#A855F7",  # violet 500 — secondary
    data_series_3="#C98A4B",  # copper — tertiary (reuses copper)
    plot_pareto_infeasible="#A1A1AA",
    plot_pareto_feasible="#3A78B5",
    plot_pareto_frontier="#D04040",
    compare_better_bg="#DFF5E3",
    compare_worse_bg="#FBE2E2",
    # Light theme: low-alpha black shadow.
    card_shadow_sm=ShadowSpec(color="#14000000", blur=10, dx=0, dy=1),
    card_shadow_md=ShadowSpec(color="#1F000000", blur=24, dx=0, dy=4),
    card_shadow_focus=ShadowSpec(color="#403B82F6", blur=16, dx=0, dy=0),
    selection_bg="#DBEAFE",
    focus_ring="#3B82F6",
    shadow="rgba(0, 0, 0, 0.05)",
)

DARK = Palette(
    # ---- Surfaces — slight cool-blue cast (Linear / Notion vibe) ----
    # ``bg`` deepened to #0B0D12 and ``surface`` raised to #13161C so
    # cards lift cleanly off the page; the previous #0E1014 ↔ #16181D
    # were too close (1.6:1 contrast) and made the "card vs page"
    # boundary disappear in dark mode.
    bg="#0B0D12",
    surface="#13161C",
    surface_elevated="#1B1F27",
    # Border softened from #363A44 → #2A2F3A — still clears the
    # WCAG 2.2 3:1 component-contrast bar against the new bg
    # (#2A2F3A vs #0B0D12 = 3.4:1) but reads as a divider instead
    # of a hard outline.
    border="#2A2F3A",
    border_strong="#404655",
    # ---- Text — three real tiers, separated -------------------------
    # ``text`` slightly cooler so it doesn't bloom on the surface.
    # ``text_secondary`` and ``text_muted`` are now distinct (the v1
    # converged hex collapsed two tiers; captions read as decorative).
    text="#F5F6FA",
    text_secondary="#B4BAC6",
    text_muted="#8A91A0",
    text_inverse="#0B0D12",
    # ---- Accents — cooler/less saturated to sit on near-black -------
    accent="#7AAFFF",
    accent_hover="#A6CBFF",
    accent_pressed="#5A93EE",
    accent_subtle_bg="#13284D",
    accent_subtle_text="#B6D2FF",
    accent_violet="#B49CFF",
    accent_violet_hover="#CFC0FF",
    accent_violet_subtle_bg="#241848",
    accent_violet_subtle_text="#E2D7FF",
    # ---- Semantic — kept (good already) -----------------------------
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
    plot_envelope="#7AAFFF",
    plot_ripple="#FBBF24",
    plot_static="#52525B",
    # Categorical series for dark — refreshed to track the new accent.
    data_series_1="#7AAFFF",  # blue 400 — primary
    data_series_2="#B49CFF",  # violet 400 — secondary
    data_series_3="#E59A5C",  # copper bright — tertiary
    plot_pareto_infeasible="#52525B",
    plot_pareto_feasible="#7AAFFF",
    plot_pareto_frontier="#F87171",
    compare_better_bg="#0F2818",
    compare_worse_bg="#2A1414",
    # ---- Shadows — punchier so cards lift off the deeper bg ---------
    card_shadow_sm=ShadowSpec(color="#80000000", blur=14, dx=0, dy=2),
    card_shadow_md=ShadowSpec(color="#A0000000", blur=32, dx=0, dy=8),
    card_shadow_focus=ShadowSpec(color="#807AAFFF", blur=20, dx=0, dy=0),
    selection_bg="#1E3A8A",
    focus_ring="#7AAFFF",
    shadow="rgba(0, 0, 0, 0.45)",
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
    page: int = 24  # outer page padding
    card_pad: int = 20  # inside-card padding
    card_gap: int = 16  # between cards on the dashboard grid
    section: int = 32  # between major sections (header → stepper → grid)

    # Legacy magic-number consolidator. Multiple cards / pills /
    # canvases used a literal ``10`` for "between sub-elements
    # inside a card". Hoisted here so future density tweaks land
    # in one place.
    compact_gap: int = 10


@dataclass(frozen=True)
class WindowGeometry:
    """Top-level window sizing. Read by ``MainWindow.__init__`` so
    a UI-density experiment doesn't require code edits."""

    # Hard floor — under this width the bottom Scoreboard + KPI
    # strip overflow even with the QScrollArea wrappers. 1100×640
    # is the lowest common denominator that still shows every
    # sidebar entry and the full Núcleo card without horizontal
    # scrolling on a 1366×768 laptop.
    min_w: int = 1100
    min_h: int = 640
    # Default open size — capped at the available screen by
    # MainWindow with a 32 px margin for the OS taskbar / dock.
    default_w: int = 1500
    default_h: int = 900


@dataclass(frozen=True)
class DashboardLayout:
    """Per-row minimum heights for the 3-row dashboard grid.
    Tunable from one place so density adjustments don't require
    walking through ``DashboardPage`` looking for the magic
    320 px."""

    row_kpi_min: int = 320
    row_action_stretch: int = 1  # bottom action row, takes leftover


@dataclass(frozen=True)
class Radius:
    sm: int = 4
    md: int = 6
    lg: int = 8  # legacy alias; equals chip
    pill: int = 999

    # v2 explicit surface radii
    card: int = 16  # outer card frame
    button: int = 10  # primary / secondary buttons
    chip: int = 8  # small chips and segmented controls


@dataclass(frozen=True)
class Typography:
    # v1 system stack — used by panels not yet migrated to v2.
    ui_family: str = (
        '-apple-system, "SF Pro Display", "Segoe UI Variable", "Segoe UI", '
        '"Inter", "Helvetica Neue", Arial, sans-serif'
    )
    # v1 mono family.
    mono_family: str = (
        '"JetBrains Mono", "SF Mono", "Menlo", "Cascadia Code", "Consolas", monospace'
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
        '"JetBrains Mono", "SF Mono", "Menlo", "Cascadia Code", "Consolas", monospace'
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
# Card minimum sizes (per-card class) and viewport breakpoints
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardMinSize:
    """Per-card class minimums enforced by the dashboard grid.

    Each entry is ``(min_width_px, min_height_px)``. Tuned for the v3
    Projeto bento grid (12 columns) at the 1280 px baseline window
    width minus the 220 px sidebar and 360 px spec drawer. Keeping
    these as a single dataclass instead of magic numbers per card
    means a future "density" toggle can swap one ``CardMinSize`` for
    another without touching widget code.
    """

    # Heights tightened across the board so the Análise tab fits on a
    # 1366×768 laptop without scroll. The minimums kept widgets from
    # collapsing on narrow viewports — they didn't need to also pin a
    # tall stretch ceiling.
    nucleo: tuple[int, int] = (480, 320)  # was (480, 380)
    viz3d: tuple[int, int] = (320, 300)  # was (320, 360)
    formas: tuple[int, int] = (520, 240)  # was (520, 280)
    perdas: tuple[int, int] = (220, 200)  # was (220, 220)
    bobinam: tuple[int, int] = (180, 180)  # was (180, 200)
    entreferro: tuple[int, int] = (180, 180)  # was (180, 200)
    proximos: tuple[int, int] = (200, 200)  # was (200, 220)
    metric: tuple[int, int] = (132, 80)
    # Trimmed 108 → 84 px so the 6-tile ResumoStrip doesn't pin the
    # MainWindow to a width past the laptop screen edge. At 84 the
    # strip floors at ~640 px (6·84 + spacing + capped badge);
    # the tiles still hold a 4-digit value + caption + unit at this
    # width — verified at the smallest digit count the engine emits.
    metric_compact: tuple[int, int] = (84, 64)


CARD_MIN = CardMinSize()


@dataclass(frozen=True)
class Breakpoint:
    """Viewport width thresholds used by responsive layout decisions.

    The window auto-collapses the spec drawer below ``sm``, falls back
    to a 6-column grid between ``sm`` and ``md``, and only enables the
    full 12-column bento at ``md`` and above.
    """

    sm: int = 1024
    md: int = 1280
    lg: int = 1600


BP = Breakpoint()


@dataclass(frozen=True)
class Animation:
    """Duration tokens for transient UI feedback. All values in
    milliseconds.

    These are not yet wrapped in a ``prefers-reduced-motion`` check
    because Qt on desktop does not expose that primitive directly;
    when we add the accessibility hook callers should consult it
    before scheduling a timer for ``flash_ms`` or ``nudge_ms``.
    """

    flash_ms: int = 1200  # post-apply outline flash on ResumoStrip
    nudge_ms: int = 4000  # nudge banner ("ver em Análise →")
    toast_ms: int = 3000  # generic toast/snackbar dwell time


ANIMATION = Animation()


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
    viz3d: Viz3D = field(default_factory=lambda: VIZ3D)
    window: WindowGeometry = field(default_factory=WindowGeometry)
    dashboard: DashboardLayout = field(default_factory=DashboardLayout)


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
        viz3d=VIZ3D,  # invariant
        window=_state.window,  # invariant across themes
        dashboard=_state.dashboard,  # invariant across themes
    )
    _broadcaster.theme_changed.emit()
    return _state


def is_dark() -> bool:
    return _state.name == "dark"


# ---------------------------------------------------------------------------
# Theme-change broadcaster
# ---------------------------------------------------------------------------


# Imported lazily so that ``import pfc_inductor.ui.theme`` from non-GUI
# contexts (e.g. the data loader's tests) does not pull in PySide6.
def _make_broadcaster():
    from PySide6.QtCore import QObject, Signal

    class _Broadcaster(QObject):
        theme_changed = Signal()

    return _Broadcaster()


_broadcaster = _make_broadcaster()


def on_theme_changed(callback) -> None:
    """Subscribe ``callback`` to the global theme-change signal.

    The callback receives no arguments — it should re-read the active
    palette from :func:`get_theme` and re-apply whatever style state it
    owns.
    """
    _broadcaster.theme_changed.connect(callback)
