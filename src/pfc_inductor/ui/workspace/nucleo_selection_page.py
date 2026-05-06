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

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.settings import SETTINGS_APP, SETTINGS_ORG
from pfc_inductor.ui.dashboard.cards import NucleoCard, Viz3DCard
from pfc_inductor.ui.optimize_dialog import OptimizerEmbed
from pfc_inductor.ui.theme import CARD_MIN, get_theme, on_theme_changed
from pfc_inductor.ui.widgets import ModeToggle

_QS_MODE_KEY = "ui/projeto/nucleo_mode"  # values: "tabela" | "otimizador"


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

        # ---- Toolbar row: hint label (L) + mode toggle (R) -------------
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)

        self._hint = QLabel(
            "Escolha o material, núcleo e fio. Use o "
            "<b>Otimizador</b> para ranquear todas as combinações.",
        )
        self._hint.setProperty("role", "muted")
        self._hint.setTextFormat(Qt.TextFormat.RichText)
        self._hint.setWordWrap(True)
        toolbar.addWidget(self._hint, 1)

        self.toggle = ModeToggle(
            [("tabela", "Tabela"), ("otimizador", "Otimizador")],
        )
        self.toggle.mode_changed.connect(self._on_mode_changed)
        toolbar.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(toolbar)

        # ---- Stacked body (page 0 = tabela, page 1 = otimizador) ------
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_tabela_page())
        self._stack.addWidget(self._build_otimizador_page())
        outer.addWidget(self._stack, 1)

        # ---- Restore last mode from QSettings -------------------------
        qs = QSettings(SETTINGS_ORG, SETTINGS_APP)
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

        self.card_nucleo = NucleoCard()
        self.card_nucleo.setMinimumSize(*CARD_MIN.nucleo)
        self.card_nucleo.selection_applied.connect(self.selection_applied.emit)

        self.card_viz3d = Viz3DCard()
        self.card_viz3d.setMinimumSize(*CARD_MIN.viz3d)

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
        self.optimizer.selection_applied.connect(self.selection_applied.emit)
        v.addWidget(self.optimizer, 1)
        return page

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

    def _refresh_qss(self) -> None:
        # The page itself has no QSS — children handle their own theming.
        # This hook exists so future palette-bound styling has a place.
        return
