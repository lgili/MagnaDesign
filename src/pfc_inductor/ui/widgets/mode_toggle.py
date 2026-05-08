"""``ModeToggle`` — 2-state segmented chip selector.

Used by :class:`NucleoSelectionPage
<pfc_inductor.ui.workspace.nucleo_selection_page.NucleoSelectionPage>`
to flip between the manual table-driven selection and the inline
optimizer view. Same visual language as the chips already shipped in
``style.py`` (``QToolButton[class~="Chip"]``) but exposed as a
discrete two-state control with a single emit signal so callers don't
have to manage exclusive checked-state by hand.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from pfc_inductor.ui.theme import get_theme, on_theme_changed


class ModeToggle(QFrame):
    """Two-button segmented control with mutually-exclusive state.

    Construct with a list of ``(key, label)`` pairs. The active key is
    emitted via :attr:`mode_changed` whenever the user clicks. Use
    :meth:`set_mode` to drive it programmatically (e.g. when restoring
    from ``QSettings``).
    """

    mode_changed = Signal(str)

    def __init__(
        self,
        items: list[tuple[str, str]],
        *,
        default: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ModeToggle")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(self._self_qss())

        h = QHBoxLayout(self)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QToolButton] = {}

        first_key = default if default is not None else (items[0][0] if items else "")
        # Initialize ``_current`` BEFORE wiring the toggled signal so the
        # very first ``setChecked(True)`` (which fires the connected
        # lambda synchronously) finds the attribute already there.
        self._current = first_key

        for key, label in items:
            btn = QToolButton()
            btn.setText(label)
            btn.setProperty("class", "Chip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(28)
            btn.toggled.connect(lambda checked, k=key: checked and self._on_btn_toggled(k))
            if key == first_key:
                btn.setChecked(True)
            self._buttons[key] = btn
            self._group.addButton(btn)
            h.addWidget(btn)

        on_theme_changed(self._refresh_qss)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_mode(self, key: str) -> None:
        if key == self._current:
            return
        btn = self._buttons.get(key)
        if btn is None:
            return
        btn.setChecked(True)  # triggers _on_btn_toggled

    def current(self) -> str:
        return self._current

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _on_btn_toggled(self, key: str) -> None:
        if key == self._current:
            return
        self._current = key
        self.mode_changed.emit(key)

    def _refresh_qss(self) -> None:
        self.setStyleSheet(self._self_qss())
        # Re-polish each chip so the theme-driven [class~="Chip"]
        # selectors pick up the new palette.
        for btn in self._buttons.values():
            st = btn.style()
            st.unpolish(btn)
            st.polish(btn)
            btn.update()

    @staticmethod
    def _self_qss() -> str:
        p = get_theme().palette
        r = get_theme().radius
        # Tinted track that hosts the chips so the segmented control
        # reads as a single component, not two separate buttons.
        return (
            f"QFrame#ModeToggle {{"
            f"  background: {p.bg};"
            f"  border: 1px solid {p.border};"
            f"  border-radius: {r.button + 2}px;"
            f"}}"
        )
