"""Settings workspace page.

Theme toggle, FEA installer, Litz optimizer, About. The "Classic
mode" toggle (which used to live here) is removed in v3 — the
legacy splitter is no longer reachable.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.settings import SETTINGS_APP, SETTINGS_ORG
from pfc_inductor.ui.icons import icon as ui_icon
from pfc_inductor.ui.theme import get_theme, is_dark
from pfc_inductor.ui.widgets import Card, wrap_scrollable

# QSettings key for the persisted FEA backend selection.
_FEA_BACKEND_KEY = "fea/backend"
# Maps the human-readable label to the env-var value the dispatcher
# reads. ``"auto"`` is the legacy shape-based heuristic (no override).
_BACKEND_OPTIONS: list[tuple[str, str]] = [
    ("Auto (legacy: FEMMT for EE/PQ, FEMM for toroid)", "auto"),
    ("Direct (in-tree, faster, no FEMMT dependency)", "direct"),
    ("FEMMT (force, even for toroids)", "femmt"),
    ("FEMM (legacy xfemm/femm.exe)", "femm"),
]


class ConfiguracoesPage(QWidget):
    """Sidebar destination for app-wide settings + dev tools."""

    theme_toggle_requested = Signal()
    fea_install_requested = Signal()
    litz_optimizer_requested = Signal()
    about_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        from pfc_inductor.ui.shell.page_header import WorkspacePageHeader

        outer.addWidget(
            WorkspacePageHeader(
                "Settings",
                "Theme, FEA (FEMMT + ONELAB), Litz wire and project info.",
            )
        )

        body = QFrame()
        body_v = QVBoxLayout(body)
        body_v.setContentsMargins(24, 16, 24, 24)
        body_v.setSpacing(16)

        body_v.addWidget(self._build_theme_card())
        body_v.addWidget(self._build_fea_card())
        body_v.addWidget(self._build_fea_backend_card())
        body_v.addWidget(self._build_litz_card())
        body_v.addWidget(self._build_about_card())
        body_v.addStretch(1)

        # Apply the saved backend selection on launch so the env var
        # is set before the first cascade run.
        self._apply_saved_backend()

        # Wrap the cards in a scroll area so the page degrades
        # gracefully on small viewports — adding more cards here
        # later (theme variants, advanced toggles, etc.) won't
        # silently push the bottom of the window past the screen
        # edge.
        outer.addWidget(wrap_scrollable(body), 1)

    # ------------------------------------------------------------------
    def _build_theme_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Toggles between light and dark themes. The sidebar always "
            "stays in the brand colour (navy).",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("Toggle theme")
        btn.setProperty("class", "Secondary")
        icon_name = "sun" if is_dark() else "moon"
        btn.setIcon(ui_icon(icon_name, color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.theme_toggle_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("Theme", body)

    def _build_fea_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Checks and installs FEM dependencies (ONELAB + FEMMT). "
            "Required to run FEM Validation with EE/ETD/PQ geometry.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("Check / install FEA")
        btn.setProperty("class", "Secondary")
        btn.setIcon(ui_icon("cog", color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.fea_install_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("FEM dependencies", body)

    def _build_fea_backend_card(self) -> Card:
        """A combo to pick the FEA backend used by Tier 3 + UI.

        Persisted in QSettings under ``fea/backend``. The
        dispatcher (``pfc_inductor.fea.runner.validate_design``)
        reads the env var ``PFC_FEA_BACKEND``, which this card
        keeps in sync. Selecting ``"auto"`` (the default) restores
        shape-based dispatch.
        """
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Selects the FEA engine for the Validate (FEA) action "
            'and Cascade Tier 3. "Direct" uses our in-tree solver '
            "(microsecond toroidals, no FEMMT cold-start). The other "
            "options force the legacy backends regardless of shape.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        self._backend_combo = QComboBox()
        for label, _value in _BACKEND_OPTIONS:
            self._backend_combo.addItem(label)
        # Load saved selection from QSettings.
        qs = QSettings(SETTINGS_ORG, SETTINGS_APP)
        saved = str(qs.value(_FEA_BACKEND_KEY, "auto") or "auto").lower()
        for i, (_label, value) in enumerate(_BACKEND_OPTIONS):
            if value == saved:
                self._backend_combo.setCurrentIndex(i)
                break
        self._backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        row = QHBoxLayout()
        row.addWidget(QLabel("Backend:"))
        row.addWidget(self._backend_combo, 1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("FEA backend", body)

    def _on_backend_changed(self, index: int) -> None:
        """Persist the selection and update ``PFC_FEA_BACKEND``."""
        if index < 0 or index >= len(_BACKEND_OPTIONS):
            return
        _label, value = _BACKEND_OPTIONS[index]
        qs = QSettings(SETTINGS_ORG, SETTINGS_APP)
        qs.setValue(_FEA_BACKEND_KEY, value)
        if value == "auto":
            os.environ.pop("PFC_FEA_BACKEND", None)
        else:
            os.environ["PFC_FEA_BACKEND"] = value

    def _apply_saved_backend(self) -> None:
        """Set the env var to match the persisted selection.

        Called from __init__ so the first cascade / FEA solve in
        a session uses the user's preference without requiring
        them to re-open this page.
        """
        qs = QSettings(SETTINGS_ORG, SETTINGS_APP)
        saved = str(qs.value(_FEA_BACKEND_KEY, "auto") or "auto").lower()
        if saved in ("direct", "femmt", "femm"):
            os.environ["PFC_FEA_BACKEND"] = saved
        else:
            os.environ.pop("PFC_FEA_BACKEND", None)

    def _build_litz_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Recommends strand diameter and strand count to hit a "
            "target AC/DC ratio via the Sullivan criterion.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("Litz optimizer")
        btn.setProperty("class", "Secondary")
        btn.setIcon(ui_icon("braid", color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.litz_optimizer_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("Litz wire", body)

    def _build_about_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Competitive positioning of the project against FEMMT, "
            "MAS, AI-mag, Frenetic, MagInc and Coilcraft.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("About")
        btn.setProperty("class", "Secondary")
        btn.setIcon(ui_icon("info", color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.about_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("About the project", body)
