"""Exportar tab — datasheet preview + export CTAs."""
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

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.icons import icon as ui_icon
from pfc_inductor.ui.theme import get_theme
from pfc_inductor.ui.widgets import Card


class ExportarTab(QWidget):
    """Exportar workspace tab."""

    export_html_requested = Signal()
    export_compare_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        intro = QLabel(
            "Gera o datasheet HTML auto-contido (3 páginas) com vistas "
            "ortográficas, especificações e BOM. Pode também exportar a "
            "matriz comparativa em HTML/CSV."
        )
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        outer.addWidget(self._build_datasheet_card())
        outer.addWidget(self._build_compare_export_card())
        outer.addStretch(1)

        self._last_summary: Optional[str] = None

    # ------------------------------------------------------------------
    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        self._summary.setText(
            f"{material.name} · {core.part_number or core.id} · "
            f"L = {result.L_actual_uH:.0f} µH · "
            f"P = {result.losses.P_total_W:.2f} W"
        )

    def clear(self) -> None:
        self._summary.setText("Aguardando cálculo…")

    # ------------------------------------------------------------------
    def _build_datasheet_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Datasheet de fabricante — 3 páginas em HTML auto-contido "
            "(imagens base64). Imprima como PDF a partir do navegador.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)

        self._summary = QLabel("Aguardando cálculo…")
        self._summary.setStyleSheet(self._summary_qss())

        btn = QPushButton("Gerar datasheet (HTML)")
        btn.setProperty("class", "Primary")
        btn.setIcon(ui_icon("file-text",
                            color=get_theme().palette.text_inverse, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.export_html_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)

        v.addWidget(desc)
        v.addWidget(self._summary)
        v.addLayout(row)
        return Card("Datasheet do design", body)

    def _build_compare_export_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Exporta a matriz de comparação atual (até 4 designs) em "
            "HTML auto-contido ou CSV.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("Exportar comparativo")
        btn.setProperty("class", "Secondary")
        btn.setIcon(ui_icon("compare", color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.export_compare_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("Comparativo (HTML/CSV)", body)

    @staticmethod
    def _summary_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"color: {p.text}; font-family: {t.numeric_family};"
            f" font-size: {t.body_md}px; padding: 8px 0;"
        )
