"""Analysis workspace tab — waveforms + flux + thermal + losses + detail.

The second tab of the Project workspace, focused on understanding how
the chosen design behaves. Layout (top → bottom on a 12-column grid):

    +--------------------------------------------------+
    |  FormasOndaCard (col 1-12)                       |
    |    multi-trace stacked: iL · v_source · B        |
    +-------------------------+------------------------+
    |  BHLoopCard (1-7)       |  ThermalGaugeCard (7-12)|
    |   trajectory on B–H     |  gradient gauge + pills |
    +-------------------------+------------------------+
    |  PerdasCard (col 1-12)                           |
    |    horizontal stacked bar + legend               |
    +-------------------------+------------------------+
    |  BobinamentoCard (1-6)  |  EntreferroCard (7-12) |
    |    table of winding     |   gap chart + tiles    |
    +-------------------------+------------------------+
    |  DetalhesTecnicosCard (1-12, collapsed default)  |
    +--------------------------------------------------+

Why the v2 redesign
-------------------
v1 surfaced *one* waveform (iL or B via toggle), no flux trajectory,
and buried the temperature deep in the Details datasheet. The user
called it "very weak". v2 adds:

- **Multi-trace topology-aware waveforms** — iL · source-voltage ·
  B(t) stacked on a shared time axis, with the source and 3-phase
  rotations synthesised analytically from the spec when the engine
  doesn't sample them. Boost / passive / 1ph / 3ph reactors each
  render the right trace set.
- **B–H loop card** — the existing ``BHLoopChart`` (previously only
  in the Validate tab) now shows the operating trajectory next to
  the saturation curve in Analysis too. Reads "where on the knee
  are we?" in one glance.
- **Thermal gauge card** — gradient bar from T_amb → T_max with a
  needle at T_winding, three numeric pills, and a Cu-vs-core
  origin split. Replaces the scalar T buried in Details.

Cards that previously lived in the bento dashboard but don't belong
here:

- ``NucleoCard`` / ``Viz3DCard`` → moved to :class:`NucleoSelectionPage
  <pfc_inductor.ui.workspace.nucleo_selection_page.NucleoSelectionPage>`.
- ``ResumoStrip`` → mounted persistently above the tab widget by
  :class:`ProjetoPage <pfc_inductor.ui.workspace.projeto_page.ProjetoPage>`
  (the Project workspace page).
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
    BHLoopCard,
    BobinamentoCard,
    DetalhesTecnicosCard,
    EntreferroCard,
    FormasOndaCard,
    PerdasCard,
    ThermalGaugeCard,
)
from pfc_inductor.ui.theme import CARD_MIN, get_theme, on_theme_changed


class AnalisePage(QWidget):
    """Analysis tab body — waveforms + losses + winding/gap detail.

    Signals
    -------
    No outbound signals — the page is purely display. Recompute is
    triggered from the spec drawer (left column) or the
    ``Recalculate`` CTA in the workspace header.
    """

    # No public signals — this tab is read-only display.
    _placeholder_signal = Signal()  # keep ``Signal`` import in use

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # The Analysis tab has to honour whatever vertical room the
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

        # Row 0 — Formas de Onda full width (now multi-trace).
        # Stretch=2 because the stacked-axes plot needs the most
        # vertical room of any card on this page.
        self.card_formas = FormasOndaCard()
        self.card_formas.setMinimumWidth(CARD_MIN.formas[0])
        grid.addWidget(self.card_formas, 0, 0, 1, 12)
        grid.setRowStretch(0, 2)

        # Row 1 — Flux (B–H) side by side with the thermal gauge. Both
        # cards earn similar vertical room so the engineer reads
        # "magnetic margin" and "thermal margin" with the same
        # mental gesture.
        self.card_bh = BHLoopCard()
        self.card_thermal = ThermalGaugeCard()
        # Re-use the bobinam minimum-width budget so the two cards
        # share the row gracefully on a 1366 px viewport.
        self.card_bh.setMinimumWidth(CARD_MIN.bobinam[0])
        self.card_thermal.setMinimumWidth(CARD_MIN.bobinam[0])
        grid.addWidget(self.card_bh, 1, 0, 1, 7)
        grid.addWidget(self.card_thermal, 1, 7, 1, 5)
        grid.setRowStretch(1, 2)

        # Row 2 — Perdas full width (stacked bar reads wide).
        self.card_perdas = PerdasCard()
        self.card_perdas.setMinimumWidth(CARD_MIN.perdas[0])
        grid.addWidget(self.card_perdas, 2, 0, 1, 12)
        grid.setRowStretch(2, 1)

        # Row 3 — Bobinamento + Entreferro lado a lado.
        self.card_bobinamento = BobinamentoCard()
        self.card_entreferro = EntreferroCard()
        self.card_bobinamento.setMinimumWidth(CARD_MIN.bobinam[0])
        self.card_entreferro.setMinimumWidth(CARD_MIN.entreferro[0])
        grid.addWidget(self.card_bobinamento, 3, 0, 1, 6)
        grid.addWidget(self.card_entreferro, 3, 6, 1, 6)
        grid.setRowStretch(3, 1)

        # Row 4 — Technical Details full-width, default collapsed.
        # Datasheet-style card with every DesignResult field grouped
        # by domain. Default collapsed so it doesn't crowd the
        # at-a-glance rows above — one click expands it for the
        # engineer who wants every number.
        self.card_detalhes = DetalhesTecnicosCard()
        grid.addWidget(self.card_detalhes, 4, 0, 1, 12)
        grid.setRowStretch(4, 0)

        # Convenience list for batch update / clear loops.
        self._cards = [
            self.card_formas,
            self.card_bh,
            self.card_thermal,
            self.card_perdas,
            self.card_bobinamento,
            self.card_entreferro,
            self.card_detalhes,
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

        title = QLabel("Waiting for the first calculation")
        title.setObjectName("AnaliseEmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        body = QLabel(
            "Adjust the specification in the left column and click "
            "<b>Recalculate</b> at the top. Waveforms, losses and "
            "winding details show up here."
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
