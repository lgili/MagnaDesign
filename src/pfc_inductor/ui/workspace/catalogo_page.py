"""Catalog workspace page — DB editor inline + MAS catalog import.

Hosts the :class:`DbEditorEmbed
<pfc_inductor.ui.db_editor.DbEditorEmbed>` directly (no modal) so the
user can browse and edit the catalog as a first-class destination.
The MAS catalog importer + Similar parts finder remain as modal
dialogs because they are short-lived ask-and-go flows (a one-shot
import dialog over hours of editing makes sense).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.ui.db_editor import DbEditorEmbed
from pfc_inductor.ui.icons import icon as ui_icon
from pfc_inductor.ui.theme import get_theme
from pfc_inductor.ui.widgets import Card


class CatalogoPage(QWidget):
    """Sidebar destination for catalog browsing + MAS import.

    Signals
    -------
    saved
        Emitted by the embedded DB editor whenever the user saves
        changes — the host (``MainWindow``) reloads catalogs and
        triggers a recompute.
    mas_import_requested
        Emitted when the user clicks "Update from MAS".
    similar_requested
        Emitted when the user clicks "Find similar".
    """

    saved = Signal()
    mas_import_requested = Signal()
    similar_requested = Signal()

    # Kept for back-compat with v3.0 wiring; now an alias of ``saved``.
    db_editor_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        from pfc_inductor.ui.shell.page_header import WorkspacePageHeader
        outer.addWidget(WorkspacePageHeader(
            "Catalog",
            "Materials, cores and wires — Brazilian vendors + ~4,760 "
            "entries from the open OpenMagnetics MAS catalog.",
        ))

        body = QFrame()
        body_v = QVBoxLayout(body)
        body_v.setContentsMargins(24, 16, 24, 24)
        body_v.setSpacing(16)
        outer.addWidget(body, 1)

        # ---- Quick-actions row (MAS import + Similar) ------------------
        body_v.addWidget(self._build_actions_card())

        # ---- Inline DB editor — the workspace centerpiece --------------
        self._db_editor = DbEditorEmbed()
        self._db_editor.saved.connect(self.saved.emit)
        editor_body = QFrame()
        eb = QVBoxLayout(editor_body)
        eb.setContentsMargins(0, 0, 0, 0)
        eb.setSpacing(0)
        eb.addWidget(self._db_editor)
        body_v.addWidget(Card("Database editor", editor_body), 1)

    # ------------------------------------------------------------------
    def _build_actions_card(self) -> Card:
        body = QFrame()
        v = QHBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        btn_mas = QPushButton("Update from MAS")
        btn_mas.setProperty("class", "Secondary")
        btn_mas.setIcon(ui_icon("download-cloud",
                                color=get_theme().palette.text, size=14))
        btn_mas.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_mas.clicked.connect(self.mas_import_requested.emit)

        btn_similar = QPushButton("Find similar")
        btn_similar.setProperty("class", "Secondary")
        btn_similar.setIcon(ui_icon("search",
                                     color=get_theme().palette.text, size=14))
        btn_similar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_similar.clicked.connect(self.similar_requested.emit)

        desc = QLabel(
            "Quick actions — import from the open OpenMagnetics "
            "catalog or find drop-in substitutes for the selected core.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)

        v.addWidget(btn_mas)
        v.addWidget(btn_similar)
        v.addStretch(1)

        wrap = QFrame()
        wv = QVBoxLayout(wrap)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.setSpacing(8)
        wv.addWidget(desc)
        wv.addWidget(body)
        return Card("Quick tools", wrap)
