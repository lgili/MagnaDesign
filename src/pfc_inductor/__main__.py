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
    """Construct the cold-start splash screen.

    Returns ``None`` on offscreen / minimal platforms (no display) and
    when no icon is available (the splash is icon-driven). Otherwise
    returns a fully-configured ``QSplashScreen`` ready to be shown.

    The splash uses the app icon at 256×256 plus a one-line "Loading…"
    label so the user has something to look at during the 5-15 s the
    cold-cache MainWindow construction takes (matplotlib font cache,
    catalog load, dashboard chart init). It auto-dismisses when the
    main window's ``finish(win)`` is called.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QPainter, QPixmap
    from PySide6.QtWidgets import QSplashScreen

    if QGuiApplication.platformName() in ("offscreen", "minimal"):
        return None
    if icon is None or icon.isNull():
        return None

    # Render the icon onto a 320×320 surface with a small bottom
    # margin so the platform-painted "Loading MagnaDesign…" caption
    # has somewhere to go.
    side = 320
    pix = QPixmap(side, side)
    p_palette = get_theme().palette
    pix.fill(QColor(p_palette.surface))
    painter = QPainter(pix)
    icon_size = 192
    icon_pix = icon.pixmap(icon_size, icon_size)
    x = (side - icon_size) // 2
    y = (side - icon_size) // 2 - 24
    painter.drawPixmap(x, y, icon_pix)
    painter.end()

    splash = QSplashScreen(pix, Qt.WindowType.WindowStaysOnTopHint)
    splash.setStyleSheet(
        f"QSplashScreen {{ background: {p_palette.surface}; color: {p_palette.text_muted}; }}"
    )
    splash.showMessage(
        "Loading MagnaDesign…",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
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
    """Boot the desktop application. Imports Qt lazily so the CLI
    path doesn't pay the 500 ms / 50 MB startup cost."""
    # ONELAB lives outside the bundle (binary distribution: gmsh +
    # getdp + ``onelab.py``). FEMMT's ``component.py`` does
    # ``from onelab import onelab`` at module top, so we MUST put
    # the configured ONELAB folder on ``sys.path`` before anything
    # in the import graph touches FEMMT — otherwise the bundle
    # fails with ``ModuleNotFoundError: No module named 'onelab'``
    # the moment the FEA dialog (or any FEMMT-touching code) loads.
    # No-op when ONELAB isn't configured yet (the setup dialog will
    # show its UI and trigger the install flow).
    try:
        from pfc_inductor.setup_deps import ensure_onelab_on_path

        ensure_onelab_on_path()
    except Exception:
        pass

    # Phase 1: import only what we need to put a splash on screen.
    # Pulling MainWindow here would re-introduce the multi-second
    # blank-screen wait the splash is meant to hide.
    _import_qt_runtime_minimal()

    app = QApplication([sys.argv[0], *argv])
    app.setApplicationName(SETTINGS_APP)
    app.setOrganizationName(SETTINGS_ORG)

    # ---- Splash FIRST -----------------------------------------------------
    # Show the splash before EVERYTHING else (theme, fonts, crash
    # reporter, palette, stylesheet, MainWindow). The previous
    # ordering ran ~8 stages of init before the user saw any pixel,
    # which on a cold-cache frozen .app added up to 5-15 s of
    # blank-screen wait — exactly the "demora 20 segundas antes do
    # splash" symptom.
    #
    # The splash only needs the application icon and a paint cycle.
    # Theme is read here (not via ``set_theme`` yet, just the
    # default light palette for the splash background) so we don't
    # block on font-database probing. Everything else is done AFTER
    # the splash is visible.
    icon = _resolve_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    splash = _build_splash(icon)
    if splash is not None:
        splash.show()
        app.processEvents()  # force paint NOW so the user sees branding

    # ---- Slow init AFTER the splash is visible ----------------------------
    # Crash reporter — opt-in, no-op when consent isn't granted
    # or the SDK / DSN aren't configured.
    try:
        from pfc_inductor.telemetry import init_crash_reporter

        init_crash_reporter()
    except Exception:
        pass

    # ``Fusion`` is the only Qt style that fully honours QSS — set
    # BEFORE the stylesheet so its palette is the baseline.
    app.setStyle("Fusion")

    # Try to register JetBrains Mono if shipped (no-op when absent).
    QFontDatabase.addApplicationFont(":/fonts/JetBrainsMono-Regular.ttf")
    # Probe the brand UI font and strip missing entries from the
    # typography stack so Qt's font matcher doesn't waste 37 ms /
    # widget hunting "Inter Variable".
    _patch_brand_typography_to_installed_fonts()

    set_theme(_load_initial_theme())
    _apply_app_palette(app)
    app.setStyleSheet(make_stylesheet(get_theme()))

    # Re-apply both palette and stylesheet on theme toggle so the
    # whole app flips together — without this hook a light → dark
    # toggle leaves the QPalette stale and unstyled widgets keep
    # showing light backgrounds.
    on_theme_changed(
        lambda: (
            _apply_app_palette(app),
            app.setStyleSheet(make_stylesheet(get_theme())),
        )
    )

    # Update the splash message once we know the theme palette.
    if splash is not None:
        from PySide6.QtCore import Qt as _Qt

        splash.showMessage(
            "Loading workspace…",
            int(_Qt.AlignmentFlag.AlignBottom | _Qt.AlignmentFlag.AlignHCenter),
            QColor(get_theme().palette.text_muted),
        )
        app.processEvents()
    _import_main_window()

    win = MainWindow()
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
    sys.exit(main())
