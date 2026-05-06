"""``NextStepsCard`` — actionable next-step list with status icons.

Each item: status icon (left) + title + (optional) "→" CTA on the right.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Optional, Sequence

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QSizePolicy,
)

from pfc_inductor.ui.icons import icon as ui_icon
from pfc_inductor.ui.theme import get_theme


ActionStatus = Literal["done", "pending", "todo"]


@dataclass
class ActionItem:
    title: str
    status: ActionStatus
    callback: Optional[Callable[[], None]] = None


_STATUS_ICON: dict[ActionStatus, str] = {
    "done":    "check-circle",
    "pending": "clock",
    "todo":    "arrow-up-right",
}


class _ActionRow(QFrame):
    def __init__(self, item: ActionItem, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._item = item
        p = get_theme().palette
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 6, 0, 6)
        h.setSpacing(10)

        # Status icon
        icon_color = {
            "done":    p.success,
            "pending": p.warning,
            "todo":    p.accent,
        }[item.status]
        icon_lbl = QLabel()
        icon_lbl.setPixmap(
            ui_icon(_STATUS_ICON[item.status], color=icon_color, size=18)
            .pixmap(18, 18)
        )
        icon_lbl.setFixedWidth(20)

        # Title
        title = QLabel(item.title)
        title.setStyleSheet(
            f"color: {p.text}; font-size: {get_theme().type.body_md}px;"
        )
        if item.status == "done":
            title.setStyleSheet(
                f"color: {p.text_muted}; font-size: "
                f"{get_theme().type.body_md}px; text-decoration: line-through;"
            )

        # CTA arrow (todo only)
        if item.status == "todo" and item.callback is not None:
            cta = QPushButton()
            cta.setProperty("class", "Tertiary")
            cta.setIcon(ui_icon("arrow-up-right", color=p.accent, size=16))
            cta.setIconSize(QSize(16, 16))
            cta.setCursor(Qt.CursorShape.PointingHandCursor)
            cta.setFixedWidth(32)
            cta.clicked.connect(item.callback)
        else:
            cta = None

        h.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(title, 1, Qt.AlignmentFlag.AlignVCenter)
        if cta is not None:
            h.addWidget(cta, 0, Qt.AlignmentFlag.AlignVCenter)


class NextStepsCard(QWidget):
    """Vertical list of action items."""

    def __init__(
        self,
        items: Optional[Sequence[ActionItem]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)
        self._items: list[ActionItem] = []
        self.set_items(items or [])

    def set_items(self, items: Sequence[ActionItem]) -> None:
        # Clear existing
        while self._layout.count():
            it = self._layout.takeAt(0)
            w = it.widget() if it else None
            if w is not None:
                w.setParent(None)
        self._items = list(items)
        for item in self._items:
            self._layout.addWidget(_ActionRow(item))

    def count(self) -> int:
        return len(self._items)
