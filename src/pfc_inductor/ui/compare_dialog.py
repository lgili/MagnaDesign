"""Multi-column compare dialog: 1..4 designs side by side with diff colouring.

Reordering
----------
Columns are drag-and-drop reorderable. Clicking and dragging anywhere on
a column body (excluding the close / apply buttons, which consume the
click first) starts a ``QDrag`` carrying the source widget; the
``_ColumnsArea`` container computes the target insert index from the
cursor x-position and emits ``reorder_requested``. The dialog re-orders
``self._slots`` and rebuilds the columns. The leftmost slot is always
the REF — dragging a column to position 0 promotes it.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.compare import METRICS, CompareSlot, categorize
from pfc_inductor.ui.theme import get_theme

MAX_SLOTS = 8

# Mime type for intra-app column drags. The bytes carry no payload —
# we look up the source widget via ``event.source()`` because drags
# are always in-process here. The mime presence just tells the drop
# zone "this is one of ours, accept it".
_COLUMN_MIME = "application/x-pfc-compare-column"

# Compare-row backgrounds resolve from the active theme at row-render
# time so light↔dark transitions don't leave stale tints behind.
_BG_NEUTRAL = "transparent"


class _ColumnWidget(QFrame):
    """One comparison column: header label, monospaced metric table.

    Draggable: clicking and holding anywhere on the column body (the
    close / apply buttons consume their own clicks first) initiates
    a ``QDrag`` carrying this widget as ``event.source()``. The
    enclosing ``_ColumnsArea`` accepts the drop and signals the
    dialog to reorder.
    """

    remove_requested = Signal(object)  # emits self
    apply_requested = Signal(object)

    def __init__(self, slot: CompareSlot, leftmost: Optional[CompareSlot] = None,
                 is_leftmost: bool = False, parent=None):
        super().__init__(parent)
        self.slot = slot
        self._is_leftmost = is_leftmost
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Mouse-down position for drag-distance threshold; cleared on
        # release / drag-start.
        self._drag_press_pos: Optional[QPoint] = None
        # Show the move cursor over draggable areas so the affordance
        # is discoverable without a tooltip.
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)

        # Header
        header = QHBoxLayout()
        header_label = QLabel(slot.short_label)
        header_label.setWordWrap(True)
        f = QFont()
        f.setBold(True)
        header_label.setFont(f)
        header.addWidget(header_label, 1)
        if is_leftmost:
            ref_pill = QLabel("REF")
            p = get_theme().palette
            ref_pill.setStyleSheet(
                f"background:{p.accent}; color:{p.text_inverse}; "
                f"padding:1px 6px; border-radius:6px; font-size:10px;"
            )
            header.addWidget(ref_pill)
        btn_close = QPushButton("✕")
        btn_close.setFixedWidth(22)
        btn_close.setFlat(True)
        btn_close.clicked.connect(lambda: self.remove_requested.emit(self))
        header.addWidget(btn_close)
        v.addLayout(header)

        # Metric rows
        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFamily("Menlo")
        for metric in METRICS:
            row = QHBoxLayout()
            row.setSpacing(2)
            lbl = QLabel(f"{metric.label}:")
            lbl.setStyleSheet(
                f"color:{get_theme().palette.text_secondary}; font-size:11px;"
            )
            lbl.setFixedWidth(120)
            row.addWidget(lbl)

            val = QLabel(self._format_value(metric))
            val.setFont(mono)
            val.setStyleSheet(self._style_for(metric, leftmost))
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(val, 1)

            v.addLayout(row)

        # Apply button
        btn_apply = QPushButton("Apply this")
        btn_apply.clicked.connect(lambda: self.apply_requested.emit(self))
        v.addWidget(btn_apply)
        v.addStretch(1)

    def _format_value(self, metric) -> str:
        try:
            txt = metric.format(self.slot)
            if metric.unit:
                txt += f" {metric.unit}"
            return txt
        except Exception:
            return "—"

    def _style_for(self, metric, leftmost: Optional[CompareSlot]) -> str:
        if self._is_leftmost or leftmost is None:
            return "padding:2px 4px;"
        try:
            this_val = metric.value_of(self.slot)
            ref_val = metric.value_of(leftmost)
            kind = categorize(metric.key, ref_val, this_val)
        except Exception:
            kind = "neutral"
        p = get_theme().palette
        bg = {"better": p.compare_better_bg, "worse": p.compare_worse_bg,
              "neutral": _BG_NEUTRAL}[kind]
        return f"padding:2px 4px; background:{bg}; border-radius:3px;"

    # ------------------------------------------------------------------
    # Drag source — see module docstring "Reordering" for the protocol.
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        """Record the press position for drag-distance evaluation.

        Children that consume the click (close button, apply button)
        intercept first via Qt's normal event propagation, so this
        only fires for clicks on the column body / labels, which is
        exactly the drag handle area we want.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_press_pos = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_press_pos = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """Start a drag once the cursor has moved past the system
        drag-distance threshold. Below that we treat it as a click."""
        if self._drag_press_pos is None:
            return super().mouseMoveEvent(event)
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(event)
        delta = (event.position().toPoint() - self._drag_press_pos).manhattanLength()
        if delta < QApplication.startDragDistance():
            return super().mouseMoveEvent(event)

        drag = QDrag(self)
        mime = QMimeData()
        # Payload is a sentinel — we only need to know the drag
        # came from our compare-column widgets. The actual source
        # is recovered via ``event.source()`` in the drop zone.
        mime.setData(_COLUMN_MIME, b"1")
        drag.setMimeData(mime)

        # Translucent self-snapshot as drag preview. Without this the
        # cursor carries a default arrow and the user can't tell which
        # column they're dragging once the mouse moves off the source.
        snap = self.grab()
        canvas = QPixmap(snap.size())
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setOpacity(0.65)
        painter.drawPixmap(0, 0, snap)
        painter.end()
        drag.setPixmap(canvas)
        drag.setHotSpot(self._drag_press_pos)

        # Reset state before exec — the modal drag loop blocks here.
        self._drag_press_pos = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        drag.exec(Qt.DropAction.MoveAction)


class _ColumnsArea(QWidget):
    """Drop zone that holds the row of ``_ColumnWidget`` columns.

    Accepts drags carrying the ``_COLUMN_MIME`` type, computes the
    target insert index from the drop x-coordinate (gap between
    columns nearest the cursor), and signals ``reorder_requested``.
    During drag-over it paints a vertical drop indicator at the
    pending insert position so the user knows where the column will
    land before they release.
    """

    # ``(source_widget, target_index)`` — target_index is the slot
    # index *after* removing the source from its current position,
    # so the dialog can splice without further bookkeeping.
    reorder_requested = Signal(object, int)

    # Drop-indicator visual: vertical line, 3 px wide, accent colour.
    _INDICATOR_WIDTH = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._columns_layout = QHBoxLayout()
        self._columns_layout.setSpacing(8)
        self.setLayout(self._columns_layout)
        # x-coordinate where the drop-indicator vertical line should
        # be painted; ``None`` while no drag is in progress.
        self._drop_indicator_x: Optional[int] = None

    @property
    def columns_layout(self) -> QHBoxLayout:
        """Exposed so ``CompareDialog._refresh_columns`` can populate
        the layout directly (preserving the original construction
        path; the only change is *where* the layout lives)."""
        return self._columns_layout

    # ------------------------------------------------------------------
    # Drag-and-drop handlers.
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_COLUMN_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if not event.mimeData().hasFormat(_COLUMN_MIME):
            event.ignore()
            return
        target_idx = self._compute_target_index(event.position().toPoint())
        # Recompute and repaint the indicator at the gap
        # corresponding to ``target_idx``.
        self._drop_indicator_x = self._gap_x_for_index(target_idx)
        self.update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._drop_indicator_x = None
        self.update()
        event.accept()

    def dropEvent(self, event) -> None:
        src = event.source()
        self._drop_indicator_x = None
        self.update()
        if not isinstance(src, _ColumnWidget):
            event.ignore()
            return
        if not event.mimeData().hasFormat(_COLUMN_MIME):
            event.ignore()
            return
        target_idx = self._compute_target_index(event.position().toPoint())
        event.acceptProposedAction()
        self.reorder_requested.emit(src, target_idx)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._drop_indicator_x is None:
            return
        # Vertical accent-coloured bar at the insert gap. Drawn on
        # top of the children so it sits over the column edges.
        painter = QPainter(self)
        try:
            colour = QColor(get_theme().palette.accent)
        except Exception:
            colour = QColor("#3a78b5")
        pen = QPen(colour)
        pen.setWidth(self._INDICATOR_WIDTH)
        painter.setPen(pen)
        x = self._drop_indicator_x
        painter.drawLine(x, 4, x, self.height() - 4)
        painter.end()

    # ------------------------------------------------------------------
    # Index math.
    # ------------------------------------------------------------------
    def _column_widgets(self) -> list[_ColumnWidget]:
        """Walk the layout in order and return the live
        ``_ColumnWidget`` instances. Skips spacers / placeholder
        widgets so the indices line up with ``self._slots``."""
        out: list[_ColumnWidget] = []
        for i in range(self._columns_layout.count()):
            w = self._columns_layout.itemAt(i).widget()
            if isinstance(w, _ColumnWidget):
                out.append(w)
        return out

    def _compute_target_index(self, pos: QPoint) -> int:
        """Map cursor x-coordinate to the slot index where a drop
        would insert. Returns 0 if the cursor is left of the first
        column, ``N`` if right of the last, or ``i`` for between
        columns ``i-1`` and ``i``."""
        cols = self._column_widgets()
        if not cols:
            return 0
        x = pos.x()
        for i, col in enumerate(cols):
            mid = col.x() + col.width() / 2
            if x < mid:
                return i
        return len(cols)

    def _gap_x_for_index(self, idx: int) -> int:
        """Where to paint the drop indicator for a given target
        index. Index 0 → left edge of first column; index N → right
        edge of last column; otherwise mid-gap between adjacent
        columns."""
        cols = self._column_widgets()
        if not cols:
            return 0
        if idx <= 0:
            return max(0, cols[0].x() - 3)
        if idx >= len(cols):
            last = cols[-1]
            return last.x() + last.width() + 3
        prev_col = cols[idx - 1]
        next_col = cols[idx]
        prev_right = prev_col.x() + prev_col.width()
        next_left = next_col.x()
        return (prev_right + next_left) // 2


class CompareDialog(QDialog):
    selection_applied = Signal(str, str, str)  # material_id, core_id, wire_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compare designs")
        self.resize(1400, 720)
        self._slots: list[CompareSlot] = []
        self._columns: list[_ColumnWidget] = []

        outer = QVBoxLayout(self)
        outer.addLayout(self._build_toolbar())
        outer.addWidget(self._build_columns_area(), 1)
        outer.addWidget(self._build_status())

        self._refresh_columns()

    def _build_toolbar(self) -> QHBoxLayout:
        h = QHBoxLayout()
        self.btn_add_current = QPushButton("Add current design")
        self.btn_add_current.setStyleSheet("font-weight: bold;")
        self.btn_add_current.clicked.connect(self._on_add_current)
        h.addWidget(self.btn_add_current)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self._on_clear)
        h.addWidget(self.btn_clear)
        h.addStretch(1)
        self.btn_export_pdf = QPushButton("Export PDF")
        self.btn_export_pdf.clicked.connect(self._on_export_pdf)
        h.addWidget(self.btn_export_pdf)
        self.btn_export_html = QPushButton("Export HTML")
        self.btn_export_html.clicked.connect(self._on_export_html)
        h.addWidget(self.btn_export_html)
        self.btn_export_csv = QPushButton("Export CSV")
        self.btn_export_csv.clicked.connect(self._on_export_csv)
        h.addWidget(self.btn_export_csv)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        h.addWidget(self.btn_close)
        return h

    def _build_columns_area(self) -> QGroupBox:
        box = QGroupBox()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        self._columns_area = _ColumnsArea()
        # Same layout reference the existing ``_refresh_columns``
        # populates — switching the container to ``_ColumnsArea``
        # is the only structural change needed for drag-and-drop.
        self._columns_layout = self._columns_area.columns_layout
        self._columns_area.reorder_requested.connect(self._on_reorder)
        v.addWidget(self._columns_area, 1)
        return box

    def _build_status(self) -> QLabel:
        self._status = QLabel("Add a design to get started.")
        self._status.setStyleSheet(
            f"color:{get_theme().palette.text_secondary}; padding:4px;"
        )
        return self._status

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def add_slot(self, slot: CompareSlot) -> bool:
        if len(self._slots) >= MAX_SLOTS:
            QMessageBox.information(
                self, "Limit reached",
                f"The comparator supports at most {MAX_SLOTS} designs side by side.",
            )
            return False
        self._slots.append(slot)
        self._refresh_columns()
        return True

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_add_current(self):
        parent = self.parent()
        if parent is None or not hasattr(parent, "current_compare_slot"):
            QMessageBox.warning(self, "No active design",
                                "Could not capture the current design.")
            return
        try:
            slot = parent.current_compare_slot()
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))
            return
        self.add_slot(slot)

    def _on_clear(self):
        self._slots.clear()
        self._refresh_columns()

    def _on_remove(self, column: _ColumnWidget):
        if column.slot in self._slots:
            self._slots.remove(column.slot)
        self._refresh_columns()

    def _on_apply(self, column: _ColumnWidget):
        s = column.slot
        self.selection_applied.emit(s.material.id, s.core.id, s.wire.id)
        self.accept()

    def _on_reorder(self, source: _ColumnWidget, target_idx: int) -> None:
        """Move ``source.slot`` to ``target_idx`` in ``self._slots``.

        ``target_idx`` is the index returned by
        ``_ColumnsArea._compute_target_index`` — the position the
        cursor pointed at when the drop happened, expressed against
        the *current* layout (i.e. before any removal). We splice
        carefully:

        - If the user dragged the column "back to where it already
          was" (target_idx in {src_idx, src_idx + 1}) we do nothing
          to avoid a wasteful refresh + flicker.
        - Otherwise we remove first, then adjust ``target_idx`` for
          the index shift caused by the removal, then re-insert.

        After reordering, ``_refresh_columns`` rebuilds the column
        widgets — index 0 is automatically the REF (the leftmost
        slot is what ``_refresh_columns`` already treats as the
        reference for diff colouring).
        """
        try:
            src_idx = self._slots.index(source.slot)
        except ValueError:
            return
        # No-op cases (drop in same gap, before or after the source).
        if target_idx in (src_idx, src_idx + 1):
            return
        slot = self._slots.pop(src_idx)
        # If we removed an element with index < target_idx, every
        # later element shifted left by one — adjust.
        adjusted = target_idx - 1 if target_idx > src_idx else target_idx
        adjusted = max(0, min(len(self._slots), adjusted))
        self._slots.insert(adjusted, slot)
        self._refresh_columns()

    # ------------------------------------------------------------------
    # Public accessors — used by the v3 ``Exportar`` tab so the user
    # can write the comparison directly from the workspace without
    # opening the dialog first.
    # ------------------------------------------------------------------
    def slots(self) -> list[CompareSlot]:
        """Snapshot of accumulated comparison slots (read-only)."""
        return list(self._slots)

    def export_html_to(self, path: str) -> str:
        """Write the current slots as a comparative HTML datasheet."""
        from pfc_inductor.report.html_compare import generate_compare_html
        return str(generate_compare_html(self._slots, path))

    def export_pdf_to(self, path: str) -> str:
        """Write the current slots as a comparative PDF datasheet
        (A4 landscape, vector text, embedded font, deterministic
        page breaks). Customer-grade artefact alongside the HTML
        preview."""
        from pfc_inductor.report.pdf_compare import generate_compare_pdf
        return str(generate_compare_pdf(self._slots, path))

    def export_csv_to(self, path: str) -> str:
        """Write the current slots as a CSV (one row per metric)."""
        self._write_csv(path)
        return path

    def _on_export_html(self):
        if not self._slots:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save comparison", "comparison.html",
            "HTML (*.html)",
        )
        if not path:
            return
        from pfc_inductor.report.html_compare import generate_compare_html
        try:
            out = generate_compare_html(self._slots, path)
        except Exception as e:
            QMessageBox.critical(self, "Export error", str(e))
            return
        QMessageBox.information(self, "Exported", f"Saved to:\n{out}")

    def _on_export_pdf(self):
        """Native PDF datasheet for the comparison.

        Same data as the HTML export, A4 landscape, embedded Inter
        font, deterministic page breaks. Print/customer artefact —
        avoids the format/colour drift that browser-print produces.
        """
        if not self._slots:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save comparison (PDF)", "comparison.pdf",
            "PDF (*.pdf)",
        )
        if not path:
            return
        try:
            out = self.export_pdf_to(path)
        except Exception as e:
            QMessageBox.critical(self, "Export error", str(e))
            return
        QMessageBox.information(self, "Exported", f"Saved to:\n{out}")

    def _on_export_csv(self):
        if not self._slots:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV", "comparison.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
        try:
            self._write_csv(path)
        except Exception as e:
            QMessageBox.critical(self, "Export error", str(e))
            return
        QMessageBox.information(self, "Exported", f"Saved to:\n{path}")

    def _write_csv(self, path: str):
        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            header = ["Metric", "Unit"] + [s.label for s in self._slots]
            w.writerow(header)
            for metric in METRICS:
                row = [metric.label, metric.unit]
                for slot in self._slots:
                    try:
                        row.append(metric.format(slot))
                    except Exception:
                        row.append("")
                w.writerow(row)

    def _refresh_columns(self):
        # Clear existing columns
        while self._columns_layout.count():
            item = self._columns_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._columns = []

        # Empty-state CTA: when the dialog opens with zero slots the
        # columns area used to be a vacant rectangle and the toolbar
        # button was the only visible affordance. New users blanked
        # out — they didn't connect "Add current design" with the
        # empty space below. Now we paint an inline placeholder card
        # with a duplicate, prominently sized CTA right where the
        # comparison columns will land.
        if not self._slots:
            placeholder = self._build_empty_placeholder()
            self._columns_layout.addWidget(placeholder, 1)
            self._status.setText(
                "Use "
                "<b>Add current design</b> to snapshot the active "
                "project. Repeat after each Recalculate to stack "
                f"up to {MAX_SLOTS} alternatives side by side."
            )
            self.btn_add_current.setEnabled(True)
            return

        leftmost = self._slots[0]
        for i, slot in enumerate(self._slots):
            col = _ColumnWidget(
                slot,
                leftmost=leftmost if i > 0 else None,
                is_leftmost=(i == 0),
                parent=self,
            )
            col.remove_requested.connect(self._on_remove)
            col.apply_requested.connect(self._on_apply)
            self._columns_layout.addWidget(col)
            self._columns.append(col)
        self._columns_layout.addStretch(1)

        n = len(self._slots)
        self._status.setText(
            f"{n}/{MAX_SLOTS} designs in the comparator. "
            f"Column 1 is the reference; green = better, red = worse."
        )
        self.btn_add_current.setEnabled(n < MAX_SLOTS)

    def _build_empty_placeholder(self) -> QWidget:
        """Painted in the columns area when ``self._slots`` is empty.

        Big centered CTA mirrors the toolbar button — discoverable
        without forcing the user's eye up to the toolbar. Same
        ``_on_add_current`` slot fires either way.
        """
        from PySide6.QtWidgets import QFrame
        p = get_theme().palette
        wrap = QFrame()
        wrap.setStyleSheet(
            f"QFrame {{ background: {p.bg};"
            f" border: 2px dashed {p.border}; border-radius: 12px; }}"
        )
        wrap.setMinimumHeight(280)
        v = QVBoxLayout(wrap)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Empty comparison")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {p.text}; font-size: 16px; font-weight: 600;"
            " border: 0;"
        )
        sub = QLabel(
            "Snapshot the current project to get started.\n"
            f"You can stack up to {MAX_SLOTS} designs side by side."
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(
            f"color: {p.text_secondary}; font-size: 12px; border: 0;"
        )
        cta = QPushButton("➕  Adicionar design atual")
        cta.setCursor(Qt.CursorShape.PointingHandCursor)
        cta.setStyleSheet(
            f"QPushButton {{ background: {p.accent}; color: white;"
            f" border: 0; border-radius: 8px; padding: 10px 20px;"
            f" font-size: 13px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {p.accent_hover}; }}"
        )
        cta.clicked.connect(self._on_add_current)
        v.addWidget(title)
        v.addSpacing(6)
        v.addWidget(sub)
        v.addSpacing(20)
        v.addWidget(cta, 0, Qt.AlignmentFlag.AlignCenter)
        return wrap
