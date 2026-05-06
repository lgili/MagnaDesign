"""Modal dialog that runs the FEA dependency installer.

Opens automatically on first launch when ONELAB is missing, and is also
reachable from the toolbar action **"Reinstalar dependências FEA"**.

The setup runs in a worker thread so the UI stays responsive — a 50 MB
download over a slow link can take a couple of minutes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.setup_deps import (
    SetupReport,
    check_fea_setup,
    setup_fea,
)

_OK = "#1c7c3b"
_BAD = "#a01818"
_WARN = "#a06700"


class _SetupWorker(QObject):
    progress = Signal(str, float)
    finished = Signal(object)   # SetupReport
    failed = Signal(str)

    def __init__(self, onelab_dir: Optional[Path]):
        super().__init__()
        self._onelab_dir = onelab_dir

    def run(self) -> None:
        def cb(msg: str, frac: float) -> None:
            self.progress.emit(msg, max(0.0, min(1.0, frac)))
        try:
            report = setup_fea(
                onelab_dir=self._onelab_dir, on_progress=cb,
            )
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
            return
        self.finished.emit(report)


class SetupDepsDialog(QDialog):
    """Walks the user through installing ONELAB + configuring FEMMT."""

    completed = Signal(bool)   # True when fea_ready after the run

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Instalar dependências FEA")
        self.resize(720, 520)
        self._thread: Optional[QThread] = None

        v = QVBoxLayout(self)

        self.lbl_intro = QLabel(
            "<b>Instalação automática do backend FEA</b><br>"
            "Vamos baixar o ONELAB (~50 MB), assinar os binários se for "
            "macOS, escrever o <code>config.json</code> da FEMMT e "
            "verificar tudo no final. É idempotente — pode rodar de novo "
            "se algo der errado."
        )
        self.lbl_intro.setWordWrap(True)
        v.addWidget(self.lbl_intro)

        self.lst_steps = QListWidget()
        v.addWidget(self.lst_steps)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        v.addWidget(self.progress)

        self.lbl_progress = QLabel("")
        self.lbl_progress.setProperty("role", "muted")
        v.addWidget(self.lbl_progress)

        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(1000)
        v.addWidget(self.txt_log, 1)

        self.lbl_result = QLabel("")
        self.lbl_result.setWordWrap(True)
        v.addWidget(self.lbl_result)

        h = QHBoxLayout()
        h.addStretch(1)
        self.btn_run = QPushButton("Instalar")
        self.btn_run.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        self.btn_run.clicked.connect(self._run)
        h.addWidget(self.btn_run)
        self.btn_close = QPushButton("Fechar")
        self.btn_close.clicked.connect(self.reject)
        h.addWidget(self.btn_close)
        v.addLayout(h)

        # Pre-populate with the current state so the user can see what's
        # missing before kicking off a download.
        self._refresh_pre_state()

    # ------------------------------------------------------------------
    def _refresh_pre_state(self) -> None:
        v = check_fea_setup()
        self.lst_steps.clear()
        items = [
            ("FEMMT importável", v.femmt_importable,
             (v.femmt_version and f"v{v.femmt_version}") or ""),
            ("ONELAB configurado",
             v.onelab_dir is not None,
             str(v.onelab_dir) if v.onelab_dir else ""),
            ("Binários ONELAB presentes", v.onelab_binaries_present, ""),
        ]
        for name, ok, detail in items:
            self._add_step_item(name, ok, detail)
        if v.fea_ready:
            self.lbl_result.setText(
                f"<span style='color:{_OK}'>● Tudo pronto.</span> "
                "Rodar o instalador é seguro mas opcional."
            )
            self.btn_run.setText("Reinstalar mesmo assim")
        else:
            self.lbl_result.setText(
                f"<span style='color:{_WARN}'>● Faltam itens.</span> "
                "Clique em <b>Instalar</b> para configurar tudo."
            )

    def _add_step_item(self, name: str, ok: bool, detail: str = "") -> None:
        marker = "✓" if ok else "✗"
        color = _OK if ok else _BAD
        text = f"{marker}  {name}" + (f"  —  {detail}" if detail else "")
        item = QListWidgetItem(text)
        item.setForeground(_qcolor(color))
        self.lst_steps.addItem(item)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        self.btn_run.setEnabled(False)
        self.lst_steps.clear()
        self.txt_log.clear()
        self.lbl_result.clear()
        self.progress.setValue(0)
        self.txt_log.appendPlainText("Iniciando setup…")

        self._worker = _SetupWorker(onelab_dir=None)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_progress(self, msg: str, frac: float) -> None:
        self.progress.setValue(int(1000 * frac))
        self.lbl_progress.setText(msg)
        self.txt_log.appendPlainText(msg)

    def _on_failed(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self.txt_log.appendPlainText(f"\nERRO: {msg}")
        self.lbl_result.setText(
            f"<span style='color:{_BAD}'>● Falhou: {msg}</span>"
        )
        self.completed.emit(False)

    def _on_finished(self, report: SetupReport) -> None:
        self.btn_run.setEnabled(True)
        self.progress.setValue(1000)
        self.lst_steps.clear()
        for s in report.steps:
            self._add_step_item(s.name, s.ok, s.detail)
        v = check_fea_setup()
        if v.fea_ready:
            self.lbl_result.setText(
                f"<span style='color:{_OK}'>● Setup concluído.</span> "
                "Pode rodar Validar (FEA) com confiança."
            )
        else:
            self.lbl_result.setText(
                f"<span style='color:{_WARN}'>● Concluído com pendências.</span> "
                + "; ".join(v.notes)
            )
        self.completed.emit(v.fea_ready)


def _qcolor(hex_str: str):
    from PySide6.QtGui import QColor
    return QColor(hex_str)
