"""Multi-select chip with a searchable popup.

A compact button shows the current selection summary ("All 18", "5
selected", etc.); clicking it opens a popup with a search box, a
checkable list, and "Select all / Clear" footer actions. Designed
for filter rows where the catalogue is too long for an inline list
but a single-select dropdown is too restrictive.

Used by :class:`OptimizerFiltersBar
<pfc_inductor.ui.widgets.optimizer_filters_bar.OptimizerFiltersBar>`
to let the user pick which materials, cores and wires the optimizer
should consider. An empty selection means *all items*, which is the
"sweep everything topology-allows" default — pick a subset only when
you want to compare specific candidates head-to-head.

Public API
----------

- :meth:`set_items` — (id, label, tooltip) triples.
- :meth:`set_selected` — preselect ids on construction or restore.
- :meth:`selected` — list of ids currently checked (empty == all).
- :meth:`is_all` — convenience: ``True`` when nothing is checked
  (i.e. the chip should be read as "include everything").
- Signal :attr:`selection_changed(list[str])` — fires on every toggle.
"""

from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.ui.theme import get_theme


class _SearchPopup(QFrame):
    """Floating popup with search + checkable list + footer actions.

    Carries the ``Qt.Popup`` window flag so clicking outside closes
    it automatically — matches QMenu semantics without inheriting
    QMenu's keyboard-navigation quirks (which break checkable items).
    """

    selection_changed = Signal(list)  # list[str] of currently checked ids
    closed = Signal()

    POPUP_WIDTH = 320
    POPUP_MAX_HEIGHT = 380

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("MultiSelectPopup")
        # ``Qt.Popup`` makes Qt auto-close on outside-click and gives
        # us focus while open. ``Qt.FramelessWindowHint`` strips the
        # title-bar so it floats like a menu.
        self.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint,
        )
        self.setFixedWidth(self.POPUP_WIDTH)
        self.setMaximumHeight(self.POPUP_MAX_HEIGHT)
        self.setStyleSheet(self._qss())

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        # ---- Search ---------------------------------------------------
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        v.addWidget(self._search)

        # ---- List -----------------------------------------------------
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        # ``itemChanged`` fires when checkstate flips, ``itemClicked``
        # fires on row click. We toggle on click so users can hit any
        # part of the row, not just the checkbox itself.
        self._list.itemClicked.connect(self._toggle_clicked)
        self._list.itemChanged.connect(self._on_item_changed)
        v.addWidget(self._list, 1)

        # ---- Footer ---------------------------------------------------
        footer = QHBoxLayout()
        footer.setSpacing(6)
        self._btn_all = QPushButton("Select all")
        self._btn_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_all.clicked.connect(self._select_all)
        self._btn_clear = QPushButton("Clear")
        self._btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_clear.clicked.connect(self._clear)
        footer.addWidget(self._btn_all)
        footer.addWidget(self._btn_clear)
        footer.addStretch(1)
        # Count chip — live readout of "K selected of N".
        self._count = QLabel("")
        self._count.setObjectName("MultiSelectCount")
        footer.addWidget(self._count)
        v.addLayout(footer)

        # Block signals while populating to avoid a flurry of changes.
        self._suspend = False

    # ------------------------------------------------------------------
    def populate(self, items: list[tuple[str, str, str]], selected: set[str]) -> None:
        """Rebuild the list. ``items`` are ``(id, label, tooltip)`` rows."""
        self._suspend = True
        self._list.clear()
        for item_id, label, tooltip in items:
            li = QListWidgetItem(label)
            li.setData(Qt.ItemDataRole.UserRole, item_id)
            li.setFlags(li.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            li.setCheckState(
                Qt.CheckState.Checked if item_id in selected else Qt.CheckState.Unchecked,
            )
            if tooltip:
                li.setToolTip(tooltip)
            self._list.addItem(li)
        self._suspend = False
        self._refresh_count()
        # Reset filter so the user starts seeing every row again.
        self._search.clear()

    # ------------------------------------------------------------------
    def _toggle_clicked(self, item: QListWidgetItem) -> None:
        # Allow clicking anywhere on the row, not just the checkbox.
        new = (
            Qt.CheckState.Unchecked
            if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
        item.setCheckState(new)

    def _on_item_changed(self, _item: QListWidgetItem) -> None:
        if self._suspend:
            return
        ids = self._collect_checked()
        self._refresh_count()
        self.selection_changed.emit(ids)

    def _collect_checked(self) -> list[str]:
        out: list[str] = []
        for i in range(self._list.count()):
            li = self._list.item(i)
            if li.checkState() == Qt.CheckState.Checked:
                out.append(str(li.data(Qt.ItemDataRole.UserRole)))
        return out

    def _refresh_count(self) -> None:
        total = self._list.count()
        checked = self._collect_checked()
        if not checked:
            self._count.setText(f"All ({total})")
        else:
            self._count.setText(f"{len(checked)} of {total}")

    def _on_search(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self._list.count()):
            li = self._list.item(i)
            visible = needle == "" or needle in li.text().lower()
            li.setHidden(not visible)

    def _select_all(self) -> None:
        # Honour the search filter — "select all" affects only the
        # currently visible rows so the user can quickly toggle a
        # named subset (e.g. type "60_high" → Select all → toggles
        # every High Flux 60 µ entry).
        self._suspend = True
        for i in range(self._list.count()):
            li = self._list.item(i)
            if not li.isHidden():
                li.setCheckState(Qt.CheckState.Checked)
        self._suspend = False
        self.selection_changed.emit(self._collect_checked())
        self._refresh_count()

    def _clear(self) -> None:
        # Same filter-honouring logic as ``_select_all`` — when no
        # search filter is active this clears every row, which is the
        # natural meaning of "Clear".
        self._suspend = True
        for i in range(self._list.count()):
            li = self._list.item(i)
            if not li.isHidden():
                li.setCheckState(Qt.CheckState.Unchecked)
        self._suspend = False
        self.selection_changed.emit(self._collect_checked())
        self._refresh_count()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Cancel):
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)

    @staticmethod
    def _qss() -> str:
        p = get_theme().palette
        r = get_theme().radius
        t = get_theme().type
        return (
            f"QFrame#MultiSelectPopup {{"
            f"  background: {p.surface_elevated};"
            f"  border: 1px solid {p.border};"
            f"  border-radius: {r.card}px;"
            f"}}"
            f"QLineEdit {{"
            f"  background: {p.surface};"
            f"  border: 1px solid {p.border};"
            f"  border-radius: 6px; padding: 4px 8px;"
            f"  color: {p.text};"
            f"}}"
            f"QListWidget {{"
            f"  background: {p.surface};"
            f"  border: 1px solid {p.border};"
            f"  border-radius: 6px;"
            f"  color: {p.text};"
            f"  outline: 0;"
            f"}}"
            f"QListWidget::item {{ padding: 4px 6px; }}"
            f"QListWidget::item:hover {{ background: {p.bg}; }}"
            f"QPushButton {{"
            f"  background: transparent;"
            f"  border: 1px solid {p.border};"
            f"  border-radius: 6px; padding: 4px 10px;"
            f"  color: {p.text_secondary};"
            f"  font-size: {t.body}px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {p.bg}; color: {p.text};"
            f"}}"
            f"QLabel#MultiSelectCount {{"
            f"  color: {p.text_muted};"
            f"  font-size: {t.caption}px;"
            f"}}"
        )


class MultiSelectChip(QToolButton):
    """Chip-button + popup multi-selector.

    Empty selection means "all items" — the chip reads "All N" and
    callers should treat the empty list as a wildcard. This matches
    the optimizer convention where no filter == sweep everything.
    """

    selection_changed = Signal(list)  # list[str] of currently checked ids

    def __init__(
        self,
        label_plural: str = "items",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._label_plural = label_plural
        self._items: list[tuple[str, str, str]] = []
        self._selected: set[str] = set()

        self.setObjectName("MultiSelectChip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(28)
        self.setText(f"All 0 {label_plural}")
        self.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
        )
        self.setStyleSheet(self._qss())
        self.clicked.connect(self._open_popup)

        # The popup is built lazily because we need a screen / parent
        # window to position it — at construction time we may not be
        # mounted yet.
        self._popup: Optional[_SearchPopup] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_items(self, items: Iterable[tuple[str, str, str]]) -> None:
        """Replace the catalogue. Tuples are ``(id, label, tooltip)``."""
        self._items = list(items)
        # Drop selections that are no longer in the catalogue.
        valid = {i for i, _, _ in self._items}
        self._selected &= valid
        self._refresh_label()
        if self._popup is not None and self._popup.isVisible():
            self._popup.populate(self._items, self._selected)

    def set_selected(self, ids: Iterable[str]) -> None:
        valid = {i for i, _, _ in self._items}
        self._selected = {i for i in ids if i in valid}
        self._refresh_label()
        if self._popup is not None and self._popup.isVisible():
            self._popup.populate(self._items, self._selected)

    def selected(self) -> list[str]:
        return list(self._selected)

    def is_all(self) -> bool:
        """``True`` when the user has selected nothing — caller should
        treat that as a wildcard ("include all items")."""
        return not self._selected

    def all_ids(self) -> list[str]:
        return [i for i, _, _ in self._items]

    # ------------------------------------------------------------------
    def _open_popup(self) -> None:
        if self._popup is None:
            self._popup = _SearchPopup(self.window())
            self._popup.selection_changed.connect(self._on_popup_changed)
        self._popup.populate(self._items, self._selected)
        # Position the popup directly below the chip, left-aligned.
        anchor = self.mapToGlobal(self.rect().bottomLeft())
        # Nudge 4 px below the chip so the popup doesn't overlap the
        # button border.
        self._popup.move(anchor.x(), anchor.y() + 4)
        self._popup.show()

    def _on_popup_changed(self, ids: list[str]) -> None:
        self._selected = set(ids)
        self._refresh_label()
        self.selection_changed.emit(self.selected())

    def _refresh_label(self) -> None:
        total = len(self._items)
        if not self._selected:
            self.setText(f"All {total} {self._label_plural}")
            self.setToolTip(
                f"All {total} {self._label_plural} included. Click to filter.",
            )
        else:
            n = len(self._selected)
            # Tooltip lists every selected label so the user can audit
            # without re-opening the popup.
            labels = [lbl for (i, lbl, _t) in self._items if i in self._selected]
            self.setText(f"{n} of {total} {self._label_plural}")
            self.setToolTip("Selected:\n• " + "\n• ".join(labels))

    def sizeHint(self) -> QSize:
        # Wide enough to fit "All 999 materials" without clipping.
        return QSize(180, 28)

    @staticmethod
    def _qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"QToolButton#MultiSelectChip {{"
            f"  background: {p.surface};"
            f"  border: 1px solid {p.border};"
            f"  border-radius: 14px;"
            f"  padding: 4px 12px;"
            f"  color: {p.text};"
            f"  font-size: {t.body}px;"
            f"  font-weight: {t.medium};"
            f"  text-align: left;"
            f"}}"
            f"QToolButton#MultiSelectChip:hover {{"
            f"  background: {p.bg};"
            f"  border-color: {p.accent};"
            f"}}"
            f"QToolButton#MultiSelectChip:focus {{"
            f"  outline: 2px solid {p.focus_ring};"
            f"  outline-offset: 1px;"
            f"}}"
        )
