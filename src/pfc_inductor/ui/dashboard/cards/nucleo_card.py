"""Seleção de Núcleo card.

Tabbed score-table view: Material | Núcleo | Fio. Each tab is a
``QTableView`` backed by ``_CandidateModel`` whose rightmost column
renders a colour-graded :class:`ScorePill
<pfc_inductor.ui.widgets.ScorePill>` via ``_ScorePillDelegate``.

Filters above each table:

- Searchable ``QLineEdit`` (case-insensitive substring against name +
  vendor).
- "Apenas curados" checkbox (vendor in :data:`_CURATED_VENDORS`).

Footer: an "Aplicar seleção" primary button. Becomes enabled when the
user picks a row whose id differs from the current selection. Emits
``selection_applied(material_id, core_id, wire_id)`` with the picked
ids — only the field for the active tab actually changes; the others
stay at their current value.
"""
from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.optimize.scoring import (
    rank_cores,
    rank_materials,
    rank_wires,
)
from pfc_inductor.ui.widgets import Card, ScorePill

# Vendors we have curated cost data + calibration for.
_CURATED_VENDORS = {
    "magnetics", "magmattec", "micrometals", "csc",
    "thornton", "dongxing", "tdk", "ferroxcube",
}


# ---------------------------------------------------------------------------
# Table model — generic over (object, columns, score)
# ---------------------------------------------------------------------------

class _CandidateModel(QAbstractTableModel):
    """Generic table model holding (candidate, columns, score) tuples.

    ``columns`` is a list of strings; ``rows`` is a list of
    ``(candidate, [str cells…], score)``. The score column is always
    the **last** logical column and uses ``Qt.UserRole`` to expose the
    raw float to :class:`_ScorePillDelegate`.
    """

    def __init__(self, headers: list[str],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._headers = list(headers) + ["Score"]
        self._rows: list[tuple[object, list[str], float]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_rows(self,
                 rows: Sequence[tuple[object, list[str], float]]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def candidate_at(self, row: int) -> object:
        return self._rows[row][0]

    def score_at(self, row: int) -> float:
        return self._rows[row][2]

    # ------------------------------------------------------------------
    # Qt model API
    # ------------------------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._headers)

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._headers[section]
        return None

    def data(self, index: QModelIndex,
             role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if r < 0 or r >= len(self._rows):
            return None
        candidate, cells, score = self._rows[r]
        is_score_col = c == len(self._headers) - 1
        if role == Qt.ItemDataRole.DisplayRole:
            if is_score_col:
                return f"{score:.0f}"
            if c < len(cells):
                return cells[c]
            return ""
        if role == Qt.ItemDataRole.UserRole and is_score_col:
            return float(score)
        if role == Qt.ItemDataRole.UserRole and c == 0:
            return candidate  # caller can fetch the row's raw object
        if role == Qt.ItemDataRole.TextAlignmentRole and is_score_col:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None


# ---------------------------------------------------------------------------
# ScorePill delegate
# ---------------------------------------------------------------------------

class _ScorePillDelegate(QStyledItemDelegate):
    """Render the score column as a coloured pill using the project
    :class:`ScorePill` widget for sizing/colour, but draw via
    ``QPainter`` so the painter integrates with the QTableView's
    selection / hover rendering."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex) -> None:
        score_obj = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(score_obj, float):
            super().paint(painter, option, index)
            return

        painter.save()
        try:
            # Build a transient pill — using ScorePill keeps colour
            # logic centralised. The transient widget is never shown.
            pill = ScorePill(score_obj)
            # Render to pixmap to avoid Qt's "cannot render unmounted
            # widget" assertions.
            pix = pill.grab()
            # Centre-align inside the cell.
            target = option.rect
            x = target.x() + (target.width() - pix.width()) // 2
            y = target.y() + (target.height() - pix.height()) // 2
            painter.drawPixmap(x, y, pix)
        finally:
            painter.restore()


# ---------------------------------------------------------------------------
# Filter proxy
# ---------------------------------------------------------------------------

class _CandidateFilterProxy(QSortFilterProxyModel):
    """Filter proxy with a search string + curated-vendor checkbox.

    The vendor lookup is done by inspecting the candidate object via
    its ``vendor`` attribute (Material, Core) — wires don't have a
    vendor field, so the curated filter is a no-op for the wire tab.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._search = ""
        self._curated_only = False
        self._sort_descending_score = True

    def set_search(self, text: str) -> None:
        self._search = text.lower().strip()
        self.invalidate()

    def set_curated_only(self, on: bool) -> None:
        self._curated_only = bool(on)
        self.invalidate()

    def filterAcceptsRow(self, source_row: int,
                         source_parent: QModelIndex) -> bool:
        m = self.sourceModel()
        if not isinstance(m, _CandidateModel):
            return True
        candidate = m.candidate_at(source_row)
        if self._search:
            haystack = " ".join(
                str(getattr(candidate, k, "") or "")
                for k in ("id", "name", "vendor")
            ).lower()
            if self._search not in haystack:
                return False
        if self._curated_only:
            vendor = (getattr(candidate, "vendor", "") or "").lower().strip()
            if vendor and vendor not in _CURATED_VENDORS:
                return False
        return True


# ---------------------------------------------------------------------------
# Tab body — one per Material / Núcleo / Fio
# ---------------------------------------------------------------------------

class _CandidateTab(QWidget):
    """Search + table + filter checkbox for a single tab."""

    selection_changed = Signal()

    def __init__(self, headers: list[str],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        # Filter row
        row = QHBoxLayout()
        row.setSpacing(8)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Buscar por nome / vendor…")
        self._chk_curated = QCheckBox("Apenas curados")
        row.addWidget(self._search, 1)
        row.addWidget(self._chk_curated, 0)
        v.addLayout(row)

        # Model + proxy + view
        self._model = _CandidateModel(headers)
        self._proxy = _CandidateFilterProxy()
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(Qt.ItemDataRole.UserRole)

        self.table = QTableView()
        self.table.setModel(self._proxy)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QTableView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QTableView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        # Row height: 28 px keeps ~9 rows visible at a 260 px minHeight,
        # which is enough to scan a top-N candidate list without scroll.
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setMinimumHeight(260)
        # Last column = score, render with delegate
        score_col = self._model.columnCount() - 1
        self.table.setItemDelegateForColumn(score_col, _ScorePillDelegate(self))
        # Default sort by score descending.
        self.table.sortByColumn(score_col, Qt.SortOrder.DescendingOrder)
        # Header sizing: stretch the first text column, fit the rest. The
        # score column gets a fixed 80 px so the colour-graded pill never
        # collapses or jitters as the parent grid resizes.
        h = self.table.horizontalHeader()
        h.setMinimumSectionSize(64)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, score_col):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(score_col, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(score_col, 80)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Expanding)
        v.addWidget(self.table, 1)

        # Wire filter signals
        self._search.textChanged.connect(self._proxy.set_search)
        self._chk_curated.toggled.connect(self._proxy.set_curated_only)
        self.table.selectionModel().selectionChanged.connect(
            lambda *_a: self.selection_changed.emit()
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_rows(
        self,
        rows: Sequence[tuple[object, list[str], float]],
        *,
        preserve_id: Optional[str] = None,
    ) -> None:
        """Replace the model rows. Optionally re-select a row by id and
        restore the vertical scroll position so the user doesn't lose
        their place when a recalc triggers a re-rank.
        """
        # Snapshot scroll + selected id BEFORE the model reset wipes them.
        scroll_pos = self.table.verticalScrollBar().value()
        if preserve_id is None:
            cand = self.selected_candidate()
            if cand is not None:
                preserve_id = getattr(cand, "id", None)

        self._model.set_rows(rows)

        # Re-select the same id if it survived the rebuild.
        if preserve_id:
            for src_row in range(self._model.rowCount()):
                cand = self._model.candidate_at(src_row)
                if getattr(cand, "id", None) == preserve_id:
                    proxy_idx = self._proxy.mapFromSource(
                        self._model.index(src_row, 0)
                    )
                    if proxy_idx.isValid():
                        self.table.selectionModel().select(
                            proxy_idx,
                            self.table.selectionModel().SelectionFlag.ClearAndSelect
                            | self.table.selectionModel().SelectionFlag.Rows,
                        )
                    break
        # Restore scroll. Done last so the selection-induced auto-scroll
        # doesn't override what the user was looking at.
        self.table.verticalScrollBar().setValue(scroll_pos)

    def selected_candidate(self) -> object | None:
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            return None
        idx = self._proxy.mapToSource(sel[0])
        return self._model.candidate_at(idx.row())

    def visible_row_count(self) -> int:
        return self._proxy.rowCount()


# ---------------------------------------------------------------------------
# Public NucleoCard
# ---------------------------------------------------------------------------

class _NucleoBody(QWidget):
    """Tabbed body — emits a single signal when the user applies a
    selection different from the current one."""

    selection_applied = Signal(str, str, str)  # material_id, core_id, wire_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self._tabs = QTabWidget()
        self.tab_material = _CandidateTab(["Material", "μᵢ", "Bsat (T)"])
        self.tab_core = _CandidateTab(["Core", "Vendor", "Ve (cm³)"])
        self.tab_wire = _CandidateTab(["Fio", "Tipo", "A_cu (mm²)"])
        self._tabs.addTab(self.tab_material, "Material")
        self._tabs.addTab(self.tab_core, "Núcleo")
        self._tabs.addTab(self.tab_wire, "Fio")
        v.addWidget(self._tabs, 1)

        # Cache inputs for re-ranking.
        self._spec: Spec | None = None
        self._materials: list[Material] = []
        self._cores: list[Core] = []
        self._wires: list[Wire] = []
        self._current_material: Material | None = None
        self._current_core: Core | None = None
        self._current_wire: Wire | None = None
        self._is_populating = False
        # Fingerprint of the last successful rebuild. The host
        # (``ProjetoPage``/``MainWindow``) calls ``populate()`` after
        # every recalc — but for a same-material core/wire pick the
        # candidate set hasn't changed, so we can skip the heavy
        # ``set_rows`` and just refresh the cached "current selection"
        # state. Avoids the table scrolling back to the top each time
        # the user clicks a different row.
        self._last_rebuild_key: tuple | None = None

        for tab in (self.tab_material, self.tab_core, self.tab_wire):
            tab.selection_changed.connect(
                lambda tab=tab: self._on_table_selection_changed(tab)
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def populate(
        self,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        current_material: Material,
        current_core: Core,
        current_wire: Wire,
    ) -> None:
        """Populate (or refresh) the three candidate tables.

        Performance contract: a same-material core/wire pick must NOT
        trigger a full rebuild — the user is browsing the ranked list
        and a rebuild would scroll them back to the top mid-click.
        We compute a "rebuild key" from the inputs that genuinely
        affect the row set; when it matches the previous call we just
        refresh the cached current-selection state and return.
        """
        rebuild_key = self._compute_rebuild_key(
            spec, materials, cores, wires, current_material,
        )

        # Always cache the current selection so ``_on_table_selection_changed``
        # has fresh comparison data, regardless of whether we rebuild.
        self._spec = spec
        self._materials = materials
        self._cores = cores
        self._wires = wires
        self._current_material = current_material
        self._current_core = current_core
        self._current_wire = current_wire

        if rebuild_key == self._last_rebuild_key:
            # Candidate set unchanged — no need to re-rank or re-render.
            # The user keeps their scroll position and (if any) selected
            # row, exactly what they want when picking the next core.
            return

        self._is_populating = True
        try:
            # Material tab
            m_rows: list[tuple[object, list[str], float]] = []
            for m, s in rank_materials(spec, materials):
                m_rows.append((m, [
                    f"{m.name} ({m.vendor})",
                    f"{m.mu_initial:.0f}",
                    f"{m.Bsat_25C_T:.2f}",
                ], s))
            self.tab_material.set_rows(
                m_rows, preserve_id=current_material.id,
            )

            # Core tab
            c_rows: list[tuple[object, list[str], float]] = []
            for c, s in rank_cores(spec, cores, current_material, current_wire):
                c_rows.append((c, [
                    c.part_number or c.id,
                    c.vendor,
                    f"{c.Ve_mm3 / 1000:.1f}",
                ], s))
            self.tab_core.set_rows(c_rows, preserve_id=current_core.id)

            # Wire tab
            w_rows: list[tuple[object, list[str], float]] = []
            for w, s in rank_wires(spec, current_core, wires, current_material):
                label = (w.id if w.type != "round"
                         else (f"AWG {w.awg}" if w.awg else w.id))
                w_rows.append((w, [
                    label,
                    w.type,
                    f"{w.A_cu_mm2:.3f}",
                ], s))
            self.tab_wire.set_rows(w_rows, preserve_id=current_wire.id)

            self._last_rebuild_key = rebuild_key
        finally:
            self._is_populating = False

    def _compute_rebuild_key(
        self, spec: Spec, materials: list[Material], cores: list[Core],
        wires: list[Wire], current_material: Material,
    ) -> tuple:
        """Fingerprint the inputs that affect the rendered row set.

        Includes:

        - ``spec.canonical_hash()`` — captures every field of the Spec
          (topology, fsw, Pout, Vin, Ku/Bsat margins). A spec edit
          re-ranks because scoring is spec-dependent.
        - Catalog identities (length + first/last id) — cheap proxy
          for "did the catalog reload?" without hashing 10 k entries.
        - ``current_material.id`` — drives the cores' compatibility
          ranking, so a material change DOES need a rebuild.

        Notably absent: ``current_core.id`` and ``current_wire.id``.
        Those don't affect the ranked rows themselves, only the
        "what's selected" state — which set_rows already preserves.
        """
        try:
            spec_hash = spec.canonical_hash()
        except Exception:
            # Pre-cascade Spec snapshots had no canonical_hash; degrade
            # to repr fingerprint so the cache still works on those.
            spec_hash = repr(sorted(spec.model_dump().items()))

        def _id_fingerprint(items: list) -> tuple:
            if not items:
                return (0, "", "")
            return (
                len(items),
                getattr(items[0], "id", ""),
                getattr(items[-1], "id", ""),
            )

        return (
            spec_hash,
            _id_fingerprint(materials),
            _id_fingerprint(cores),
            _id_fingerprint(wires),
            current_material.id,
        )

    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        # Update only the "current selection" — full re-rank can be
        # triggered explicitly via populate().
        self._current_material = material
        self._current_core = core
        self._current_wire = wire

    def clear(self) -> None:
        for tab in (self.tab_material, self.tab_core, self.tab_wire):
            tab.set_rows([])
        # Drop the rebuild cache so the next ``populate()`` after a
        # ``clear()`` always re-renders (otherwise the user would see
        # stale empty tabs even after a fresh recalc).
        self._last_rebuild_key = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _on_table_selection_changed(self, changed_tab: _CandidateTab) -> None:
        if self._is_populating or not self._spec:
            return

        prospective_mat, prospective_core, prospective_wire = self._prospective_selection()

        # If the user selected a new material, re-rank the other two
        # tables immediately without triggering a full recompute.
        if changed_tab is self.tab_material:
            if prospective_mat and prospective_mat != self._current_material:
                # 1. Filter cores compatible with the new material.
                compatible_cores = [
                    c for c in self._cores
                    if c.default_material_id == prospective_mat.id
                ]
                # Fallback: if no cores are explicitly compatible, show all.
                if not compatible_cores:
                    compatible_cores = self._cores

                # 2. Re-rank the compatible cores.
                c_rows: list[tuple[object, list[str], float]] = []
                for c, s in rank_cores(
                    self._spec, compatible_cores, prospective_mat, self._current_wire
                ):
                    c_rows.append((c, [c.part_number or c.id, c.vendor, f"{c.Ve_mm3 / 1000:.1f}"], s))
                self.tab_core.set_rows(c_rows)

                # 3. Re-rank wires (less critical, but good to keep consistent).
                w_rows: list[tuple[object, list[str], float]] = []
                for w, s in rank_wires(
                    self._spec, self._current_core, self._wires, prospective_mat
                ):
                    label = (w.id if w.type != "round" else (f"AWG {w.awg}" if w.awg else w.id))
                    w_rows.append((w, [label, w.type, f"{w.A_cu_mm2:.3f}"], s))
                self.tab_wire.set_rows(w_rows)
            return

        # For core or wire changes, trigger a full recompute.
        has_changed = (
            (prospective_mat and prospective_mat != self._current_material)
            or (prospective_core and prospective_core != self._current_core)
            or (prospective_wire and prospective_wire != self._current_wire)
        )
        if has_changed:
            # Ensure we have a valid selection before emitting.
            if not all((prospective_mat, prospective_core, prospective_wire)):
                return
            self.selection_applied.emit(
                prospective_mat.id,
                prospective_core.id,
                prospective_wire.id,
            )

    def _prospective_selection(self) -> tuple[Material | None, Core | None, Wire | None]:
        mat = self.tab_material.selected_candidate()
        crc = self.tab_core.selected_candidate()
        wir = self.tab_wire.selected_candidate()
        return (
            mat if isinstance(mat, Material) else self._current_material,
            crc if isinstance(crc, Core) else self._current_core,
            wir if isinstance(wir, Wire) else self._current_wire,
        )

    def _prospective_ids(self) -> tuple[str, str, str]:
        mat, crc, wir = self._prospective_selection()
        return (
            mat.id if mat else "",
            crc.id if crc else "",
            wir.id if wir else "",
        )


# Lightweight QLabel re-import alias keeps the file's primary widget
# names obvious — avoids a top-of-file QLabel symbol clash with the
# transitive Card → ScorePill (also a QLabel).
def QLabel_(text: str = ""):
    from PySide6.QtWidgets import QLabel
    lbl = QLabel(text)
    lbl.setProperty("role", "muted")
    return lbl


# ---------------------------------------------------------------------------
# Card wrapper
# ---------------------------------------------------------------------------

class NucleoCard(Card):
    """Public façade: forwards :meth:`update_from_design` and the
    :attr:`selection_applied` signal."""

    selection_applied = Signal(str, str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _NucleoBody()
        super().__init__("Seleção de Núcleo", body, parent=parent)
        self._nbody = body
        body.selection_applied.connect(self.selection_applied.emit)

    def populate(self, *args, **kwargs) -> None:
        self._nbody.populate(*args, **kwargs)

    def update_from_design(self, *args, **kwargs) -> None:
        self._nbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._nbody.clear()
