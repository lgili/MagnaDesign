"""History panel — git-like timeline of design iterations.

Shows the project's snapshot log on the left (newest first, with
a one-line headline per row) and a diff view on the right that
compares two selected snapshots. Two snapshots can be picked
either:

* Click one row → diff against the immediately-prior snapshot
  (the most common case, "what did this last recalc change?").
* Cmd-click a second row → diff between the two clicked rows
  (for cross-iteration comparisons further apart).

Diff colouring:

* **Green** — change improves the metric (lower loss, lower
  ΔT, higher η, etc., per the rules in
  :mod:`pfc_inductor.history`).
* **Red** — change worsens it.
* **Neutral grey** — non-numeric change (selection swap,
  topology change) where "better" has no canonical direction.
"""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from pfc_inductor.history import (
    HistoryStore, Snapshot, diff_snapshots,
)
from pfc_inductor.ui.theme import get_theme, on_theme_changed


class HistoryPanel(QWidget):
    """Embeddable widget — timeline + diff. Designed for the
    ProjetoPage left rail or its own modal."""

    # Emitted when the user clicks "Restore this snapshot" — host
    # is responsible for rebuilding the spec from the snapshot.
    restore_requested = Signal(object)  # Snapshot

    def __init__(
        self,
        store: HistoryStore,
        project: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._project = project
        self._snapshots: list[Snapshot] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header ──
        head = QFrame()
        h = QHBoxLayout(head)
        h.setContentsMargins(12, 8, 12, 8)
        self._title = QLabel("Project history")
        self._title.setStyleSheet("font-weight: 700;")
        h.addWidget(self._title)
        h.addStretch(1)
        self._btn_refresh = QPushButton("⟳")
        self._btn_refresh.setFixedWidth(32)
        self._btn_refresh.setToolTip("Refresh from disk")
        self._btn_refresh.setAutoDefault(False)
        self._btn_refresh.clicked.connect(self.reload)
        h.addWidget(self._btn_refresh)
        outer.addWidget(head)

        # ── Splitter: timeline | diff ──
        split = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(split, 1)

        # Timeline list — newest first.
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        split.addWidget(self._list)

        # Diff pane — vertical scroll of rows.
        diff_holder = QWidget()
        dv = QVBoxLayout(diff_holder)
        dv.setContentsMargins(8, 8, 8, 8)
        dv.setSpacing(4)
        self._diff_header = QLabel(
            "Click a snapshot in the timeline to diff against the "
            "previous one."
        )
        self._diff_header.setWordWrap(True)
        self._diff_header.setStyleSheet(
            f"color: {get_theme().palette.text_muted}; padding: 4px 0;"
        )
        dv.addWidget(self._diff_header)
        self._diff_rows = QFrame()
        self._diff_rows_layout = QVBoxLayout(self._diff_rows)
        self._diff_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._diff_rows_layout.setSpacing(2)
        dv.addWidget(self._diff_rows, 1)
        split.addWidget(diff_holder)

        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)

        # ── Footer with Restore button ──
        foot = QFrame()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(12, 8, 12, 8)
        fl.addStretch(1)
        self._btn_restore = QPushButton("Restore this snapshot")
        self._btn_restore.setEnabled(False)
        self._btn_restore.setAutoDefault(False)
        self._btn_restore.clicked.connect(self._on_restore_clicked)
        fl.addWidget(self._btn_restore)
        outer.addWidget(foot)

        on_theme_changed(self._refresh_qss)
        self._refresh_qss()
        self.reload()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_project(self, project: str) -> None:
        if project == self._project:
            return
        self._project = project
        self.reload()

    def reload(self) -> None:
        """Re-fetch snapshots from the store."""
        try:
            self._snapshots = self._store.list_snapshots(
                project=self._project or None, limit=200,
            )
        except Exception:
            self._snapshots = []
        self._list.clear()
        for snap in self._snapshots:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S",
                                  time.localtime(snap.ts))
            item = QListWidgetItem(f"{stamp}\n{snap.headline}")
            item.setData(Qt.ItemDataRole.UserRole, snap.id)
            self._list.addItem(item)
        # Auto-select the newest so the diff pane fills.
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    # ------------------------------------------------------------------
    # Selection / diff
    # ------------------------------------------------------------------
    def _on_selection_changed(self) -> None:
        items = self._list.selectedItems()
        if not items:
            self._render_diff(None, None)
            self._btn_restore.setEnabled(False)
            return
        ids = [it.data(Qt.ItemDataRole.UserRole) for it in items]
        snaps = [s for s in self._snapshots if s.id in ids]
        snaps.sort(key=lambda s: s.ts)  # older first

        if len(snaps) == 1:
            # Compare against the immediately previous snapshot
            # in the same project. If this is the very first
            # snapshot, show a "no prior" message.
            current = snaps[0]
            idx = next(
                (i for i, s in enumerate(self._snapshots)
                 if s.id == current.id),
                None,
            )
            prior = (
                self._snapshots[idx + 1] if idx is not None
                and idx + 1 < len(self._snapshots) else None
            )
            self._render_diff(prior, current)
        elif len(snaps) >= 2:
            # Compare the oldest and newest of the selection.
            self._render_diff(snaps[0], snaps[-1])
        self._btn_restore.setEnabled(len(items) == 1)

    def _on_restore_clicked(self) -> None:
        items = self._list.selectedItems()
        if len(items) != 1:
            return
        sid = items[0].data(Qt.ItemDataRole.UserRole)
        snap = next((s for s in self._snapshots if s.id == sid), None)
        if snap is not None:
            self.restore_requested.emit(snap)

    # ------------------------------------------------------------------
    # Render diff rows
    # ------------------------------------------------------------------
    def _render_diff(
        self, before: Optional[Snapshot], after: Optional[Snapshot],
    ) -> None:
        # Wipe prior rows.
        while self._diff_rows_layout.count():
            it = self._diff_rows_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        if after is None:
            self._diff_header.setText("No snapshot selected.")
            return
        if before is None:
            stamp = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(after.ts)
            )
            self._diff_header.setText(
                f"<b>{stamp}</b> — first snapshot of this project. "
                f"Nothing to diff against yet."
            )
            return

        ts_a = time.strftime("%H:%M:%S", time.localtime(before.ts))
        ts_b = time.strftime("%H:%M:%S", time.localtime(after.ts))
        self._diff_header.setText(
            f"<b>{ts_a}</b> → <b>{ts_b}</b>  "
            f"<span style='color:{get_theme().palette.text_muted}'>"
            f"({len(diff_snapshots(before, after))} field(s) changed)"
            "</span>"
        )

        # Group rows by section (spec / selection / summary).
        diffs = diff_snapshots(before, after)
        if not diffs:
            self._diff_rows_layout.addWidget(
                _MutedLabel("No changes between these snapshots.")
            )
            return

        last_section = None
        for d in diffs:
            section = d.path.split(".")[0]
            if section != last_section:
                lbl = QLabel(section.upper())
                p = get_theme().palette
                lbl.setStyleSheet(
                    f"color: {p.text_muted}; "
                    f"font-size: 9px; font-weight: 700; "
                    f"letter-spacing: 0.5px; "
                    f"padding: 8px 0 2px 0;"
                )
                self._diff_rows_layout.addWidget(lbl)
                last_section = section
            self._diff_rows_layout.addWidget(_DiffRow(d))

    # ------------------------------------------------------------------
    def _refresh_qss(self) -> None:
        p = get_theme().palette
        self.setStyleSheet(
            f"QListWidget {{ background: {p.surface}; "
            f"               border: 1px solid {p.border}; }}"
            f"QListWidget::item:alternate {{ "
            f"               background: {p.surface_elevated}; }}"
            f"QListWidget::item:selected {{ "
            f"               background: {p.accent_violet}; "
            f"               color: white; }}"
        )


class _DiffRow(QFrame):
    """One key-value pair: ``key  before → after  Δ delta``."""

    def __init__(self, d, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        p = get_theme().palette
        if d.is_better is True:
            color = p.success
            mark = "✓"
        elif d.is_better is False:
            color = p.danger
            mark = "✗"
        else:
            color = p.text_muted
            mark = "•"
        h = QHBoxLayout(self)
        h.setContentsMargins(4, 2, 4, 2)
        h.setSpacing(8)
        sign = QLabel(mark)
        sign.setStyleSheet(
            f"color: {color}; font-weight: 700; min-width: 14px;"
        )
        h.addWidget(sign)
        # Strip the section prefix from the key for compactness.
        bare = d.path.split(".", 1)[1] if "." in d.path else d.path
        key = QLabel(bare)
        key.setStyleSheet(
            f"color: {p.text}; font-family: monospace; min-width: 160px;"
        )
        h.addWidget(key)
        before_label = _format(d.before)
        after_label = _format(d.after)
        bf = QLabel(f"{before_label}  →  <b>{after_label}</b>")
        bf.setStyleSheet(f"color: {p.text}; font-family: monospace;")
        h.addWidget(bf, 1)
        if d.delta_pct is not None:
            delta_str = (f"{d.delta:+.3g}" if d.delta is not None else "")
            tail = QLabel(f"{delta_str} ({d.delta_pct:+.1f} %)")
            tail.setStyleSheet(f"color: {color}; font-weight: 600;")
            h.addWidget(tail)


class _MutedLabel(QLabel):
    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        p = get_theme().palette
        self.setStyleSheet(f"color: {p.text_muted}; padding: 12px;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)


def _format(v) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    if v is None:
        return "—"
    return str(v)
