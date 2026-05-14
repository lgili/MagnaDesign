"""Load-power modulation sub-form embedded in the SpecPanel.

Sibling of :class:`ModulationGroup
<pfc_inductor.ui.widgets.modulation_group.ModulationGroup>` for the
load-variation (Pout sweep) case. When the master checkbox is on,
the engine routes through
:func:`pfc_inductor.modulation.eval_load_band` and the Analysis tab
shows a band envelope of L / B / ΔT / losses vs Pout — useful for
compressor-VFD designs where the load swings 50–130 % naturally.

UI shape
--------

::

    ☐  Variable load (Pout sweep)

    └── (revealed when checked):
        Profile:           [Uniform        ▼]
        Pout min:          [ 300.0  ] W
        Pout max:          [ 780.0  ] W
        Eval points:       [   5  ]
        ┌── (compressor_swing only) ─┐
        │ Pout nominal:    600 W      │
        └─────────────────────────────┘

Public API
----------

- :meth:`is_enabled` — True when the user has ticked the box.
- :meth:`to_modulation` — returns a ``LoadModulation`` instance
  (or ``None`` when the box is unchecked) — what the SpecPanel
  passes to ``Spec.load_modulation``.
- :meth:`from_modulation` — reverse: populate the controls from
  a saved spec.
- Signal :attr:`changed` — fires on any sub-field edit so the
  parent SpecPanel's debounced recalc / dirty-tracking runs.

Mutual exclusion with the fsw band is enforced one layer up by
the Spec validator and by SpecPanel turning off the sibling
checkbox when this one comes on.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import LoadModulation, LoadProfile

# (key, label, hint) — keys map 1:1 to ``LoadModulation.profile``.
LOAD_PROFILE_CHOICES: tuple[tuple[LoadProfile, str, str], ...] = (
    (
        "uniform",
        "Uniform sweep",
        "Sample evenly between pout_min and pout_max. Use when "
        "the load just sweeps linearly across the range.",
    ),
    (
        "triangular_dither",
        "Triangular (edge-weighted)",
        "Same Pout points as uniform, but the worst-case search "
        "restricts to the band edges — the load spends most of "
        "its time near pout_min / pout_max.",
    ),
    (
        "compressor_swing",
        "Compressor 50–130 % swing",
        "IEC-60335 appliance-compressor application range. The "
        "engine fills pout_min = 0.5·nominal and pout_max = "
        "1.3·nominal from the Pout nominal field below.",
    ),
)


class LoadModulationGroup(QGroupBox):
    """Collapsible Load Modulation sub-form. Defaults to disabled."""

    changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("MODULATION (LOAD)", parent)
        self.setObjectName("LoadModulationGroup")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # ---- Master toggle -----------------------------------------
        self._chk_enabled = QCheckBox("Variable load — sweep Pout across a band")
        self._chk_enabled.setToolTip(
            "When checked, the engine evaluates the design at every "
            "Pout point in the band and aggregates the worst-case "
            "envelope. Default off — single-point design at the "
            "Pout above. Mutually exclusive with the fsw band."
        )
        self._chk_enabled.toggled.connect(self._on_toggle)
        outer.addWidget(self._chk_enabled)

        # ---- Body (revealed when toggle is on) ---------------------
        self._body = QFrame()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.setSpacing(6)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)

        self._cmb_profile = QComboBox()
        for key, label, tooltip in LOAD_PROFILE_CHOICES:
            self._cmb_profile.addItem(label, key)
            idx = self._cmb_profile.count() - 1
            self._cmb_profile.setItemData(idx, tooltip, Qt.ItemDataRole.ToolTipRole)
        self._cmb_profile.currentIndexChanged.connect(self._on_profile_changed)
        form.addRow("Profile:", self._cmb_profile)

        self._sp_pout_min = QDoubleSpinBox()
        self._sp_pout_min.setRange(0.1, 100_000.0)
        self._sp_pout_min.setValue(300.0)
        self._sp_pout_min.setSingleStep(10.0)
        self._sp_pout_min.setDecimals(1)
        self._sp_pout_min.setSuffix(" W")
        form.addRow("Pout min:", self._sp_pout_min)

        self._sp_pout_max = QDoubleSpinBox()
        self._sp_pout_max.setRange(0.1, 100_000.0)
        self._sp_pout_max.setValue(780.0)
        self._sp_pout_max.setSingleStep(10.0)
        self._sp_pout_max.setDecimals(1)
        self._sp_pout_max.setSuffix(" W")
        form.addRow("Pout max:", self._sp_pout_max)

        self._sp_n_eval = QSpinBox()
        self._sp_n_eval.setRange(2, 50)
        self._sp_n_eval.setValue(5)
        self._sp_n_eval.setToolTip(
            "Number of Pout points the engine evaluates. 5 surfaces "
            "the worst-case envelope; 10–20 for finer resolution at "
            "the cost of 5×–20× the engine time."
        )
        form.addRow("Eval points:", self._sp_n_eval)

        body_layout.addLayout(form)

        # ---- compressor_swing block — visible only for that profile
        self._swing_box = QFrame()
        self._swing_box.setFrameShape(QFrame.Shape.StyledPanel)
        swing_form = QFormLayout(self._swing_box)
        swing_form.setContentsMargins(8, 6, 8, 6)
        swing_form.setSpacing(4)
        self._sp_pout_nominal = QDoubleSpinBox()
        self._sp_pout_nominal.setRange(0.1, 100_000.0)
        self._sp_pout_nominal.setValue(600.0)
        self._sp_pout_nominal.setSingleStep(10.0)
        self._sp_pout_nominal.setDecimals(1)
        self._sp_pout_nominal.setSuffix(" W")
        self._sp_pout_nominal.setToolTip(
            "Compressor nominal load. The 50–130 % swing band fills "
            "in pout_min and pout_max automatically."
        )
        swing_form.addRow("Pout nominal:", self._sp_pout_nominal)
        body_layout.addWidget(self._swing_box)

        # Hint shown when the band is set — summarises the actual
        # eval grid the engine will use.
        self._derived_label = QLabel("")
        self._derived_label.setProperty("role", "muted")
        self._derived_label.setWordWrap(True)
        body_layout.addWidget(self._derived_label)

        outer.addWidget(self._body)

        for spin in (
            self._sp_pout_min,
            self._sp_pout_max,
            self._sp_n_eval,
            self._sp_pout_nominal,
        ):
            spin.valueChanged.connect(self._on_field_changed)

        # Initial layout: master toggle off ⇒ body hidden.
        self._body.setVisible(False)
        self._swing_box.setVisible(False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def is_enabled(self) -> bool:
        return self._chk_enabled.isChecked()

    def set_enabled(self, enabled: bool) -> None:
        """Programmatic toggle — used by SpecPanel to enforce mutual
        exclusion with the fsw modulation group (when fsw turns on,
        load turns off, and vice versa)."""
        # Block signals so the sibling-toggle doesn't ping-pong.
        self._chk_enabled.blockSignals(True)
        try:
            self._chk_enabled.setChecked(enabled)
            self._body.setVisible(enabled)
            self._refresh_swing_visibility()
        finally:
            self._chk_enabled.blockSignals(False)

    def to_modulation(self) -> Optional[LoadModulation]:
        """Return the band as a Pydantic model, or ``None`` when
        the master toggle is off."""
        if not self._chk_enabled.isChecked():
            return None
        profile = self._current_profile()
        kwargs = {
            "pout_min_W": float(self._sp_pout_min.value()),
            "pout_max_W": float(self._sp_pout_max.value()),
            "profile": profile,
            "n_eval_points": int(self._sp_n_eval.value()),
        }
        if profile == "compressor_swing":
            kwargs["pout_nominal_W"] = float(self._sp_pout_nominal.value())
        return LoadModulation(**kwargs)

    def from_modulation(self, mod: Optional[LoadModulation]) -> None:
        """Reverse mapping — populate controls from a saved spec."""
        self.blockSignals(True)
        try:
            if mod is None:
                self._chk_enabled.setChecked(False)
                self._body.setVisible(False)
                return
            self._chk_enabled.setChecked(True)
            self._sp_pout_min.setValue(mod.pout_min_W)
            self._sp_pout_max.setValue(mod.pout_max_W)
            self._sp_n_eval.setValue(mod.n_eval_points)
            self._select_profile(mod.profile)
            if mod.pout_nominal_W is not None:
                self._sp_pout_nominal.setValue(mod.pout_nominal_W)
            self._body.setVisible(True)
            self._refresh_swing_visibility()
            self._refresh_derived_label()
        finally:
            self.blockSignals(False)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _on_toggle(self, checked: bool) -> None:
        self._body.setVisible(checked)
        self._refresh_swing_visibility()
        self._refresh_derived_label()
        self.changed.emit()

    def _on_profile_changed(self, _idx: int) -> None:
        self._refresh_swing_visibility()
        self._refresh_derived_label()
        self.changed.emit()

    def _on_field_changed(self, _value) -> None:
        self._refresh_swing_visibility()
        self._refresh_derived_label()
        self.changed.emit()

    def _refresh_swing_visibility(self) -> None:
        is_swing = self._current_profile() == "compressor_swing"
        # For compressor_swing the pout_min/max spinboxes are
        # informational only — the engine reads the nominal-derived
        # values. Disable rather than hide so the user can still see
        # what the active band evaluates to.
        for w in (self._sp_pout_min, self._sp_pout_max):
            w.setEnabled(not is_swing)
        self._swing_box.setVisible(is_swing)
        if is_swing:
            self._derive_pout_from_nominal()

    def _derive_pout_from_nominal(self) -> None:
        """Push the 50–130 % swing band into the spinboxes so the
        user sees what range the engine will actually sweep."""
        nominal = float(self._sp_pout_nominal.value())
        pout_min = nominal * 0.5
        pout_max = nominal * 1.3
        for w, value in (
            (self._sp_pout_min, pout_min),
            (self._sp_pout_max, pout_max),
        ):
            w.blockSignals(True)
            try:
                w.setValue(value)
            finally:
                w.blockSignals(False)

    def _refresh_derived_label(self) -> None:
        if not self._chk_enabled.isChecked():
            self._derived_label.setText("")
            return
        try:
            mod = self.to_modulation()
        except (ValueError, TypeError) as exc:
            self._derived_label.setText(f"⚠ Invalid band: {exc}")
            return
        if mod is None:
            self._derived_label.setText("")
            return
        points = mod.pout_points_W()
        suffix = ""
        if mod.profile == "compressor_swing" and mod.pout_nominal_W:
            suffix = f"  ·  50–130 % of {mod.pout_nominal_W:.0f} W"
        self._derived_label.setText(
            f"≈ {len(points)} Pout points  ·  "
            f"{points[0]:.0f} → {points[-1]:.0f} W{suffix}"
        )

    def _current_profile(self) -> LoadProfile:
        data = self._cmb_profile.currentData()
        if isinstance(data, str):
            return data  # type: ignore[return-value]
        return "uniform"

    def _select_profile(self, profile: str) -> None:
        for i in range(self._cmb_profile.count()):
            if self._cmb_profile.itemData(i) == profile:
                self._cmb_profile.setCurrentIndex(i)
                return
