"""Spec input panel: all fields of ``Spec`` *except* topology.

Topology selection lives in a single source of truth — the
:class:`TopologyPickerDialog
<pfc_inductor.ui.dialogs.TopologyPickerDialog>`, opened via the
"Alterar Topologia" button on the SpecDrawer. The previous
arrangement had a ``QComboBox`` here AND the picker button on the
drawer, so the user saw the same choice in two places (and could
desync them by editing the combobox without opening the picker).

The panel keeps an internal ``_topology`` / ``_n_phases`` pair that
:meth:`set_topology` updates; the rest of the form (Vin / Vout /
fsw / thermal / line-reactor block visibility) reacts to that state.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Spec


class SpecPanel(QWidget):
    """Left-side panel: collects spec, emits when changed."""

    changed = Signal()
    calculate_requested = Signal()
    topology_changed = Signal(str, int)  # canonical key, n_phases

    def __init__(
        self,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        from PySide6.QtWidgets import QFrame, QLabel, QScrollArea
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

        # Topology lives in the SpecDrawer's "Alterar Topologia" header
        # button (single source of truth). We hold the canonical state
        # here so ``get_spec()`` and the converter / line-reactor box
        # visibility remain reactive.
        self._topology: str = "boost_ccm"
        self._n_phases: int = 1

        body.addWidget(self._build_input_box())
        self._converter_box = self._build_converter_box()
        body.addWidget(self._converter_box)
        self._line_reactor_box = self._build_line_reactor_box()
        body.addWidget(self._line_reactor_box)
        body.addWidget(self._build_thermal_box())
        body.addStretch(1)

        # Apply initial visibility (hide line-reactor block on default
        # boost-CCM topology).
        self._apply_topology_visibility()

        # The drawer used to pin a "Calcular" Primary button at the
        # bottom — that was the third Recalcular CTA on the screen
        # (header + drawer + scoreboard). Engineers reported
        # decision paralysis. The header's Recalcular button + the
        # ``Ctrl+R`` shortcut now own that action; the drawer no
        # longer competes. ``btn_calculate`` is kept as a hidden
        # widget so external code that referenced it (controllers,
        # tests) doesn't ``AttributeError``.
        self.btn_calculate = QPushButton("Calcular")
        self.btn_calculate.setVisible(False)
        self.btn_calculate.clicked.connect(self.calculate_requested.emit)

        self._wire_signals()

    def _build_line_reactor_box(self) -> QGroupBox:
        """Hidden by default; visible only when topology = line_reactor.

        The 1φ/3φ choice was previously a ``QComboBox`` here; it now
        comes from the topology picker dialog (which ships
        ``line_reactor_1ph`` and ``line_reactor_3ph`` as separate
        cards). The pane still surfaces the *electrical* line-reactor
        fields (V_line, I_rated, L_req) which the picker dialog
        intentionally does NOT cover.
        """
        box = QGroupBox("REATOR DE LINHA")
        form = QFormLayout(box)
        self.sp_vline = self._dspin(80, 690, 220.0, 1.0, " Vrms")
        self.sp_irated = self._dspin(0.1, 500, 2.2, 0.5, " A")
        self.sp_l_req = self._dspin(0.1, 1000, 10.0, 0.1, " mH")
        form.addRow("V de linha:", self.sp_vline)
        form.addRow("I nominal (RMS):", self.sp_irated)
        form.addRow("Indutância alvo:", self.sp_l_req)
        return box

    # ------------------------------------------------------------------
    # Topology — set from outside (TopologyPickerDialog), read here.
    # ------------------------------------------------------------------
    def topology(self) -> str:
        """Canonical ``Spec.topology`` value: ``boost_ccm`` |
        ``passive_choke`` | ``line_reactor``."""
        return self._topology

    def n_phases(self) -> int:
        """1 or 3 — meaningful only when ``topology() == "line_reactor"``."""
        return self._n_phases

    def set_topology(self, name: str, n_phases: int = 1) -> None:
        """Replace the active topology.

        Accepts both the canonical Spec keys (``boost_ccm`` /
        ``passive_choke`` / ``line_reactor``) and the picker dialog's
        suffixed variants (``line_reactor_1ph`` / ``line_reactor_3ph``).
        Emits :attr:`topology_changed` and :attr:`changed` so the
        debounced recalc on MainWindow picks up the new state.
        """
        if name == "line_reactor_1ph":
            name = "line_reactor"
            n_phases = 1
        elif name == "line_reactor_3ph":
            name = "line_reactor"
            n_phases = 3

        if name not in ("boost_ccm", "passive_choke", "line_reactor"):
            raise ValueError(f"unsupported topology: {name!r}")

        if name == self._topology and n_phases == self._n_phases:
            return  # no change — avoid spurious recalcs

        self._topology = name
        self._n_phases = int(n_phases) if n_phases in (1, 3) else 1
        self._apply_topology_visibility()
        self.topology_changed.emit(self._topology, self._n_phases)
        self.changed.emit()

    def _apply_topology_visibility(self) -> None:
        """Show/hide form blocks that don't apply to the active topology."""
        is_lr = self._topology == "line_reactor"
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
        self.sp_tmax = self._dspin(60, 180, 125.0, 1.0, " °C")
        self.sp_ku = self._dspin(0.05, 0.7, 0.7, 0.01, "")
        self.sp_bsat_margin = self._dspin(0.0, 0.5, 0.20, 0.01, "")
        form.addRow("T ambiente:", self.sp_tamb)
        form.addRow("T máx enrolamento:", self.sp_tmax)
        form.addRow("Ku máx (uso da janela):", self.sp_ku)
        form.addRow("Margem Bsat:", self.sp_bsat_margin)
        return box

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
        # Topology is driven externally via ``set_topology`` (which
        # emits ``changed`` itself), so it is not in this list. All
        # remaining inputs are ``QDoubleSpinBox`` instances.
        widgets = [
            self.sp_vin_min, self.sp_vin_max, self.sp_vin_nom,
            self.sp_fline, self.sp_vout, self.sp_pout, self.sp_eta, self.sp_fsw,
            self.sp_ripple, self.sp_tamb, self.sp_tmax, self.sp_ku, self.sp_bsat_margin,
            self.sp_vline, self.sp_irated, self.sp_l_req,
        ]
        for w in widgets:
            # QDoubleSpinBox.valueChanged emits float; discard it.
            w.valueChanged.connect(lambda _v: self.changed.emit())

    def set_spec(self, spec: Spec) -> None:
        """Write ``spec`` back into the form fields — reverse of
        :meth:`get_spec`. Used by *File → Open Project* to restore a
        saved session.

        Signals are blocked during the bulk write so the debounced
        recalc fires once at the end (not 16 times during the partial
        update). Caller is expected to trigger ``_on_calculate`` after.
        """
        self.blockSignals(True)
        try:
            # Topology first — it gates which input block is visible.
            self.set_topology(spec.topology, n_phases=spec.n_phases)
            self.sp_vin_min.setValue(spec.Vin_min_Vrms)
            self.sp_vin_max.setValue(spec.Vin_max_Vrms)
            self.sp_vin_nom.setValue(spec.Vin_nom_Vrms)
            self.sp_fline.setValue(spec.f_line_Hz)
            self.sp_vout.setValue(spec.Vout_V)
            self.sp_pout.setValue(spec.Pout_W)
            self.sp_eta.setValue(spec.eta)
            self.sp_fsw.setValue(spec.f_sw_kHz)
            self.sp_ripple.setValue(spec.ripple_pct)
            self.sp_tamb.setValue(spec.T_amb_C)
            self.sp_tmax.setValue(spec.T_max_C)
            self.sp_ku.setValue(spec.Ku_max)
            self.sp_bsat_margin.setValue(spec.Bsat_margin)
            # Line-reactor-only fields are silently ignored when the
            # topology doesn't expose them — matches ``get_spec``'s
            # one-way logic for the boost / passive branch.
            if spec.topology == "line_reactor":
                self.sp_vline.setValue(spec.Vin_nom_Vrms)
                self.sp_l_req.setValue(spec.L_req_mH)
                self.sp_irated.setValue(spec.I_rated_Arms)
        finally:
            self.blockSignals(False)
        # Single fan-out at the end — host re-reads via ``get_spec``.
        self.changed.emit()

    def get_spec(self) -> Spec:
        topo = self._topology
        # Line reactor uses its own V/I from the dedicated block; for other
        # topologies we fall back to the AC input block values.
        if topo == "line_reactor":
            v_nom = self.sp_vline.value()
            n_phases = self._n_phases
            i_rated = self.sp_irated.value()
            l_req = self.sp_l_req.value()
        else:
            v_nom = self.sp_vin_nom.value()
            # ``n_phases`` is meaningless for boost / passive choke;
            # the legacy default 3 is preserved for spec serialisation
            # so existing snapshot tests don't drift.
            n_phases = 3
            i_rated = 2.2
            l_req = 10.0
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
            L_req_mH=l_req,
            I_rated_Arms=i_rated,
        )
