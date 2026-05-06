"""Bottom application status bar.

Layout (left → right):
- Save-status indicator: green dot + "Projeto salvo há N min"
  (or amber + "Alterações não salvas").
- Spacer.
- Three pill counters: ``N Avisos`` (warning), ``N Erros`` (danger),
  ``N Validações`` (success). Zero counts switch to the neutral pill so
  a fresh design does not scream colour.

The widget is a ``QFrame`` (not a ``QStatusBar``) so it can host pill
labels with full QSS control. Replaces ``QMainWindow.statusBar()``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QWidget,
)

from pfc_inductor.ui.theme import get_theme


# Threshold above which the counter actually colours itself with the
# semantic variant. Below threshold (i.e. zero) we use the neutral pill.
_COLOUR_THRESHOLD = 1


class _PillCounter(QLabel):
    """Pill label whose variant flips between ``neutral`` and a semantic
    colour based on whether the counter is above zero."""

    def __init__(self, label_template: str, semantic: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("class", "Pill")
        self._template = label_template
        self._semantic = semantic
        self._count = 0
        self.set_count(0)

    def set_count(self, n: int) -> None:
        self._count = max(0, int(n))
        self.setText(self._template.format(n=self._count))
        variant = "neutral" if self._count < _COLOUR_THRESHOLD else self._semantic
        self.setProperty("pill", variant)
        st = self.style()
        st.unpolish(self)
        st.polish(self)
        self.update()


class BottomStatusBar(QFrame):
    """Persistent bottom bar."""

    HEIGHT = 32

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("BottomStatusBar")
        self.setFixedHeight(self.HEIGHT)
        self.setStyleSheet(self._self_qss())

        h = QHBoxLayout(self)
        h.setContentsMargins(24, 0, 24, 0)
        h.setSpacing(12)

        # ---- left: save status -----------------------------------------
        self._save_label = QLabel("● Pronto")
        self._save_label.setStyleSheet(self._save_label_qss(saved=True))
        h.addWidget(self._save_label, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addStretch(1)

        # ---- right: 3 pills --------------------------------------------
        self._pill_warnings = _PillCounter("{n} Avisos", "warning")
        self._pill_errors = _PillCounter("{n} Erros", "danger")
        self._pill_validations = _PillCounter("{n} Validações", "success")
        for p in (self._pill_warnings, self._pill_errors, self._pill_validations):
            h.addWidget(p, 0, Qt.AlignmentFlag.AlignVCenter)

        # ---- relative-time refresh timer -------------------------------
        self._last_saved_at: Optional[datetime] = None
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)  # 1 min
        self._timer.timeout.connect(self._refresh_save_text)
        self._timer.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_warnings(self, n: int) -> None:
        self._pill_warnings.set_count(n)

    def set_errors(self, n: int) -> None:
        self._pill_errors.set_count(n)

    def set_validations(self, n: int) -> None:
        self._pill_validations.set_count(n)

    def set_save_status(self, *, unsaved: bool,
                        last_saved_at: Optional[datetime] = None) -> None:
        self._last_saved_at = last_saved_at
        if unsaved:
            self._save_label.setText("● Alterações não salvas")
            self._save_label.setStyleSheet(self._save_label_qss(saved=False))
        else:
            self._save_label.setStyleSheet(self._save_label_qss(saved=True))
            self._refresh_save_text()

    # Test-friendly read accessors --------------------------------------
    def warnings_text(self) -> str:
        return self._pill_warnings.text()

    def errors_text(self) -> str:
        return self._pill_errors.text()

    def validations_text(self) -> str:
        return self._pill_validations.text()

    def warnings_variant(self) -> str:
        return str(self._pill_warnings.property("pill"))

    def errors_variant(self) -> str:
        return str(self._pill_errors.property("pill"))

    def validations_variant(self) -> str:
        return str(self._pill_validations.property("pill"))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _refresh_save_text(self) -> None:
        if self._last_saved_at is None:
            self._save_label.setText("● Pronto")
            return
        delta = datetime.now() - self._last_saved_at
        seconds = int(delta.total_seconds())
        if seconds < 60:
            txt = "● Projeto salvo agora"
        elif seconds < 3600:
            mins = seconds // 60
            txt = f"● Projeto salvo há {mins} min"
        elif seconds < 86_400:
            hours = seconds // 3600
            txt = f"● Projeto salvo há {hours} h"
        else:
            txt = f"● Salvo em {self._last_saved_at:%d/%m %H:%M}"
        self._save_label.setText(txt)

    @staticmethod
    def _self_qss() -> str:
        p = get_theme().palette
        return (
            f"QFrame#BottomStatusBar {{"
            f"  background: {p.surface};"
            f"  border: 0;"
            f"  border-top: 1px solid {p.border};"
            f"}}"
        )

    @staticmethod
    def _save_label_qss(*, saved: bool) -> str:
        p = get_theme().palette
        t = get_theme().type
        color = p.success if saved else p.warning
        return (
            f"QLabel {{"
            f"  color: {color};"
            f"  font-family: {t.ui_family_brand};"
            f"  font-size: {t.caption}px;"
            f"  font-weight: {t.medium};"
            f"}}"
        )
