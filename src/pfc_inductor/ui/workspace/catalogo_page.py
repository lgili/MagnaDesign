"""Catálogo workspace page — DB editor + MAS catalog import.

Both legacy dialogs (``DbEditorDialog`` and ``CatalogUpdateDialog``)
are still launched as modals; the page just gives them a discoverable
home in the sidebar instead of hiding them in an overflow menu.
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

from pfc_inductor.ui.icons import icon as ui_icon
from pfc_inductor.ui.theme import get_theme
from pfc_inductor.ui.widgets import Card


class CatalogoPage(QWidget):
    """Sidebar destination for catalog browsing + MAS import."""

    db_editor_requested = Signal()
    mas_import_requested = Signal()
    similar_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        title = QLabel("Catálogo")
        title.setProperty("role", "title")
        outer.addWidget(title)

        intro = QLabel(
            "Materiais, núcleos e fios disponíveis no projeto. Edite "
            "valores existentes, adicione vendors brasileiros (Thornton, "
            "Magmattec, Dongxing) ou puxe ~410 materiais e 4 350 fios "
            "do catálogo aberto OpenMagnetics MAS.",
        )
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        outer.addWidget(self._build_db_card())
        outer.addWidget(self._build_mas_card())
        outer.addWidget(self._build_similar_card())
        outer.addStretch(1)

    # ------------------------------------------------------------------
    def _build_db_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Editor JSON-backed das tabelas de materiais, núcleos e "
            "fios. Edita em-place; salva no diretório de dados do "
            "usuário sem mexer nos arquivos do pacote.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("Abrir editor de base de dados")
        btn.setProperty("class", "Secondary")
        btn.setIcon(ui_icon("database",
                            color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.db_editor_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("Base de dados local", body)

    def _build_mas_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Faz pull do catálogo OpenMagnetics MAS (~410 mat, "
            "4 350 fios) e funde com a base local. Pode escolher "
            "merge-substituir ou merge-acrescentar.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("Atualizar do MAS")
        btn.setProperty("class", "Secondary")
        btn.setIcon(ui_icon("download-cloud",
                            color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.mas_import_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("Importar OpenMagnetics MAS", body)

    def _build_similar_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Busca substitutos drop-in (mesmo Ve, mesma classe de "
            "material, AL próximo) — útil para troca de fornecedor "
            "ou para checar se há um core mais barato.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("Buscar similares")
        btn.setProperty("class", "Secondary")
        btn.setIcon(ui_icon("search",
                            color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.similar_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("Buscar substitutos similares", body)
