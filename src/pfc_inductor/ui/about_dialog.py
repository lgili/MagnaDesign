"""About dialog — surfaces project pitch and competitive differentials.

Reads from `pfc_inductor.positioning` so the in-app view never drifts
from the docs source of truth.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor import __version__
from pfc_inductor.positioning import (
    COMPETITORS,
    DIFFERENTIALS,
    PITCH,
    coverage_label,
)


class AboutDialog(QDialog):
    """Modal dialog with pitch + 7 differentials × N competitors matrix."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("About MagnaDesign")
        self.resize(960, 620)

        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_matrix(), 1)
        outer.addWidget(self._build_competitors())
        outer.addLayout(self._build_buttons())

    def _build_header(self) -> QGroupBox:
        box = QGroupBox()
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 8, 12, 12)
        v.setSpacing(6)

        title = QLabel("MagnaDesign")
        title.setProperty("role", "title")
        v.addWidget(title)

        tagline = QLabel("Topology-aware desktop suite for inductor design")
        tagline.setProperty("role", "muted")
        v.addWidget(tagline)

        sub = QLabel(f"version {__version__}")
        sub.setProperty("role", "muted")
        v.addWidget(sub)

        pitch = QLabel(PITCH)
        pitch.setWordWrap(True)
        v.addWidget(pitch)
        return box

    def _build_matrix(self) -> QGroupBox:
        box = QGroupBox("DIFFERENTIATORS vs. ALTERNATIVES")
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 12, 8, 8)

        legend = QLabel("✓ has · ≈ partial · ✗ missing · — not applicable")
        legend.setProperty("role", "muted")
        v.addWidget(legend)

        n_competitors = len(COMPETITORS)
        # Columns: differentiator title + "Us" + each competitor short name
        headers = ["Differentiator", "Us"] + [c.short for c in COMPETITORS]
        tbl = QTableWidget(len(DIFFERENTIALS), 1 + 1 + n_competitors)
        tbl.setHorizontalHeaderLabels(headers)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        tbl.verticalHeader().setVisible(False)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFamily("Menlo")

        for i, diff in enumerate(DIFFERENTIALS):
            # Title cell with blurb as tooltip
            title_item = QTableWidgetItem(diff.title)
            title_item.setToolTip(diff.blurb)
            tbl.setItem(i, 0, title_item)

            us_item = QTableWidgetItem("✓")
            us_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            us_item.setForeground(Qt.GlobalColor.darkGreen)
            us_item.setFont(mono)
            tbl.setItem(i, 1, us_item)

            for j, comp in enumerate(COMPETITORS):
                cov = diff.coverage.get(comp.id, "na")
                lbl = coverage_label(cov)
                cell = QTableWidgetItem(lbl)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setFont(mono)
                if cov == "yes":
                    cell.setForeground(Qt.GlobalColor.darkGreen)
                elif cov == "partial":
                    cell.setForeground(Qt.GlobalColor.darkYellow)
                elif cov == "no":
                    cell.setForeground(Qt.GlobalColor.darkRed)
                cell.setToolTip(f"{comp.name} — {cov}")
                tbl.setItem(i, 2 + j, cell)

        tbl.resizeRowsToContents()
        v.addWidget(tbl, 1)
        return box

    def _build_competitors(self) -> QGroupBox:
        box = QGroupBox("LINKS TO COMPARED PROJECTS")
        h = QHBoxLayout(box)
        h.setContentsMargins(8, 12, 8, 8)
        h.setSpacing(6)
        for c in COMPETITORS:
            btn = QPushButton(c.short)
            btn.setToolTip(f"{c.name} — {c.note}\n{c.url}")
            btn.setProperty("ghost", "true")
            url = c.url
            btn.clicked.connect(lambda _checked=False, u=url:
                                QDesktopServices.openUrl(QUrl(u)))
            h.addWidget(btn)
        h.addStretch(1)
        return box

    def _build_buttons(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addStretch(1)
        btn_docs = QPushButton("Open docs/POSITIONING.md")
        btn_docs.clicked.connect(self._open_positioning_doc)
        h.addWidget(btn_docs)
        btn_close = QPushButton("Close")
        btn_close.setProperty("primary", "true")
        btn_close.clicked.connect(self.accept)
        h.addWidget(btn_close)
        return h

    def _open_positioning_doc(self):
        """Open the local POSITIONING.md in the default app."""
        from pathlib import Path
        # Walk up from this file: src/pfc_inductor/ui/about_dialog.py → repo root
        here = Path(__file__).resolve()
        repo_root = here.parents[3]
        doc_path = repo_root / "docs" / "POSITIONING.md"
        if doc_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(doc_path)))
        else:
            # Fall back to the GitHub URL once we publish.
            pass
