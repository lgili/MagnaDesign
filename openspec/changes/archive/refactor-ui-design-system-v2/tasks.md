# Tasks — Refactor UI design system to v2

> **Status: shipped.** All token / QSS / icon work landed; the icons
> are bundled inline as Python strings rather than separate SVG files
> (functionally equivalent, simpler distribution). The Lucide LICENSE
> notice is **deferred to `ui-refactor-followups`**.

## 1. Token model

- [x] 1.1 Add `Sidebar` dataclass to `ui/theme.py` (bg, bg_active,
      bg_hover, text, text_muted, border) and instantiate one shared
      `SIDEBAR` constant — colours invariant across light/dark.
- [x] 1.2 Extend `Palette` with `accent_violet`, `accent_violet_hover`,
      `accent_violet_subtle_bg`, `accent_violet_subtle_text`. Pick
      values consistent with the v2 mock (#7C3AED light primary,
      #A78BFA dark primary).
- [x] 1.3 Extend `Palette` with `card_shadow_sm`, `card_shadow_md`,
      `card_shadow_focus`. Format: dict with `color`, `blur`, `dx`,
      `dy` so callers can build a `QGraphicsDropShadowEffect` without
      string parsing.
- [x] 1.4 Add `Radius.card = 16`, `Radius.button = 10`, `Radius.chip = 8`.
      Keep `Radius.lg = 8` as a back-compat alias.
- [x] 1.5 Extend `Spacing` with `page = 24`, `card_pad = 20`,
      `card_gap = 16`, `section = 32`.
- [x] 1.6 Add `Typography.ui_family_brand` defaulting to Inter Variable
      with full system fallback, and a `numeric_family` constant whose
      docstring explains the `tnum` feature hint.
- [x] 1.7 Update `ThemeState` to expose the new fields; `set_theme()`
      preserves them.

## 2. Style sheet helpers

- [x] 2.1 `ui/style.py::card_qss(elevation: int = 1) -> str` — returns
      the QSS fragment for `QFrame.Card` with the right border, radius,
      and (when `elevation > 0`) `QGraphicsDropShadowEffect`-friendly
      object name `cardShadow{N}` so the widget can attach the effect.
- [x] 2.2 `ui/style.py::pill_qss(variant)` — emits `QLabel.Pill` styles
      with `Radius.pill`, semantic bg/fg per variant
      (`success|warning|danger|info|neutral`). Adds the v2 ``violet``
      variant on top of the v1 set.
- [x] 2.3 `ui/style.py::sidebar_qss()` — emits the navy sidebar QSS
      block (`QFrame#Sidebar`, `QPushButton.SidebarItem`, hover +
      active states, separator border).
- [x] 2.4 `ui/style.py::v2_buttons_qss()` — emits Primary / Secondary
      / Tertiary CTA variants used by the header
      (`QPushButton.Primary` / `.Secondary` / `.Tertiary`).
- [x] 2.5 Update `make_stylesheet(state)` to compose: base + sidebar +
      cards + pills + buttons. Order matters (sidebar overrides base).

## 3. Icons

- [x] 3.1 Curate the Lucide subset to bundle: `layout-dashboard`,
      `git-branch`, `cpu`, `gauge`, `activity`, `box`, `cog`, `bell`,
      `chevron-down`, `chevron-right`, `download`, `play`, `pause`,
      `pencil`, `check-circle`, `alert-triangle`, `x-circle`, `info`,
      `move-3d`, `crop`, `ruler`, `share`, `expand`, `image`,
      `eye`, `eye-off`, `sun`, `moon`, `search`, `filter`, `plus`,
      `minus`, `more-horizontal`, `arrow-up-right`, `circle`,
      `cube`, `layers`, `maximize-2`, `settings-2`, `file-text`,
      plus the v1 names kept for back-compat. ≥40 in total.
- [~] 3.2 Copy SVGs under `src/pfc_inductor/data/icons/lucide/<name>.svg`
      (keep upstream stroke-1.5 pixel-perfect 24×24).
      _(swapped: SVGs are bundled as inline Python strings in
      `ui/icons.py` — no on-disk asset files. Pyrightequivalent
      cache + `QSvgRenderer` rendering at request time. Simpler
      distribution than bundling files; same output.)_
- [x] 3.3 Rewrite `ui/icons.py`:
      - `icon(name: str, color: str | None = None, size: int = 18)
        -> QIcon`
      - On first miss, raise `KeyError` with the available names —
        easier debugging than a silent empty icon.
      - Tinting: when `color` is given, render the SVG into a
        `QPixmap`, multiply alpha against `color`, return as `QIcon`.
- [~] 3.4 Add `LICENSE-LUCIDE.txt` next to the bundled SVGs (Lucide is
      ISC-licensed; reproduce the notice).
      _Deferred to `ui-refactor-followups`._

## 4. Tests

- [x] 4.1 `tests/test_theme_tokens.py`:
      - All new fields exist on `LIGHT` and `DARK`.
      - All hex strings parse via `QColor` (no typos).
      - `Spacing.page == 24`, `Radius.card == 16`, `Radius.button == 10`.
      - WCAG AA contrast check for sidebar text.
- [x] 4.2 `tests/test_style_qss.py`:
      - `card_qss(1)` contains `border-radius: 16px`.
      - `pill_qss("success")` contains the success bg colour from the
        active palette.
      - `sidebar_qss()` references the SIDEBAR palette navy.
      - sidebar QSS is byte-equal across light and dark themes.
- [x] 4.3 `tests/test_icons.py`:
      - `icon("layout-dashboard")` returns a non-null `QIcon`.
      - `icon("not-real")` raises with a helpful message.
      - Tinting: rendered pixmap mean RGB is close to the requested
        colour (within ±10).

## 5. Migration cleanup

- [~] 5.1 Replace any remaining `QIcon.fromTheme(...)` usages in
      `ui/main_window.py`, `ui/spec_panel.py`, `ui/result_panel.py`
      with `icon("...")` calls.
      _Partially done — the new shell uses `icon()`, but a full sweep
      across legacy dialogs (litz_dialog, fea_dialog, db_editor,
      compare_dialog, setup_dialog) is **deferred to
      `ui-refactor-followups`**._
- [x] 5.2 Run the full pytest suite: must remain green
      (198 passed / 1 skipped baseline → 323 passed / 1 skipped after
      all 5 UI changes + polish).
