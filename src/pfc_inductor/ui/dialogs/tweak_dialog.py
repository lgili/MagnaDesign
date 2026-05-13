"""Tweak dialog — "Ajustar protótipo".

Opens from the result panel's "Ajustar" button. Lets the engineer
type the physical numbers from the bench prototype (a couple more
turns than the solver picked, a warmer ambient for a summer
worst-case) and recompute the design against those instead of the
ones the solver chose.

The dialog is purely presentational over a :class:`DesignOverrides`
value — it does not call the engine itself. The host (MainWindow)
reads ``overrides()`` on accept and triggers the recalc through its
standard ``_on_calculate`` path with the overrides applied.
"""

from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, DesignOverrides, Wire


class TweakDialog(QDialog):
    """Modal dialog to capture :class:`DesignOverrides` from the user.

    Each field carries an "Apply" checkbox: unchecked = ``None`` (use
    the calculated baseline); checked = the spin-box value wins. The
    layout deliberately puts the baseline value next to each field
    so the engineer reads "calculated 28 → I'll wind 30" without
    flipping back to the result panel.
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        baseline_N: int,
        baseline_T_amb_C: float,
        baseline_gap_mm: float = 0.0,
        current: Optional[DesignOverrides] = None,
        # Optional catalogs for wire/core swap selectors. When None,
        # the rows are skipped — keeps the dialog usable in legacy
        # callers that don't have catalog handles ready.
        wires: Optional[Sequence[Wire]] = None,
        cores: Optional[Sequence[Core]] = None,
        baseline_wire_id: str = "",
        baseline_core_id: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ajustar protótipo")
        self.setModal(True)
        self.setMinimumWidth(460)

        self._baseline_N = int(baseline_N)
        self._baseline_T_amb_C = float(baseline_T_amb_C)
        self._baseline_gap_mm = float(baseline_gap_mm)
        self._wires = list(wires) if wires else []
        self._cores = list(cores) if cores else []
        self._baseline_wire_id = str(baseline_wire_id)
        self._baseline_core_id = str(baseline_core_id)

        outer = QVBoxLayout(self)
        outer.setSpacing(10)
        outer.setContentsMargins(16, 14, 16, 14)

        intro = QLabel(
            "Aplique ajustes manuais de protótipo sobre o design calculado. "
            "Campos não marcados usam o valor do solver."
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "muted")
        outer.addWidget(intro)

        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        # ---- N (turns) -------------------------------------------
        self.cb_N = QCheckBox()
        self.sp_N = QSpinBox()
        self.sp_N.setRange(1, 2000)
        self.sp_N.setValue(self._baseline_N)
        self.sp_N.setSuffix(" voltas")
        self.lbl_N_calc = QLabel(f"calculado: {self._baseline_N}")
        self.lbl_N_calc.setProperty("role", "muted")
        form.addRow(self.cb_N, self._row("Voltas N", self.sp_N, self.lbl_N_calc))

        # ---- T_amb -----------------------------------------------
        self.cb_T = QCheckBox()
        self.sp_T = QDoubleSpinBox()
        self.sp_T.setRange(-40.0, 150.0)
        self.sp_T.setDecimals(1)
        self.sp_T.setSingleStep(1.0)
        self.sp_T.setSuffix(" °C")
        self.sp_T.setValue(self._baseline_T_amb_C)
        self.lbl_T_calc = QLabel(f"spec: {self._baseline_T_amb_C:.1f} °C")
        self.lbl_T_calc.setProperty("role", "muted")
        form.addRow(self.cb_T, self._row("T ambiente", self.sp_T, self.lbl_T_calc))

        # ---- n_stacks (cores empilhados) -------------------------
        self.cb_S = QCheckBox()
        self.sp_S = QSpinBox()
        self.sp_S.setRange(1, 8)
        self.sp_S.setValue(1)
        self.sp_S.setSuffix("×")
        self.lbl_S_calc = QLabel("padrão: 1× (núcleo único)")
        self.lbl_S_calc.setProperty("role", "muted")
        self.lbl_S_calc.setToolTip(
            "Empilhar núcleos físicos lado a lado. 2× dobra Ae/Ve, "
            "MLT cresce ~2·HT por unidade extra."
        )
        form.addRow(self.cb_S, self._row("Cores empilhados", self.sp_S, self.lbl_S_calc))

        # ---- gap (mm) -----------------------------------------------
        self.cb_G = QCheckBox()
        self.sp_G = QDoubleSpinBox()
        self.sp_G.setRange(0.0, 20.0)
        self.sp_G.setDecimals(2)
        self.sp_G.setSingleStep(0.05)
        self.sp_G.setSuffix(" mm")
        self.sp_G.setValue(max(self._baseline_gap_mm, 0.10))
        baseline_label = (
            f"calculado: {self._baseline_gap_mm:.2f} mm"
            if self._baseline_gap_mm > 0
            else "calculado: (sem gap — núcleo de pó)"
        )
        self.lbl_G_calc = QLabel(baseline_label)
        self.lbl_G_calc.setProperty("role", "muted")
        self.lbl_G_calc.setToolTip(
            "Entreferro físico. Em ferrites, define a indutância e a "
            "margem de saturação. Ignorado em núcleos de pó (gap "
            "distribuído já está no AL do catálogo)."
        )
        form.addRow(self.cb_G, self._row("Entreferro", self.sp_G, self.lbl_G_calc))

        # ---- Wire swap ----------------------------------------------
        # Optional — only emitted when the caller passes a wires
        # catalog. The combo shows every catalog wire with a compact
        # "id — type/AWG" label so the engineer can pick the wire they
        # actually had in stock.
        self.cb_W = QCheckBox()
        self.cmb_W = QComboBox()
        self.cmb_W.setEditable(False)
        self.cmb_W.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.cmb_W.setMaxVisibleItems(15)
        if self._wires:
            for w in self._wires:
                self.cmb_W.addItem(_wire_label(w), w.id)
            self._select_combo_id(self.cmb_W, self._baseline_wire_id)
            self.lbl_W_calc = QLabel("(do projeto)")
        else:
            self.cmb_W.addItem("(catálogo indisponível)", "")
            self.lbl_W_calc = QLabel("")
            self.cb_W.setEnabled(False)
        self.lbl_W_calc.setProperty("role", "muted")
        self.lbl_W_calc.setToolTip(
            "Substituir o fio escolhido pelo solver pelo fio que você "
            "tem em estoque. Útil pra revalidar o projeto contra um "
            "AWG diferente sem mudar o spec."
        )
        form.addRow(self.cb_W, self._row("Fio", self.cmb_W, self.lbl_W_calc))

        # ---- Core swap ----------------------------------------------
        self.cb_C = QCheckBox()
        self.cmb_C = QComboBox()
        self.cmb_C.setEditable(False)
        self.cmb_C.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.cmb_C.setMaxVisibleItems(15)
        if self._cores:
            for c in self._cores:
                self.cmb_C.addItem(_core_label(c), c.id)
            self._select_combo_id(self.cmb_C, self._baseline_core_id)
            self.lbl_C_calc = QLabel("(do projeto)")
        else:
            self.cmb_C.addItem("(catálogo indisponível)", "")
            self.lbl_C_calc = QLabel("")
            self.cb_C.setEnabled(False)
        self.lbl_C_calc.setProperty("role", "muted")
        self.lbl_C_calc.setToolTip(
            "Trocar o núcleo magnético sem refazer o sweep. Útil pra "
            "comparar o mesmo bobinamento em cores próximos do catálogo."
        )
        form.addRow(self.cb_C, self._row("Núcleo", self.cmb_C, self.lbl_C_calc))

        outer.addLayout(form)

        # Disable spin boxes until the checkbox is ticked — keeps
        # the "I haven't decided to override this" state visible.
        self.cb_N.toggled.connect(self.sp_N.setEnabled)
        self.cb_T.toggled.connect(self.sp_T.setEnabled)
        self.cb_S.toggled.connect(self.sp_S.setEnabled)
        self.cb_G.toggled.connect(self.sp_G.setEnabled)
        self.cb_W.toggled.connect(self.cmb_W.setEnabled)
        self.cb_C.toggled.connect(self.cmb_C.setEnabled)
        self.sp_N.setEnabled(False)
        self.sp_T.setEnabled(False)
        self.sp_S.setEnabled(False)
        self.sp_G.setEnabled(False)
        self.cmb_W.setEnabled(False)
        self.cmb_C.setEnabled(False)

        # Pre-fill from existing overrides.
        if current is not None:
            if current.N_turns is not None:
                self.cb_N.setChecked(True)
                self.sp_N.setValue(int(current.N_turns))
            if current.T_amb_C is not None:
                self.cb_T.setChecked(True)
                self.sp_T.setValue(float(current.T_amb_C))
            if current.n_stacks is not None and current.n_stacks > 1:
                self.cb_S.setChecked(True)
                self.sp_S.setValue(int(current.n_stacks))
            if current.gap_mm is not None:
                self.cb_G.setChecked(True)
                self.sp_G.setValue(float(current.gap_mm))
            if current.wire_id is not None and self._wires:
                self.cb_W.setChecked(True)
                self._select_combo_id(self.cmb_W, current.wire_id)
            if current.core_id is not None and self._cores:
                self.cb_C.setChecked(True)
                self._select_combo_id(self.cmb_C, current.core_id)

        # ---- Buttons --------------------------------------------
        self.btn_reset = QPushButton("Resetar ajuste")
        self.btn_reset.clicked.connect(self._clear)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Aplicar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_reset)
        btn_row.addStretch(1)
        btn_row.addWidget(bb)
        outer.addLayout(btn_row)

    @staticmethod
    def _row(label: str, widget: QWidget, hint: QLabel) -> QWidget:
        """Pack a label + spinbox + grey hint label into one row."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        lbl = QLabel(label)
        lbl.setMinimumWidth(90)
        h.addWidget(lbl)
        h.addWidget(widget, 1)
        h.addWidget(hint)
        h.setAlignment(hint, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return w

    def _clear(self) -> None:
        """Reset to "no overrides" state — every checkbox off,
        spin boxes / combos back to baseline."""
        self.cb_N.setChecked(False)
        self.cb_T.setChecked(False)
        self.cb_S.setChecked(False)
        self.cb_G.setChecked(False)
        self.cb_W.setChecked(False)
        self.cb_C.setChecked(False)
        self.sp_N.setValue(self._baseline_N)
        self.sp_T.setValue(self._baseline_T_amb_C)
        self.sp_S.setValue(1)
        self.sp_G.setValue(max(self._baseline_gap_mm, 0.10))
        if self._wires:
            self._select_combo_id(self.cmb_W, self._baseline_wire_id)
        if self._cores:
            self._select_combo_id(self.cmb_C, self._baseline_core_id)

    def overrides(self) -> DesignOverrides:
        """Read the dialog state back into a :class:`DesignOverrides`."""
        wire_id = None
        if self.cb_W.isChecked() and self._wires:
            data = self.cmb_W.currentData()
            wire_id = str(data) if data else None
        core_id = None
        if self.cb_C.isChecked() and self._cores:
            data = self.cmb_C.currentData()
            core_id = str(data) if data else None
        return DesignOverrides(
            N_turns=int(self.sp_N.value()) if self.cb_N.isChecked() else None,
            T_amb_C=float(self.sp_T.value()) if self.cb_T.isChecked() else None,
            n_stacks=int(self.sp_S.value()) if self.cb_S.isChecked() else None,
            gap_mm=float(self.sp_G.value()) if self.cb_G.isChecked() else None,
            wire_id=wire_id,
            core_id=core_id,
        )

    # ── Helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _select_combo_id(combo: QComboBox, item_id: str) -> None:
        """Set the combo's current index to whichever entry has the
        matching ``itemData`` id. No-op when the id isn't present —
        leaves the combo on its first item (which is the default
        "do-nothing" entry)."""
        if not item_id:
            return
        idx = combo.findData(item_id)
        if idx >= 0:
            combo.setCurrentIndex(idx)


# ─── Label helpers ───────────────────────────────────────────────────


def _wire_label(w: Wire) -> str:
    """Short, scannable label for a Wire in a combo entry."""
    parts: list[str] = [w.id]
    awg = getattr(w, "awg", None)
    if awg is not None:
        parts.append(f"AWG {awg}")
    d_mm = getattr(w, "diameter_mm", None)
    if d_mm is not None:
        try:
            parts.append(f"⌀{float(d_mm):.2f} mm")
        except (TypeError, ValueError):
            pass
    return " · ".join(parts)


def _core_label(c: Core) -> str:
    """Short, scannable label for a Core in a combo entry."""
    parts: list[str] = [c.id]
    shape = getattr(c, "shape", "")
    if shape:
        parts.append(str(shape))
    Ae = getattr(c, "Ae_mm2", None)
    if Ae is not None:
        try:
            parts.append(f"Ae={float(Ae):.0f}mm²")
        except (TypeError, ValueError):
            pass
    return " · ".join(parts)
