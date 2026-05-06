"""Topology picker dialog.

Shown when the user clicks "Alterar Topologia" on the Topologia card.
Presents the four supported topologies as selectable cards, each with
a small schematic preview and a one-line description. Returns the
canonical topology key + ``n_phases`` (only meaningful for the line
reactor variants).

The dialog is intentionally light — no engine calls, no heavy state.
It is a presentational widget over a ``Literal`` choice.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel,
    QFrame, QWidget, QSizePolicy, QDialogButtonBox,
)

from pfc_inductor.ui.theme import get_theme
from pfc_inductor.ui.widgets import TopologySchematicWidget


# (key, label, n_phases-or-None, description)
_OPTIONS: list[tuple[str, str, Optional[int], str]] = [
    ("boost_ccm", "Boost CCM Active", None,
     "PFC ativo. Indutor + chave + diodo + capacitor barramento. "
     "fsw típica 50–200 kHz."),
    ("passive_choke", "Passive PFC Choke", None,
     "Choke passivo na saída do retificador. Filtragem suave, "
     "menor custo, sem chaveamento."),
    ("line_reactor_1ph", "Line Reactor (1ph)", 1,
     "Reator de linha 1φ na entrada do retificador a diodo. "
     "Para conformidade IEC 61000-3-2."),
    ("line_reactor_3ph", "Line Reactor (3ph)", 3,
     "Reator de linha 3φ na entrada de retificador 6-pulsos. "
     "Reduz THD harmônica para drive industrial."),
]


class _TopologyOption(QFrame):
    """Single selectable topology card."""

    def __init__(self, key: str, label: str, description: str,
                 schematic_kind: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._key = key
        self._selected = False
        self._click_cb = None
        self.setObjectName("TopologyOption")
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._self_qss(False))

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        self._schematic = TopologySchematicWidget()
        self._schematic.set_topology(schematic_kind)
        self._schematic.setMinimumHeight(90)
        self._schematic.setMaximumHeight(120)
        v.addWidget(self._schematic)

        title = QLabel(label)
        title.setProperty("role", "title")
        v.addWidget(title)

        desc = QLabel(description)
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        v.addWidget(desc)

    @property
    def key(self) -> str:
        return self._key

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self.setStyleSheet(self._self_qss(on))

    def mousePressEvent(self, event):
        # Forward the click to a parent dialog (which connects via the
        # ``clicked`` callback set by the caller).
        if self._click_cb is not None:
            self._click_cb(self._key)
        super().mousePressEvent(event)

    def set_click_callback(self, cb) -> None:
        self._click_cb = cb

    @staticmethod
    def _self_qss(selected: bool) -> str:
        p = get_theme().palette
        border = p.accent if selected else p.border
        bg = p.accent_subtle_bg if selected else p.surface
        return (
            f"QFrame#TopologyOption {{"
            f"  background: {bg};"
            f"  border: 2px solid {border};"
            f"  border-radius: 12px;"
            f"}}"
            f"QFrame#TopologyOption:hover {{"
            f"  border-color: {p.accent};"
            f"}}"
        )


class TopologyPickerDialog(QDialog):
    """Modal picker. Result accessor: :meth:`selected_key` /
    :meth:`selected_n_phases`.

    Returns ``QDialog.Accepted`` when the user double-clicks a card or
    clicks OK; ``Rejected`` otherwise.
    """

    def __init__(
        self,
        current: str = "boost_ccm",
        n_phases: int = 1,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Escolher Topologia")
        self.setMinimumSize(720, 480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(16)

        title = QLabel("Selecione uma topologia")
        title.setProperty("role", "title")
        outer.addWidget(title)

        subtitle = QLabel(
            "A escolha define a matemática do indutor "
            "(forma de onda, perdas, dimensionamento)."
        )
        subtitle.setProperty("role", "muted")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        # Resolve which option matches the current selection.
        if current == "line_reactor":
            current_key = ("line_reactor_3ph"
                           if n_phases == 3 else "line_reactor_1ph")
        else:
            current_key = current

        # ---- 2×2 grid of options --------------------------------------
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        outer.addLayout(grid, 1)

        self._options: dict[str, _TopologyOption] = {}
        for i, (key, label, _phases, desc) in enumerate(_OPTIONS):
            opt = _TopologyOption(key=key, label=label, description=desc,
                                   schematic_kind=key, parent=self)
            opt.set_click_callback(self._on_option_clicked)
            r, c = divmod(i, 2)
            grid.addWidget(opt, r, c)
            self._options[key] = opt

        # ---- buttons --------------------------------------------------
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        # Style the OK button as primary.
        ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setProperty("class", "Primary")
            ok_btn.setText("Aplicar")
        cancel_btn = btns.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setProperty("class", "Secondary")
            cancel_btn.setText("Cancelar")
        outer.addWidget(btns)

        self._selected_key: str = current_key if current_key in self._options \
            else "boost_ccm"
        self._refresh_selection()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def selected_key(self) -> str:
        """Canonical Spec.topology value: ``boost_ccm`` |
        ``passive_choke`` | ``line_reactor``."""
        if self._selected_key.startswith("line_reactor"):
            return "line_reactor"
        return self._selected_key

    def selected_n_phases(self) -> int:
        """1 or 3 — meaningful only when ``selected_key() ==
        "line_reactor"``."""
        if self._selected_key == "line_reactor_3ph":
            return 3
        return 1

    def selected_schematic_key(self) -> str:
        """The internal key including the 1ph/3ph suffix — useful for
        the next dialog screen."""
        return self._selected_key

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _on_option_clicked(self, key: str) -> None:
        self._selected_key = key
        self._refresh_selection()

    def _refresh_selection(self) -> None:
        for k, opt in self._options.items():
            opt.set_selected(k == self._selected_key)
