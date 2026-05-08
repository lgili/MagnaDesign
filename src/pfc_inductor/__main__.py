"""Entry point: `python -m pfc_inductor` or `pfc-inductor`."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from pfc_inductor.settings import SETTINGS_APP, SETTINGS_ORG
from pfc_inductor.ui.main_window import MainWindow
from pfc_inductor.ui.style import make_stylesheet
from pfc_inductor.ui.theme import get_theme, set_theme


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


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(SETTINGS_APP)
    app.setOrganizationName(SETTINGS_ORG)

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
    app.setStyleSheet(make_stylesheet(get_theme()))

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
