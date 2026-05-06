"""Entry point: `python -m pfc_inductor` or `pfc-inductor`."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontDatabase
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


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(SETTINGS_APP)
    app.setOrganizationName(SETTINGS_ORG)

    # Try to register JetBrains Mono if shipped (no-op when absent).
    QFontDatabase.addApplicationFont(":/fonts/JetBrainsMono-Regular.ttf")

    set_theme(_load_initial_theme())
    app.setStyleSheet(make_stylesheet(get_theme()))

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
