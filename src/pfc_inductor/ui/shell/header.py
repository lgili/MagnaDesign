"""Workspace header bar.

Contents (left → right):
- Editable project-name field with a pencil edit affordance.
- "Salvo" / "Não salvo" pill that reflects ``WorkflowState.unsaved``.
- Spacer.
- Secondary CTA: "Comparar soluções".
- Secondary CTA: "Gerar Relatório".
- Primary CTA: "Recalcular" — main loop action; users hit it after
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

    HEIGHT = 64

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("WorkspaceHeader")
        self.setFixedHeight(self.HEIGHT)
        self.setStyleSheet(self._self_qss())

        h = QHBoxLayout(self)
        h.setContentsMargins(24, 12, 24, 12)
        h.setSpacing(12)

        # ---- left: project-name editor + pencil ------------------------
        self._name_edit = QLineEdit("Untitled Project")
        self._name_edit.setObjectName("ProjectNameEdit")
        self._name_edit.setStyleSheet(self._name_edit_qss())
        self._name_edit.setFrame(False)
        self._name_edit.setMinimumWidth(220)
        self._name_edit.editingFinished.connect(self._on_name_edited)

        self._btn_pencil = QToolButton()
        self._btn_pencil.setObjectName("ProjectNamePencil")
        self._btn_pencil.setIcon(
            ui_icon("pencil", color=get_theme().palette.text_muted, size=14)
        )
        self._btn_pencil.setIconSize(QSize(14, 14))
        self._btn_pencil.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_pencil.setStyleSheet(
            "QToolButton { background: transparent; border: 0; padding: 4px; }"
            "QToolButton:hover { background: "
            f"{get_theme().palette.bg}; border-radius: 6px; }}"
        )
        self._btn_pencil.clicked.connect(self._name_edit.setFocus)

        # ---- save-status pill ------------------------------------------
        self._status_pill = QLabel("● Salvo")
        self._status_pill.setProperty("class", "Pill")
        self._status_pill.setProperty("pill", "success")
        self._apply_dynamic_property_refresh(self._status_pill)

        # ---- right: CTA buttons ----------------------------------------
        self._btn_compare = QPushButton("Comparar soluções")
        self._btn_compare.setProperty("class", "Secondary")
        self._btn_compare.setIcon(
            ui_icon("compare", color=get_theme().palette.text, size=16)
        )
        self._btn_compare.setIconSize(QSize(16, 16))
        self._btn_compare.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_compare.clicked.connect(self.compare_requested.emit)
        self._apply_dynamic_property_refresh(self._btn_compare)

        self._btn_report = QPushButton("Gerar Relatório")
        # Demoted from Primary → Secondary so "Recalcular" can hold the
        # single Primary slot. Report is a one-shot end-of-flow action;
        # Recalcular is the inner-loop action the engineer hits dozens
        # of times per session.
        self._btn_report.setProperty("class", "Secondary")
        self._btn_report.setIcon(
            ui_icon("file-text", color=get_theme().palette.text, size=16)
        )
        self._btn_report.setIconSize(QSize(16, 16))
        self._btn_report.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_report.clicked.connect(self.report_requested.emit)
        self._apply_dynamic_property_refresh(self._btn_report)

        self._btn_recalc = QPushButton("Recalcular")
        self._btn_recalc.setProperty("class", "Primary")
        self._btn_recalc.setIcon(
            ui_icon("refresh", color=get_theme().palette.text_inverse, size=16)
        )
        self._btn_recalc.setIconSize(QSize(16, 16))
        self._btn_recalc.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_recalc.setShortcut("Ctrl+R")
        self._btn_recalc.setToolTip("Recalcular o design (Ctrl+R)")
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
            self._status_pill.setText("● Não salvo")
            self._status_pill.setProperty("pill", "warning")
            self._status_pill.setToolTip("Há alterações não salvas")
        else:
            self._status_pill.setText("● Salvo")
            self._status_pill.setProperty("pill", "success")
            tip = "Projeto salvo"
            if last_saved_at is not None:
                tip += f" em {last_saved_at:%H:%M}"
            self._status_pill.setToolTip(tip)
        self._apply_dynamic_property_refresh(self._status_pill)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _on_name_edited(self) -> None:
        self.name_changed.emit(self._name_edit.text())

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
