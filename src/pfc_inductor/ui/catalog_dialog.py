"""Dialog for refreshing the OpenMagnetics MAS catalog.

Runs ``scripts/import_mas_catalog.py`` (the ``run_import`` function) on a
``QThread`` so a 5–10 s import doesn't block the UI. Emits a summary so
the caller can reload the in-memory database when it's done.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

# The import script is intentionally outside the package so it can run as
# a standalone CLI; we add it to sys.path here only when needed.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class _ImportWorker(QObject):
    finished = Signal(int, str)   # exit_code, captured stdout
    progress = Signal(str)        # streaming log line

    def __init__(self, source_dir: Path):
        super().__init__()
        self._source = source_dir

    def run(self) -> None:
        import io
        import sys

        scripts_dir = _REPO_ROOT / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))

        try:
            import import_mas_catalog  # type: ignore[import-not-found]
        except Exception as e:
            self.finished.emit(2, f"Failed to load importer: {e}")
            return

        # Tee stdout so the user sees the merge summary in the dialog.
        buf = io.StringIO()
        original_stdout = sys.stdout

        class _Tee:
            def write(self_inner, s):
                buf.write(s)
                if s.strip():
                    self.progress.emit(s.rstrip("\n"))
                original_stdout.write(s)

            def flush(self_inner):
                original_stdout.flush()

        sys.stdout = _Tee()  # type: ignore[assignment,arg-type]
        try:
            code = import_mas_catalog.run_import(self._source, dry_run=False)
        except Exception as e:
            self.finished.emit(2, f"Importer crashed: {e}")
            return
        finally:
            sys.stdout = original_stdout

        self.finished.emit(int(code), buf.getvalue())


class CatalogUpdateDialog(QDialog):
    """Run the catalog importer and report the merge counts."""

    completed = Signal()  # caller should reload the in-memory db

    def __init__(
        self, source_dir: Optional[Path] = None, parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Update component catalog")
        self.resize(640, 420)
        self._source = source_dir or _REPO_ROOT / "vendor" / "openmagnetics-catalog"
        self._thread: Optional[QThread] = None

        v = QVBoxLayout(self)

        intro = QLabel(
            "<b>OpenMagnetics MAS catalog</b><br>"
            "Imports materials and wires from the OpenMagnetics catalog into "
            "your local library. Does not replace curated data or your edits."
        )
        intro.setWordWrap(True)
        v.addWidget(intro)

        self.lbl_source = QLabel(f"<i>Source:</i> {self._source}")
        self.lbl_source.setWordWrap(True)
        self.lbl_source.setProperty("role", "muted")
        v.addWidget(self.lbl_source)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.hide()
        v.addWidget(self.progress)

        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(500)
        v.addWidget(self.txt_log, 1)

        self.lbl_result = QLabel("")
        self.lbl_result.setWordWrap(True)
        v.addWidget(self.lbl_result)

        h = QHBoxLayout()
        h.addStretch(1)
        self.btn_run = QPushButton("Update catalog")
        self.btn_run.clicked.connect(self._run)
        h.addWidget(self.btn_run)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        h.addWidget(self.btn_close)
        v.addLayout(h)

    def _run(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        if not self._source.exists():
            self.lbl_result.setText(
                f"<span style='color:#a01818'>Directory does not exist: "
                f"{self._source}</span>"
            )
            return
        self.btn_run.setEnabled(False)
        self.progress.show()
        self.txt_log.clear()
        self.txt_log.appendPlainText(f"Importing from: {self._source}")

        self._worker = _ImportWorker(self._source)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.txt_log.appendPlainText)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_finished(self, code: int, captured: str) -> None:
        self.progress.hide()
        self.btn_run.setEnabled(True)
        if code != 0:
            self.lbl_result.setText(
                f"<span style='color:#a01818'>Failed (code {code}). "
                f"See the log above.</span>"
            )
            return
        self.lbl_result.setText(
            "<span style='color:#1c7c3b'>"
            "Catalog updated. The new items already appear in the lists."
            "</span>"
        )
        self.completed.emit()
