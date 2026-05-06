"""Persistent navy sidebar with brand block + nav items + footer.

The sidebar is the application's primary navigation surface. Its colours
(:data:`SIDEBAR <pfc_inductor.ui.theme.SIDEBAR>`) are theme-invariant —
toggling light/dark does not change them.

Public API
----------

- :data:`SIDEBAR_AREAS` — the canonical (id, label, icon-name) tuples.
- :class:`Sidebar` — the widget. Emits ``navigation_requested(area_id)``
  when the user clicks a nav item, ``theme_toggle_requested()`` when the
  footer's sun/moon icon is clicked, and ``overflow_action_requested(name)``
  when the footer's "…" menu fires.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QButtonGroup,
    QWidget, QToolButton, QMenu, QSizePolicy,
)

from pfc_inductor.ui.theme import SIDEBAR
from pfc_inductor.ui.icons import icon as ui_icon


# ---------------------------------------------------------------------------
# Canonical nav definition
# ---------------------------------------------------------------------------

# (area_id, label, lucide_icon_name)
SIDEBAR_AREAS: tuple[tuple[str, str, str], ...] = (
    ("dashboard",   "Dashboard",       "layout-dashboard"),
    ("topologia",   "Topologia",       "git-branch"),
    ("nucleos",     "Núcleos",         "cpu"),
    ("bobinamento", "Bobinamento",     "activity"),
    ("simulacao",   "Simulação",       "gauge"),
    ("mecanico",    "Mecânico",        "box"),
    ("relatorios",  "Relatórios",      "file-text"),
    ("configuracoes", "Configurações", "cog"),
)

# Overflow menu — legacy tools that don't get top-level real estate.
OVERFLOW_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("optimizer",  "Otimizador",        "sliders"),
    ("compare",    "Comparar designs",  "compare"),
    ("similar",    "Buscar similares",  "search"),
    ("litz",       "Otimizador Litz",   "braid"),
    ("fea",        "Validar (FEA)",     "cube"),
    ("db_editor",  "Base de dados",     "database"),
    ("catalog",    "Atualizar catálogo", "download-cloud"),
    ("setup_fea",  "Instalar FEA",      "cog"),
    ("about",      "Sobre",             "info"),
)


# ---------------------------------------------------------------------------
# Sidebar widget
# ---------------------------------------------------------------------------

class Sidebar(QFrame):
    """Left-edge navigation chrome. 250 px wide, navy, brand-invariant."""

    navigation_requested = Signal(str)        # area_id
    theme_toggle_requested = Signal()
    overflow_action_requested = Signal(str)   # action key

    WIDTH = 250

    def __init__(self, parent: Optional[QWidget] = None,
                 dark_theme: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(self.WIDTH)
        self.setFrameShape(QFrame.Shape.NoFrame)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_nav(), 1)
        outer.addWidget(self._build_footer())

        # Default selection: Dashboard.
        self._select_area("dashboard")
        self._dark_theme = dark_theme
        self._refresh_theme_icon()

    # ------------------------------------------------------------------
    # Sub-builders
    # ------------------------------------------------------------------
    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("SidebarHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(20, 18, 20, 14)
        h.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(
            ui_icon("cube", color=SIDEBAR.accent, size=22).pixmap(22, 22)
        )

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)
        title = QLabel("MagnaDesign")
        title.setObjectName("SidebarLogoText")
        caption = QLabel("Inductor Design Suite")
        caption.setObjectName("SidebarLogoCaption")
        text_col.addWidget(title)
        text_col.addWidget(caption)

        h.addWidget(logo)
        h.addLayout(text_col, 1)
        return header

    def _build_nav(self) -> QWidget:
        nav = QFrame()
        nav.setObjectName("SidebarNav")
        nav.setStyleSheet(
            "QFrame#SidebarNav { background: transparent; border: 0; }"
        )
        v = QVBoxLayout(nav)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(2)

        self._nav_buttons: dict[str, QPushButton] = {}
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        for area_id, label, icon_name in SIDEBAR_AREAS:
            btn = QPushButton(label)
            btn.setProperty("class", "SidebarItem")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setIcon(ui_icon(icon_name, color=SIDEBAR.text_muted, size=16))
            btn.setIconSize(QSize(16, 16))
            btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Fixed)
            btn.clicked.connect(
                lambda _checked=False, a=area_id: self._on_nav_clicked(a)
            )
            self._button_group.addButton(btn)
            self._nav_buttons[area_id] = btn
            v.addWidget(btn)

        v.addStretch(1)
        return nav

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("SidebarFooter")
        h = QHBoxLayout(footer)
        h.setContentsMargins(16, 10, 12, 10)
        h.setSpacing(6)

        # Theme toggle
        self._btn_theme = QToolButton()
        self._btn_theme.setProperty("class", "Chip")
        self._btn_theme.setIconSize(QSize(16, 16))
        self._btn_theme.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_theme.setStyleSheet(
            "QToolButton { background: transparent; border: 0; padding: 4px; }"
            "QToolButton:hover { background: " + SIDEBAR.bg_hover + "; "
            "border-radius: 8px; }"
        )
        self._btn_theme.clicked.connect(self.theme_toggle_requested.emit)

        # Version label
        version = QLabel("v0.2 Pro")
        version.setObjectName("SidebarVersion")

        # Overflow menu
        self._btn_overflow = QToolButton()
        self._btn_overflow.setIcon(
            ui_icon("more-horizontal", color=SIDEBAR.text_muted, size=18)
        )
        self._btn_overflow.setIconSize(QSize(18, 18))
        self._btn_overflow.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_overflow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._btn_overflow.setStyleSheet(
            "QToolButton { background: transparent; border: 0; padding: 4px; }"
            "QToolButton:hover { background: " + SIDEBAR.bg_hover + "; "
            "border-radius: 8px; }"
            "QToolButton::menu-indicator { image: none; width: 0; }"
        )
        self._build_overflow_menu()

        h.addWidget(self._btn_theme)
        h.addWidget(version, 1, alignment=Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self._btn_overflow)
        return footer

    def _build_overflow_menu(self) -> None:
        menu = QMenu(self)
        for key, label, icon_name in OVERFLOW_ACTIONS:
            act = QAction(
                ui_icon(icon_name, color=SIDEBAR.text, size=16),
                label,
                self,
            )
            act.triggered.connect(
                lambda _checked=False, k=key: self.overflow_action_requested.emit(k)
            )
            menu.addAction(act)
        self._btn_overflow.setMenu(menu)
        self._overflow_menu = menu

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_active_area(self, area_id: str) -> None:
        """Programmatically change the highlighted nav item without
        emitting ``navigation_requested`` (so external state changes
        don't loop)."""
        self._select_area(area_id)

    def set_dark_theme(self, dark: bool) -> None:
        """Tell the sidebar which theme is active so it can pick the
        right footer icon (sun ↔ moon)."""
        self._dark_theme = dark
        self._refresh_theme_icon()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _select_area(self, area_id: str) -> None:
        for aid, btn in self._nav_buttons.items():
            btn.setChecked(aid == area_id)

    def _on_nav_clicked(self, area_id: str) -> None:
        self._select_area(area_id)
        self.navigation_requested.emit(area_id)

    def _refresh_theme_icon(self) -> None:
        # If currently dark, show "sun" (click goes to light) and vice versa.
        name = "sun" if self._dark_theme else "moon"
        self._btn_theme.setIcon(
            ui_icon(name, color=SIDEBAR.text, size=16)
        )
        self._btn_theme.setToolTip(
            "Tema claro" if self._dark_theme else "Tema escuro"
        )
