"""Database editor dialog: edit materials, cores, wires.

Uses a JSON text editor per entry (validated against pydantic model on save).
Power-user friendly without writing 200 lines of generic form generators.
"""
from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.data_loader import (
    load_cores,
    load_materials,
    load_wires,
    save_cores,
    save_materials,
    save_wires,
)
from pfc_inductor.models import Core, Material, Wire


class _ListJsonEditor(QWidget):
    """Tab content: left = list of entries, right = JSON editor + buttons."""

    changed = Signal()

    def __init__(self, kind: str, model_cls, entries: list, parent=None):
        super().__init__(parent)
        self.kind = kind  # 'material' | 'core' | 'wire'
        self.model_cls = model_cls
        self.entries = list(entries)
        self._dirty = False

        outer = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        # Left: list
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        lv.addWidget(self.list, 1)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Adicionar")
        self.btn_dup = QPushButton("Duplicar")
        self.btn_del = QPushButton("Remover")
        self.btn_add.clicked.connect(self._on_add)
        self.btn_dup.clicked.connect(self._on_duplicate)
        self.btn_del.clicked.connect(self._on_delete)
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_dup)
        btn_row.addWidget(self.btn_del)
        lv.addLayout(btn_row)

        splitter.addWidget(left)

        # Right: JSON editor + save
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.editor = QTextEdit()
        f = QFont()
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setFamily("Menlo")
        self.editor.setFont(f)
        rv.addWidget(self.editor, 1)

        bb = QHBoxLayout()
        self.btn_apply = QPushButton("Aplicar alteração")
        self.btn_apply.clicked.connect(self._on_apply)
        bb.addWidget(self.btn_apply)
        bb.addStretch(1)
        rv.addLayout(bb)
        splitter.addWidget(right)
        splitter.setSizes([320, 600])

        self._refresh_list()

    @property
    def dirty(self) -> bool:
        return self._dirty

    def _refresh_list(self, select_id: Optional[str] = None):
        self.list.blockSignals(True)
        self.list.clear()
        for e in self.entries:
            label = self._label_for(e)
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, e.id)
            self.list.addItem(it)
        self.list.blockSignals(False)
        if select_id is not None:
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.ItemDataRole.UserRole) == select_id:
                    self.list.setCurrentRow(i)
                    return
        if self.list.count() > 0:
            self.list.setCurrentRow(0)

    def _label_for(self, e) -> str:
        if isinstance(e, Material):
            return f"{e.vendor} — {e.name}"
        if isinstance(e, Core):
            return f"{e.vendor} — {e.part_number} ({e.shape})"
        if isinstance(e, Wire):
            return f"{e.id}  ({e.type}, A={e.A_cu_mm2:.3f} mm²)"
        return str(e)

    def _on_select(self, current: QListWidgetItem, _prev):
        if current is None:
            self.editor.clear()
            return
        eid = current.data(Qt.ItemDataRole.UserRole)
        for e in self.entries:
            if e.id == eid:
                txt = json.dumps(e.model_dump(mode="json"), indent=2, ensure_ascii=False)
                self.editor.setPlainText(txt)
                return

    def _on_add(self):
        new_id, ok = QInputDialog.getText(
            self, "Novo registro", "ID único do novo registro:",
        )
        if not ok or not new_id:
            return
        new_id = new_id.strip()
        if any(e.id == new_id for e in self.entries):
            QMessageBox.warning(self, "ID em uso", f"Já existe um registro com id '{new_id}'.")
            return
        # Build minimal stub from the model class
        try:
            stub = self._stub_for_new(new_id)
        except Exception as e:
            QMessageBox.warning(self, "Erro", f"Não consegui criar stub: {e}")
            return
        self.entries.append(stub)
        self._dirty = True
        self.changed.emit()
        self._refresh_list(select_id=new_id)

    def _stub_for_new(self, new_id: str):
        from pfc_inductor.models.material import SteinmetzParams
        if self.model_cls is Material:
            return Material(
                id=new_id, vendor="?", family="?", name=new_id,
                type="powder", mu_initial=60, Bsat_25C_T=1.0, Bsat_100C_T=0.9,
                steinmetz=SteinmetzParams(Pv_ref_mWcm3=200, alpha=1.4, beta=2.5),
                rolloff=None,
            )
        if self.model_cls is Core:
            return Core(
                id=new_id, vendor="?", shape="toroid", part_number=new_id,
                default_material_id=self.entries[0].default_material_id if self.entries else "?",
                Ae_mm2=100, le_mm=80, Ve_mm3=8000, Wa_mm2=300, MLT_mm=60, AL_nH=100,
            )
        if self.model_cls is Wire:
            return Wire(id=new_id, type="round", A_cu_mm2=0.5, d_cu_mm=0.8, d_iso_mm=0.85)
        raise TypeError(f"Unsupported model {self.model_cls}")

    def _on_duplicate(self):
        cur = self.list.currentItem()
        if cur is None:
            return
        eid = cur.data(Qt.ItemDataRole.UserRole)
        original = next((e for e in self.entries if e.id == eid), None)
        if original is None:
            return
        new_id, ok = QInputDialog.getText(
            self, "Duplicar registro", "ID do novo registro:", text=eid + "-copy"
        )
        if not ok or not new_id:
            return
        if any(e.id == new_id for e in self.entries):
            QMessageBox.warning(self, "ID em uso", f"Já existe '{new_id}'.")
            return
        data = original.model_dump(mode="json")
        data["id"] = new_id
        try:
            new_e = self.model_cls(**data)
        except Exception as e:
            QMessageBox.warning(self, "Erro", f"Falha ao duplicar: {e}")
            return
        self.entries.append(new_e)
        self._dirty = True
        self.changed.emit()
        self._refresh_list(select_id=new_id)

    def _on_delete(self):
        cur = self.list.currentItem()
        if cur is None:
            return
        eid = cur.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(
            self, "Confirmar remoção",
            f"Remover '{eid}'? Esta ação será gravada ao salvar.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.entries = [e for e in self.entries if e.id != eid]
        self._dirty = True
        self.changed.emit()
        self._refresh_list()

    def _on_apply(self):
        cur = self.list.currentItem()
        if cur is None:
            return
        eid = cur.data(Qt.ItemDataRole.UserRole)
        try:
            data = json.loads(self.editor.toPlainText())
            new_e = self.model_cls(**data)
        except json.JSONDecodeError as e:
            QMessageBox.warning(self, "JSON inválido", f"Erro de sintaxe: {e}")
            return
        except Exception as e:
            QMessageBox.warning(self, "Validação falhou", str(e))
            return
        # Replace entry preserving order
        for i, e in enumerate(self.entries):
            if e.id == eid:
                self.entries[i] = new_e
                break
        self._dirty = True
        self.changed.emit()
        self._refresh_list(select_id=new_e.id)


class DbEditorDialog(QDialog):
    saved = Signal()  # Emitted when DB has been written

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editor da base de dados")
        self.resize(1200, 700)

        layout = QVBoxLayout(self)
        info = QLabel(
            "Edite materiais, núcleos e fios. Alterações são gravadas no diretório "
            "de dados do usuário (não afeta o pacote instalado)."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.tab_mat = _ListJsonEditor("material", Material, load_materials())
        self.tab_core = _ListJsonEditor("core", Core, load_cores())
        self.tab_wire = _ListJsonEditor("wire", Wire, load_wires())

        self.tabs.addTab(self.tab_mat, f"Materiais ({len(self.tab_mat.entries)})")
        self.tabs.addTab(self.tab_core, f"Núcleos ({len(self.tab_core.entries)})")
        self.tabs.addTab(self.tab_wire, f"Fios ({len(self.tab_wire.entries)})")

        for t in (self.tab_mat, self.tab_core, self.tab_wire):
            t.changed.connect(self._refresh_titles)

        bb = QHBoxLayout()
        self.btn_save = QPushButton("Salvar tudo")
        self.btn_save.setStyleSheet("font-weight: bold; padding: 4px 14px;")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_close = QPushButton("Fechar")
        self.btn_close.clicked.connect(self.reject)
        bb.addStretch(1)
        bb.addWidget(self.btn_save)
        bb.addWidget(self.btn_close)
        layout.addLayout(bb)

    def _refresh_titles(self):
        for tab, name in (
            (self.tab_mat, "Materiais"),
            (self.tab_core, "Núcleos"),
            (self.tab_wire, "Fios"),
        ):
            idx = self.tabs.indexOf(tab)
            mark = " *" if tab.dirty else ""
            self.tabs.setTabText(idx, f"{name} ({len(tab.entries)}){mark}")

    def _on_save(self):
        try:
            if self.tab_mat.dirty:
                save_materials(self.tab_mat.entries)
            if self.tab_core.dirty:
                save_cores(self.tab_core.entries)
            if self.tab_wire.dirty:
                save_wires(self.tab_wire.entries)
        except Exception as e:
            QMessageBox.critical(self, "Erro ao salvar", str(e))
            return
        self.saved.emit()
        QMessageBox.information(self, "Salvo", "Base de dados atualizada.")
        self.accept()
