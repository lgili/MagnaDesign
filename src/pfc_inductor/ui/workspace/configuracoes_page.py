"""Configurações workspace page.

Theme toggle, FEA installer, Litz optimizer, About. The "Modo
clássico" toggle (which used to live here) is removed in v3 — the
legacy splitter is no longer reachable.
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
from pfc_inductor.ui.theme import get_theme, is_dark
from pfc_inductor.ui.widgets import Card, wrap_scrollable


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
        outer.addWidget(WorkspacePageHeader(
            "Configurações",
            "Tema, FEA (FEMMT + ONELAB), Litz wire e informações do projeto.",
        ))

        body = QFrame()
        body_v = QVBoxLayout(body)
        body_v.setContentsMargins(24, 16, 24, 24)
        body_v.setSpacing(16)

        body_v.addWidget(self._build_theme_card())
        body_v.addWidget(self._build_fea_card())
        body_v.addWidget(self._build_litz_card())
        body_v.addWidget(self._build_about_card())
        body_v.addStretch(1)

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
            "Alterna entre tema claro e escuro. A barra lateral "
            "permanece sempre na cor de marca (navy).",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("Alternar tema")
        btn.setProperty("class", "Secondary")
        icon_name = "sun" if is_dark() else "moon"
        btn.setIcon(ui_icon(icon_name,
                            color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.theme_toggle_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("Tema", body)

    def _build_fea_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Verifica e instala dependências FEM (ONELAB + FEMMT). "
            "Necessário para rodar a Validação FEM com geometria "
            "EE/ETD/PQ.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("Verificar / instalar FEA")
        btn.setProperty("class", "Secondary")
        btn.setIcon(ui_icon("cog", color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.fea_install_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("Dependências FEM", body)

    def _build_litz_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Recomenda diâmetro de strand e número de strands para "
            "atingir um ratio AC/DC alvo via critério Sullivan.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("Otimizador Litz")
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
            "Posicionamento competitivo do projeto contra FEMMT, MAS, "
            "AI-mag, Frenetic, MagInc e Coilcraft.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("Sobre")
        btn.setProperty("class", "Secondary")
        btn.setIcon(ui_icon("info", color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.about_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("Sobre o projeto", body)
