"""``DataTable`` — labelled key/value/unit table.

Used in Bobinamento and Entreferro cards. Two visual columns: label on
the left (regular weight, secondary text), value on the right (mono,
tabular-nums, semibold) with the unit immediately after in muted weight.
Optional zebra striping.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QWidget, QSizePolicy,
)

from pfc_inductor.ui.theme import get_theme, on_theme_changed


Row = tuple[str, str, Optional[str]]


class DataTable(QFrame):
    """Static, theme-aware key/value/unit table."""

    def __init__(
        self,
        rows: Optional[Sequence[Row]] = None,
        *,
        striped: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("DataTable")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)
        self._striped = striped

        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(0)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 0)
        self._grid.setColumnStretch(2, 0)

        self._row_widgets: list[tuple[QFrame, QLabel, QLabel, QLabel]] = []
        self._rows_cache: list[Row] = list(rows or [])
        self.set_rows(self._rows_cache)
        on_theme_changed(self._refresh_qss)

    def _refresh_qss(self) -> None:
        # Easiest: redraw rows so palette-driven inline colours pick up
        # the new theme.
        self.set_rows(self._rows_cache)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_rows(self, rows: Iterable[Row]) -> None:
        # Snapshot so the theme refresh has something to redraw.
        self._rows_cache = list(rows)
        rows = self._rows_cache
        # Clear previous
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.setParent(None)
        self._row_widgets.clear()

        p = get_theme().palette
        t = get_theme().type
        for i, (label, value, unit) in enumerate(rows):
            bg_frame = QFrame()
            bg_frame.setStyleSheet(
                self._row_qss(p.bg if (self._striped and i % 2 == 1) else "transparent")
            )
            # Bg frame is purely visual — content is added via the grid.
            self._grid.addWidget(bg_frame, i, 0, 1, 3)

            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"color: {p.text_secondary}; "
                f"font-size: {t.body}px; padding: 6px 10px;"
            )

            val = QLabel(value)
            val_font = val.font()
            val_font.setStyleHint(QFont.StyleHint.Monospace)
            val_font.setFamilies([
                "JetBrains Mono", "SF Mono", "Menlo",
                "Cascadia Code", "Consolas", "monospace",
            ])
            val_font.setPixelSize(t.body_md)
            val_font.setWeight(QFont.Weight.DemiBold)
            val.setFont(val_font)
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            val.setStyleSheet(f"color: {p.text}; padding: 6px 4px;")

            unit_lbl = QLabel(unit or "")
            unit_lbl.setStyleSheet(
                f"color: {p.text_muted}; font-size: {t.caption}px;"
                "padding: 6px 10px 6px 0;"
            )

            self._grid.addWidget(lbl, i, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
            self._grid.addWidget(val, i, 1, alignment=Qt.AlignmentFlag.AlignVCenter)
            self._grid.addWidget(unit_lbl, i, 2,
                                 alignment=Qt.AlignmentFlag.AlignVCenter)
            self._row_widgets.append((bg_frame, lbl, val, unit_lbl))

    def row_count(self) -> int:
        return len(self._row_widgets)

    def value_text(self, row_index: int) -> str:
        return self._row_widgets[row_index][2].text()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _row_qss(bg: str) -> str:
        return f"background: {bg}; border-radius: 4px;"
