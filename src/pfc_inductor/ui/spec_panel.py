"""Spec input panel: all fields of `Spec` plus core/material/wire selectors."""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QDoubleSpinBox, QComboBox,
    QGroupBox, QVBoxLayout, QPushButton, QHBoxLayout, QCheckBox,
    QCompleter,
)

from pfc_inductor.data_loader import load_curated_ids
from pfc_inductor.models import Spec, Core, Wire, Material


def _make_searchable(combo: QComboBox) -> None:
    """Turn a ``QComboBox`` into an editable, type-to-filter widget.

    The user can type any substring of an item name and the popup will
    show only matching rows. Clicking on one selects it and resolves
    back to the full label, preserving the ``itemData`` (the entry id)
    we store on each row.
    """
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    completer = QCompleter(combo.model(), combo)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    combo.setCompleter(completer)


class SpecPanel(QWidget):
    """Left-side panel: collects spec + selections, emits when changed."""

    changed = Signal()
    calculate_requested = Signal()

    def __init__(
        self,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._materials = materials
        self._cores = cores
        self._wires = wires

        from PySide6.QtWidgets import QLabel, QScrollArea, QFrame
        # Outer fixed: scroll area on top, primary CTA pinned at bottom.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        inner = QWidget()
        scroll.setWidget(inner)

        body = QVBoxLayout(inner)
        body.setContentsMargins(12, 12, 12, 4)
        body.setSpacing(8)

        title = QLabel("Especificação")
        title.setProperty("role", "title")
        body.addWidget(title)

        body.addWidget(self._build_topology_box())
        body.addWidget(self._build_input_box())
        self._converter_box = self._build_converter_box()
        body.addWidget(self._converter_box)
        self._line_reactor_box = self._build_line_reactor_box()
        self._line_reactor_box.setVisible(False)
        body.addWidget(self._line_reactor_box)
        body.addWidget(self._build_thermal_box())
        body.addWidget(self._build_selection_box())
        body.addStretch(1)

        # Primary CTA pinned outside scroll area so it stays visible.
        cta_row = QHBoxLayout()
        cta_row.setContentsMargins(12, 8, 12, 12)
        self.btn_calculate = QPushButton("Calcular")
        self.btn_calculate.setProperty("primary", "true")
        self.btn_calculate.setMinimumHeight(28)
        self.btn_calculate.clicked.connect(self.calculate_requested.emit)
        cta_row.addWidget(self.btn_calculate, 1)
        outer.addLayout(cta_row)

        self._wire_signals()
        self._set_initial_selection()

    def _build_topology_box(self) -> QGroupBox:
        box = QGroupBox("TOPOLOGIA")
        form = QFormLayout(box)
        self.cmb_topology = QComboBox()
        self.cmb_topology.addItem("PFC ativo (boost CCM)", "boost_ccm")
        self.cmb_topology.addItem("Choke passivo de linha", "passive_choke")
        self.cmb_topology.addItem("Reator de linha (50/60 Hz)", "line_reactor")
        self.cmb_topology.currentIndexChanged.connect(self._on_topology_changed)
        form.addRow("Tipo:", self.cmb_topology)
        return box

    def _build_line_reactor_box(self) -> QGroupBox:
        """Hidden by default; visible only when topology = line_reactor."""
        box = QGroupBox("REATOR DE LINHA")
        form = QFormLayout(box)
        self.cmb_phases = QComboBox()
        self.cmb_phases.addItem("Trifásico (3φ)", 3)
        self.cmb_phases.addItem("Monofásico (1φ)", 1)
        self.sp_vline = self._dspin(80, 690, 380.0, 1.0, " Vrms")
        self.sp_irated = self._dspin(0.1, 500, 30.0, 0.5, " A")
        self.sp_pctZ = self._dspin(0.5, 20, 5.0, 0.5, " %")
        form.addRow("Fases:", self.cmb_phases)
        form.addRow("V de linha:", self.sp_vline)
        form.addRow("I nominal (RMS):", self.sp_irated)
        form.addRow("% impedância alvo:", self.sp_pctZ)
        return box

    def _on_topology_changed(self):
        """Show/hide blocks that don't apply to the active topology.

        ``cmb_topology`` is also wired in ``_wire_signals`` to emit
        ``changed``, so we deliberately do *not* emit it again here —
        otherwise the debounce timer in MainWindow gets restarted twice
        per topology pick and the recalc-after-typing-stops semantics
        get fuzzy.
        """
        topo = self.cmb_topology.currentData()
        is_lr = topo == "line_reactor"
        self._line_reactor_box.setVisible(is_lr)
        self._converter_box.setVisible(not is_lr)

    def _build_input_box(self) -> QGroupBox:
        box = QGroupBox("ENTRADA AC")
        form = QFormLayout(box)
        self.sp_vin_min = self._dspin(50, 300, 85.0, 1.0, " Vrms")
        self.sp_vin_max = self._dspin(80, 300, 265.0, 1.0, " Vrms")
        self.sp_vin_nom = self._dspin(50, 300, 220.0, 1.0, " Vrms")
        self.sp_fline = self._dspin(40, 70, 50.0, 1.0, " Hz")
        form.addRow("Vin mín (worst case):", self.sp_vin_min)
        form.addRow("Vin máx:", self.sp_vin_max)
        form.addRow("Vin nominal:", self.sp_vin_nom)
        form.addRow("f rede:", self.sp_fline)
        return box

    def _build_converter_box(self) -> QGroupBox:
        box = QGroupBox("CONVERSOR")
        form = QFormLayout(box)
        self.sp_vout = self._dspin(100, 800, 400.0, 1.0, " V")
        self.sp_pout = self._dspin(50, 5000, 800.0, 10.0, " W")
        self.sp_eta = self._dspin(0.5, 1.0, 0.97, 0.01, "")
        self.sp_fsw = self._dspin(10, 500, 65.0, 1.0, " kHz")
        self.sp_ripple = self._dspin(5, 100, 30.0, 1.0, " %")
        form.addRow("Vout (DC bus):", self.sp_vout)
        form.addRow("Pout:", self.sp_pout)
        form.addRow("Eficiência:", self.sp_eta)
        form.addRow("fsw:", self.sp_fsw)
        form.addRow("Ripple pico-pico:", self.sp_ripple)
        return box

    def _build_thermal_box(self) -> QGroupBox:
        box = QGroupBox("TÉRMICO / JANELA")
        form = QFormLayout(box)
        self.sp_tamb = self._dspin(-20, 80, 40.0, 1.0, " °C")
        self.sp_tmax = self._dspin(60, 180, 100.0, 1.0, " °C")
        self.sp_ku = self._dspin(0.05, 0.7, 0.40, 0.01, "")
        self.sp_bsat_margin = self._dspin(0.0, 0.5, 0.20, 0.01, "")
        form.addRow("T ambiente:", self.sp_tamb)
        form.addRow("T máx enrolamento:", self.sp_tmax)
        form.addRow("Ku máx (uso da janela):", self.sp_ku)
        form.addRow("Margem Bsat:", self.sp_bsat_margin)
        return box

    def _build_selection_box(self) -> QGroupBox:
        box = QGroupBox("SELEÇÃO")
        form = QFormLayout(box)

        self._curated_material_ids = load_curated_ids("materials")
        self._curated_wire_ids = load_curated_ids("wires")

        self.chk_curated_only = QCheckBox("Mostrar apenas curados")
        self.chk_curated_only.setToolTip(
            "Esconde os ~410 materiais e ~1380 fios importados do catálogo "
            "OpenMagnetics MAS — útil quando as listas ficam longas demais."
        )
        self.chk_curated_only.toggled.connect(self._refresh_visible_options)

        # Hide cores that obviously can't satisfy the current spec
        # (window overflow, can't reach L_required, saturates) — fast
        # heuristic, no design solver. Default ON.
        self.chk_filter_cores = QCheckBox("Filtrar núcleos viáveis")
        self.chk_filter_cores.setChecked(True)
        self.chk_filter_cores.setToolTip(
            "Esconde núcleos que claramente não vão satisfazer Pout/L/Ku "
            "para a especificação atual. Re-aplica quando você muda "
            "material, fio ou parâmetros do conversor — e clica de novo "
            "neste filtro depois de mudar Pout/Vin/fsw para revalidar."
        )
        self.chk_filter_cores.toggled.connect(self._on_material_changed)

        # All three selectors are sortable + type-to-filter so the user
        # can find an entry by typing any substring (e.g. "kool 60",
        # "ee 32", "AWG 14") instead of scrolling through hundreds of
        # rows.
        self.cmb_material = QComboBox()
        _make_searchable(self.cmb_material)
        self.cmb_material.currentIndexChanged.connect(self._on_material_changed)
        self.cmb_core = QComboBox()
        _make_searchable(self.cmb_core)
        self.cmb_wire = QComboBox()
        _make_searchable(self.cmb_wire)
        # Re-filter cores when wire changes — different wire areas
        # affect the window-overflow heuristic.
        self.cmb_wire.currentIndexChanged.connect(self._on_wire_changed)

        # Header label that says "X viáveis · Y ocultos: …"
        from PySide6.QtWidgets import QLabel
        self.lbl_filter_status = QLabel("")
        self.lbl_filter_status.setProperty("role", "muted")
        self.lbl_filter_status.setWordWrap(True)

        form.addRow("", self.chk_curated_only)
        form.addRow("", self.chk_filter_cores)
        form.addRow("Material:", self.cmb_material)
        form.addRow("Núcleo:", self.cmb_core)
        form.addRow("", self.lbl_filter_status)
        form.addRow("Fio:", self.cmb_wire)

        self._refresh_visible_options()
        return box

    def _on_wire_changed(self) -> None:
        """Wire change re-runs the core filter (wire area changes Ku)."""
        if self.chk_filter_cores.isChecked():
            self._on_material_changed()

    def _refresh_visible_options(self) -> None:
        """Repopulate material + wire combos based on the curated-only flag."""
        curated_only = self.chk_curated_only.isChecked()
        prev_mat = self.cmb_material.currentData()
        prev_wire = self.cmb_wire.currentData()

        mats = (
            [m for m in self._materials if m.id in self._curated_material_ids]
            if curated_only else list(self._materials)
        )
        if not mats:
            mats = list(self._materials)
        # Sort case-insensitively by display label (vendor — name) so the
        # type-to-filter completer feels predictable.
        mats = sorted(mats, key=lambda m: f"{m.vendor} — {m.name}".lower())
        self.cmb_material.blockSignals(True)
        self.cmb_material.clear()
        for m in mats:
            self.cmb_material.addItem(f"{m.vendor} — {m.name}", m.id)
        self.cmb_material.blockSignals(False)
        self._reselect_combo(self.cmb_material, prev_mat)

        wires = (
            [w for w in self._wires if w.id in self._curated_wire_ids]
            if curated_only else list(self._wires)
        )
        if not wires:
            wires = list(self._wires)
        wires = sorted(wires, key=lambda w: w.id.lower())
        self.cmb_wire.blockSignals(True)
        self.cmb_wire.clear()
        for w in wires:
            label = w.id if w.type == "round" else f"{w.id} (Litz)"
            self.cmb_wire.addItem(label, w.id)
        self.cmb_wire.blockSignals(False)
        self._reselect_combo(self.cmb_wire, prev_wire)

        self._on_material_changed()

    @staticmethod
    def _reselect_combo(combo: QComboBox, target_id) -> None:
        if target_id is None:
            return
        for i in range(combo.count()):
            if combo.itemData(i) == target_id:
                combo.setCurrentIndex(i)
                return

    def _on_material_changed(self):
        """Refresh core combobox: filter by material compat + (optional)
        quick feasibility heuristic for the current spec.
        """
        target = self.cmb_material.currentData()
        if target is None:
            return
        prev_core = self.cmb_core.currentData()
        compat = [c for c in self._cores if c.default_material_id == target]
        if not compat:
            compat = self._cores  # fallback: show all

        # Apply the fast viability filter when the user has the toggle
        # on and we have enough info to build a Spec.
        viable = compat
        status = ""
        if self.chk_filter_cores.isChecked():
            viable, status = self._filter_cores_for_spec(compat, target)
        if not viable:
            # Shouldn't happen but guard against an empty combo.
            viable = compat
            status = (
                "Filtro removeu todos — mostrando todos os compatíveis. "
                "Ajuste Pout/Ku máx ou troque material/fio."
            )
        self.lbl_filter_status.setText(status)

        # Sort by part number for the type-to-filter completer.
        viable_sorted = sorted(viable, key=lambda c: c.part_number.lower())
        self.cmb_core.blockSignals(True)
        self.cmb_core.clear()
        for c in viable_sorted:
            self.cmb_core.addItem(
                f"{c.part_number}  ({c.shape}, Ve={c.Ve_mm3/1000:.1f} cm³, AL={c.AL_nH:.0f} nH)",
                c.id,
            )
        self.cmb_core.blockSignals(False)
        self._reselect_combo(self.cmb_core, prev_core)
        self.cmb_core.currentIndexChanged.emit(self.cmb_core.currentIndex())
        self.changed.emit()

    def _filter_cores_for_spec(
        self, cores_compat: list[Core], material_id: str,
    ) -> tuple[list[Core], str]:
        """Run the quick feasibility heuristic.

        Returns (viable_cores, status_text). Empty status means "no
        cores were filtered out".
        """
        try:
            from pfc_inductor.optimize.feasibility import filter_viable_cores
            from pfc_inductor.data_loader import find_material
            spec = self.get_spec()
            material = find_material(self._materials, material_id)
            wire_id = self.cmb_wire.currentData()
            if not wire_id:
                return cores_compat, ""
            wire = next((w for w in self._wires if w.id == wire_id), None)
            if wire is None:
                return cores_compat, ""
            viable, reasons = filter_viable_cores(
                spec, cores_compat, material, wire,
            )
        except Exception:
            # On any error (eg incomplete spec), don't filter — show all.
            return cores_compat, ""

        n_hidden = len(cores_compat) - len(viable)
        if n_hidden <= 0:
            return viable, f"{len(viable)} viáveis · 0 ocultos"
        bits = [f"{n} {label}"
                for label, n in (
                    ("L pequeno", reasons.get("too_small_L", 0)),
                    ("janela", reasons.get("window_overflow", 0)),
                    ("saturação", reasons.get("saturates", 0)),
                ) if n > 0]
        why = ", ".join(bits) if bits else "—"
        return viable, (
            f"{len(viable)} viáveis · {n_hidden} ocultos ({why})"
        )

    def _set_initial_selection(self):
        """Pick a sensible starting point: High Flux 60u + suitable toroid + AWG14."""
        for i in range(self.cmb_material.count()):
            if "60_HighFlux" in self.cmb_material.itemText(i):
                self.cmb_material.setCurrentIndex(i)
                break
        # _on_material_changed has fired; pick a 30-100 cm³ core if possible
        best_idx = 0
        for i in range(self.cmb_core.count()):
            txt = self.cmb_core.itemText(i)
            try:
                ve_str = txt.split("Ve=")[1].split(" ")[0]
                ve = float(ve_str)
                if 30 <= ve <= 100:
                    best_idx = i
                    break
            except (IndexError, ValueError):
                continue
        self.cmb_core.setCurrentIndex(best_idx)
        for i in range(self.cmb_wire.count()):
            if self.cmb_wire.itemData(i) == "AWG14":
                self.cmb_wire.setCurrentIndex(i)
                break

    @staticmethod
    def _dspin(mn, mx, val, step, suffix) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(mn, mx)
        s.setValue(val)
        s.setSingleStep(step)
        s.setDecimals(2)
        s.setSuffix(suffix)
        return s

    def _wire_signals(self):
        widgets = [
            self.cmb_topology, self.sp_vin_min, self.sp_vin_max, self.sp_vin_nom,
            self.sp_fline, self.sp_vout, self.sp_pout, self.sp_eta, self.sp_fsw,
            self.sp_ripple, self.sp_tamb, self.sp_tmax, self.sp_ku, self.sp_bsat_margin,
            self.cmb_core, self.cmb_material, self.cmb_wire,
            self.cmb_phases, self.sp_vline, self.sp_irated, self.sp_pctZ,
        ]
        for w in widgets:
            if isinstance(w, QComboBox):
                # QComboBox.currentIndexChanged emits int; discard it.
                w.currentIndexChanged.connect(lambda _idx: self.changed.emit())
            else:
                # QDoubleSpinBox.valueChanged emits float; discard it.
                w.valueChanged.connect(lambda _v: self.changed.emit())

    def get_spec(self) -> Spec:
        topo = self.cmb_topology.currentData()
        # Line reactor uses its own V/I from the dedicated block; for other
        # topologies we fall back to the AC input block values.
        if topo == "line_reactor":
            v_nom = self.sp_vline.value()
            n_phases = int(self.cmb_phases.currentData() or 3)
            i_rated = self.sp_irated.value()
            pct_z = self.sp_pctZ.value()
        else:
            v_nom = self.sp_vin_nom.value()
            n_phases = 3
            i_rated = 30.0
            pct_z = 5.0
        return Spec(
            topology=topo,
            Vin_min_Vrms=self.sp_vin_min.value(),
            Vin_max_Vrms=self.sp_vin_max.value(),
            Vin_nom_Vrms=v_nom,
            f_line_Hz=self.sp_fline.value(),
            Vout_V=self.sp_vout.value(),
            Pout_W=self.sp_pout.value(),
            eta=self.sp_eta.value(),
            f_sw_kHz=self.sp_fsw.value(),
            ripple_pct=self.sp_ripple.value(),
            T_amb_C=self.sp_tamb.value(),
            T_max_C=self.sp_tmax.value(),
            Ku_max=self.sp_ku.value(),
            Bsat_margin=self.sp_bsat_margin.value(),
            n_phases=n_phases,
            pct_impedance=pct_z,
            I_rated_Arms=i_rated,
        )

    def get_core_id(self) -> str:
        return self.cmb_core.currentData()

    def get_material_id(self) -> str:
        return self.cmb_material.currentData()

    def get_wire_id(self) -> str:
        return self.cmb_wire.currentData()
