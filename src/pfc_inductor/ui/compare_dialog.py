"""Multi-column compare dialog: 1..4 designs side by side with diff colouring."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
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

MAX_SLOTS = 4

# Compare-row backgrounds resolve from the active theme at row-render
# time so light↔dark transitions don't leave stale tints behind.
_BG_NEUTRAL = "transparent"


class _ColumnWidget(QFrame):
    """One comparison column: header label, monospaced metric table."""

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
        btn_apply = QPushButton("Aplicar este")
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


class CompareDialog(QDialog):
    selection_applied = Signal(str, str, str)  # material_id, core_id, wire_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Comparar designs")
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
        self.btn_add_current = QPushButton("Adicionar design atual")
        self.btn_add_current.setStyleSheet("font-weight: bold;")
        self.btn_add_current.clicked.connect(self._on_add_current)
        h.addWidget(self.btn_add_current)
        self.btn_clear = QPushButton("Limpar")
        self.btn_clear.clicked.connect(self._on_clear)
        h.addWidget(self.btn_clear)
        h.addStretch(1)
        self.btn_export_html = QPushButton("Exportar HTML")
        self.btn_export_html.clicked.connect(self._on_export_html)
        h.addWidget(self.btn_export_html)
        self.btn_export_csv = QPushButton("Exportar CSV")
        self.btn_export_csv.clicked.connect(self._on_export_csv)
        h.addWidget(self.btn_export_csv)
        self.btn_close = QPushButton("Fechar")
        self.btn_close.clicked.connect(self.reject)
        h.addWidget(self.btn_close)
        return h

    def _build_columns_area(self) -> QGroupBox:
        box = QGroupBox()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        self._columns_layout = QHBoxLayout()
        self._columns_layout.setSpacing(8)
        wrap = QWidget()
        wrap.setLayout(self._columns_layout)
        v.addWidget(wrap, 1)
        return box

    def _build_status(self) -> QLabel:
        self._status = QLabel("Adicione um design para começar.")
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
                self, "Limite atingido",
                f"O comparador suporta no máximo {MAX_SLOTS} designs lado a lado.",
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
            QMessageBox.warning(self, "Sem design ativo",
                                "Não foi possível pegar o design atual.")
            return
        try:
            slot = parent.current_compare_slot()
        except Exception as e:
            QMessageBox.warning(self, "Erro", str(e))
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

    def export_csv_to(self, path: str) -> str:
        """Write the current slots as a CSV (one row per metric)."""
        self._write_csv(path)
        return path

    def _on_export_html(self):
        if not self._slots:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Salvar comparação", "comparacao.html",
            "HTML (*.html)",
        )
        if not path:
            return
        from pfc_inductor.report.html_compare import generate_compare_html
        try:
            out = generate_compare_html(self._slots, path)
        except Exception as e:
            QMessageBox.critical(self, "Erro ao exportar", str(e))
            return
        QMessageBox.information(self, "Exportado", f"Salvo em:\n{out}")

    def _on_export_csv(self):
        if not self._slots:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Salvar CSV", "comparacao.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
        try:
            self._write_csv(path)
        except Exception as e:
            QMessageBox.critical(self, "Erro ao exportar", str(e))
            return
        QMessageBox.information(self, "Exportado", f"Salvo em:\n{path}")

    def _write_csv(self, path: str):
        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            header = ["Métrica", "Unidade"] + [s.label for s in self._slots]
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

        leftmost = self._slots[0] if self._slots else None
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
        if n == 0:
            self._status.setText("Adicione um design para começar (botão "
                                  "'Adicionar design atual').")
        else:
            self._status.setText(
                f"{n}/{MAX_SLOTS} designs no comparador. "
                f"Coluna 1 é a referência; verde = melhor, vermelho = pior."
            )
        self.btn_add_current.setEnabled(n < MAX_SLOTS)
