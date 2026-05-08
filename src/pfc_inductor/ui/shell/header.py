"""Workspace header bar.

Contents (left → right):
- Editable project-name field with a pencil edit affordance.
- "Saved" / "Unsaved" pill that reflects ``WorkflowState.unsaved``.
- Spacer.
- Secondary CTA: "Compare solutions".
- Secondary CTA: "Generate report".
- Primary CTA: "Recalculate" — main loop action; users hit it after
  any spec change because auto-recalc is intentionally off (see
  ``MainWindow._auto_calc``). One primary per surface, by design.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QWidget,
)

from pfc_inductor.ui.icons import icon as ui_icon
from pfc_inductor.ui.theme import get_theme, on_theme_changed


class WorkspaceHeader(QFrame):
    """Top bar above the page area."""

    name_changed = Signal(str)
    compare_requested = Signal()
    report_requested = Signal()
    recalculate_requested = Signal()

    # Lowered from 64 to 56 px to recover vertical room for the bento
    # below — the project name + 3 CTAs comfortably fit at this height
    # and it matches the Linear/Stripe shell density target.
    HEIGHT = 56

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("WorkspaceHeader")
        self.setFixedHeight(self.HEIGHT)
        self.setStyleSheet(self._self_qss())

        h = QHBoxLayout(self)
        # Vertical margin trimmed 12 → 8 px to match the new 56 px height.
        h.setContentsMargins(24, 8, 24, 8)
        h.setSpacing(12)

        # ---- left: project-name editor + pencil ------------------------
        self._name_edit = QLineEdit("Untitled Project")
        self._name_edit.setObjectName("ProjectNameEdit")
        self._name_edit.setStyleSheet(self._name_edit_qss())
        self._name_edit.setFrame(False)
        self._name_edit.setMinimumWidth(220)
        self._name_edit.editingFinished.connect(self._on_name_edited)

        # Pencil icon was 14 px with no tooltip — invisible at first
        # glance. Bumped to 16 px and added a tooltip + accessible
        # name so screen readers + hover users discover the
        # "rename project" action.
        self._btn_pencil = QToolButton()
        self._btn_pencil.setObjectName("ProjectNamePencil")
        self._btn_pencil.setIcon(
            ui_icon("pencil", color=get_theme().palette.text_secondary, size=16)
        )
        self._btn_pencil.setIconSize(QSize(16, 16))
        self._btn_pencil.setFixedSize(28, 28)
        self._btn_pencil.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_pencil.setToolTip("Rename project")
        self._btn_pencil.setAccessibleName("Rename project")
        self._btn_pencil.setStyleSheet(
            "QToolButton { background: transparent; border: 0;"
            " border-radius: 6px; padding: 4px; }"
            f"QToolButton:hover {{ background: {get_theme().palette.bg}; }}"
            f"QToolButton:focus {{ outline: 2px solid {get_theme().palette.focus_ring};"
            "  outline-offset: 1px; }"
        )
        self._btn_pencil.clicked.connect(self._name_edit.setFocus)
        # Double-click on the project-name field also opens edit mode —
        # makes the affordance discoverable without finding the pencil.
        self._name_edit.mouseDoubleClickEvent = self._on_name_double_click

        # ---- save-status pill ------------------------------------------
        self._status_pill = QLabel("● Saved")
        self._status_pill.setProperty("class", "Pill")
        self._status_pill.setProperty("pill", "success")
        self._apply_dynamic_property_refresh(self._status_pill)

        # ---- right: CTA buttons ----------------------------------------
        # Shorter labels — "Compare solutions" / "Generate report" each
        # cost ~150 px in the header and were pushing the workspace
        # minimum width past 800 px. Tooltips preserve the long form
        # for first-time users.
        self._btn_compare = QPushButton("Compare")
        self._btn_compare.setProperty("class", "Secondary")
        self._btn_compare.setIcon(
            ui_icon("compare", color=get_theme().palette.text, size=16)
        )
        self._btn_compare.setIconSize(QSize(16, 16))
        self._btn_compare.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_compare.setToolTip("Compare solutions side-by-side")
        self._btn_compare.clicked.connect(self.compare_requested.emit)
        self._apply_dynamic_property_refresh(self._btn_compare)

        self._btn_report = QPushButton("Report")
        # Demoted from Primary → Secondary so "Recalculate" can hold the
        # single Primary slot. Report is a one-shot end-of-flow action;
        # Recalculate is the inner-loop action the engineer hits dozens
        # of times per session.
        self._btn_report.setProperty("class", "Secondary")
        self._btn_report.setIcon(
            ui_icon("file-text", color=get_theme().palette.text, size=16)
        )
        self._btn_report.setIconSize(QSize(16, 16))
        self._btn_report.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_report.setToolTip("Generate datasheet report (HTML)")
        self._btn_report.clicked.connect(self.report_requested.emit)
        self._apply_dynamic_property_refresh(self._btn_report)

        self._btn_recalc = QPushButton("Recalculate")
        self._btn_recalc.setProperty("class", "Primary")
        self._btn_recalc.setIcon(
            ui_icon("refresh", color=get_theme().palette.text_inverse, size=16)
        )
        self._btn_recalc.setIconSize(QSize(16, 16))
        self._btn_recalc.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_recalc.setShortcut("Ctrl+R")
        self._btn_recalc.setToolTip("Recalculate the design (Ctrl+R)")
        self._btn_recalc.clicked.connect(self.recalculate_requested.emit)
        self._apply_dynamic_property_refresh(self._btn_recalc)

        # ---- compose ---------------------------------------------------
        h.addWidget(self._name_edit, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self._btn_pencil, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addSpacing(12)
        h.addWidget(self._status_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addStretch(1)
        h.addWidget(self._btn_compare, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self._btn_report, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self._btn_recalc, 0, Qt.AlignmentFlag.AlignVCenter)

        # Subscribe to theme changes so inline QSS refreshes.
        on_theme_changed(self._refresh_qss)
        self._unsaved_state: bool = False
        self._last_saved_at: Optional[datetime] = None

    def _refresh_qss(self) -> None:
        self.setStyleSheet(self._self_qss())
        self._name_edit.setStyleSheet(self._name_edit_qss())
        p = get_theme().palette
        # Re-apply pencil button + status pill colours.
        self._btn_pencil.setIcon(ui_icon("pencil", color=p.text_muted, size=14))
        # CTA button icons follow text/text_inverse depending on class.
        self._btn_compare.setIcon(ui_icon("compare", color=p.text, size=16))
        self._btn_report.setIcon(ui_icon("file-text", color=p.text, size=16))
        self._btn_recalc.setIcon(ui_icon("refresh", color=p.text_inverse, size=16))
        # Refresh the save-status pill (which uses palette via QSS).
        self.set_save_status(
            unsaved=self._unsaved_state, last_saved_at=self._last_saved_at,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_project_name(self, name: str) -> None:
        if self._name_edit.text() != name:
            self._name_edit.setText(name)

    def set_save_status(self, *, unsaved: bool,
                        last_saved_at: Optional[datetime] = None) -> None:
        self._unsaved_state = unsaved
        self._last_saved_at = last_saved_at
        if unsaved:
            self._status_pill.setText("● Unsaved")
            self._status_pill.setProperty("pill", "warning")
            self._status_pill.setToolTip("There are unsaved changes")
        else:
            self._status_pill.setText("● Saved")
            self._status_pill.setProperty("pill", "success")
            tip = "Project saved"
            if last_saved_at is not None:
                tip += f" at {last_saved_at:%H:%M}"
            self._status_pill.setToolTip(tip)
        self._apply_dynamic_property_refresh(self._status_pill)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _on_name_edited(self) -> None:
        self.name_changed.emit(self._name_edit.text())

    def _on_name_double_click(self, event) -> None:
        """Double-click on the project-name field selects all text +
        focuses it for quick rename — alt path to the pencil button.
        Forwards the event to the original handler so cursor placement
        still works for users who genuinely meant to position the
        caret rather than rename.
        """
        from PySide6.QtWidgets import QLineEdit
        QLineEdit.mouseDoubleClickEvent(self._name_edit, event)
        self._name_edit.selectAll()

    @staticmethod
    def _apply_dynamic_property_refresh(w: QWidget) -> None:
        # Qt re-evaluates the stylesheet for ``[property="x"]`` selectors
        # only when the style is unpolished and re-polished.
        st = w.style()
        st.unpolish(w)
        st.polish(w)
        w.update()

    @staticmethod
    def _self_qss() -> str:
        p = get_theme().palette
        return (
            f"QFrame#WorkspaceHeader {{"
            f"  background: {p.surface};"
            f"  border: 0;"
            f"  border-bottom: 1px solid {p.border};"
            f"}}"
        )

    @staticmethod
    def _name_edit_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"QLineEdit#ProjectNameEdit {{"
            f"  background: transparent;"
            f"  border: 0;"
            f"  color: {p.text};"
            f"  font-family: {t.ui_family_brand};"
            f"  font-size: {t.title_md}px;"
            f"  font-weight: {t.semibold};"
            f"  padding: 4px 0;"
            f"}}"
            f"QLineEdit#ProjectNameEdit:focus {{"
            f"  border-bottom: 2px solid {p.accent};"
            f"}}"
        )
