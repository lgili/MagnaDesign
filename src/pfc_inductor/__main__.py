"""Entry point: `python -m pfc_inductor` or `pfc-inductor`."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from pfc_inductor.settings import SETTINGS_APP, SETTINGS_ORG
from pfc_inductor.ui.main_window import MainWindow
from pfc_inductor.ui.style import make_stylesheet
from pfc_inductor.ui.theme import get_theme, on_theme_changed, set_theme


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


def main() -> int:
    app = QApplication(sys.argv)
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
