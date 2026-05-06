"""Top-left view chips: Frente / Cima / Lateral / Iso."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QToolButton, QButtonGroup, QWidget,
)

from pfc_inductor.ui.theme import get_theme


_VIEWS = (
    ("front", "Frente"),
    ("top",   "Cima"),
    ("side",  "Lateral"),
    ("iso",   "Iso"),
)


class ViewChips(QFrame):
    """Mutually-exclusive chip group for canonical camera presets."""

    view_changed = Signal(str)  # one of "front", "top", "side", "iso"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ViewChips")
        self.setStyleSheet(self._self_qss())
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 6, 6, 6)
        h.setSpacing(4)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QToolButton] = {}
        for key, label in _VIEWS:
            btn = QToolButton()
            btn.setProperty("class", "Chip")
            btn.setText(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, k=key: self._on_clicked(k))
            self._group.addButton(btn)
            self._buttons[key] = btn
            h.addWidget(btn)
        # Default: Iso
        self._buttons["iso"].setChecked(True)

    # ------------------------------------------------------------------
    def set_active(self, view: str) -> None:
        """Update the active chip without emitting the signal."""
        for k, btn in self._buttons.items():
            btn.setChecked(k == view)

    def active(self) -> str:
        for k, btn in self._buttons.items():
            if btn.isChecked():
                return k
        return "iso"

    # ------------------------------------------------------------------
    def _on_clicked(self, key: str) -> None:
        self.set_active(key)
        self.view_changed.emit(key)

    @staticmethod
    def _self_qss() -> str:
        p = get_theme().palette
        return (
            f"QFrame#ViewChips {{"
            f"  background: rgba(255,255,255,200);"
            f"  border: 1px solid {p.border};"
            f"  border-radius: 12px;"
            f"}}"
        )
