"""Vertical right-edge icon toolbar for the 3D viewer."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QToolButton, QWidget, QMenu, QCheckBox,
    QWidgetAction,
)

from pfc_inductor.ui.icons import icon as ui_icon
from pfc_inductor.ui.theme import get_theme, on_theme_changed


# (icon-name, signal-attr, tooltip)
_BUTTONS = (
    ("maximize-2",   "fullscreen_requested",  "Tela cheia"),
    ("image",        "screenshot_requested",  "Screenshot (PNG)"),
    ("layers",       None,                     "Camadas"),
    ("crop",         "section_toggled",       "Corte"),
    ("ruler",        "measure_toggled",       "Medidas"),
    ("settings-2",   "settings_requested",    "Configurações"),
)


class SideToolbar(QFrame):
    """Vertical icon stack overlaid on the right edge of the 3D viewer."""

    fullscreen_requested = Signal()
    screenshot_requested = Signal()
    layers_requested = Signal(dict)        # {winding: bool, bobbin: bool, airgap: bool}
    section_toggled = Signal(bool)
    measure_toggled = Signal(bool)
    settings_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("SideToolbar")
        self.setStyleSheet(self._self_qss())
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)

        self._buttons: dict[str, QToolButton] = {}
        for icon_name, sig_name, tooltip in _BUTTONS:
            btn = QToolButton()
            btn.setIcon(
                ui_icon(icon_name,
                        color=get_theme().palette.text_secondary, size=18)
            )
            btn.setIconSize(QSize(18, 18))
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedSize(34, 34)
            btn.setStyleSheet(self._button_qss())
            v.addWidget(btn)
            self._buttons[icon_name] = btn
            if icon_name == "layers":
                self._wire_layers_button(btn)
            elif icon_name in ("crop", "ruler"):
                btn.setCheckable(True)
                if sig_name == "section_toggled":
                    btn.toggled.connect(self.section_toggled.emit)
                elif sig_name == "measure_toggled":
                    btn.toggled.connect(self.measure_toggled.emit)
            elif sig_name is not None:
                btn.clicked.connect(getattr(self, sig_name).emit)
        on_theme_changed(self._refresh_qss)

    def _refresh_qss(self) -> None:
        self.setStyleSheet(self._self_qss())
        for btn in self._buttons.values():
            btn.setStyleSheet(self._button_qss())
        # Re-tint icons.
        from pfc_inductor.ui.icons import icon as ui_icon
        for icon_name, btn in self._buttons.items():
            btn.setIcon(
                ui_icon(icon_name,
                        color=get_theme().palette.text_secondary, size=18)
            )

    # ------------------------------------------------------------------
    # Layer popup
    # ------------------------------------------------------------------
    def _wire_layers_button(self, btn: QToolButton) -> None:
        menu = QMenu(self)
        self._chk_winding = QCheckBox("Bobinagem", menu)
        self._chk_bobbin = QCheckBox("Bobina (plástico)", menu)
        self._chk_airgap = QCheckBox("Entreferro", menu)
        self._chk_winding.setChecked(True)
        self._chk_bobbin.setChecked(False)
        self._chk_airgap.setChecked(True)
        for chk in (self._chk_winding, self._chk_bobbin, self._chk_airgap):
            chk.setStyleSheet(
                "QCheckBox { padding: 6px 12px; min-width: 140px; }"
            )
            wact = QWidgetAction(menu)
            wact.setDefaultWidget(chk)
            menu.addAction(wact)
            chk.toggled.connect(self._emit_layers)
        btn.setMenu(menu)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        btn.setStyleSheet(
            self._button_qss()
            + "QToolButton::menu-indicator { image: none; width: 0; }"
        )

    def _emit_layers(self) -> None:
        self.layers_requested.emit({
            "winding": self._chk_winding.isChecked(),
            "bobbin":  self._chk_bobbin.isChecked(),
            "airgap":  self._chk_airgap.isChecked(),
        })

    # ------------------------------------------------------------------
    @staticmethod
    def _self_qss() -> str:
        p = get_theme().palette
        return (
            f"QFrame#SideToolbar {{"
            f"  background: rgba(255,255,255,200);"
            f"  border: 1px solid {p.border};"
            f"  border-radius: 12px;"
            f"}}"
        )

    @staticmethod
    def _button_qss() -> str:
        p = get_theme().palette
        return (
            f"QToolButton {{ background: transparent; border: 0;"
            f"  border-radius: 8px; }}"
            f"QToolButton:hover {{ background: {p.bg}; }}"
            f"QToolButton:checked {{ background: {p.accent_subtle_bg}; }}"
        )
