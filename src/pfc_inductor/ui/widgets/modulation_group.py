"""VFD-modulation sub-form embedded in the SpecPanel.

A collapsible group that lets the engineer flip on a switching-
frequency band for the design. When enabled, the engine routes
through :func:`pfc_inductor.modulation.eval_band` and the
worst-case / compliance / cascade surfaces honour the band.

UI shape
--------

::

    ☐  Variable fsw (VFD modulation)

    └── (revealed when checked):
        Profile:        [Uniform        ▼]
        fsw min:        [  4.0  ] kHz
        fsw max:        [ 25.0  ] kHz
        Eval points:    [   5  ]
        ┌── (RPM-band only) ──┐
        │ Pole pairs:    2    │
        │ RPM min:    1500    │
        │ RPM max:    4500    │
        └─────────────────────┘

Public API
----------

- :meth:`is_enabled` — True when the user has ticked the box.
- :meth:`to_modulation` — returns an ``FswModulation`` instance
  (or ``None`` when the box is unchecked) — what the SpecPanel
  passes to ``Spec.fsw_modulation``.
- :meth:`from_modulation` — reverse: populate the controls from
  a saved spec.
- Signal :attr:`changed` — fires on any sub-field edit so the
  parent SpecPanel's debounced recalc / dirty-tracking runs.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import FswModulation, ModulationProfile


# (key, label, hint) — keys map 1:1 to ``FswModulation.profile``.
PROFILE_CHOICES: tuple[tuple[ModulationProfile, str, str], ...] = (
    ("uniform", "Uniform sweep",
     "Sample evenly between fsw_min and fsw_max. Use when the "
     "modulator is a plain triangular sweep across the band."),
    ("triangular_dither", "Triangular dither (edge-weighted)",
     "Same fsw points as uniform, but the worst-case search "
     "restricts to the band edges — the dither spends most of its "
     "time near fsw_min / fsw_max."),
    ("rpm_band", "RPM band (compressor VFD)",
     "Derive the fsw band from the compressor RPM range × pole "
     "pairs. Use the RPM block below."),
)


class ModulationGroup(QGroupBox):
    """Collapsible Modulation sub-form. Defaults to disabled —
    legacy specs that don't use VFD ride through unchanged."""

    changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("MODULATION (VFD)", parent)
        self.setObjectName("ModulationGroup")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # ---- Master toggle -----------------------------------------
        self._chk_enabled = QCheckBox("Variable fsw — evaluate across a band")
        self._chk_enabled.setToolTip(
            "When checked, the engine evaluates the design at every "
            "fsw point in the band and aggregates the worst-case "
            "envelope. Default off — single-point design at fsw "
            "above.",
        )
        self._chk_enabled.toggled.connect(self._on_toggle)
        outer.addWidget(self._chk_enabled)

        # ---- Body (revealed when toggle is on) ---------------------
        self._body = QFrame()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.setSpacing(6)

        # Top-level fields (always visible inside the body).
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)

        self._cmb_profile = QComboBox()
        for key, label, tooltip in PROFILE_CHOICES:
            self._cmb_profile.addItem(label, key)
            idx = self._cmb_profile.count() - 1
            self._cmb_profile.setItemData(
                idx, tooltip, Qt.ItemDataRole.ToolTipRole,
            )
        self._cmb_profile.currentIndexChanged.connect(
            self._on_profile_changed,
        )
        form.addRow("Profile:", self._cmb_profile)

        self._sp_fsw_min = QDoubleSpinBox()
        self._sp_fsw_min.setRange(0.5, 1000.0)
        self._sp_fsw_min.setValue(4.0)
        self._sp_fsw_min.setSingleStep(0.5)
        self._sp_fsw_min.setDecimals(1)
        self._sp_fsw_min.setSuffix(" kHz")
        form.addRow("fsw min:", self._sp_fsw_min)

        self._sp_fsw_max = QDoubleSpinBox()
        self._sp_fsw_max.setRange(0.5, 1000.0)
        self._sp_fsw_max.setValue(25.0)
        self._sp_fsw_max.setSingleStep(0.5)
        self._sp_fsw_max.setDecimals(1)
        self._sp_fsw_max.setSuffix(" kHz")
        form.addRow("fsw max:", self._sp_fsw_max)

        self._sp_n_eval = QSpinBox()
        self._sp_n_eval.setRange(2, 50)
        self._sp_n_eval.setValue(5)
        self._sp_n_eval.setToolTip(
            "Number of fsw points the engine evaluates. 5 surfaces "
            "the worst-case envelope on a typical compressor band; "
            "bump to 10–20 for finer resolution at the cost of "
            "5×–20× the engine time.",
        )
        form.addRow("Eval points:", self._sp_n_eval)

        body_layout.addLayout(form)

        # ---- RPM-band block (revealed only for the rpm_band profile)
        self._rpm_box = QFrame()
        self._rpm_box.setFrameShape(QFrame.Shape.StyledPanel)
        rpm_form = QFormLayout(self._rpm_box)
        rpm_form.setContentsMargins(8, 6, 8, 6)
        rpm_form.setSpacing(4)

        self._sp_pole_pairs = QSpinBox()
        self._sp_pole_pairs.setRange(1, 20)
        self._sp_pole_pairs.setValue(2)
        self._sp_pole_pairs.setToolTip(
            "Motor pole pairs. 2 is typical for an appliance "
            "compressor (refrigerator / freezer); HVAC compressors "
            "are usually 2 or 3.",
        )
        rpm_form.addRow("Pole pairs:", self._sp_pole_pairs)

        self._sp_rpm_min = QDoubleSpinBox()
        self._sp_rpm_min.setRange(1.0, 50_000.0)
        self._sp_rpm_min.setValue(1500.0)
        self._sp_rpm_min.setSingleStep(100.0)
        self._sp_rpm_min.setDecimals(0)
        self._sp_rpm_min.setSuffix(" RPM")
        rpm_form.addRow("RPM min:", self._sp_rpm_min)

        self._sp_rpm_max = QDoubleSpinBox()
        self._sp_rpm_max.setRange(1.0, 50_000.0)
        self._sp_rpm_max.setValue(4500.0)
        self._sp_rpm_max.setSingleStep(100.0)
        self._sp_rpm_max.setDecimals(0)
        self._sp_rpm_max.setSuffix(" RPM")
        rpm_form.addRow("RPM max:", self._sp_rpm_max)

        body_layout.addWidget(self._rpm_box)

        # Hint shown only when RPM-band is active — derived fsw range.
        self._derived_label = QLabel("")
        self._derived_label.setProperty("role", "muted")
        self._derived_label.setWordWrap(True)
        body_layout.addWidget(self._derived_label)

        outer.addWidget(self._body)

        # Wire change signals on every editable control so the
        # parent's debounced recalc fires the same way the rest
        # of the SpecPanel's spinboxes already do.
        for spin in (
            self._sp_fsw_min, self._sp_fsw_max, self._sp_n_eval,
            self._sp_pole_pairs, self._sp_rpm_min, self._sp_rpm_max,
        ):
            spin.valueChanged.connect(self._on_field_changed)

        # Initial layout: master toggle off ⇒ body hidden.
        self._body.setVisible(False)
        self._rpm_box.setVisible(False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def is_enabled(self) -> bool:
        return self._chk_enabled.isChecked()

    def to_modulation(self) -> Optional[FswModulation]:
        """Return the band as a Pydantic model, or ``None`` when
        the master toggle is off.

        Raises ``ValueError`` (via Pydantic) if the inputs don't
        validate (e.g. fsw_max ≤ fsw_min). The caller catches this
        and surfaces the message in the status bar.
        """
        if not self._chk_enabled.isChecked():
            return None
        profile = self._current_profile()
        kwargs = {
            "fsw_min_kHz": float(self._sp_fsw_min.value()),
            "fsw_max_kHz": float(self._sp_fsw_max.value()),
            "profile": profile,
            "n_eval_points": int(self._sp_n_eval.value()),
        }
        if profile == "rpm_band":
            kwargs.update({
                "rpm_min": float(self._sp_rpm_min.value()),
                "rpm_max": float(self._sp_rpm_max.value()),
                "pole_pairs": int(self._sp_pole_pairs.value()),
            })
        return FswModulation(**kwargs)

    def from_modulation(self, mod: Optional[FswModulation]) -> None:
        """Reverse mapping — populate the controls from a saved
        spec. Called by ``SpecPanel.set_spec`` during File → Open."""
        # Block signals during the bulk write so the parent doesn't
        # see N intermediate ``changed`` emissions.
        self.blockSignals(True)
        try:
            if mod is None:
                self._chk_enabled.setChecked(False)
                self._body.setVisible(False)
                return
            self._chk_enabled.setChecked(True)
            self._sp_fsw_min.setValue(mod.fsw_min_kHz)
            self._sp_fsw_max.setValue(mod.fsw_max_kHz)
            self._sp_n_eval.setValue(mod.n_eval_points)
            self._select_profile(mod.profile)
            if mod.rpm_min is not None:
                self._sp_rpm_min.setValue(mod.rpm_min)
            if mod.rpm_max is not None:
                self._sp_rpm_max.setValue(mod.rpm_max)
            if mod.pole_pairs is not None:
                self._sp_pole_pairs.setValue(mod.pole_pairs)
            self._body.setVisible(True)
            self._refresh_rpm_visibility()
            self._refresh_derived_label()
        finally:
            self.blockSignals(False)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _on_toggle(self, checked: bool) -> None:
        self._body.setVisible(checked)
        self._refresh_rpm_visibility()
        self._refresh_derived_label()
        self.changed.emit()

    def _on_profile_changed(self, _idx: int) -> None:
        self._refresh_rpm_visibility()
        self._refresh_derived_label()
        self.changed.emit()

    def _on_field_changed(self, _value) -> None:
        self._refresh_derived_label()
        self.changed.emit()

    def _refresh_rpm_visibility(self) -> None:
        is_rpm = self._current_profile() == "rpm_band"
        # When RPM-band is active the manual fsw spinboxes are
        # informational only — the engine reads the RPM-derived
        # values. Disable rather than hide so the user can still
        # see what the active band evaluates to.
        for w in (self._sp_fsw_min, self._sp_fsw_max):
            w.setEnabled(not is_rpm)
        self._rpm_box.setVisible(is_rpm)
        if is_rpm:
            self._derive_fsw_from_rpm()

    def _derive_fsw_from_rpm(self) -> None:
        """Push the derived fsw band into the spinboxes so the
        user sees what range the engine will actually sweep."""
        from pfc_inductor.models import rpm_to_fsw
        rpm_min = float(self._sp_rpm_min.value())
        rpm_max = float(self._sp_rpm_max.value())
        pp = int(self._sp_pole_pairs.value())
        fsw_min = rpm_to_fsw(rpm_min, pp)
        fsw_max = rpm_to_fsw(rpm_max, pp)
        # Block signals so the spinbox-set doesn't fire ``changed``
        # twice (once here, once on user-action paths).
        for w, value in (
            (self._sp_fsw_min, fsw_min),
            (self._sp_fsw_max, fsw_max),
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
        points = mod.fsw_points_kHz()
        suffix = ""
        if mod.profile == "rpm_band" and mod.rpm_min and mod.rpm_max:
            suffix = (
                f"  ·  derived from "
                f"{mod.rpm_min:.0f}–{mod.rpm_max:.0f} RPM × "
                f"{mod.pole_pairs} poles"
            )
        self._derived_label.setText(
            f"≈ {len(points)} fsw points  ·  "
            f"{points[0]:.1f} → {points[-1]:.1f} kHz{suffix}",
        )

    def _current_profile(self) -> ModulationProfile:
        data = self._cmb_profile.currentData()
        if isinstance(data, str):
            return data  # type: ignore[return-value]
        return "uniform"

    def _select_profile(self, profile: str) -> None:
        for i in range(self._cmb_profile.count()):
            if self._cmb_profile.itemData(i) == profile:
                self._cmb_profile.setCurrentIndex(i)
                return
