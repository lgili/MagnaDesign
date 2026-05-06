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

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
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
        # The Análise tab has to honour whatever vertical room the
        # parent QTabWidget gives it — without an Expanding policy on
        # the page itself, Qt grows the page to its preferred height
        # (= grid's minimum sum, ~700 px) and pushes the surrounding
        # Scoreboard off the screen on smaller laptops.
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Use a QStackedWidget (not a bare QStackedLayout) so we can
        # add it to the outer QVBoxLayout with an explicit stretch
        # factor of 1 — that's what tells Qt the stack should consume
        # all available vertical space and clip via the inner
        # QScrollArea instead of dictating the page's preferred height.
        self._stack = QStackedWidget(self)
        self._stack.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Expanding)
        outer.addWidget(self._stack, 1)

        # Empty-state placeholder (page 0).
        self._empty_state = self._build_empty_state()
        self._stack.addWidget(self._empty_state)

        # Live grid (page 1) — built lazily by _apply_palette_bg.
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Expanding)
        self._scroll = scroll

        inner = QWidget()
        scroll.setWidget(inner)
        self._inner = inner
        self._stack.addWidget(scroll)
        # Show empty by default until the first design lands.
        self._stack.setCurrentIndex(0)
        self._has_data = False

        self._grid_built = False
        self._apply_palette_bg()
        on_theme_changed(self._apply_palette_bg)
        on_theme_changed(self._refresh_empty_qss)

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

        # Width-only minimums — letting card heights stay elastic
        # means the AnalisePage sums to a much smaller minimum height,
        # so the page fits on a 768 px laptop without overflowing the
        # window. The QScrollArea above wraps the grid for the case
        # where the user genuinely wants more vertical room than the
        # window provides.

        # Row 0 — Formas de Onda full width.
        self.card_formas = FormasOndaCard()
        self.card_formas.setMinimumWidth(CARD_MIN.formas[0])
        grid.addWidget(self.card_formas, 0, 0, 1, 12)
        grid.setRowStretch(0, 2)

        # Row 1 — Perdas full width (stacked bar reads wide).
        self.card_perdas = PerdasCard()
        self.card_perdas.setMinimumWidth(CARD_MIN.perdas[0])
        grid.addWidget(self.card_perdas, 1, 0, 1, 12)
        grid.setRowStretch(1, 1)

        # Row 2 — Bobinamento + Entreferro lado a lado.
        self.card_bobinamento = BobinamentoCard()
        self.card_entreferro = EntreferroCard()
        self.card_bobinamento.setMinimumWidth(CARD_MIN.bobinam[0])
        self.card_entreferro.setMinimumWidth(CARD_MIN.entreferro[0])
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
        # First successful update — swap from the empty placeholder to
        # the live grid. Subsequent updates are no-ops on the stack.
        if not self._has_data:
            self._has_data = True
            self._stack.setCurrentIndex(1)

    def clear(self) -> None:
        for card in self._cards:
            card.clear()
        # Revert to the empty placeholder so the page reads as
        # "waiting for input" instead of "broken with em-dashes".
        self._has_data = False
        self._stack.setCurrentIndex(0)

    # ------------------------------------------------------------------
    # Empty-state placeholder
    # ------------------------------------------------------------------
    def _build_empty_state(self) -> QWidget:
        page = QFrame()
        page.setObjectName("AnaliseEmptyState")
        v = QVBoxLayout(page)
        v.setContentsMargins(48, 48, 48, 48)
        v.setSpacing(12)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Aguardando o primeiro cálculo")
        title.setObjectName("AnaliseEmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        body = QLabel(
            "Ajuste a especificação na coluna esquerda e clique em "
            "<b>Recalcular</b> no topo. As formas de onda, perdas e "
            "detalhes do enrolamento aparecem aqui."
        )
        body.setObjectName("AnaliseEmptyBody")
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setMaximumWidth(520)

        v.addStretch(1)
        v.addWidget(title, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(body, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addStretch(2)

        self._empty_title = title
        self._empty_body = body
        self._refresh_empty_qss()
        return page

    def _refresh_empty_qss(self) -> None:
        if not hasattr(self, "_empty_title"):
            return
        p = get_theme().palette
        t = get_theme().type
        # Theme-tinted background that distinguishes the empty state
        # from a stuck/loading view but still sits on the same page bg.
        if hasattr(self, "_empty_state"):
            self._empty_state.setStyleSheet(
                f"QFrame#AnaliseEmptyState {{ background: {p.bg};"
                f" border: 0; }}"
            )
        self._empty_title.setStyleSheet(
            f"color: {p.text}; font-size: {t.title_lg}px;"
            f" font-weight: {t.semibold};"
        )
        self._empty_body.setStyleSheet(
            f"color: {p.text_secondary}; font-size: {t.body_md}px;"
        )
