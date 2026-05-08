"""Persistent collapsible spec drawer.

Wraps the existing :class:`SpecPanel <pfc_inductor.ui.spec_panel.SpecPanel>`
inside a slim left-edge dock. The form (topology, AC input, converter,
thermal, selection) is reused unchanged — the drawer only adds:

- A header strip with the panel title and a chevron toggle that
  collapses the drawer to a 40 px icon-only stub.
- An "Alterar Topologia" button next to the topology combobox that
  opens :class:`TopologyPickerDialog
  <pfc_inductor.ui.dialogs.TopologyPickerDialog>`.
- Persistence of the collapse state via ``QSettings`` so it survives
  app restarts.

The drawer forwards :attr:`SpecPanel.calculate_requested` upward as
its own :attr:`calculate_requested` signal so the host
(:class:`ProjetoPage <pfc_inductor.ui.workspace.projeto_page.ProjetoPage>`)
can route it without knowing about the inner panel.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, Material, Wire
from pfc_inductor.settings import SETTINGS_APP, SETTINGS_ORG
from pfc_inductor.ui.icons import icon as ui_icon
from pfc_inductor.ui.spec_panel import SpecPanel
from pfc_inductor.ui.theme import get_theme, on_theme_changed

_DRAWER_KEY = "shell/spec_drawer_collapsed"
_EXPANDED_WIDTH = 360
# Collapsed width trimmed 44 → 24 — when the drawer is folded the only
# affordance the user needs is the chevron to expand it again. The
# previous 44 px column doubled as a rail of 5 shortcut icons (topology
# / entrada AC / conversor / térmico / seleção) which duplicated
# functions already in the spec form *and* visually competed with the
# 220 px sidebar one column to its left, creating a "two-sidebars" look.
_COLLAPSED_WIDTH = 24


class SpecDrawer(QFrame):
    """Left-edge drawer hosting the spec form. Collapsible to icons."""

    calculate_requested = Signal()
    topology_change_requested = Signal()
    name_changed = Signal(str)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SpecDrawer")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(self._self_qss())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- Header strip -------------------------------------------------
        self._header = QFrame()
        self._header.setObjectName("SpecDrawerHeader")
        self._header.setStyleSheet(self._header_qss())
        h = QHBoxLayout(self._header)
        h.setContentsMargins(14, 10, 8, 10)
        h.setSpacing(8)

        self._title = QLabel("Especificação")
        self._title.setProperty("role", "title")
        self._toggle_btn = QToolButton()
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setStyleSheet(self._chevron_qss())
        self._toggle_btn.clicked.connect(self.toggle_collapsed)
        h.addWidget(self._title, 1)
        h.addWidget(self._toggle_btn, 0)
        outer.addWidget(self._header)

        # ---- Topology indicator row -- single source of truth ------------
        # The button shows the *current* topology and acts as the only
        # affordance for changing it. The combobox that used to live
        # inside ``SpecPanel`` was removed; both widgets fronted the
        # same Spec field and the user could desync them by editing
        # the combobox directly without going through the picker
        # dialog.
        self._topo_row = QFrame()
        self._topo_row.setStyleSheet(self._sub_qss())
        tr = QHBoxLayout(self._topo_row)
        tr.setContentsMargins(14, 8, 14, 8)
        tr.setSpacing(8)
        self._btn_change_topo = QPushButton(self._topology_button_label(
            "boost_ccm", 1,
        ))
        self._btn_change_topo.setProperty("class", "Secondary")
        self._btn_change_topo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_change_topo.setIcon(
            ui_icon("git-branch", color=get_theme().palette.text, size=14)
        )
        self._btn_change_topo.setToolTip(
            "Topologia atual — clique para alterar (abre o seletor "
            "com pré-visualização do esquemático).",
        )
        self._btn_change_topo.clicked.connect(self.topology_change_requested.emit)
        tr.addWidget(self._btn_change_topo, 1)
        outer.addWidget(self._topo_row)

        # ---- Embedded SpecPanel ------------------------------------------
        self._spec_panel = SpecPanel(parent=self)
        self._spec_panel.calculate_requested.connect(self.calculate_requested.emit)
        # Keep the drawer's topology button label in sync whenever the
        # panel's internal state changes (e.g. via ``set_topology`` from
        # MainWindow after the picker dialog returns).
        self._spec_panel.topology_changed.connect(
            self._on_spec_topology_changed,
        )
        outer.addWidget(self._spec_panel, 1)

        # Collapsed state has no extra body — the chevron toggle in the
        # header is enough to re-expand. ``_collapsed_stub`` is kept as
        # an empty frame so ``_apply_state`` can show/hide a single
        # widget instead of branching on every layout child. The
        # previous version stacked 5 shortcut icons here that
        # duplicated form sections; users prefer expanding the drawer.
        self._collapsed_stub = QFrame()
        self._collapsed_stub.setVisible(False)
        outer.addWidget(self._collapsed_stub, 1)

        # Restore previous state
        qs = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._collapsed = bool(qs.value(_DRAWER_KEY, False, type=bool))
        self._apply_state()

        on_theme_changed(self._refresh_qss)

    # ------------------------------------------------------------------
    # Topology label — driven by the SpecPanel's state.
    # ------------------------------------------------------------------
    @staticmethod
    def _topology_button_label(topology: str, n_phases: int = 1) -> str:
        """Pretty label for the Alterar-Topologia button.

        Centralised so the picker dialog's options and this row read
        the same set of names — see ``topology_picker_choices()`` for
        the canonical English labels.
        """
        if topology == "boost_ccm":
            return "Topologia: PFC ativo (boost CCM)"
        if topology == "passive_choke":
            return "Topologia: Choke passivo"
        if topology == "line_reactor":
            phase_label = "3φ" if n_phases == 3 else "1φ"
            return f"Topologia: Reator de linha {phase_label}"
        return f"Topologia: {topology}"

    def _on_spec_topology_changed(self, topology: str, n_phases: int) -> None:
        self._btn_change_topo.setText(
            self._topology_button_label(topology, n_phases),
        )

    # ------------------------------------------------------------------
    # Public API — accessors that proxy to the embedded SpecPanel so
    # ``CalculationController`` can speak to the drawer interchangeably.
    # ------------------------------------------------------------------
    @property
    def spec_panel(self) -> SpecPanel:
        return self._spec_panel

    def get_spec(self):
        return self._spec_panel.get_spec()

    def get_material_id(self) -> str:
        return self._spec_panel.get_material_id()

    def get_core_id(self) -> str:
        return self._spec_panel.get_core_id()

    def get_wire_id(self) -> str:
        return self._spec_panel.get_wire_id()

    # ------------------------------------------------------------------
    # Collapse / expand
    # ------------------------------------------------------------------
    def is_collapsed(self) -> bool:
        return self._collapsed

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._apply_state()
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(_DRAWER_KEY, collapsed)

    def _apply_state(self) -> None:
        self.setFixedWidth(_COLLAPSED_WIDTH if self._collapsed else _EXPANDED_WIDTH)
        self._title.setVisible(not self._collapsed)
        self._spec_panel.setVisible(not self._collapsed)
        self._topo_row.setVisible(not self._collapsed)
        self._collapsed_stub.setVisible(self._collapsed)
        # Tighten header margins when collapsed so the chevron has room
        # to centre inside the 24 px rail (the expanded margins of
        # 14/8 would clip it).
        header_lay = self._header.layout()
        if header_lay is not None:
            if self._collapsed:
                header_lay.setContentsMargins(3, 10, 3, 10)
            else:
                header_lay.setContentsMargins(14, 10, 8, 10)
        self._refresh_chevron_icon()

    def _refresh_chevron_icon(self) -> None:
        name = "chevron-right" if not self._collapsed else "chevron-left"
        # ``chevron-left`` isn't bundled — fall back to chevron-right
        # rotated via property if needed. For now we use the bundled one
        # and rely on icon rotation (180°) by simply swapping label text.
        # Lucide bundle has chevron-down/right; reuse "chevron-right" and
        # flip via icon name "chevron-down" when collapsed for a clear
        # different glyph.
        if self._collapsed:
            ic = ui_icon("chevron-right", color=get_theme().palette.text_muted, size=18)
        else:
            # When expanded, indicate "click to collapse left" — use down
            # arrow as a "fold" hint (chevron-down in the bundled set).
            ic = ui_icon("chevron-down", color=get_theme().palette.text_muted, size=18)
            _ = name  # silence linter
        self._toggle_btn.setIcon(ic)

    # ------------------------------------------------------------------
    # Theme refresh
    # ------------------------------------------------------------------
    def _refresh_qss(self) -> None:
        self.setStyleSheet(self._self_qss())
        self._header.setStyleSheet(self._header_qss())
        self._topo_row.setStyleSheet(self._sub_qss())
        self._toggle_btn.setStyleSheet(self._chevron_qss())
        # Re-tint icons.
        p = get_theme().palette
        self._btn_change_topo.setIcon(
            ui_icon("git-branch", color=p.text, size=14)
        )
        self._refresh_chevron_icon()

    @staticmethod
    def _self_qss() -> str:
        p = get_theme().palette
        return (
            f"QFrame#SpecDrawer {{"
            f"  background: {p.surface};"
            f"  border: 0;"
            f"  border-right: 1px solid {p.border};"
            f"}}"
        )

    @staticmethod
    def _header_qss() -> str:
        p = get_theme().palette
        return (
            f"QFrame#SpecDrawerHeader {{"
            f"  background: {p.surface};"
            f"  border: 0;"
            f"  border-bottom: 1px solid {p.border};"
            f"}}"
        )

    @staticmethod
    def _sub_qss() -> str:
        p = get_theme().palette
        return (
            f"QFrame {{"
            f"  background: {p.surface};"
            f"  border: 0;"
            f"  border-bottom: 1px solid {p.border};"
            f"}}"
        )

    @staticmethod
    def _chevron_qss() -> str:
        p = get_theme().palette
        return (
            f"QToolButton {{"
            f"  background: transparent; border: 0; padding: 4px;"
            f"  border-radius: 6px;"
            f"}}"
            f"QToolButton:hover {{ background: {p.bg}; }}"
        )
