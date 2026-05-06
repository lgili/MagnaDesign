"""Bottom action bar: Explodir / Corte / Medidas / Exportar."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QPushButton, QWidget, QMenu,
)

from pfc_inductor.ui.icons import icon as ui_icon
from pfc_inductor.ui.theme import get_theme, on_theme_changed


class BottomActions(QFrame):
    """Four labelled tertiary buttons overlaid at the bottom of the viewer."""

    explode_toggled = Signal(bool)
    section_toggled = Signal(bool)
    measure_toggled = Signal(bool)
    export_requested = Signal(str)  # "png" | "stl" | "vrml"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("BottomActions")
        self.setStyleSheet(self._self_qss())
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 6, 6, 6)
        h.setSpacing(4)

        p = get_theme().palette

        self.btn_explode = self._make_button("Explodir", "share")
        self.btn_explode.setCheckable(True)
        self.btn_explode.toggled.connect(self.explode_toggled.emit)

        self.btn_section = self._make_button("Corte", "crop")
        self.btn_section.setCheckable(True)
        self.btn_section.toggled.connect(self.section_toggled.emit)

        self.btn_measure = self._make_button("Medidas", "ruler")
        self.btn_measure.setCheckable(True)
        self.btn_measure.toggled.connect(self.measure_toggled.emit)

        self.btn_export = self._make_button("Exportar", "download")
        export_menu = QMenu(self)
        for label, key in (("PNG (imagem)", "png"),
                            ("STL (mesh)", "stl"),
                            ("VRML (cena)", "vrml")):
            act = export_menu.addAction(label)
            act.triggered.connect(
                lambda _checked=False, k=key: self.export_requested.emit(k)
            )
        self.btn_export.setMenu(export_menu)

        for btn in (self.btn_explode, self.btn_section,
                    self.btn_measure, self.btn_export):
            h.addWidget(btn)
        on_theme_changed(self._refresh_qss)

    def _refresh_qss(self) -> None:
        self.setStyleSheet(self._self_qss())
        for btn in (self.btn_explode, self.btn_section,
                    self.btn_measure, self.btn_export):
            btn.setStyleSheet(self._button_qss())

    # ------------------------------------------------------------------
    def _make_button(self, label: str, icon_name: str) -> QPushButton:
        p = get_theme().palette
        btn = QPushButton(label)
        btn.setProperty("class", "Tertiary")
        btn.setIcon(ui_icon(icon_name, color=p.text_secondary, size=14))
        btn.setIconSize(QSize(14, 14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(self._button_qss())
        return btn

    @staticmethod
    def _self_qss() -> str:
        p = get_theme().palette
        return (
            f"QFrame#BottomActions {{"
            f"  background: rgba(255,255,255,200);"
            f"  border: 1px solid {p.border};"
            f"  border-radius: 12px;"
            f"}}"
        )

    @staticmethod
    def _button_qss() -> str:
        p = get_theme().palette
        return (
            f"QPushButton {{ background: transparent; border: 0;"
            f"  border-radius: 8px; padding: 6px 12px;"
            f"  color: {p.text_secondary}; }}"
            f"QPushButton:hover {{ background: {p.bg}; color: {p.text}; }}"
            f"QPushButton:checked {{ background: {p.accent_subtle_bg};"
            f"  color: {p.accent_subtle_text}; }}"
            f"QPushButton::menu-indicator {{ image: none; width: 0; }}"
        )
