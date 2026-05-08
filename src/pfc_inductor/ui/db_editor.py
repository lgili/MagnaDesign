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

        # Right: summary banner + JSON editor + save
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)

        # Summary read-only header — tells the user what they're
        # looking at WITHOUT making them parse JSON. Updated whenever
        # selection changes; remains visible even after edits.
        self._summary = QLabel()
        self._summary.setObjectName("DbEntrySummary")
        self._summary.setWordWrap(True)
        self._summary.setTextFormat(Qt.TextFormat.RichText)
        self._summary.setStyleSheet(self._summary_qss())
        rv.addWidget(self._summary)

        # Caveat banner — flags JSON editing as advanced so casual
        # users don't fear breaking things. The banner is dismissable
        # in the future; for now it's always-on.
        warn = QLabel(
            "⚠ Advanced JSON editing. We validate on <b>Apply "
            "change</b> before saving — invalid JSON stays in the "
            "field until corrected.",
        )
        warn.setObjectName("DbEditorWarning")
        warn.setWordWrap(True)
        warn.setStyleSheet(self._warn_qss())
        rv.addWidget(warn)

        self.editor = QTextEdit()
        f = QFont()
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setFamily("Menlo")
        self.editor.setFont(f)
        rv.addWidget(self.editor, 1)

        bb = QHBoxLayout()
        self.btn_apply = QPushButton("Apply change")
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
            self._summary.setText("No record selected.")
            return
        eid = current.data(Qt.ItemDataRole.UserRole)
        for e in self.entries:
            if e.id == eid:
                txt = json.dumps(e.model_dump(mode="json"), indent=2, ensure_ascii=False)
                self.editor.setPlainText(txt)
                self._summary.setText(self._summary_for(e))
                return

    def _summary_for(self, e) -> str:
        """Plain-language synopsis of the entry — human-readable
        alternative to scanning the JSON. Bold key facts so the user
        can recognise the part without parsing the full record.
        """
        if isinstance(e, Material):
            return (
                f"<b>{e.vendor} — {e.name}</b><br>"
                f"<span style='color:#71717A'>{e.family} · {e.type} · "
                f"μ_initial = {e.mu_initial:.0f} · "
                f"Bsat@25°C = {e.Bsat_25C_T:.2f} T</span>"
            )
        if isinstance(e, Core):
            return (
                f"<b>{e.vendor} — {e.part_number}</b> "
                f"<span style='color:#71717A'>({e.shape})</span><br>"
                f"<span style='color:#71717A'>"
                f"Ae = {e.Ae_mm2:.0f} mm² · le = {e.le_mm:.0f} mm · "
                f"Wa = {e.Wa_mm2:.0f} mm² · AL = {e.AL_nH:.0f} nH/N²</span>"
            )
        if isinstance(e, Wire):
            d = e.outer_diameter_mm() if hasattr(e, "outer_diameter_mm") else 0.0
            return (
                f"<b>{e.id}</b> "
                f"<span style='color:#71717A'>({e.type})</span><br>"
                f"<span style='color:#71717A'>"
                f"A_cu = {e.A_cu_mm2:.3f} mm² · OD ≈ {d:.3f} mm</span>"
            )
        return str(e)

    @staticmethod
    def _summary_qss() -> str:
        return (
            "QLabel#DbEntrySummary {"
            "  background: transparent;"
            "  border: 0;"
            "  padding: 8px 4px 12px 4px;"
            "  font-size: 13px;"
            "}"
        )

    @staticmethod
    def _warn_qss() -> str:
        return (
            "QLabel#DbEditorWarning {"
            "  background: #FFFBEB;"
            "  border: 1px solid #FCD34D;"
            "  border-radius: 8px;"
            "  padding: 8px 12px;"
            "  color: #92400E;"
            "  font-size: 11px;"
            "}"
        )

    def _on_add(self):
        new_id, ok = QInputDialog.getText(
            self,
            "New record",
            "Unique ID for the new record:",
        )
        if not ok or not new_id:
            return
        new_id = new_id.strip()
        if any(e.id == new_id for e in self.entries):
            QMessageBox.warning(self, "ID in use", f"A record with id '{new_id}' already exists.")
            return
        # Build minimal stub from the model class
        try:
            stub = self._stub_for_new(new_id)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not create stub: {e}")
            return
        self.entries.append(stub)
        self._dirty = True
        self.changed.emit()
        self._refresh_list(select_id=new_id)

    def _stub_for_new(self, new_id: str):
        from pfc_inductor.models.material import SteinmetzParams

        if self.model_cls is Material:
            return Material(
                id=new_id,
                vendor="?",
                family="?",
                name=new_id,
                type="powder",
                mu_initial=60,
                Bsat_25C_T=1.0,
                Bsat_100C_T=0.9,
                steinmetz=SteinmetzParams(Pv_ref_mWcm3=200, alpha=1.4, beta=2.5),
                rolloff=None,
            )
        if self.model_cls is Core:
            return Core(
                id=new_id,
                vendor="?",
                shape="toroid",
                part_number=new_id,
                default_material_id=self.entries[0].default_material_id if self.entries else "?",
                Ae_mm2=100,
                le_mm=80,
                Ve_mm3=8000,
                Wa_mm2=300,
                MLT_mm=60,
                AL_nH=100,
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
            self, "Duplicate record", "ID for the new record:", text=eid + "-copy"
        )
        if not ok or not new_id:
            return
        if any(e.id == new_id for e in self.entries):
            QMessageBox.warning(self, "ID in use", f"'{new_id}' already exists.")
            return
        data = original.model_dump(mode="json")
        data["id"] = new_id
        try:
            new_e = self.model_cls(**data)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Duplication failed: {e}")
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
        if (
            QMessageBox.question(
                self,
                "Confirm removal",
                f"Remove '{eid}'? This action is committed on save.",
            )
            != QMessageBox.StandardButton.Yes
        ):
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
            QMessageBox.warning(self, "Invalid JSON", f"Syntax error: {e}")
            return
        except Exception as e:
            QMessageBox.warning(self, "Validation failed", str(e))
            return
        # Replace entry preserving order
        for i, e in enumerate(self.entries):
            if e.id == eid:
                self.entries[i] = new_e
                break
        self._dirty = True
        self.changed.emit()
        self._refresh_list(select_id=new_e.id)


class DbEditorEmbed(QWidget):
    """Embeddable variant of the DB editor.

    Same body as :class:`DbEditorDialog` but lives as a ``QWidget`` so
    it can be mounted directly inside a workspace page (the v3 Catalog
    page does this). Emits ``saved`` whenever the user successfully
    writes the catalog to disk; the host listens and triggers a
    recompute.
    """

    saved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        info = QLabel(
            "Edit materials, cores and wires. Changes are written to "
            "the user data directory (does not affect the installed package)."
        )
        info.setWordWrap(True)
        info.setProperty("role", "muted")
        layout.addWidget(info)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.tab_mat = _ListJsonEditor("material", Material, load_materials())
        self.tab_core = _ListJsonEditor("core", Core, load_cores())
        self.tab_wire = _ListJsonEditor("wire", Wire, load_wires())

        self.tabs.addTab(self.tab_mat, f"Materials ({len(self.tab_mat.entries)})")
        self.tabs.addTab(self.tab_core, f"Cores ({len(self.tab_core.entries)})")
        self.tabs.addTab(self.tab_wire, f"Wires ({len(self.tab_wire.entries)})")

        for t in (self.tab_mat, self.tab_core, self.tab_wire):
            t.changed.connect(self._refresh_titles)

        bb = QHBoxLayout()
        self.btn_save = QPushButton("Save all")
        self.btn_save.setProperty("class", "Primary")
        self.btn_save.clicked.connect(self._on_save)
        bb.addStretch(1)
        bb.addWidget(self.btn_save)
        layout.addLayout(bb)

    def _refresh_titles(self):
        for tab, name in (
            (self.tab_mat, "Materials"),
            (self.tab_core, "Cores"),
            (self.tab_wire, "Wires"),
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
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Save error", str(e))
            return
        self.saved.emit()
        QMessageBox.information(self, "Saved", "Database updated.")


class DbEditorDialog(QDialog):
    """Modal wrapper around :class:`DbEditorEmbed`.

    Kept for back-compat with callers that expect a dialog (e.g. the
    Catalog overflow path). New code should prefer the embed."""

    saved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Database editor")
        self.resize(1200, 700)

        layout = QVBoxLayout(self)
        self._embed = DbEditorEmbed(self)
        self._embed.saved.connect(self._on_inner_saved)
        layout.addWidget(self._embed, 1)

        # Add a Close button alongside the embed's Save button, in a
        # row at the bottom that the embed itself doesn't render.
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

    # Forward attribute access to the embed for back-compat
    # (``dlg.tab_mat`` etc.).
    @property
    def tab_mat(self):
        return self._embed.tab_mat

    @property
    def tab_core(self):
        return self._embed.tab_core

    @property
    def tab_wire(self):
        return self._embed.tab_wire

    @property
    def tabs(self):
        return self._embed.tabs

    def _on_inner_saved(self):
        self.saved.emit()
        self.accept()
