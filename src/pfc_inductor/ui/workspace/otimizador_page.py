"""Otimizador workspace page.

The full Pareto-sweep + ranked-table view lives in
:class:`OptimizerDialog <pfc_inductor.ui.optimize_dialog.OptimizerDialog>`.
This page wraps it as a non-modal CTA card so the user reaches the
optimizer from the sidebar instead of an obscure overflow menu.

The dialog itself stays as the heavy lifter — refactoring it into a
``QWidget`` page is a separate change. What matters for the v3 flow:

- The optimizer is a *first-class destination* in the sidebar.
- Clicking "Abrir Otimizador" launches the modal exactly like the
  legacy overflow menu used to.
- The ``selection_applied(material_id, core_id, wire_id)`` signal
  bubbles up so ``MainWindow`` reuses the same recompute path it
  uses for the Núcleo card "Aplicar".
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


class OtimizadorPage(QWidget):
    """Sidebar destination for the optimizer.

    Signals
    -------
    open_requested
        Emitted when the user clicks "Abrir Otimizador". The host
        (``MainWindow``) opens :class:`OptimizerDialog` in response.
    """

    open_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        title = QLabel("Otimizador")
        title.setProperty("role", "title")
        outer.addWidget(title)

        intro = QLabel(
            "Varre todas as combinações (núcleo × material × fio) "
            "viáveis para a spec atual e mostra a Pareto-front em três "
            "eixos simultâneos: perdas, volume e custo. Selecione um "
            "ponto e clique \"Aplicar\" para trazê-lo de volta ao "
            "projeto.",
        )
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        bullets = QLabel(
            "• ~2 000 designs/segundo no thread separado.\n"
            "• Filtro \"apenas viáveis\" desativa as soluções que "
            "saturariam ou estouram a janela.\n"
            "• Objetivos: minimize perdas / volume / custo, "
            "ou Pareto multiobjetivo.\n"
            "• Top-N pode ser enviado direto ao Comparativo."
        )
        bullets.setProperty("role", "muted")
        bullets.setWordWrap(True)
        v.addWidget(bullets)

        btn = QPushButton("Abrir Otimizador")
        btn.setProperty("class", "Primary")
        btn.setIcon(ui_icon("sliders",
                            color=get_theme().palette.text_inverse, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.open_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addLayout(row)

        outer.addWidget(Card("Pareto sweep multi-objetivo", body))
        outer.addStretch(1)
