"""Dashboard page — 12-column bento grid for the Projeto workspace.

Layout (col 1-12, top to bottom):

    +-----------------------------------------------------------+
    |  ResumoStrip (col 1-12, fixed 96 px)                       |
    +----------------------------------+------------------------+
    |  Núcleo (col 1-7)                 |  Visualização 3D (col 8-12) |
    |  minHeight 380                     |  minHeight 360         |
    +-----------------------------------------------------------+
    |  Formas de Onda (col 1-12)                                 |
    +-------------+----------+----------+--------------+--------+
    |  Perdas (3) | Bobi (3) | Entref(3)| Próximos (3) |
    +-------------+----------+----------+--------------+

Why bento, not a fixed 2-col grid:
- A 2-col uniform grid forces a 480 px-wide table to share width with
  a metric tile that wants 130 px — both end up wrong. The bento lets
  each card claim its natural span (Núcleo 7/12, Viz3D 5/12, etc.)
  without competing.
- Resumo is now an inline ``ResumoStrip`` (no card chrome) at the top
  rather than a 2×3 ``ResumoCard`` block — recovers ~120 px of vertical
  room for the table-and-3D row.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.dashboard.cards import (
    BobinamentoCard,
    EntreferroCard,
    FormasOndaCard,
    NucleoCard,
    PerdasCard,
    ProximosPassosCard,
    Viz3DCard,
)
from pfc_inductor.ui.dashboard.protocols import DesignDisplay
from pfc_inductor.ui.theme import CARD_MIN, get_theme, on_theme_changed
from pfc_inductor.ui.widgets import ResumoStrip


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
        self._scroll.setStyleSheet(f"QScrollArea {{ background: {bg}; border: 0; }}")
        self._inner.setStyleSheet(f"background: {bg};")

        # Avoid re-creating the grid on every theme toggle.
        if getattr(self, "_grid_built", False):
            return
        self._grid_built = True

        sp = get_theme().spacing
        grid = QGridLayout(self._inner)
        grid.setContentsMargins(sp.page, sp.page, sp.page, sp.page)
        grid.setHorizontalSpacing(sp.card_gap)
        grid.setVerticalSpacing(sp.card_gap)

        # 12-column bento grid. Each card claims a natural span:
        # Núcleo 7, Viz3D 5, Resumo 12, FormasOnda 12, bottom strip 3+3+3+3.
        for c in range(12):
            grid.setColumnStretch(c, 1)

        # ---- row 0: ResumoStrip (full width, no card chrome) ----------
        self.kpi_strip = ResumoStrip()
        grid.addWidget(self.kpi_strip, 0, 0, 1, 12)

        # ---- row 1: Núcleo (7) | Visualização 3D (5) ------------------
        self.card_nucleo = NucleoCard()
        self.card_nucleo.setMinimumSize(*CARD_MIN.nucleo)
        self.card_viz3d = Viz3DCard()
        self.card_viz3d.setMinimumSize(*CARD_MIN.viz3d)
        grid.addWidget(self.card_nucleo, 1, 0, 1, 7)
        grid.addWidget(self.card_viz3d, 1, 7, 1, 5)
        # Row floor pulled from theme.dashboard.row_kpi_min (320 px
        # default) so dashboard density tweaks land in one place.
        # The cards still pin their own minimums; this floor only
        # matters when stretching tall on bigger displays.
        from pfc_inductor.ui.theme import get_theme as _get_theme

        _dl = _get_theme().dashboard
        grid.setRowMinimumHeight(1, _dl.row_kpi_min)
        grid.setRowStretch(1, 2)

        # ---- row 2: Formas de Onda (full width) -----------------------
        self.card_formas = FormasOndaCard()
        self.card_formas.setMinimumSize(*CARD_MIN.formas)
        grid.addWidget(self.card_formas, 2, 0, 1, 12)
        grid.setRowStretch(2, 1)

        # ---- row 3: 4 sub-cards (3/3/3/3 on the 12-col grid) ---------
        self.card_perdas = PerdasCard()
        self.card_bobinamento = BobinamentoCard()
        self.card_entreferro = EntreferroCard()
        self.card_proximos = ProximosPassosCard()
        self.card_perdas.setMinimumSize(*CARD_MIN.perdas)
        self.card_bobinamento.setMinimumSize(*CARD_MIN.bobinam)
        self.card_entreferro.setMinimumSize(*CARD_MIN.entreferro)
        self.card_proximos.setMinimumSize(*CARD_MIN.proximos)
        grid.addWidget(self.card_perdas, 3, 0, 1, 3)
        grid.addWidget(self.card_bobinamento, 3, 3, 1, 3)
        grid.addWidget(self.card_entreferro, 3, 6, 1, 3)
        grid.addWidget(self.card_proximos, 3, 9, 1, 3)

        # ---- forward Próximos-Passos signals --------------------------
        self.card_proximos.fea_requested.connect(self.fea_requested.emit)
        self.card_proximos.compare_requested.connect(self.compare_requested.emit)
        self.card_proximos.litz_requested.connect(self.litz_requested.emit)
        self.card_proximos.report_requested.connect(self.report_requested.emit)
        self.card_proximos.similar_requested.connect(self.similar_requested.emit)

        # ---- collect cards for batch operations -----------------------
        # ``kpi_strip`` is included so ``update_from_design`` fans out
        # to it via the same loop as the cards. ``ResumoCard`` is no
        # longer mounted here — kept importable for tests/legacy pages.
        # Typed as ``list[DesignDisplay]`` so mypy/pyright catch a card
        # that drifts away from the contract.
        self._cards: list[DesignDisplay] = [
            self.kpi_strip,
            self.card_formas,
            self.card_nucleo,
            self.card_viz3d,
            self.card_perdas,
            self.card_bobinamento,
            self.card_entreferro,
            self.card_proximos,
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update_from_design(
        self, result: DesignResult, spec: Spec, core: Core, wire: Wire, material: Material
    ) -> None:
        for card in self._cards:
            card.update_from_design(result, spec, core, wire, material)

    def clear(self) -> None:
        for card in self._cards:
            card.clear()

    def mark_action_done(self, key: str) -> None:
        """Forward to ProximosPassosCard so the parent can mark e.g.
        "report" done after generating a datasheet."""
        self.card_proximos.mark_step_done(key)
