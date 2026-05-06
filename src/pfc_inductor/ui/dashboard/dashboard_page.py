"""Dashboard page — 3-row card grid with the 9 MagnaDesign cards.

Row 0 (3 cols):  Topologia │ Resumo │ Formas de Onda
Row 1 (3 cols):  Núcleo (1)  │ Visualização 3D (col-span 2)
Row 2 (4 sub-cols spanning 3 outer cols): Perdas │ Bobinamento │ Entreferro │ Próximos Passos
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QGridLayout, QVBoxLayout, QScrollArea, QFrame,
)

from pfc_inductor.models import Spec, Material, Core, Wire, DesignResult
from pfc_inductor.ui.theme import get_theme, on_theme_changed
from pfc_inductor.ui.dashboard.cards import (
    TopologiaCard, ResumoCard, FormasOndaCard, NucleoCard,
    Viz3DCard, PerdasCard, BobinamentoCard, EntreferroCard,
    ProximosPassosCard,
)


class DashboardPage(QWidget):
    """The default page mounted in the workspace stack.

    Signals
    -------
    Each forwarded signal corresponds to a Próximos-Passos action — the
    parent (``MainWindow``) wires them to the existing dialog launchers.
    """

    fea_requested = Signal()
    compare_requested = Signal()
    litz_requested = Signal()
    report_requested = Signal()
    similar_requested = Signal()
    topology_change_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll = scroll

        inner = QWidget()
        scroll.setWidget(inner)
        self._inner = inner
        outer.addWidget(scroll, 1)
        self._apply_palette_bg()
        on_theme_changed(self._apply_palette_bg)

    def _apply_palette_bg(self) -> None:
        bg = get_theme().palette.bg
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background: {bg}; border: 0; }}"
        )
        self._inner.setStyleSheet(f"background: {bg};")

        sp = get_theme().spacing
        grid = QGridLayout(self._inner)
        grid.setContentsMargins(sp.page, sp.page, sp.page, sp.page)
        grid.setHorizontalSpacing(sp.card_gap)
        grid.setVerticalSpacing(sp.card_gap)

        # Equal-width 3 outer columns
        for c in range(3):
            grid.setColumnStretch(c, 1)

        # ---- row 0: Topologia | Resumo | Formas de Onda ---------------
        self.card_topologia = TopologiaCard()
        self.card_resumo = ResumoCard()
        self.card_formas = FormasOndaCard()
        grid.addWidget(self.card_topologia, 0, 0)
        grid.addWidget(self.card_resumo, 0, 1)
        grid.addWidget(self.card_formas, 0, 2)

        # ---- row 1: Núcleo (1 col) | Visualização 3D (2 cols) --------
        self.card_nucleo = NucleoCard()
        self.card_viz3d = Viz3DCard()
        grid.addWidget(self.card_nucleo, 1, 0)
        grid.addWidget(self.card_viz3d, 1, 1, 1, 2)
        # Make row 1 taller to accommodate the 3D viewer.
        grid.setRowStretch(1, 1)

        # ---- row 2: 4 sub-cards inside one row that spans 3 cols ------
        bottom_strip = QFrame()
        bs = QGridLayout(bottom_strip)
        bs.setContentsMargins(0, 0, 0, 0)
        bs.setHorizontalSpacing(sp.card_gap)
        bs.setVerticalSpacing(0)

        self.card_perdas = PerdasCard()
        self.card_bobinamento = BobinamentoCard()
        self.card_entreferro = EntreferroCard()
        self.card_proximos = ProximosPassosCard()
        for c in range(4):
            bs.setColumnStretch(c, 1)
        bs.addWidget(self.card_perdas, 0, 0)
        bs.addWidget(self.card_bobinamento, 0, 1)
        bs.addWidget(self.card_entreferro, 0, 2)
        bs.addWidget(self.card_proximos, 0, 3)
        grid.addWidget(bottom_strip, 2, 0, 1, 3)

        # ---- forward Próximos-Passos signals --------------------------
        self.card_proximos.fea_requested.connect(self.fea_requested.emit)
        self.card_proximos.compare_requested.connect(self.compare_requested.emit)
        self.card_proximos.litz_requested.connect(self.litz_requested.emit)
        self.card_proximos.report_requested.connect(self.report_requested.emit)
        self.card_proximos.similar_requested.connect(self.similar_requested.emit)
        self.card_topologia.topology_change_requested.connect(
            self.topology_change_requested.emit
        )

        # ---- collect cards for batch operations -----------------------
        self._cards = [
            self.card_topologia, self.card_resumo, self.card_formas,
            self.card_nucleo, self.card_viz3d,
            self.card_perdas, self.card_bobinamento,
            self.card_entreferro, self.card_proximos,
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        for card in self._cards:
            card.update_from_design(result, spec, core, wire, material)

    def clear(self) -> None:
        for card in self._cards:
            card.clear()

    def mark_action_done(self, key: str) -> None:
        """Forward to ProximosPassosCard so the parent can mark e.g.
        "report" done after generating a datasheet."""
        self.card_proximos.mark_step_done(key)
