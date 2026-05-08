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

# All user-visible labels and tooltips are English. Internal IDs
# (``area_id`` keys, ``QSettings`` slots, signal payloads) keep their
# legacy names so saved geometry and routing logic survive the rewrite.
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.ui.icons import icon as ui_icon
from pfc_inductor.ui.theme import SIDEBAR, get_theme

# ---------------------------------------------------------------------------
# Canonical nav definition
# ---------------------------------------------------------------------------

# (area_id, label, lucide_icon_name, tooltip)
#
# v3: 4 real destinations. The legacy 8-area split was just navigating
# back to subsets of the dashboard — extra clicks for less information.
# The Project area now hosts the entire design workspace (SpecDrawer +
# Design/Validate/Export tabs); the other three areas are first-class
# tools that used to be hidden in the overflow menu.
#
# ``area_id`` keys are kept stable for ``QSettings`` compatibility:
# - ``dashboard`` → display label "Project" (ID preserved so saved
#   geometry / state survives the rename)
# 4-tuple: (area_id, label, icon, tooltip). Tooltips disambiguate the
# two optimizer entries — without them, "Full optimizer" is internal
# jargon that pushes a casual user toward the wrong choice.
SIDEBAR_AREAS: tuple[tuple[str, str, str, str], ...] = (
    (
        "dashboard",
        "Project",
        "layout-dashboard",
        "Main workspace — spec, selection, analysis, validation and export.",
    ),
    ("otimizador", "Optimizer", "sliders", "Fast Pareto sweep (≈ 30 s) — losses × volume × cost."),
    (
        "cascade",
        "Full optimizer",
        "layers",
        "Multi-tier optimization with RK4 transient and FEM validation "
        "(≈ 5–15 min). Use when you need the defensible final design.",
    ),
    (
        "catalogo",
        "Catalog",
        "database",
        "Edit materials, cores and wires. Imports from OpenMagnetics MAS.",
    ),
    ("configuracoes", "Settings", "cog", "Theme, FEA, Litz and project information."),
)

# Overflow menu — kept lean for the few tools that don't deserve a
# sidebar slot but need a discoverable home anyway.
OVERFLOW_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("compare", "Compare designs", "compare"),
    ("about", "About", "info"),
)


# ---------------------------------------------------------------------------
# Sidebar widget
# ---------------------------------------------------------------------------


class Sidebar(QFrame):
    """Left-edge navigation chrome. 220 px wide, navy, brand-invariant.

    Width was 250 px; trimmed to 220 to give the workspace ~30 px of
    extra horizontal real estate on laptop viewports without the nav
    labels truncating (longest is "Full optimizer" at ~110 px @ 13 px).
    """

    navigation_requested = Signal(str)  # area_id
    theme_toggle_requested = Signal()
    overflow_action_requested = Signal(str)  # action key

    WIDTH = 220

    def __init__(self, parent: Optional[QWidget] = None, dark_theme: bool = False) -> None:
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
        header.setStyleSheet(
            "QFrame#SidebarHeader { background: transparent; border: 0; padding: 0; }"
        )
        h = QHBoxLayout(header)
        # Slimmed top/bottom 18/14 → 12/10 (-10 px) and dropped the
        # "Inductor Design Suite" caption below the wordmark — the
        # wordmark itself already says what the app is, the tagline
        # was eating ~12 px without informing anyone past the first
        # session. Net: brand mark went from ~80 px → ~52 px tall,
        # giving the nav items more room above the fold on smaller
        # laptop screens. Tooltip on the wordmark preserves the
        # tagline for anyone who hovers.
        h.setContentsMargins(20, 12, 20, 10)
        h.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(ui_icon("cube", color=SIDEBAR.accent, size=20).pixmap(20, 20))
        logo.setStyleSheet("background: transparent; border: 0;")

        t = get_theme().type
        title = QLabel("MagnaDesign")
        title.setObjectName("SidebarLogoText")
        title.setToolTip("MagnaDesign — Inductor Design Suite")
        title.setStyleSheet(
            f"color: {SIDEBAR.text_active}; "
            f"font-family: {t.ui_family_brand}; "
            f"font-size: {t.title_md}px; "
            f"font-weight: {t.semibold}; "
            f"background: transparent; border: 0;"
            f"letter-spacing: -0.01em;"
        )

        h.addWidget(logo)
        h.addWidget(title, 1)
        return header

    def _build_nav(self) -> QWidget:
        nav = QFrame()
        nav.setObjectName("SidebarNav")
        nav.setStyleSheet("QFrame#SidebarNav { background: transparent; border: 0; }")
        v = QVBoxLayout(nav)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(2)

        self._nav_buttons: dict[str, QPushButton] = {}
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        t = get_theme().type
        nav_item_qss = (
            f"QPushButton {{"
            f"  background: transparent; color: {SIDEBAR.text_muted};"
            f"  border: 0; border-radius: 10px; padding: 8px 12px;"
            f"  text-align: left;"
            f"  font-family: {t.ui_family_brand};"
            f"  font-size: {t.body_md}px;"
            f"  font-weight: {t.medium};"
            f"  min-height: 22px;"
            f"}}"
            f"QPushButton:hover {{ background: {SIDEBAR.bg_hover};"
            f"  color: {SIDEBAR.text}; }}"
            f"QPushButton:checked {{ background: {SIDEBAR.bg_active};"
            f"  color: {SIDEBAR.text_active};"
            f"  font-weight: {t.semibold}; }}"
        )
        for area_id, label, icon_name, tooltip in SIDEBAR_AREAS:
            btn = QPushButton(label)
            btn.setProperty("class", "SidebarItem")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setIcon(ui_icon(icon_name, color=SIDEBAR.text_muted, size=16))
            btn.setIconSize(QSize(16, 16))
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setStyleSheet(nav_item_qss)
            # Tooltip disambiguates the two optimizer entries; also
            # surfaces what each area does for first-time users.
            btn.setToolTip(tooltip)
            btn.setAccessibleName(label)
            btn.setAccessibleDescription(tooltip)
            btn.clicked.connect(lambda _checked=False, a=area_id: self._on_nav_clicked(a))
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
        t = get_theme().type
        version.setStyleSheet(
            f"color: {SIDEBAR.text_muted}; "
            f"font-family: {t.ui_family_brand}; "
            f"font-size: {t.caption}px; "
            f"background: transparent; border: 0;"
        )

        # Overflow menu
        self._btn_overflow = QToolButton()
        self._btn_overflow.setIcon(ui_icon("more-horizontal", color=SIDEBAR.text_muted, size=18))
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
        self._btn_theme.setIcon(ui_icon(name, color=SIDEBAR.text, size=16))
        self._btn_theme.setToolTip("Light theme" if self._dark_theme else "Dark theme")
