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

        title = QLabel("Specification")
        title.setProperty("role", "title")
        body.addWidget(title)

        # Topology lives in the SpecDrawer's "Change Topology" header
        # button (single source of truth). We hold the canonical state
        # here so ``get_spec()`` and the converter / line-reactor box
        # visibility remain reactive.
        self._topology: str = "boost_ccm"
        self._n_phases: int = 1

        self._ac_input_box = self._build_input_box()
        body.addWidget(self._ac_input_box)
        self._dc_input_box = self._build_dc_input_box()
        body.addWidget(self._dc_input_box)
        self._converter_box = self._build_converter_box()
        body.addWidget(self._converter_box)
        self._line_reactor_box = self._build_line_reactor_box()
        body.addWidget(self._line_reactor_box)
        body.addWidget(self._build_thermal_box())

        # ---- VFD modulation sub-form ----------------------------------
        # Lazy import — keeps the spec_panel import graph clean of
        # the modulation widget for headless / test contexts that
        # never instantiate the panel.
        from pfc_inductor.ui.widgets.modulation_group import ModulationGroup

        self.modulation_group = ModulationGroup()
        self.modulation_group.changed.connect(self.changed.emit)
        body.addWidget(self.modulation_group)

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
        form.addRow("Target inductance:", self.sp_l_req)
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
        ``passive_choke`` / ``line_reactor`` / ``buck_ccm``) and the
        picker dialog's suffixed variants (``line_reactor_1ph`` /
        ``line_reactor_3ph``). Emits :attr:`topology_changed` and
        :attr:`changed` so the debounced recalc on MainWindow picks
        up the new state.
        """
        if name == "line_reactor_1ph":
            name = "line_reactor"
            n_phases = 1
        elif name == "line_reactor_3ph":
            name = "line_reactor"
            n_phases = 3

        if name not in ("boost_ccm", "passive_choke", "line_reactor", "buck_ccm"):
            raise ValueError(f"unsupported topology: {name!r}")

        if name == self._topology and n_phases == self._n_phases:
            return  # no change — avoid spurious recalcs

        # When entering buck mode from boost defaults (Vout=400, fsw=65)
        # the converter box values are physically wrong (Vout > Vin_dc).
        # Pre-fill textbook 12 V → 3.3 V POL defaults so the user gets
        # a runnable spec on the first click. We only auto-fill when
        # the current values look like the boost defaults — if the user
        # already set Vout/fsw to something buck-shaped, leave them be.
        prev = self._topology
        if name == "buck_ccm" and prev != "buck_ccm":
            self._apply_buck_defaults_if_boostlike()
        elif prev == "buck_ccm" and name != "buck_ccm":
            self._apply_boost_defaults_if_bucklike()

        self._topology = name
        self._n_phases = int(n_phases) if n_phases in (1, 3) else 1
        self._apply_topology_visibility()
        self.topology_changed.emit(self._topology, self._n_phases)
        self.changed.emit()

    def _apply_topology_visibility(self) -> None:
        """Show/hide form blocks that don't apply to the active topology."""
        is_lr = self._topology == "line_reactor"
        is_buck = self._topology == "buck_ccm"
        # Line-reactor block: visible only for line_reactor.
        self._line_reactor_box.setVisible(is_lr)
        # AC input block: hidden for line_reactor (it has its own
        # V/I block) and for buck_ccm (DC input).
        self._ac_input_box.setVisible(not is_lr and not is_buck)
        # DC input block: only for buck_ccm.
        self._dc_input_box.setVisible(is_buck)
        # Converter block (Vout / Pout / η / fsw / ripple): visible
        # for boost / passive / buck. Hidden only for line_reactor,
        # which has its own electrical fields.
        self._converter_box.setVisible(not is_lr)

    # ------------------------------------------------------------------
    # Topology-default helpers — keep the UI runnable when toggling
    # between AC and DC topologies. The user can always overwrite the
    # filled-in numbers, but a fresh switch shouldn't produce a spec
    # that fails the validator (e.g. boost's Vout=400 V vs buck's
    # Vin_dc=12 V).
    # ------------------------------------------------------------------
    def _values_look_like_boost_defaults(self) -> bool:
        return abs(self.sp_vout.value() - 400.0) < 1.0 and abs(self.sp_fsw.value() - 65.0) < 1.0

    def _values_look_like_buck_defaults(self) -> bool:
        # Loose check: any Vout < 100 V is buck-shaped (boost designs
        # rarely go below 200 V on the DC bus).
        return self.sp_vout.value() < 100.0

    def _apply_buck_defaults_if_boostlike(self) -> None:
        """If the converter values still match boost defaults, swap to
        a textbook 12 V → 3.3 V POL preset."""
        if self._values_look_like_boost_defaults():
            self.sp_vout.setValue(3.3)
            self.sp_pout.setValue(10.0)
            self.sp_fsw.setValue(500.0)

    def _apply_boost_defaults_if_bucklike(self) -> None:
        """Inverse: if leaving buck and the values are still buck-shaped,
        restore the boost defaults so the validator (Vout > Vin_pk·1.41)
        passes."""
        if self._values_look_like_buck_defaults():
            self.sp_vout.setValue(400.0)
            self.sp_pout.setValue(800.0)
            self.sp_fsw.setValue(65.0)

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

    def _build_dc_input_box(self) -> QGroupBox:
        """DC input block — visible only when topology == ``buck_ccm``.

        Buck-CCM is a step-down DC-DC; it has no AC line frequency, no
        line-Vrms range. Instead the design is parameterised by:

          * ``Vin_dc_V``      — nominal DC input
          * ``Vin_dc_min_V``  — worst-case low (drives current calc)
          * ``Vin_dc_max_V``  — worst-case high (drives ripple calc)

        Defaults match the textbook 12 V → 3.3 V POL example we use in
        ``tests/test_topology_buck_ccm.py`` so a fresh user who picks
        "Buck CCM" gets a runnable spec immediately.
        """
        box = QGroupBox("ENTRADA DC")
        form = QFormLayout(box)
        self.sp_vin_dc = self._dspin(1.0, 1000.0, 12.0, 0.1, " V")
        self.sp_vin_dc_min = self._dspin(1.0, 1000.0, 10.8, 0.1, " V")
        self.sp_vin_dc_max = self._dspin(1.0, 1000.0, 13.2, 0.1, " V")
        form.addRow("Vin DC nominal:", self.sp_vin_dc)
        form.addRow("Vin DC mín (worst current):", self.sp_vin_dc_min)
        form.addRow("Vin DC máx (worst ripple):", self.sp_vin_dc_max)
        return box

    def _build_converter_box(self) -> QGroupBox:
        box = QGroupBox("CONVERSOR")
        form = QFormLayout(box)
        # Vout: boost typically 400 V; buck typically a few V.
        # Allow the full 0.5–800 V range so both topologies fit
        # without re-bounding when the user toggles topology.
        self.sp_vout = self._dspin(0.5, 800, 400.0, 1.0, " V")
        self.sp_pout = self._dspin(1, 5000, 800.0, 10.0, " W")
        self.sp_eta = self._dspin(0.5, 1.0, 0.97, 0.01, "")
        # f_sw: bucks commonly 100–1000 kHz; cap at 2000 kHz for GaN.
        self.sp_fsw = self._dspin(10, 2000, 65.0, 1.0, " kHz")
        self.sp_ripple = self._dspin(5, 100, 30.0, 1.0, " %")
        form.addRow("Vout (DC bus):", self.sp_vout)
        form.addRow("Pout:", self.sp_pout)
        form.addRow("Efficiency:", self.sp_eta)
        form.addRow("fsw:", self.sp_fsw)
        form.addRow("Ripple pico-pico:", self.sp_ripple)
        return box

    def _build_thermal_box(self) -> QGroupBox:
        box = QGroupBox("THERMAL / WINDOW")
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
            self.sp_vin_min,
            self.sp_vin_max,
            self.sp_vin_nom,
            self.sp_fline,
            self.sp_vout,
            self.sp_pout,
            self.sp_eta,
            self.sp_fsw,
            self.sp_ripple,
            self.sp_tamb,
            self.sp_tmax,
            self.sp_ku,
            self.sp_bsat_margin,
            self.sp_vline,
            self.sp_irated,
            self.sp_l_req,
            # Buck-only DC input fields — they only feed `get_spec`
            # when topology=="buck_ccm" but we still want a manual
            # edit to trigger the debounced recalc when buck is active.
            self.sp_vin_dc,
            self.sp_vin_dc_min,
            self.sp_vin_dc_max,
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
            # Buck-CCM: pull DC input fields, falling back to legacy
            # AC values for specs that haven't migrated.
            if spec.topology == "buck_ccm":
                v_dc = spec.Vin_dc_V or spec.Vin_min_Vrms or 12.0
                v_dc_min = spec.Vin_dc_min_V or spec.Vin_dc_V or spec.Vin_min_Vrms or v_dc
                v_dc_max = spec.Vin_dc_max_V or spec.Vin_dc_V or spec.Vin_max_Vrms or v_dc
                self.sp_vin_dc.setValue(float(v_dc))
                self.sp_vin_dc_min.setValue(float(v_dc_min))
                self.sp_vin_dc_max.setValue(float(v_dc_max))
                # ``ripple_ratio`` is the buck design knob; if absent,
                # the existing ``ripple_pct`` already covers it.
                if spec.ripple_ratio is not None:
                    self.sp_ripple.setValue(spec.ripple_ratio * 100.0)
            # VFD band — populates from the saved spec; no-op when
            # the spec doesn't carry a band (legacy `.pfc`).
            self.modulation_group.from_modulation(spec.fsw_modulation)
        finally:
            self.blockSignals(False)
        # Single fan-out at the end — host re-reads via ``get_spec``.
        self.changed.emit()

    def get_spec(self) -> Spec:
        topo = self._topology
        # Per-topology source of voltages / currents:
        #
        #   * line_reactor — uses its own V/I block (``sp_vline`` etc.)
        #   * buck_ccm     — uses the DC input block (``sp_vin_dc*``);
        #                    legacy AC fields are populated with safe
        #                    placeholders so the Pydantic model still
        #                    constructs (the validator only reads the
        #                    DC fields for buck).
        #   * boost / passive — AC input block.
        vin_dc: Optional[float] = None
        vin_dc_min: Optional[float] = None
        vin_dc_max: Optional[float] = None
        ripple_ratio: Optional[float] = None
        if topo == "line_reactor":
            v_nom = self.sp_vline.value()
            v_min_ac = self.sp_vin_min.value()
            v_max_ac = self.sp_vin_max.value()
            n_phases = self._n_phases
            i_rated = self.sp_irated.value()
            l_req = self.sp_l_req.value()
        elif topo == "buck_ccm":
            # Buck doesn't use AC fields; fill them with the DC values
            # so legacy serialisers and downstream UI tiles that still
            # read ``Vin_min_Vrms`` (e.g. some report tables) display
            # something sensible. The validator/engine path goes
            # through the DC fields explicitly.
            vin_dc = self.sp_vin_dc.value()
            vin_dc_min = self.sp_vin_dc_min.value()
            vin_dc_max = self.sp_vin_dc_max.value()
            v_nom = vin_dc
            v_min_ac = vin_dc_min
            v_max_ac = vin_dc_max
            n_phases = 3  # placeholder, ignored for buck
            i_rated = 2.2
            l_req = 10.0
            # Convert the % ripple field to a 0..1 ratio for buck.
            ripple_ratio = self.sp_ripple.value() / 100.0
        else:
            v_nom = self.sp_vin_nom.value()
            v_min_ac = self.sp_vin_min.value()
            v_max_ac = self.sp_vin_max.value()
            # ``n_phases`` is meaningless for boost / passive choke;
            # the legacy default 3 is preserved for spec serialisation
            # so existing snapshot tests don't drift.
            n_phases = 3
            i_rated = 2.2
            l_req = 10.0
        # VFD band — None when the master toggle is off, which
        # routes the engine back through the single-point path.
        try:
            fsw_modulation = self.modulation_group.to_modulation()
        except (ValueError, TypeError):
            # Invalid band (e.g. fsw_max ≤ fsw_min) — surface as a
            # silent fall-through to single-point so the engine
            # still runs. The ModulationGroup's derived-label has
            # already shown the error to the user.
            fsw_modulation = None
        return Spec(
            topology=topo,
            Vin_min_Vrms=v_min_ac,
            Vin_max_Vrms=v_max_ac,
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
            Vin_dc_V=vin_dc,
            Vin_dc_min_V=vin_dc_min,
            Vin_dc_max_V=vin_dc_max,
            ripple_ratio=ripple_ratio,
            fsw_modulation=fsw_modulation,
        )
