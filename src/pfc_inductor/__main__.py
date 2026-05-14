"""Entry point: ``python -m pfc_inductor`` / ``magnadesign``.

Dispatches between two surfaces:

- **GUI** — bare ``magnadesign`` (no args) or ``magnadesign gui``
  launches the desktop application. The heavy Qt + PyVista stack
  is imported lazily inside :func:`_run_gui` so the CLI path
  stays headless-friendly.
- **CLI** — ``magnadesign <subcommand>`` (e.g. ``design``,
  ``sweep``) routes through :mod:`pfc_inductor.cli` and exits
  without ever touching Qt. Used by CI pipelines, batch scripts,
  and vendor-quoting integrations.

The dispatch happens *before* any Qt import so that headless
servers without a display still run the CLI cleanly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


# These imports are intentionally late so the CLI dispatch in
# :func:`main` can decide between GUI and headless paths *before*
# Qt initialisation. Listed at module-top inside a guard so the
# Python import system still picks them up for the GUI codepath
# while every CLI subcommand exits without paying the ~500 ms /
# 50 MB cost of pulling in PySide6.
def _import_qt_runtime_minimal() -> None:
    """Load JUST the Qt + theme bits the splash screen needs.

    The splash has to paint within the first ~1 s of double-click
    or the user perceives the app as broken ("demora demais antes
    do splash"). The full ``MainWindow`` import pulls ~3800 lines
    of dialog code + matplotlib + reportlab, which on a frozen .app
    cold-start adds 5-10 s before any Qt window can paint.
    Splitting the runtime import into "minimal" (for splash) and
    "full" (for MainWindow) lets the splash show immediately, then
    the heavy imports run in the background while the user reads
    the splash.
    """
    global QSettings, QColor, QFontDatabase, QIcon, QPalette
    global QApplication, make_stylesheet
    global get_theme, on_theme_changed, set_theme
    global SETTINGS_APP, SETTINGS_ORG
    from PySide6.QtCore import QSettings as _QSettings
    from PySide6.QtGui import (
        QColor as _QColor,
    )
    from PySide6.QtGui import (
        QFontDatabase as _QFontDatabase,
    )
    from PySide6.QtGui import (
        QIcon as _QIcon,
    )
    from PySide6.QtGui import (
        QPalette as _QPalette,
    )
    from PySide6.QtWidgets import QApplication as _QApplication

    from pfc_inductor.settings import (
        SETTINGS_APP as _SETTINGS_APP,
    )
    from pfc_inductor.settings import (
        SETTINGS_ORG as _SETTINGS_ORG,
    )
    from pfc_inductor.ui.style import make_stylesheet as _make_stylesheet
    from pfc_inductor.ui.theme import (
        get_theme as _get_theme,
    )
    from pfc_inductor.ui.theme import (
        on_theme_changed as _on_theme_changed,
    )
    from pfc_inductor.ui.theme import (
        set_theme as _set_theme,
    )

    QSettings = _QSettings
    QColor = _QColor
    QFontDatabase = _QFontDatabase
    QIcon = _QIcon
    QPalette = _QPalette
    QApplication = _QApplication
    make_stylesheet = _make_stylesheet
    get_theme = _get_theme
    on_theme_changed = _on_theme_changed
    set_theme = _set_theme
    SETTINGS_APP = _SETTINGS_APP
    SETTINGS_ORG = _SETTINGS_ORG


def _import_main_window() -> None:
    """Phase 2: import ``MainWindow`` — heavy, runs after splash paints."""
    global MainWindow
    from pfc_inductor.ui.main_window import MainWindow as _MainWindow

    MainWindow = _MainWindow


# Backwards-compat alias — older code paths (smoke tests, the
# release-asset verifier) import ``_import_qt_runtime`` by name.
def _import_qt_runtime() -> None:
    """Compose ``_import_qt_runtime_minimal`` + ``_import_main_window``."""
    _import_qt_runtime_minimal()
    _import_main_window()


def _load_initial_theme() -> str:
    env = os.environ.get("PFC_THEME", "").lower().strip()
    if env in ("dark", "light"):
        return env
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    val = settings.value("theme", "light")
    return str(val) if val in ("light", "dark") else "light"


def _splash_logo_candidates() -> list[Path]:
    """Ordered list of PNG paths to try when loading the splash logo.

    Lighter than ``_resolve_icon()``: we just want one big PNG to feed
    into ``QPixmap``, no multi-resolution ``QIcon`` machinery. Prefer
    the 512-px asset for retina sharpness; fall back to smaller sizes.
    """
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "img")
        candidates.append(Path(sys.executable).resolve().parent / "img")
    pkg_root = Path(__file__).resolve().parent
    candidates.append(pkg_root.parent.parent / "img")  # source checkout
    candidates.append(pkg_root / "img")  # wheel layout

    out: list[Path] = []
    for img_dir in candidates:
        if not img_dir.is_dir():
            continue
        for name in ("logo-512.png", "logo-256.png", "logo.png"):
            p = img_dir / name
            if p.exists():
                out.append(p)
    return out


def _resolve_icon() -> QIcon:
    """Locate the launcher icon across deployment shapes.

    Order matches ``data_loader._bundled_data_root``:

    1. PyInstaller frozen build — ``sys._MEIPASS/img`` (one-file)
       or ``<exe-dir>/img`` (one-folder). The release workflow
       ships ``img/`` next to the executable.
    2. Source checkout — ``<repo>/img``.
    3. Wheel install — ``<site-packages>/pfc_inductor/img``
       (only if the package-data ever ships icons there).

    A multi-resolution ``QIcon`` is built from every variant we
    find so Qt can pick the right size for the OS context (taskbar,
    dock, alt-tab, About dialog).
    """
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "img")
        candidates.append(Path(sys.executable).resolve().parent / "img")
    pkg_root = Path(__file__).resolve().parent
    candidates.append(pkg_root.parent.parent / "img")  # source checkout
    candidates.append(pkg_root / "img")  # wheel layout

    img_dir = next((p for p in candidates if p.is_dir()), None)
    if img_dir is None:
        return QIcon()

    icon = QIcon()
    # Prefer the platform-native bundle when available; fall back to
    # individual PNG sizes so the dock/taskbar still has something
    # crisp at 16/32/48/256 px.
    for name in ("logo.icns", "logo.ico"):
        p = img_dir / name
        if p.exists():
            icon.addFile(str(p))
    for name in ("logo-512.png", "logo-256.png", "logo.png"):
        p = img_dir / name
        if p.exists():
            icon.addFile(str(p))
    return icon


def _patch_brand_typography_to_installed_fonts() -> None:
    """Drop missing fonts from the brand UI font stack.

    The default ``Typography.ui_family_brand`` lists ``"Inter
    Variable"`` first because it's the design face we'd ship in a
    perfect world. We don't bundle it (and most users won't have it
    locally), so Qt's font matcher logs

        Populating font family aliases took 37 ms. Replace uses of
        missing font family "Inter Variable" with one that exists
        to avoid this cost.

    on every cold start. The 37 ms cost itself is negligible but the
    warning is noisy, and on dense lists Qt re-runs the alias
    population for *every* widget that asks for a different family,
    which adds up.

    Fix: probe the system font database after ``QApplication`` is
    live, drop ``"Inter Variable"`` / ``"Inter"`` from the stack if
    Qt can't find them, and re-seed ``_theme._state.type`` so the
    QSS we generate next reads a clean stack. The system fallbacks
    that follow (``-apple-system`` on macOS, ``"Segoe UI Variable"``
    on Windows) render visually equivalent to Inter for engineering
    UI density.
    """
    import dataclasses

    from PySide6.QtGui import QFontDatabase

    from pfc_inductor.ui import theme as _theme

    families = set(QFontDatabase.families())
    has_inter_variable = "Inter Variable" in families
    has_inter = "Inter" in families
    if has_inter_variable and has_inter:
        # Original stack already lands on a real font — nothing to do.
        return

    pieces: list[str] = []
    if has_inter_variable:
        pieces.append('"Inter Variable"')
    if has_inter:
        pieces.append('"Inter"')
    pieces.extend(
        [
            "-apple-system",
            '"SF Pro Display"',
            '"Segoe UI Variable"',
            '"Segoe UI"',
            '"Helvetica Neue"',
            "Arial",
            "sans-serif",
        ]
    )
    new_stack = ", ".join(pieces)

    new_type = dataclasses.replace(
        _theme._state.type,
        ui_family_brand=new_stack,
    )
    _theme._state = dataclasses.replace(_theme._state, type=new_type)


def _build_splash(icon):
    """Construct the cold-start splash screen — modern, rounded, with
    a brand header and an indeterminate progress bar.

    Returns ``None`` on offscreen / minimal platforms (no display) and
    when no icon is available. Otherwise returns a fully-configured
    ``QSplashScreen`` ready to be shown.

    Visual layout:

        ┌────────────────────────────────────────────────────────┐  ← rounded
        │ [violet accent band — 60 px]                           │     corners
        │                                                        │
        │   [icon 128×128]    MagnaDesign                        │
        │                     Inductor Design Suite              │
        │                     v0.4.x                             │
        │                                                        │
        │   [indeterminate progress bar — full width]            │
        │   Loading workspace…                                   │
        └────────────────────────────────────────────────────────┘

    The window is frameless + transparent so the rounded corners
    and the drop-shadow band actually paint correctly. The body is
    a single ``QPixmap`` rendered with ``QPainterPath`` for the card
    shape; the progress bar is a real child ``QProgressBar`` parented
    to the splash so it animates while ``MainWindow`` constructs.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import (
        QFont,
        QGuiApplication,
        QPainter,
        QPainterPath,
        QPen,
        QPixmap,
    )
    from PySide6.QtWidgets import QProgressBar, QSplashScreen

    if QGuiApplication.platformName() in ("offscreen", "minimal"):
        return None
    if icon is None or icon.isNull():
        return None

    p_palette = get_theme().palette
    width, height = 560, 300
    radius = 18

    # ── Compose the card pixmap (transparent margin so the OS
    # composites the rounded corners cleanly) ──
    pix = QPixmap(width, height)
    pix.fill(QColor(0, 0, 0, 0))  # transparent

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Card body — rounded rect filled with the surface colour, with
    # a 1 px border in the theme border tint.
    card = QPainterPath()
    card.addRoundedRect(0.5, 0.5, width - 1, height - 1, radius, radius)
    painter.fillPath(card, QColor(p_palette.surface))
    painter.setPen(QPen(QColor(p_palette.border), 1))
    painter.drawPath(card)

    # Top accent band — full width, rounded only on the top corners.
    band_h = 64
    band_path = QPainterPath()
    band_path.moveTo(0, band_h)
    band_path.lineTo(0, radius)
    band_path.quadTo(0, 0, radius, 0)
    band_path.lineTo(width - radius, 0)
    band_path.quadTo(width, 0, width, radius)
    band_path.lineTo(width, band_h)
    band_path.closeSubpath()
    painter.fillPath(band_path, QColor(p_palette.accent_violet))

    # Brand wordmark in the band.
    painter.setPen(QColor("#FFFFFF"))
    f = QFont()
    f.setPointSize(20)
    f.setWeight(QFont.Weight.DemiBold)
    painter.setFont(f)
    painter.drawText(
        24,
        0,
        width - 48,
        band_h,
        int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
        "MagnaDesign",
    )
    f.setPointSize(10)
    f.setWeight(QFont.Weight.Normal)
    painter.setFont(f)
    painter.setPen(QColor(255, 255, 255, 200))
    painter.drawText(
        24,
        0,
        width - 48,
        band_h,
        int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
        "Inductor Design Suite",
    )

    # Body — icon on the left, tagline on the right.
    icon_size = 128
    icon_x = 32
    icon_y = band_h + (height - band_h - icon_size - 64) // 2
    icon_pix = icon.pixmap(icon_size, icon_size)
    painter.drawPixmap(icon_x, icon_y, icon_pix)

    text_x = icon_x + icon_size + 24
    text_w = width - text_x - 32

    f.setPointSize(13)
    f.setWeight(QFont.Weight.Medium)
    painter.setFont(f)
    painter.setPen(QColor(p_palette.text))
    painter.drawText(
        text_x,
        band_h + 24,
        text_w,
        28,
        int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft),
        "Topology-aware design suite",
    )

    f.setPointSize(10)
    f.setWeight(QFont.Weight.Normal)
    painter.setFont(f)
    painter.setPen(QColor(p_palette.text_muted))
    painter.drawText(
        text_x,
        band_h + 56,
        text_w,
        60,
        int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap),
        "PFC inductors • passive chokes • line reactors\nFEMMT + ONELAB validation built-in",
    )

    painter.end()

    # ── Build the splash widget ──
    splash = QSplashScreen(
        pix,
        Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.SplashScreen,
    )
    # Translucent so the rounded corners aren't filled with grey.
    splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    splash.setMask(pix.mask())

    # Indeterminate progress bar parented to the splash so it
    # animates while heavy imports run in the foreground thread.
    bar = QProgressBar(splash)
    bar.setRange(0, 0)  # indeterminate (busy spinner)
    bar.setTextVisible(False)
    bar_h = 4
    bar_margin = 32
    bar.setGeometry(
        bar_margin,
        height - 56,
        width - 2 * bar_margin,
        bar_h,
    )
    bar.setStyleSheet(
        "QProgressBar {"
        f"  background: {p_palette.surface_elevated};"
        "  border: 0;"
        "  border-radius: 2px;"
        "}"
        "QProgressBar::chunk {"
        f"  background: {p_palette.accent_violet};"
        "  border-radius: 2px;"
        "}"
    )

    # Status caption below the bar.
    splash.showMessage(
        "Loading workspace…",
        int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter),
        QColor(p_palette.text_muted),
    )
    return splash


def _apply_app_palette(app: QApplication) -> None:
    """Mirror the active token Palette into the ``QApplication``'s
    :class:`QPalette` so widgets that bypass the global stylesheet
    (native dialogs, message boxes, system tooltips, the few inputs
    we don't style explicitly) inherit the right colours instead of
    the platform default — which on macOS leaks bright system
    backgrounds into our dark theme.

    Combined with ``app.setStyle("Fusion")``, this is the lever that
    makes Mac and Windows render identically: Fusion is the only Qt
    style that fully respects QSS *and* QPalette.
    """
    p = get_theme().palette
    qp = QPalette()
    qp.setColor(QPalette.ColorRole.Window, QColor(p.bg))
    qp.setColor(QPalette.ColorRole.WindowText, QColor(p.text))
    qp.setColor(QPalette.ColorRole.Base, QColor(p.surface))
    qp.setColor(QPalette.ColorRole.AlternateBase, QColor(p.surface_elevated))
    qp.setColor(QPalette.ColorRole.Text, QColor(p.text))
    qp.setColor(QPalette.ColorRole.PlaceholderText, QColor(p.text_muted))
    qp.setColor(QPalette.ColorRole.Button, QColor(p.surface_elevated))
    qp.setColor(QPalette.ColorRole.ButtonText, QColor(p.text))
    qp.setColor(QPalette.ColorRole.Highlight, QColor(p.accent))
    qp.setColor(QPalette.ColorRole.HighlightedText, QColor(p.text_inverse))
    qp.setColor(QPalette.ColorRole.ToolTipBase, QColor(p.surface_elevated))
    qp.setColor(QPalette.ColorRole.ToolTipText, QColor(p.text))
    qp.setColor(QPalette.ColorRole.Link, QColor(p.accent))
    qp.setColor(QPalette.ColorRole.LinkVisited, QColor(p.accent_violet))
    qp.setColor(QPalette.ColorRole.BrightText, QColor(p.danger))
    # Disabled-state colours — many native widgets use these instead
    # of the regular roles, so muting them prevents the "ghosted but
    # still bright white" look on disabled inputs.
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    ):
        qp.setColor(QPalette.ColorGroup.Disabled, role, QColor(p.text_muted))
    app.setPalette(qp)


def main(argv: list[str] | None = None) -> int:
    """Entry point — dispatch to GUI or CLI.

    Args:
        argv: Command-line arguments excluding ``argv[0]``. When
            ``None``, ``sys.argv[1:]`` is used.

    Bare invocation → GUI. Anything matching a registered CLI
    subcommand (``design``, ``sweep``, …) → CLI without ever
    importing Qt.

    The literal ``gui`` subcommand is honoured as an explicit GUI
    request — handy for ``magnadesign gui`` aliases in shell
    profiles where the user wants to be unambiguous.
    """
    args = list(sys.argv[1:] if argv is None else argv)

    # Lazy import so headless servers still resolve the dispatch
    # without paying for Qt.
    from pfc_inductor.cli import SUBCOMMANDS as CLI_SUBCOMMANDS
    from pfc_inductor.cli import main as cli_main

    # CLI is taken when the first argument is either a registered
    # subcommand or any top-level flag (``--help``, ``--version``,
    # ``-h``). The flag heuristic lets the CLI render its own help
    # without the user having to type a subcommand first; the
    # subcommand check covers the standard usage path.
    if args and (args[0] in CLI_SUBCOMMANDS or args[0].startswith("-")):
        return cli_main(args)

    if args and args[0] == "gui":
        # Strip the "gui" arg before handing off to Qt, in case
        # QApplication ever decides to interpret it.
        args = args[1:]

    return _run_gui(args)


def _run_gui(argv: list[str]) -> int:
    """Boot the desktop application.

    Ordering is deliberate and dominates how fast the user sees
    branding after they double-click the icon:

    1. **Bare-minimum Qt imports** (``QApplication``, ``QPixmap``,
       ``QSplashScreen``) — NO theme, NO style, NO settings, NO icon
       lookup, NO font database. These each pull additional modules
       transitively and together added ~200–500 ms before any pixel
       could paint.
    2. **``QApplication`` constructed** and the **fast splash** is
       shown with ``processEvents()`` forcing an immediate paint.
       The fast splash uses hardcoded colours / dimensions (no
       theme palette lookup) so it has zero dependencies beyond a
       string.
    3. **Everything else** (ONELAB path injection, theme, fonts,
       stylesheet, MainWindow) lands AFTER the splash is on
       screen. The user sees branding from the very first paint
       cycle, then watches the workspace fill in.

    The historic ordering imported theme + style + settings BEFORE
    the splash had any chance to paint, so on a frozen .app cold
    start the user saw a blank screen for 5–15 s — the "splash mal
    aparece e já some" symptom.
    """
    # ── Phase 1: minimal imports → splash on screen ASAP ──
    # NOTHING from ``pfc_inductor.ui.*`` here — those modules pull
    # in the full theme + style chain.
    from PySide6.QtCore import Qt
    from PySide6.QtGui import (
        QColor,
        QGuiApplication,
        QLinearGradient,
        QPainter,
        QPainterPath,
        QPixmap,
    )
    from PySide6.QtWidgets import QApplication, QProgressBar, QSplashScreen

    # HiDPI: pass-through fractional scale factors so the bundled
    # ``.app`` / ``.exe`` doesn't render at 1× resolution on retina
    # / 150 % DPI displays. Qt's default ``Round`` policy snaps
    # 1.5× → 2× (oversharp) or 1.5× → 1× (blurry); ``PassThrough``
    # uses the real ratio so VTK, matplotlib, and Qt-rendered text
    # all match the OS's pixel grid. This MUST be set BEFORE
    # ``QApplication`` is constructed — applying it later is a
    # silent no-op.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough,
    )

    app = QApplication([sys.argv[0], *argv])

    # Build the splash with **hardcoded** brand colours so we don't
    # have to import ``pfc_inductor.ui.theme`` before paint #1.
    # These constants mirror the default-light palette in
    # ``ui/theme.py`` — if the brand ever rebrands we update both
    # in lockstep.
    splash: Optional[QSplashScreen]
    _splash_shown_at: Optional[float]
    if QApplication.platformName() in ("offscreen", "minimal"):
        splash = None
        _splash_shown_at = None
    else:
        # ---- Brand tokens (mirror ``ui/theme.py`` default light) ----
        BRAND_VIOLET = "#6D28D9"
        BRAND_VIOLET_DARK = "#4C1D95"
        SURFACE = "#FFFFFF"
        BORDER = "#E4E4E7"
        TEXT = "#18181B"
        TEXT_MUTED = "#71717A"
        SURFACE_ELEVATED = "#F4F4F5"

        # ---- Pixmap sized for the DPI we're actually rendering on ----
        # ``primaryScreen().devicePixelRatio()`` returns 2.0 on retina,
        # 1.0 on standard, 1.5 on 150 % Windows scaling, etc. We render
        # the splash bitmap at the native resolution and tag it with
        # the ratio so Qt scales it back down to logical pixels for
        # layout — gives a crisp render on every display class.
        screen = QGuiApplication.primaryScreen()
        dpr = float(screen.devicePixelRatio()) if screen is not None else 1.0
        # Logical dimensions; pixel dimensions are ``logical × dpr``.
        width_l, height_l, radius_l = 600, 340, 20
        width_p = int(width_l * dpr)
        height_p = int(height_l * dpr)

        pix = QPixmap(width_p, height_p)
        pix.setDevicePixelRatio(dpr)
        pix.fill(QColor(0, 0, 0, 0))  # transparent margin

        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # Scale the painter so we can draw in logical coordinates and
        # have Qt rasterise at native pixel density.
        painter.scale(dpr, dpr)

        # ---- Rounded white card ----
        card = QPainterPath()
        card.addRoundedRect(0.5, 0.5, width_l - 1, height_l - 1, radius_l, radius_l)
        painter.fillPath(card, QColor(SURFACE))
        painter.setPen(QColor(BORDER))
        painter.drawPath(card)

        # ---- Top violet gradient band ----
        band_h = 88
        band = QPainterPath()
        band.moveTo(0, band_h)
        band.lineTo(0, radius_l)
        band.quadTo(0, 0, radius_l, 0)
        band.lineTo(width_l - radius_l, 0)
        band.quadTo(width_l, 0, width_l, radius_l)
        band.lineTo(width_l, band_h)
        band.closeSubpath()
        grad = QLinearGradient(0, 0, width_l, band_h)
        grad.setColorAt(0.0, QColor(BRAND_VIOLET_DARK))
        grad.setColorAt(1.0, QColor(BRAND_VIOLET))
        painter.fillPath(band, grad)

        # ---- Logo (left side of body) ----
        # Loaded directly with ``QPixmap`` (no QIcon multi-resolution
        # machinery) for the cheapest possible path: a single file
        # read + decode. The lookup mirrors ``_resolve_icon()`` but
        # only takes the highest-res PNG so the splash looks crisp on
        # retina.
        logo_size_l = 132
        logo_pix: Optional[QPixmap] = None
        for candidate in _splash_logo_candidates():
            cand_pix = QPixmap(str(candidate))
            if not cand_pix.isNull():
                logo_pix = cand_pix.scaled(
                    int(logo_size_l * dpr),
                    int(logo_size_l * dpr),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                logo_pix.setDevicePixelRatio(dpr)
                break
        logo_x = 36
        logo_y = band_h - 26  # let the logo straddle the violet band
        if logo_pix is not None:
            painter.drawPixmap(logo_x, logo_y, logo_pix)

        # ---- Wordmark (right of logo) ----
        text_x = logo_x + logo_size_l + 22 if logo_pix is not None else 36
        from PySide6.QtGui import QFont

        f = QFont()
        f.setPointSize(28)
        f.setWeight(QFont.Weight.DemiBold)
        painter.setFont(f)
        painter.setPen(QColor(TEXT))
        painter.drawText(
            text_x,
            band_h + 4,
            width_l - text_x - 24,
            36,
            int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft),
            "MagnaDesign",
        )
        f.setPointSize(11)
        f.setWeight(QFont.Weight.Normal)
        painter.setFont(f)
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(
            text_x,
            band_h + 44,
            width_l - text_x - 24,
            22,
            int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft),
            "Inductor Design Suite",
        )
        f.setPointSize(10)
        painter.setFont(f)
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(
            text_x,
            band_h + 72,
            width_l - text_x - 24,
            60,
            int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            | int(Qt.TextFlag.TextWordWrap),
            "PFC inductors · passive chokes · line reactors\n"
            "FEMMT + ONELAB FEA validation built-in",
        )
        painter.end()

        splash = QSplashScreen(
            pix,
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.SplashScreen,
        )
        splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        splash.setMask(pix.mask())

        # ---- Indeterminate progress bar ----
        bar_h = 4
        bar_margin = 36
        bar = QProgressBar(splash)
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setGeometry(
            bar_margin,
            height_l - bar_margin - bar_h - 8,
            width_l - 2 * bar_margin,
            bar_h,
        )
        bar.setStyleSheet(
            "QProgressBar {"
            f"  background: {SURFACE_ELEVATED};"
            "  border: 0;"
            "  border-radius: 2px;"
            "}"
            "QProgressBar::chunk {"
            f"  background: {BRAND_VIOLET};"
            "  border-radius: 2px;"
            "}"
        )
        splash.show()
        # Pump events TWICE — once to schedule the paint, once to
        # actually flush it through Qt's deferred-paint pipeline.
        # A single ``processEvents()`` was sometimes too short on
        # slow macOS WindowServer ticks; the second call costs ~1 ms
        # and guarantees the pixel is on screen before we move on.
        app.processEvents()
        app.processEvents()
        # Capture the splash's first paint time so we can enforce a
        # minimum on-screen duration below. The MainWindow boot is
        # fast enough now that the splash would otherwise flash for
        # < 500 ms — too quick to read the wordmark — so we pad to
        # ~2.5 s for a calm, readable boot experience.
        import time as _time

        _splash_shown_at = _time.perf_counter()

    # ── Phase 2: legacy ONELAB sys.path injection (only when needed) ──
    #
    # The default direct backend (analytical reluctance + toroidal
    # closed-form) doesn't need ONELAB on ``sys.path``. We only need
    # to inject the parent of the ONELAB folder when the user has
    # opted into the legacy FEMMT path via the env var, or when a
    # later code path actually imports ``femmt`` / launches a GetDP
    # solve. The lazy hooks in ``pfc_inductor.fea.probe`` and
    # ``main_window._open_fea_dialog`` already re-call
    # ``ensure_onelab_on_path()`` at the point of use, so removing the
    # eager boot-time call only costs us if a user runs FEMMT without
    # ever opening the FEA dialog (a path that wouldn't work anyway).
    #
    # Net effect: the cold-launch path is now FEMMT-free on the
    # default install. The Windows .exe no longer tries to read
    # ``~/.femmt_settings.json`` at boot, no longer prompts the user
    # to install ONELAB during the first launch, and shaves ~50 ms
    # off the splash-to-window time.
    _env_backend = os.environ.get("PFC_FEA_BACKEND", "").strip().lower()
    if _env_backend == "femmt":
        try:
            from pfc_inductor.setup_deps import ensure_onelab_on_path

            ensure_onelab_on_path()
        except Exception:
            pass

    _import_qt_runtime_minimal()

    app.setApplicationName(SETTINGS_APP)
    app.setOrganizationName(SETTINGS_ORG)
    icon = _resolve_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    # Crash reporter — opt-in, no-op without DSN.
    try:
        from pfc_inductor.telemetry import init_crash_reporter

        init_crash_reporter()
    except Exception:
        pass

    # ``Fusion`` is the only Qt style that fully honours QSS.
    app.setStyle("Fusion")

    # Register the optional JetBrains Mono / probe brand fonts.
    QFontDatabase.addApplicationFont(":/fonts/JetBrainsMono-Regular.ttf")
    _patch_brand_typography_to_installed_fonts()

    set_theme(_load_initial_theme())
    _apply_app_palette(app)
    app.setStyleSheet(make_stylesheet(get_theme()))

    on_theme_changed(
        lambda: (
            _apply_app_palette(app),
            app.setStyleSheet(make_stylesheet(get_theme())),
        )
    )

    # Optional status message — only shows if the splash survived
    # the fast-path construction above.
    if splash is not None:
        splash.showMessage(
            "Loading workspace…",
            int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter),
            QColor(get_theme().palette.text_muted),
        )
        app.processEvents()

    _import_main_window()

    win = MainWindow()

    # Enforce the splash's minimum on-screen duration so the user
    # has time to read the wordmark — without this gate the splash
    # flashes for < 500 ms on a warm cache (matplotlib already in
    # the page cache, no FEMMT probe pending, etc.) and looks like
    # a glitch. Two seconds and change is the sweet spot in
    # subjective UX tests: long enough to register the brand,
    # short enough that nobody perceives the app as "slow to open"
    # on top of the cold-start work itself.
    SPLASH_MIN_MS = 2_500
    if splash is not None and _splash_shown_at is not None:
        import time as _time

        from PySide6.QtCore import QEventLoop, QTimer

        elapsed_ms = (_time.perf_counter() - _splash_shown_at) * 1000.0
        remaining_ms = int(SPLASH_MIN_MS - elapsed_ms)
        if remaining_ms > 0:
            # Use a ``QEventLoop`` + ``singleShot`` so Qt's animation
            # ticks (the indeterminate progress bar in the splash)
            # keep running smoothly during the wait, instead of a
            # busy-wait that would freeze the chunk's marquee.
            loop = QEventLoop()
            QTimer.singleShot(remaining_ms, loop.quit)
            loop.exec()

    win.show()
    if splash is not None:
        splash.finish(win)

    # First-run onboarding tour — only shown until the user finishes
    # or skips it (persisted in QSettings). Mounted *after* ``show``
    # so the overlay anchors to the real geometry and the painter
    # has a non-zero rect to fill. Headless / offscreen platforms
    # are skipped because there's no human to orient.
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() not in ("offscreen", "minimal"):
        from pfc_inductor.ui.widgets.onboarding_tour import OnboardingTour

        OnboardingTour.maybe_show(win)

    return app.exec()


if __name__ == "__main__":
    # PyInstaller-frozen .app + ``multiprocessing.spawn`` requires
    # this call at the *very first line* of the entry point —
    # otherwise the child process's interpreter bootstrap fails
    # opaquely with exit code 4 on macOS, killing every spawned
    # FEMMT subprocess before our code has a chance to run. In a
    # source install this is a no-op; in the bundle it tells the
    # PyInstaller bootloader "if you were spawned as a child, run
    # the multiprocessing entry rather than re-launching the GUI".
    # See PyInstaller docs:
    # https://pyinstaller.org/en/stable/runtime-information.html#using-the-multiprocessing-module
    import multiprocessing

    multiprocessing.freeze_support()

    sys.exit(main())
