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
def _import_qt_runtime() -> None:
    """Load the Qt + theme stack into module globals.

    Called from :func:`_run_gui` exactly once. Splitting the
    imports into a helper means the CLI path never touches Qt —
    important for headless servers (CI, vendor-quoting pipelines)
    that don't have a display.
    """
    global QSettings, QColor, QFontDatabase, QIcon, QPalette
    global QApplication, MainWindow, make_stylesheet
    global get_theme, on_theme_changed, set_theme
    global SETTINGS_APP, SETTINGS_ORG
    from PySide6.QtCore import QSettings as _QSettings
    from PySide6.QtGui import (
        QColor as _QColor,
        QFontDatabase as _QFontDatabase,
        QIcon as _QIcon,
        QPalette as _QPalette,
    )
    from PySide6.QtWidgets import QApplication as _QApplication

    from pfc_inductor.settings import (
        SETTINGS_APP as _SETTINGS_APP,
        SETTINGS_ORG as _SETTINGS_ORG,
    )
    from pfc_inductor.ui.main_window import MainWindow as _MainWindow
    from pfc_inductor.ui.style import make_stylesheet as _make_stylesheet
    from pfc_inductor.ui.theme import (
        get_theme as _get_theme,
        on_theme_changed as _on_theme_changed,
        set_theme as _set_theme,
    )
    QSettings = _QSettings
    QColor = _QColor
    QFontDatabase = _QFontDatabase
    QIcon = _QIcon
    QPalette = _QPalette
    QApplication = _QApplication
    MainWindow = _MainWindow
    make_stylesheet = _make_stylesheet
    get_theme = _get_theme
    on_theme_changed = _on_theme_changed
    set_theme = _set_theme
    SETTINGS_APP = _SETTINGS_APP
    SETTINGS_ORG = _SETTINGS_ORG


def _load_initial_theme() -> str:
    env = os.environ.get("PFC_THEME", "").lower().strip()
    if env in ("dark", "light"):
        return env
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    val = settings.value("theme", "light")
    return str(val) if val in ("light", "dark") else "light"


def _resolve_icon() -> "QIcon":
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
    candidates.append(pkg_root.parent.parent / "img")          # source checkout
    candidates.append(pkg_root / "img")                         # wheel layout

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
    pieces.extend([
        "-apple-system",
        '"SF Pro Display"',
        '"Segoe UI Variable"',
        '"Segoe UI"',
        '"Helvetica Neue"',
        "Arial",
        "sans-serif",
    ])
    new_stack = ", ".join(pieces)

    new_type = dataclasses.replace(
        _theme._state.type, ui_family_brand=new_stack,
    )
    _theme._state = dataclasses.replace(_theme._state, type=new_type)


def _apply_app_palette(app: "QApplication") -> None:
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
    qp.setColor(QPalette.ColorRole.Window,         QColor(p.bg))
    qp.setColor(QPalette.ColorRole.WindowText,     QColor(p.text))
    qp.setColor(QPalette.ColorRole.Base,           QColor(p.surface))
    qp.setColor(QPalette.ColorRole.AlternateBase,  QColor(p.surface_elevated))
    qp.setColor(QPalette.ColorRole.Text,           QColor(p.text))
    qp.setColor(QPalette.ColorRole.PlaceholderText, QColor(p.text_muted))
    qp.setColor(QPalette.ColorRole.Button,         QColor(p.surface_elevated))
    qp.setColor(QPalette.ColorRole.ButtonText,     QColor(p.text))
    qp.setColor(QPalette.ColorRole.Highlight,      QColor(p.accent))
    qp.setColor(QPalette.ColorRole.HighlightedText, QColor(p.text_inverse))
    qp.setColor(QPalette.ColorRole.ToolTipBase,    QColor(p.surface_elevated))
    qp.setColor(QPalette.ColorRole.ToolTipText,    QColor(p.text))
    qp.setColor(QPalette.ColorRole.Link,           QColor(p.accent))
    qp.setColor(QPalette.ColorRole.LinkVisited,    QColor(p.accent_violet))
    qp.setColor(QPalette.ColorRole.BrightText,     QColor(p.danger))
    # Disabled-state colours — many native widgets use these instead
    # of the regular roles, so muting them prevents the "ghosted but
    # still bright white" look on disabled inputs.
    for role in (QPalette.ColorRole.Text,
                 QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText):
        qp.setColor(QPalette.ColorGroup.Disabled, role,
                    QColor(p.text_muted))
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
    _import_qt_runtime()

    app = QApplication([sys.argv[0], *argv])
    app.setApplicationName(SETTINGS_APP)
    app.setOrganizationName(SETTINGS_ORG)

    # ---- Cross-platform style normalisation ---------------------------
    # macOS defaults to the native ``macintosh`` style which IGNORES
    # large parts of QSS (QPushButton stays white-rounded, QToolButton
    # ignores background colours, etc.). Windows uses ``windowsvista``
    # which respects more but still drifts from Mac. ``Fusion`` is the
    # only Qt style that fully honours QSS, so forcing it everywhere
    # gives pixel-equivalent rendering across platforms — the missing
    # piece behind the "tema escuro está uma merda + Mac/Win não bate"
    # report. Set BEFORE the stylesheet so Fusion's palette is the
    # baseline our QSS extends.
    app.setStyle("Fusion")

    # Application icon — used by the OS dock/taskbar, the About
    # dialog, every QMainWindow's title bar (unless overridden), and
    # alt-tab. Set on the QApplication so child windows inherit it
    # without each having to call ``setWindowIcon`` itself.
    icon = _resolve_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    # Try to register JetBrains Mono if shipped (no-op when absent).
    QFontDatabase.addApplicationFont(":/fonts/JetBrainsMono-Regular.ttf")

    # Probe the brand UI font (Inter Variable). When it isn't
    # installed, Qt logs a 37 ms "Populating font family aliases"
    # warning on every cold start. Strip the missing entries from
    # the typography stack so the first family Qt looks up actually
    # exists.
    _patch_brand_typography_to_installed_fonts()

    set_theme(_load_initial_theme())
    _apply_app_palette(app)
    app.setStyleSheet(make_stylesheet(get_theme()))

    # Re-apply both palette and stylesheet on theme toggle so the
    # whole app flips together — without this hook a light → dark
    # toggle leaves the QPalette stale and unstyled widgets keep
    # showing light backgrounds.
    on_theme_changed(lambda: (
        _apply_app_palette(app),
        app.setStyleSheet(make_stylesheet(get_theme())),
    ))

    win = MainWindow()
    win.show()

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
