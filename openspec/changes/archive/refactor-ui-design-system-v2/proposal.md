# Refactor UI design system to v2 ("MagnaDesign")

## Why

The current `ui/theme.py` + `ui/style.py` is a competent v1 — Linear-grade
neutrals, light/dark parity, mono-font for numerics — but it was scoped for a
plain three-column form layout. The new dashboard target ("MagnaDesign —
Inductor Design Suite", per the user-supplied mock) demands tokens that v1
does not express:

- A **persistent dark navy chrome** (sidebar) that is invariant across
  light/dark themes — i.e. a *brand* surface, not a *neutral* surface.
- **Card-grade radii (16 px)** distinct from button radii (10 px) and chip
  radii (8 px). v1 has a single `Radius.lg = 8` used everywhere.
- **Layered card shadows** (small/medium hover) — v1 has a single shadow
  string used inconsistently.
- A **brand accent pair** (primary blue + supporting violet) used by the
  stepper, the "Gerar Relatório" CTA, and category iconography. v1 has only
  `accent` (single colour).
- A **dashboard density scale** (24 px page, 20 px card, 16 px gap) that
  differs from the current xs/sm/md/lg ramp.
- A **typography refresh** — Inter as the primary UI face when available
  (with full system fallback), `tabular-nums` enabled wherever numbers live.

This change introduces those tokens. It is the foundation every other UI
refactor depends on; nothing else can land cleanly until it is in place.

## What changes

- `ui/theme.py`
  - Add `Sidebar` palette (always-dark navy chrome) decoupled from
    `Palette.bg`.
  - Add `accent_violet`, `accent_violet_subtle_bg`, `accent_violet_subtle_text`
    (brand secondary, used for highlighted stepper step + chip variants).
  - Add `card_shadow_sm`, `card_shadow_md`, `card_shadow_focus` strings
    (Qt `QGraphicsDropShadowEffect`-compatible RGBA + offsets).
  - Add `Radius.card = 16`, `Radius.button = 10`, `Radius.chip = 8` (keep
    `lg = 8` as a back-compat alias).
  - Extend `Spacing` with `page = 24`, `card_pad = 20`, `card_gap = 16`,
    `section = 32`.
  - Add `Typography.ui_family_brand` defaulting to
    `'"Inter Variable", "Inter", -apple-system, "Segoe UI Variable", …'`
    and `Typography.numeric_family` (mono with `font-feature-settings:
    "tnum"` hint).
  - Add a `Sidebar` dataclass (its own `bg`, `bg_active`, `bg_hover`,
    `text`, `text_muted`, `border`) — referenced by both light and dark
    themes (same colours).
- `ui/style.py`
  - Emit QSS for the new tokens (sidebar background, card shadow class,
    primary/secondary CTA buttons with `Radius.button`, stepper segment
    states).
  - Provide `card_qss(elevation: int)` helper returning the right shadow
    + border combo.
  - Provide `pill_qss(variant: "success"|"warning"|"danger"|"info"|"neutral")`
    helper for the 4-state status pills used in the bottom status bar.
- `ui/icons.py`
  - Adopt **Lucide** as the canonical icon set (MIT-licensed, ~1400 icons,
    24×24 SVG). Drop the ad-hoc `QIcon.fromTheme` pattern.
  - Bundle a curated subset (~40 icons) under `data/icons/lucide/` to keep
    the app fully offline; `icon(name, color=None)` returns a tinted
    `QIcon` rendered from SVG via `QSvgRenderer`.
- Tests
  - `tests/test_theme_tokens.py` — assert all new tokens exist on both
    `LIGHT` and `DARK` palettes and have valid CSS hex / RGBA strings.
  - `tests/test_style_qss.py` — render the QSS once per theme, assert no
    `KeyError` from missing tokens and that a few sentinel fragments are
    present (e.g. `border-radius: 16px` for cards).
  - `tests/test_icons.py` — assert `icon("layout-dashboard")` returns a
    non-null `QIcon` and an `icon("does-not-exist")` raises a clear error.

## Impact

- **Affected capabilities:** NEW `ui-design-system`.
- **Affected modules:** `ui/theme.py`, `ui/style.py`, `ui/icons.py`,
  `data/icons/lucide/*.svg` (new bundled assets).
- **Dependencies:** no new pip deps. `QSvgRenderer` ships with PySide6.
- **Risk:** zero functional risk — tokens are additive. Existing widgets
  keep working until each successor change rewires them. The only
  visible effect of *this* change alone is the new icons appearing where
  they are explicitly opted-in.
- **Sequencing:** lands first; all other UI refactors depend on its
  tokens.
