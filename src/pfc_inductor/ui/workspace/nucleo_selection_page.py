"""Núcleo selection workspace tab.

The first tab of the Projeto workspace, dedicated entirely to choosing
material + core + wire. Two equally-weighted modes share the tab:

- **Tabela**: ``NucleoCard`` (60% L, scored Material/Núcleo/Fio tabs)
  next to ``Viz3DCard`` (40% R, live preview of the active selection).
- **Otimizador**: ``OptimizerEmbed`` taking the full tab width — its
  three-pane layout (controls + ranked table + Pareto plot) needs the
  whole 1140 px to read clearly.

The mode is restored from ``QSettings`` so the engineer comes back to
the workflow they were in. Switching modes does **not** rerun any
calculation; it only swaps which body is on screen.

This page replaces the ``Design`` tab portion of the v3 dashboard that
hosted the same NucleoCard inside the bento grid.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.settings import SETTINGS_APP, SETTINGS_ORG
from pfc_inductor.ui.dashboard.cards import NucleoCard, Viz3DCard
from pfc_inductor.ui.optimize_dialog import OptimizerEmbed
from pfc_inductor.ui.theme import ANIMATION, CARD_MIN, get_theme, on_theme_changed
from pfc_inductor.ui.widgets import ModeToggle

_QS_MODE_KEY = "ui/projeto/nucleo_mode"  # values: "tabela" | "otimizador"
_QS_HINT_DISMISSED_KEY = "ui/projeto/nucleo_hint_dismissed"


class NucleoSelectionPage(QWidget):
    """First tab of the Projeto workspace — material/core/wire choice.

    Signals
    -------
    selection_applied
        Emitted with ``(material_id, core_id, wire_id)`` when either
        the inline ``NucleoCard`` or the ``OptimizerEmbed`` requests a
        new selection. The host (``MainWindow`` via ``ProjetoPage``)
        re-runs ``design()`` and fans the result back to every tab.
    """

    selection_applied = Signal(str, str, str)
    # Emitted when the user applied a selection from the inline
    # OptimizerEmbed. The host (ProjetoPage) listens and switches the
    # workspace tab to "Análise" so the new design's waveforms are
    # visible immediately. Manual table-driven applies don't fire this
    # — those keep the user in context (table + 3D preview).
    suggest_analise_navigation = Signal()

    def __init__(
        self,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._materials = list(materials)
        self._cores = list(cores)
        self._wires = list(wires)

        outer = QVBoxLayout(self)
        sp = get_theme().spacing
        outer.setContentsMargins(sp.page, sp.page, sp.page, sp.page)
        outer.setSpacing(sp.card_gap)

        # ---- Dismissable hint banner (only on first visits) ----------
        qs = QSettings(SETTINGS_ORG, SETTINGS_APP)
        if not bool(qs.value(_QS_HINT_DISMISSED_KEY, False, type=bool)):
            self._hint_banner = self._build_hint_banner()
            outer.addWidget(self._hint_banner)
        else:
            self._hint_banner = None

        # ---- Toolbar row: caption (L) + mode toggle (R) ---------------
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)

        self._caption = QLabel("Seleção do projeto")
        # Use a strong-secondary colour: text (8.8:1) and semibold so it
        # reads as a section heading, not as muted copy.
        p = get_theme().palette
        t = get_theme().type
        self._caption.setStyleSheet(
            f"color: {p.text}; font-size: {t.title_md}px;"
            f" font-weight: {t.semibold};"
        )
        toolbar.addWidget(self._caption, 1)

        self.toggle = ModeToggle(
            [("tabela", "Tabela"), ("otimizador", "Otimizador")],
        )
        self.toggle.mode_changed.connect(self._on_mode_changed)
        toolbar.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(toolbar)

        # ---- Stacked body (page 0 = tabela, page 1 = otimizador) ------
        # Wrap the stack inside a QScrollArea so the page never forces
        # the window taller than the screen. The NucleoCard's table
        # already enforces its own minimumHeight; if the user shrinks
        # the window below that, the scrollbar handles it gracefully
        # rather than pushing the Scoreboard out of view.
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_tabela_page())
        self._stack.addWidget(self._build_otimizador_page())
        scroll = QScrollArea()
        scroll.setWidget(self._stack)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Expanding)
        outer.addWidget(scroll, 1)

        # ---- Nudge banner: appears below the stack for ~4s after the
        # inline optimizer applies a selection. Hidden by default.
        self._nudge_banner = self._build_nudge_banner()
        self._nudge_banner.hide()
        outer.addWidget(self._nudge_banner)

        # ---- Restore last mode from QSettings -------------------------
        last = str(qs.value(_QS_MODE_KEY, "tabela"))
        if last not in ("tabela", "otimizador"):
            last = "tabela"
        self.toggle.set_mode(last)
        self._on_mode_changed(last)

        on_theme_changed(self._refresh_qss)

    # ------------------------------------------------------------------
    # Tab body factories
    # ------------------------------------------------------------------
    def _build_tabela_page(self) -> QWidget:
        """60/40 split: NucleoCard (left) + Viz3DCard (right)."""
        page = QFrame()
        page.setObjectName("NucleoTabelaPage")
        h = QHBoxLayout(page)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(get_theme().spacing.card_gap)

        # Only constrain the *width* — leaving height elastic lets the
        # page collapse on a 768 px-tall laptop without pushing the
        # Scoreboard off the bottom. The NucleoCard's internal
        # QTableView already enforces its own minimumHeight (260 px)
        # so the table stays scannable regardless.
        self.card_nucleo = NucleoCard()
        self.card_nucleo.setMinimumWidth(CARD_MIN.nucleo[0])
        self.card_nucleo.selection_applied.connect(self.selection_applied.emit)

        self.card_viz3d = Viz3DCard()
        self.card_viz3d.setMinimumWidth(CARD_MIN.viz3d[0])

        # 60/40 via stretch factors. Avoids fragile pixel widths.
        h.addWidget(self.card_nucleo, 6)
        h.addWidget(self.card_viz3d, 4)
        return page

    def _build_otimizador_page(self) -> QWidget:
        """Full-width OptimizerEmbed."""
        page = QFrame()
        page.setObjectName("NucleoOtimizadorPage")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # The embed starts disabled (no spec yet); MainWindow will call
        # ``set_inputs`` after the first successful calc.
        self.optimizer = OptimizerEmbed(
            materials=self._materials,
            cores=self._cores,
            wires=self._wires,
        )
        # Route the inline-optimizer apply through ``_on_optimizer_applied``
        # so we can both bubble the signal up AND nudge the user toward
        # the Análise tab where the waveforms of the new selection live.
        self.optimizer.selection_applied.connect(self._on_optimizer_applied)
        v.addWidget(self.optimizer, 1)
        return page

    def _build_hint_banner(self) -> QFrame:
        """First-launch tutorial banner with a dismiss "✕" affordance.

        Persists ``ui/projeto/nucleo_hint_dismissed`` in QSettings so
        the banner never reappears once the engineer has clicked it
        away. Lives above the toolbar row, doesn't shift on collapse.
        """
        banner = QFrame()
        banner.setObjectName("HintBanner")
        h = QHBoxLayout(banner)
        h.setContentsMargins(14, 10, 8, 10)
        h.setSpacing(10)

        # Body text — Rich text so we can bold "Otimizador" inline.
        body = QLabel(
            "Escolha o material, núcleo e fio na <b>Tabela</b>, ou use "
            "o <b>Otimizador</b> para ranquear todas as combinações por "
            "perda, volume, temperatura ou custo."
        )
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setObjectName("HintBannerBody")
        h.addWidget(body, 1)

        # Dismiss button — small ghost "✕". Always 24×24 px so the hit
        # target stays comfortable at a desktop pointer.
        dismiss = QToolButton()
        dismiss.setText("✕")
        dismiss.setFixedSize(24, 24)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setObjectName("HintBannerDismiss")
        dismiss.setToolTip("Não mostrar novamente")
        dismiss.clicked.connect(self._dismiss_hint)
        h.addWidget(dismiss, 0, Qt.AlignmentFlag.AlignTop)

        self._refresh_hint_qss(banner, body, dismiss)
        return banner

    def _build_nudge_banner(self) -> QFrame:
        """Transient post-apply banner suggesting Análise navigation.

        Appears for ANIMATION.nudge_ms after the inline OptimizerEmbed
        emits ``selection_applied``. The "Ver Análise →" button bubbles
        a :attr:`suggest_analise_navigation` signal that ProjetoPage
        catches and uses to ``switch_to("analise")``.
        """
        banner = QFrame()
        banner.setObjectName("NudgeBanner")
        h = QHBoxLayout(banner)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(10)

        body = QLabel(
            "Seleção aplicada. Veja as formas de onda do novo design."
        )
        body.setObjectName("NudgeBannerBody")
        h.addWidget(body, 1)

        btn = QPushButton("Ver Análise →")
        btn.setObjectName("NudgeBannerCta")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setProperty("class", "Tertiary")
        btn.clicked.connect(self._on_nudge_clicked)
        h.addWidget(btn, 0)

        self._refresh_nudge_qss(banner, body)
        return banner

    # ------------------------------------------------------------------
    # Public API — called by ProjetoPage / MainWindow on each recalc
    # ------------------------------------------------------------------
    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        # NucleoCard tracks "current ids" so the Apply button only
        # enables when the user actually picks something different.
        self.card_nucleo.update_from_design(result, spec, core, wire, material)
        self.card_viz3d.update_from_design(result, spec, core, wire, material)

    def populate(
        self,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        material: Material,
        core: Core,
        wire: Wire,
    ) -> None:
        """Populate the score-table candidate lists on the NucleoCard
        and refresh the inline OptimizerEmbed inputs so its sweep can
        run without the modal dialog."""
        self._materials = list(materials)
        self._cores = list(cores)
        self._wires = list(wires)
        self.card_nucleo.populate(
            spec, materials, cores, wires, material, core, wire,
        )
        self.optimizer.set_inputs(
            spec, materials, cores, wires,
            current_material_id=material.id,
        )

    def clear(self) -> None:
        self.card_nucleo.clear()
        self.card_viz3d.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _on_mode_changed(self, key: str) -> None:
        self._stack.setCurrentIndex(0 if key == "tabela" else 1)
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(_QS_MODE_KEY, key)

    def _on_optimizer_applied(
        self, mat_id: str, core_id: str, wire_id: str,
    ) -> None:
        """Bubble the optimizer's selection upward AND surface a nudge
        toward the Análise tab so the user sees the new waveforms.

        We don't auto-navigate — that strips the user of agency and
        also breaks the otimizador-then-tweak-then-otimizador-again
        loop. A 4 s nudge with a clickable CTA is the gentler middle.
        """
        self.selection_applied.emit(mat_id, core_id, wire_id)
        self._nudge_banner.show()
        QTimer.singleShot(ANIMATION.nudge_ms, self._nudge_banner.hide)

    def _on_nudge_clicked(self) -> None:
        self._nudge_banner.hide()
        self.suggest_analise_navigation.emit()

    def _dismiss_hint(self) -> None:
        if self._hint_banner is None:
            return
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(
            _QS_HINT_DISMISSED_KEY, True,
        )
        self._hint_banner.hide()
        self._hint_banner.deleteLater()
        self._hint_banner = None

    def _refresh_qss(self) -> None:
        # Re-apply theme-bound inline styles on banners (the global
        # stylesheet doesn't reach #HintBanner / #NudgeBanner).
        if self._hint_banner is not None:
            body = self._hint_banner.findChild(QLabel, "HintBannerBody")
            dismiss = self._hint_banner.findChild(QToolButton, "HintBannerDismiss")
            if body is not None and dismiss is not None:
                self._refresh_hint_qss(self._hint_banner, body, dismiss)
        if hasattr(self, "_nudge_banner"):
            body = self._nudge_banner.findChild(QLabel, "NudgeBannerBody")
            if body is not None:
                self._refresh_nudge_qss(self._nudge_banner, body)
        # Re-apply caption colour too, in case the palette flipped.
        p = get_theme().palette
        t = get_theme().type
        self._caption.setStyleSheet(
            f"color: {p.text}; font-size: {t.title_md}px;"
            f" font-weight: {t.semibold};"
        )

    @staticmethod
    def _refresh_hint_qss(banner: QFrame, body: QLabel,
                          dismiss: QToolButton) -> None:
        p = get_theme().palette
        t = get_theme().type
        r = get_theme().radius
        banner.setStyleSheet(
            f"QFrame#HintBanner {{"
            f"  background: {p.info_bg};"
            f"  border: 1px solid {p.info};"
            f"  border-radius: {r.md}px;"
            f"}}"
        )
        body.setStyleSheet(
            f"color: {p.text}; font-size: {t.body}px;"
            f" background: transparent;"
        )
        dismiss.setStyleSheet(
            f"QToolButton {{"
            f"  background: transparent; border: 0;"
            f"  color: {p.text_secondary};"
            f"  font-size: {t.body_md}px; font-weight: {t.semibold};"
            f"  border-radius: {r.sm}px;"
            f"}}"
            f"QToolButton:hover {{ background: {p.surface}; "
            f"color: {p.text}; }}"
        )

    @staticmethod
    def _refresh_nudge_qss(banner: QFrame, body: QLabel) -> None:
        p = get_theme().palette
        t = get_theme().type
        r = get_theme().radius
        banner.setStyleSheet(
            f"QFrame#NudgeBanner {{"
            f"  background: {p.accent_violet_subtle_bg};"
            f"  border: 1px solid {p.accent_violet};"
            f"  border-radius: {r.md}px;"
            f"}}"
        )
        body.setStyleSheet(
            f"color: {p.accent_violet_subtle_text};"
            f" font-size: {t.body}px; font-weight: {t.medium};"
            f" background: transparent;"
        )
