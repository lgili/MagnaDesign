"""Análise workspace tab — waveforms + losses + winding/gap details.

The second tab of the Projeto workspace, focused on understanding how
the chosen design behaves. Layout (top to bottom on a 12-column grid):

    +--------------------------------------------------+
    |  FormasOndaCard (col 1-12)                       |
    |    panoramic iL(t) plot + 4 metric tiles below   |
    +--------------------------------------------------+
    |  PerdasCard (col 1-12)                           |
    |    horizontal stacked bar + legend               |
    +-------------------------+------------------------+
    |  BobinamentoCard (1-6)  |  EntreferroCard (7-12) |
    |    table of winding     |   gap chart + tiles    |
    |    detail values        |                        |
    +-------------------------+------------------------+

Cards that previously lived in the bento dashboard but don't belong
here:

- ``NucleoCard`` / ``Viz3DCard`` → moved to :class:`NucleoSelectionPage
  <pfc_inductor.ui.workspace.nucleo_selection_page.NucleoSelectionPage>`.
- ``ResumoStrip`` → mounted persistently above the tab widget by
  :class:`ProjetoPage <pfc_inductor.ui.workspace.projeto_page.ProjetoPage>`.
- ``ResumoCard`` (2×3 metric grid) → dropped; replaced by ResumoStrip.
- ``ProximosPassosCard`` → dropped; the 5 actions are reachable via
  the workspace header CTAs and the sidebar overflow menu.
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
    PerdasCard,
)
from pfc_inductor.ui.theme import CARD_MIN, get_theme, on_theme_changed


class AnalisePage(QWidget):
    """Análise tab body — waveforms + losses + winding/gap detail.

    Signals
    -------
    No outbound signals — the page is purely display. Recompute is
    triggered from the spec drawer (left column) or the
    ``Recalcular`` CTA in the workspace header.
    """

    # No public signals — this tab is read-only display.
    _placeholder_signal = Signal()  # keep ``Signal`` import in use

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
        self._grid_built = False
        self._apply_palette_bg()
        on_theme_changed(self._apply_palette_bg)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _apply_palette_bg(self) -> None:
        bg = get_theme().palette.bg
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background: {bg}; border: 0; }}"
        )
        self._inner.setStyleSheet(f"background: {bg};")
        if self._grid_built:
            return
        self._grid_built = True

        sp = get_theme().spacing
        grid = QGridLayout(self._inner)
        grid.setContentsMargins(sp.page, sp.page, sp.page, sp.page)
        grid.setHorizontalSpacing(sp.card_gap)
        grid.setVerticalSpacing(sp.card_gap)
        for c in range(12):
            grid.setColumnStretch(c, 1)

        # Row 0 — Formas de Onda full width.
        self.card_formas = FormasOndaCard()
        self.card_formas.setMinimumSize(*CARD_MIN.formas)
        grid.addWidget(self.card_formas, 0, 0, 1, 12)
        grid.setRowStretch(0, 2)

        # Row 1 — Perdas full width (stacked bar reads wide).
        self.card_perdas = PerdasCard()
        self.card_perdas.setMinimumSize(*CARD_MIN.perdas)
        grid.addWidget(self.card_perdas, 1, 0, 1, 12)
        grid.setRowStretch(1, 1)

        # Row 2 — Bobinamento + Entreferro lado a lado.
        self.card_bobinamento = BobinamentoCard()
        self.card_entreferro = EntreferroCard()
        self.card_bobinamento.setMinimumSize(*CARD_MIN.bobinam)
        self.card_entreferro.setMinimumSize(*CARD_MIN.entreferro)
        grid.addWidget(self.card_bobinamento, 2, 0, 1, 6)
        grid.addWidget(self.card_entreferro, 2, 6, 1, 6)
        grid.setRowStretch(2, 1)

        # Convenience list for batch update / clear loops.
        self._cards = [
            self.card_formas,
            self.card_perdas,
            self.card_bobinamento,
            self.card_entreferro,
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
