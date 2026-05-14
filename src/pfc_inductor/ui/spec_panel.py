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
    QRadioButton,
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
        # Interleaved-boost-PFC phase count (2 or 3). Only meaningful
        # when ``self._topology == "interleaved_boost_pfc"``; default
        # 2 keeps round-trip compat with specs that don't carry it.
        self._n_interleave: int = 2

        self._ac_input_box = self._build_input_box()
        body.addWidget(self._ac_input_box)
        self._dc_input_box = self._build_dc_input_box()
        body.addWidget(self._dc_input_box)
        self._converter_box = self._build_converter_box()
        body.addWidget(self._converter_box)
        self._flyback_box = self._build_flyback_box()
        body.addWidget(self._flyback_box)
        self._interleave_box = self._build_interleave_box()
        body.addWidget(self._interleave_box)
        self._line_reactor_box = self._build_line_reactor_box()
        body.addWidget(self._line_reactor_box)
        body.addWidget(self._build_thermal_box())

        # ---- VFD modulation sub-form ----------------------------------
        # Lazy import — keeps the spec_panel import graph clean of
        # the modulation widget for headless / test contexts that
        # never instantiate the panel.
        from pfc_inductor.ui.widgets.load_modulation_group import (
            LoadModulationGroup,
        )
        from pfc_inductor.ui.widgets.modulation_group import ModulationGroup

        self.modulation_group = ModulationGroup()
        self.modulation_group.changed.connect(self.changed.emit)
        # Mutual exclusion with the load-modulation sibling. When the
        # fsw band turns on, the load band turns off — see
        # ``_on_fsw_modulation_toggled`` / ``_on_load_modulation_toggled``.
        self.modulation_group._chk_enabled.toggled.connect(
            self._on_fsw_modulation_toggled,
        )
        body.addWidget(self.modulation_group)

        # ---- Load-power modulation sub-form ---------------------------
        # Sibling of the fsw band: sweeps Pout instead of fsw. Mutual-
        # exclusion is enforced by the Spec validator and by the two
        # checkbox handlers below — only one band can be active at a
        # time per spec.
        self.load_modulation_group = LoadModulationGroup()
        self.load_modulation_group.changed.connect(self.changed.emit)
        self.load_modulation_group._chk_enabled.toggled.connect(
            self._on_load_modulation_toggled,
        )
        body.addWidget(self.load_modulation_group)

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
        box = QGroupBox("LINE REACTOR")
        form = QFormLayout(box)
        self.sp_vline = self._dspin(80, 690, 220.0, 1.0, " Vrms")
        self.sp_irated = self._dspin(0.1, 500, 2.2, 0.5, " A")
        self.sp_l_req = self._dspin(0.1, 1000, 10.0, 0.1, " mH")
        form.addRow("Line voltage:", self.sp_vline)
        form.addRow("Rated current (RMS):", self.sp_irated)
        form.addRow("Target inductance:", self.sp_l_req)
        return box

    def _build_flyback_box(self) -> QGroupBox:
        """Flyback-specific parameters — visible only when
        ``topology == 'flyback'``.

        Three fields the engine reads only for the flyback path:

        * ``flyback_mode`` — operating mode at design time
          (DCM is the textbook default; CCM with reflected-voltage
          assumptions is the alternative for higher-power isolated
          designs). Picked here as a radio pair so the engineer
          sees the choice without having to read the Spec docstring.
        * ``turns_ratio_n`` — primary:secondary turns ratio. Drives
          the reflected-voltage stress on the primary MOSFET and the
          peak-to-average current ratio on the secondary diode.
        * ``window_split_primary`` — fraction of the bobbin window
          allocated to the primary winding (0.30–0.65, default 0.45).
          Above 0.5 favours primary copper at the cost of secondary
          AC loss; below it inverts the trade-off.
        """
        box = QGroupBox("FLYBACK")
        form = QFormLayout(box)
        # Mode picker — radio pair rather than combobox so both
        # options stay visible and discoverable.
        mode_row = QWidget()
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(8)
        self.rb_flyback_dcm = QRadioButton("DCM")
        self.rb_flyback_dcm.setChecked(True)
        self.rb_flyback_ccm = QRadioButton("CCM")
        mode_layout.addWidget(self.rb_flyback_dcm)
        mode_layout.addWidget(self.rb_flyback_ccm)
        mode_layout.addStretch(1)
        form.addRow("Mode:", mode_row)

        self.sp_turns_ratio = self._dspin(0.5, 20.0, 4.0, 0.1, "")
        form.addRow("Turns ratio Np/Ns:", self.sp_turns_ratio)

        self.sp_window_split = self._dspin(0.30, 0.65, 0.45, 0.01, "")
        form.addRow("Window split (primary):", self.sp_window_split)

        # Wire the changed signal so the debounced recalc picks up
        # turns-ratio / mode edits.
        self.rb_flyback_dcm.toggled.connect(self.changed.emit)
        self.sp_turns_ratio.valueChanged.connect(self.changed.emit)
        self.sp_window_split.valueChanged.connect(self.changed.emit)
        return box

    def _build_interleave_box(self) -> QGroupBox:
        """Interleaved-boost phase count — visible only when
        ``topology == 'interleaved_boost_pfc'``.

        The topology picker offers 2-phase and 3-phase as separate
        cards, but engineers often want to flip between them without
        re-opening the modal. The inline radio here is the round-trip
        editor.
        """
        box = QGroupBox("INTERLEAVED BOOST")
        form = QFormLayout(box)
        phases_row = QWidget()
        phases_layout = QHBoxLayout(phases_row)
        phases_layout.setContentsMargins(0, 0, 0, 0)
        phases_layout.setSpacing(8)
        self.rb_interleave_2 = QRadioButton("2 phases")
        self.rb_interleave_2.setChecked(True)
        self.rb_interleave_3 = QRadioButton("3 phases")
        phases_layout.addWidget(self.rb_interleave_2)
        phases_layout.addWidget(self.rb_interleave_3)
        phases_layout.addStretch(1)
        form.addRow("Number of phases:", phases_row)

        def _on_phases_toggled(_checked: bool) -> None:
            new_n = 3 if self.rb_interleave_3.isChecked() else 2
            if new_n != self._n_interleave:
                self._n_interleave = new_n
                self.topology_changed.emit(self._topology, new_n)
                self.changed.emit()

        self.rb_interleave_2.toggled.connect(_on_phases_toggled)
        self.rb_interleave_3.toggled.connect(_on_phases_toggled)
        return box

    # ------------------------------------------------------------------
    # Topology — set from outside (TopologyPickerDialog), read here.
    # ------------------------------------------------------------------
    def topology(self) -> str:
        """Canonical ``Spec.topology`` value."""
        return self._topology

    def n_phases(self) -> int:
        """1 or 3 — meaningful only when ``topology() == "line_reactor"``."""
        return self._n_phases

    def n_interleave(self) -> int:
        """2 or 3 — meaningful only when ``topology() ==
        "interleaved_boost_pfc"``."""
        return self._n_interleave

    def set_topology(
        self,
        name: str,
        n_phases: int = 1,
        n_interleave: int = 2,
    ) -> None:
        """Replace the active topology.

        Accepts both the canonical Spec keys and the picker dialog's
        suffixed variants:

        - ``line_reactor_1ph`` / ``line_reactor_3ph`` →
          ``line_reactor`` with the appropriate ``n_phases``.
        - ``interleaved_boost_pfc_2ph`` /
          ``interleaved_boost_pfc_3ph`` → ``interleaved_boost_pfc``
          with the appropriate ``n_interleave``.

        Emits :attr:`topology_changed` and :attr:`changed` so the
        debounced recalc on MainWindow picks up the new state.
        """
        if name == "line_reactor_1ph":
            name = "line_reactor"
            n_phases = 1
        elif name == "line_reactor_3ph":
            name = "line_reactor"
            n_phases = 3
        elif name == "interleaved_boost_pfc_2ph":
            name = "interleaved_boost_pfc"
            n_interleave = 2
        elif name == "interleaved_boost_pfc_3ph":
            name = "interleaved_boost_pfc"
            n_interleave = 3

        if name not in (
            "boost_ccm",
            "passive_choke",
            "line_reactor",
            "buck_ccm",
            "flyback",
            "interleaved_boost_pfc",
        ):
            raise ValueError(f"unsupported topology: {name!r}")

        if (
            name == self._topology
            and n_phases == self._n_phases
            and n_interleave == self._n_interleave
        ):
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
        # Flyback uses the same DC-input bus as buck (12 V → 5 V is the
        # textbook case), so the same auto-fill heuristic applies. The
        # set is broader than buck — flyback can also work at high-Vin
        # (post-PFC 375 V) or low-Vin (12 V wall adapter), but the
        # defaults need to be runnable, not optimal.
        if name == "flyback" and prev not in ("flyback", "buck_ccm"):
            self._apply_flyback_defaults_if_boostlike()
        elif prev == "flyback" and name not in ("flyback", "buck_ccm"):
            self._apply_boost_defaults_if_bucklike()

        self._topology = name
        self._n_phases = int(n_phases) if n_phases in (1, 3) else 1
        self._n_interleave = int(n_interleave) if n_interleave in (2, 3) else 2
        self._apply_topology_visibility()
        # The signal carries a single "count" int that is interpreted
        # per-topology by listeners: ``n_phases`` for line_reactor and
        # ``n_interleave`` for interleaved_boost_pfc; 1 otherwise.
        if self._topology == "line_reactor":
            count_for_label = self._n_phases
        elif self._topology == "interleaved_boost_pfc":
            count_for_label = self._n_interleave
        else:
            count_for_label = 1
        self.topology_changed.emit(self._topology, count_for_label)
        self.changed.emit()

    def _apply_topology_visibility(self) -> None:
        """Show/hide form blocks that don't apply to the active topology."""
        is_lr = self._topology == "line_reactor"
        is_buck = self._topology == "buck_ccm"
        is_flyback = self._topology == "flyback"
        is_passive = self._topology == "passive_choke"
        is_interleaved = self._topology == "interleaved_boost_pfc"
        is_dc_input = is_buck or is_flyback
        # Line-reactor block: visible only for line_reactor.
        self._line_reactor_box.setVisible(is_lr)
        # AC input block: hidden for line_reactor (it has its own
        # V/I block) and for any DC-input topology (buck / flyback).
        self._ac_input_box.setVisible(not is_lr and not is_dc_input)
        # DC input block: shown for both buck_ccm and flyback.
        self._dc_input_box.setVisible(is_dc_input)
        # Converter block (Vout / Pout / η / fsw / ripple): visible
        # for every topology except line_reactor (which has its own
        # electrical fields).
        self._converter_box.setVisible(not is_lr)
        # Flyback-only fields: turns ratio + mode + window split.
        self._flyback_box.setVisible(is_flyback)
        # Interleave count selector: only for interleaved_boost_pfc.
        self._interleave_box.setVisible(is_interleaved)
        # ``fsw`` is meaningless for passive_choke (unswitched
        # filter — only Vin / Pout / Ku matter). Hide the spinbox to
        # keep the panel honest. The widget stays in the form so the
        # value persists if the user toggles back.
        if hasattr(self, "sp_fsw"):
            self.sp_fsw.setEnabled(not is_passive)
            self.sp_fsw.setToolTip(
                "Not applicable to passive choke (unswitched filter)"
                if is_passive
                else "Converter switching frequency"
            )
        # Sync the interleave radio buttons with the internal state
        # so toggling topology in / out of interleaved_boost preserves
        # the user's last 2 vs 3 choice.
        if hasattr(self, "rb_interleave_2"):
            blocker_2 = self.rb_interleave_2.blockSignals(True)
            blocker_3 = self.rb_interleave_3.blockSignals(True)
            try:
                self.rb_interleave_3.setChecked(self._n_interleave == 3)
                self.rb_interleave_2.setChecked(self._n_interleave != 3)
            finally:
                self.rb_interleave_2.blockSignals(blocker_2)
                self.rb_interleave_3.blockSignals(blocker_3)

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

    def _apply_flyback_defaults_if_boostlike(self) -> None:
        """Switch the converter box to a 12 V → 5 V, 10 W, 100 kHz
        flyback preset (TI UCC28780 EVM ballpark) when entering
        flyback from a boost-like spec. Mirrors the buck helper —
        we don't overwrite if the user has already moved off the
        boost defaults."""
        if self._values_look_like_boost_defaults():
            self.sp_vout.setValue(5.0)
            self.sp_pout.setValue(10.0)
            self.sp_fsw.setValue(100.0)

    def _build_input_box(self) -> QGroupBox:
        box = QGroupBox("AC INPUT")
        form = QFormLayout(box)
        self.sp_vin_min = self._dspin(50, 300, 85.0, 1.0, " Vrms")
        self.sp_vin_max = self._dspin(80, 300, 265.0, 1.0, " Vrms")
        self.sp_vin_nom = self._dspin(50, 300, 220.0, 1.0, " Vrms")
        self.sp_fline = self._dspin(40, 70, 50.0, 1.0, " Hz")
        form.addRow("Vin min (worst case):", self.sp_vin_min)
        form.addRow("Vin max:", self.sp_vin_max)
        form.addRow("Vin nominal:", self.sp_vin_nom)
        form.addRow("Line frequency:", self.sp_fline)
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
        box = QGroupBox("DC INPUT")
        form = QFormLayout(box)
        self.sp_vin_dc = self._dspin(1.0, 1000.0, 12.0, 0.1, " V")
        self.sp_vin_dc_min = self._dspin(1.0, 1000.0, 10.8, 0.1, " V")
        self.sp_vin_dc_max = self._dspin(1.0, 1000.0, 13.2, 0.1, " V")
        form.addRow("Vin DC nominal:", self.sp_vin_dc)
        form.addRow("Vin DC min (worst current):", self.sp_vin_dc_min)
        form.addRow("Vin DC max (worst ripple):", self.sp_vin_dc_max)
        return box

    def _build_converter_box(self) -> QGroupBox:
        box = QGroupBox("CONVERTER")
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
        form.addRow("Ripple (peak-to-peak):", self.sp_ripple)
        return box

    def _build_thermal_box(self) -> QGroupBox:
        box = QGroupBox("THERMAL / WINDOW")
        form = QFormLayout(box)
        self.sp_tamb = self._dspin(-20, 80, 40.0, 1.0, " °C")
        self.sp_tmax = self._dspin(60, 180, 125.0, 1.0, " °C")
        self.sp_ku = self._dspin(0.05, 0.7, 0.7, 0.01, "")
        self.sp_bsat_margin = self._dspin(0.0, 0.5, 0.20, 0.01, "")
        form.addRow("T ambient:", self.sp_tamb)
        form.addRow("T max winding:", self.sp_tmax)
        form.addRow("Ku max (window usage):", self.sp_ku)
        form.addRow("Bsat margin:", self.sp_bsat_margin)
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

    # ------------------------------------------------------------------
    # Modulation mutual-exclusion handlers
    # ------------------------------------------------------------------
    def _on_fsw_modulation_toggled(self, checked: bool) -> None:
        """When the fsw band turns on, turn off the load band.

        The Spec validator rejects specs with both bands set, but
        rejecting at validation time produces a confusing UX
        (recalc fails with a wall of error text). Better: enforce
        the exclusion at the UI layer so the radio-like behaviour
        is the only state the user ever sees.
        """
        if not checked:
            return
        if hasattr(self, "load_modulation_group") and self.load_modulation_group.is_enabled():
            self.load_modulation_group.set_enabled(False)

    def _on_load_modulation_toggled(self, checked: bool) -> None:
        """Mirror of ``_on_fsw_modulation_toggled`` — when the load
        band turns on, turn off the fsw band."""
        if not checked:
            return
        if hasattr(self, "modulation_group") and self.modulation_group.is_enabled():
            # Tap the checkbox so the group's own ``_on_toggle`` runs
            # and the body/derived-label collapse cleanly.
            self.modulation_group._chk_enabled.blockSignals(True)
            try:
                self.modulation_group._chk_enabled.setChecked(False)
            finally:
                self.modulation_group._chk_enabled.blockSignals(False)
            self.modulation_group._body.setVisible(False)
            self.modulation_group._derived_label.setText("")

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
            # Load-power band — same shape, sibling of the fsw band.
            self.load_modulation_group.from_modulation(spec.load_modulation)
            # Flyback-only fields: only populate when topology matches.
            # The spinbox values persist across topology toggles so a
            # user who experimented with flyback and switched away
            # finds their last settings on return.
            if spec.topology == "flyback":
                mode = (spec.flyback_mode or "dcm").lower()
                self.rb_flyback_ccm.setChecked(mode == "ccm")
                self.rb_flyback_dcm.setChecked(mode != "ccm")
                if spec.turns_ratio_n:
                    self.sp_turns_ratio.setValue(float(spec.turns_ratio_n))
                self.sp_window_split.setValue(float(spec.window_split_primary))
            # Interleaved-boost: pull n_interleave so the inline radio
            # matches the picker-dialog choice on project load.
            if spec.topology == "interleaved_boost_pfc":
                self._n_interleave = int(spec.n_interleave or 2)
                self.rb_interleave_3.setChecked(self._n_interleave == 3)
                self.rb_interleave_2.setChecked(self._n_interleave != 3)
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
        elif topo == "flyback":
            # Flyback shares the DC-input block with buck. Same
            # legacy-field placeholder strategy.
            vin_dc = self.sp_vin_dc.value()
            vin_dc_min = self.sp_vin_dc_min.value()
            vin_dc_max = self.sp_vin_dc_max.value()
            v_nom = vin_dc
            v_min_ac = vin_dc_min
            v_max_ac = vin_dc_max
            n_phases = 3
            i_rated = 2.2
            l_req = 10.0
            # The flyback-specific fields (``flyback_mode``,
            # ``turns_ratio_n``, ``window_split_primary``) are not
            # exposed in the current spec panel — they default to the
            # validator's ``None`` (engine picks the optimal turns
            # ratio at design time). The advanced section that surfaces
            # them is queued for the next UX pass.
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
        # Load-power band — sibling of fsw_modulation. Mutually
        # exclusive (the Spec validator + the UI sibling-toggle
        # both enforce it), so reaching here with BOTH non-None
        # would mean the user wired around the UI; safe path is
        # to drop the fsw band and keep the load band (the more
        # recently-toggled one wins via UI mutual-exclusion).
        try:
            load_modulation = self.load_modulation_group.to_modulation()
        except (ValueError, TypeError):
            load_modulation = None
        if fsw_modulation is not None and load_modulation is not None:
            fsw_modulation = None
        # Flyback-only fields. Only emit them when topology is flyback;
        # for any other topology the engine ignores them, but leaving
        # them at None keeps the spec snapshot small and the serialised
        # JSON honest about what the user actually configured.
        if topo == "flyback":
            flyback_mode = "ccm" if self.rb_flyback_ccm.isChecked() else "dcm"
            turns_ratio_n = self.sp_turns_ratio.value()
            window_split_primary = self.sp_window_split.value()
        else:
            flyback_mode = None
            turns_ratio_n = None
            window_split_primary = 0.45  # Spec default
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
            n_interleave=self._n_interleave,
            L_req_mH=l_req,
            I_rated_Arms=i_rated,
            Vin_dc_V=vin_dc,
            Vin_dc_min_V=vin_dc_min,
            Vin_dc_max_V=vin_dc_max,
            ripple_ratio=ripple_ratio,
            fsw_modulation=fsw_modulation,
            load_modulation=load_modulation,
            flyback_mode=flyback_mode,
            turns_ratio_n=turns_ratio_n,
            window_split_primary=window_split_primary,
        )
