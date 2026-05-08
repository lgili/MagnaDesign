"""``PowerInductanceCard`` — active power vs inductance saturation card.

Live counterpart to the PDF's ``Active power vs inductance —
saturation impact'' figure. Sits on the Analysis tab directly
below the L vs I card so the engineer reads the saturation
phenomenon in two complementary frames:

- **L vs I** (the card above): operating-point view — "what
  happens to the inductance as the bias current rises?"
- **P vs L** (this card): throughput view — "what happens to the
  active power as the inductance falls under saturation?"

Together they tell the complete saturation story: I rises → L
falls → PF degrades → P plateaus. The choke's whole job is to
contain that chain near the design point.

Boost-PFC topologies show a placeholder note (PF ≈ 1 by active
control, no saturation tapering); the card stays mounted but
harmlessly empty so the Analysis tab's row layout stays
deterministic across topologies.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.physics import power_factor as pfm
from pfc_inductor.ui.theme import get_theme, on_theme_changed
from pfc_inductor.ui.widgets import Card
from pfc_inductor.ui.widgets.power_inductance_chart import PowerInductanceChart


class _PowerInductanceBody(QWidget):
    """Body of the P vs L card: caption + chart + summary strip."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        caption = QLabel(
            "Active input power as a function of effective inductance, "
            "traced parametrically as the bias current sweeps from "
            "zero past I_pk into deep saturation. As L falls, PF "
            "degrades and the real-power throughput tapers — exactly "
            "the failure mode the choke is sized to contain."
        )
        caption.setProperty("role", "muted")
        caption.setWordWrap(True)
        v.addWidget(caption)

        self._chart = PowerInductanceChart()
        self._chart.setMinimumHeight(220)
        v.addWidget(self._chart, 1)

        # Summary strip: three numeric labels — operating L, operating
        # P, and the "P / I_rms × V_eff" headline ratio (= PF in
        # disguise) so the engineer reads the throughput efficiency
        # at a glance.
        self._strip = QFrame()
        self._strip.setObjectName("PowerInductanceSummary")
        strip_h = QHBoxLayout(self._strip)
        strip_h.setContentsMargins(0, 0, 0, 0)
        strip_h.setSpacing(12)
        self._lbl_lop = QLabel("L_op —")
        self._lbl_pop = QLabel("P_op —")
        self._lbl_ratio = QLabel("P / S —")
        for lbl in (self._lbl_lop, self._lbl_pop, self._lbl_ratio):
            lbl.setProperty("role", "metric")
            strip_h.addWidget(lbl)
        strip_h.addStretch(1)
        v.addWidget(self._strip)

        self._refresh_qss()
        on_theme_changed(self._refresh_qss)

    # ------------------------------------------------------------------
    def update_from_design(
        self, result: DesignResult, spec: Spec, core: Core, wire: Wire, material: Material
    ) -> None:
        self._chart.update_from_design(
            result,
            spec,
            core,
            wire,
            material,
        )
        if (
            spec.topology in ("boost_ccm", "interleaved_boost_pfc")
            or result.L_actual_uH <= 0
            or result.I_pk_max_A <= 0
        ):
            self._lbl_lop.setText("L_op  —")
            self._lbl_pop.setText("P_op  —")
            self._lbl_ratio.setText("P / S  —")
            self._set_ratio_tone(None)
            return
        L_op = float(result.L_actual_uH)
        I_pk = float(result.I_pk_max_A)
        P_op = pfm.active_power_at_inst_current_W(spec, L_op, I_pk)
        # P / S is exactly PF — but expressed here as a "throughput
        # efficiency" so the engineer reads "real power over apparent
        # power that the source has to push" rather than just PF.
        S_op = pfm.apparent_power_VA(spec, L_op)
        ratio = P_op / max(S_op, 1.0)
        self._lbl_lop.setText(f"L_op  {L_op:.0f} µH")
        self._lbl_pop.setText(f"P_op  {P_op / 1000.0:.1f} kW")
        self._lbl_ratio.setText(f"P / S  {ratio:.2f}")
        self._set_ratio_tone(ratio)

    def clear(self) -> None:
        self._chart.clear()
        self._lbl_lop.setText("L_op  —")
        self._lbl_pop.setText("P_op  —")
        self._lbl_ratio.setText("P / S  —")
        self._set_ratio_tone(None)

    # ------------------------------------------------------------------
    def _set_ratio_tone(self, ratio: Optional[float]) -> None:
        """``P / S`` is the input PF expressed as throughput
        efficiency. Use the same green/warning/danger thresholds
        the standalone PF strip uses (≥ 0.92 / ≥ 0.85 / below)."""
        p = get_theme().palette
        if ratio is None:
            color = p.text
        elif ratio >= 0.92:
            color = p.success
        elif ratio >= 0.85:
            color = p.warning
        else:
            color = p.danger
        self._lbl_ratio.setStyleSheet(
            f"color: {color}; font-weight: 600;",
        )

    def _refresh_qss(self) -> None:
        p = get_theme().palette
        self._strip.setStyleSheet(
            f"QFrame#PowerInductanceSummary {{"
            f"  background: transparent;"
            f"  border-top: 1px solid {p.border};"
            f"  padding-top: 6px;"
            f"}}"
            f"QLabel {{ color: {p.text}; font-size: 12px; }}"
        )


class PowerInductanceCard(Card):
    """Dashboard card wrapping :class:`PowerInductanceChart`."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _PowerInductanceBody()
        super().__init__("Active power vs inductance (saturation)", body, parent=parent)
        self._wbody = body

    def update_from_design(self, *args, **kwargs) -> None:
        self._wbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._wbody.clear()
