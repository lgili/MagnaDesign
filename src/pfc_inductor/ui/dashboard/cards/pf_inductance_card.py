"""``PFvsLCard`` — power factor vs choke / reactor inductance.

Live counterpart to the PDF's PF-vs-L curve. Sits on the Analysis
tab next to the L vs I card so the engineer reads two
complementary saturation views:

- **L vs I** (existing): "given the chosen design, how does the
  effective inductance hold up as the current rises?"
- **PF vs L** (this card): "what input power factor / source-side
  apparent power does each choice of L give me?" — the design-
  space view.

Boost-PFC topologies render an empty placeholder because the
active control loop sets PF ≈ 1 regardless of L. The card stays
mounted but harmlessly empty so the Analysis tab's row layout is
deterministic across topologies.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.physics import power_factor as pfm
from pfc_inductor.ui.theme import get_theme, on_theme_changed
from pfc_inductor.ui.widgets import Card
from pfc_inductor.ui.widgets.pf_inductance_chart import PFInductanceChart


class _PFvsLBody(QWidget):
    """Body of the PF-vs-L card: caption + chart + summary strip."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        caption = QLabel(
            "Estimated input power factor and source-side apparent "
            "power as a function of inductance. PF rises sharply "
            "with the first 'mH' of reactance and saturates past "
            "the diminishing-returns plateau."
        )
        caption.setProperty("role", "muted")
        caption.setWordWrap(True)
        v.addWidget(caption)

        self._chart = PFInductanceChart()
        self._chart.setMinimumHeight(220)
        v.addWidget(self._chart, 1)

        # Summary strip — three numeric labels: design PF, apparent
        # power S, and THD estimate. Reads "PF 0.91 · S 11.5 kVA ·
        # THD 25 %".
        self._strip = QFrame()
        self._strip.setObjectName("PFvsLSummary")
        strip_h = QHBoxLayout(self._strip)
        strip_h.setContentsMargins(0, 0, 0, 0)
        strip_h.setSpacing(12)
        self._lbl_pf = QLabel("PF —")
        self._lbl_S = QLabel("S —")
        self._lbl_thd = QLabel("THD —")
        for lbl in (self._lbl_pf, self._lbl_S, self._lbl_thd):
            lbl.setProperty("role", "metric")
            strip_h.addWidget(lbl)
        strip_h.addStretch(1)
        v.addWidget(self._strip)

        self._refresh_qss()
        on_theme_changed(self._refresh_qss)

    # ------------------------------------------------------------------
    def update_from_design(self, result: DesignResult, spec: Spec,
                            core: Core, wire: Wire,
                            material: Material) -> None:
        self._chart.update_from_design(
            result, spec, core, wire, material,
        )
        # Boost-PFC keeps the strip deliberately blank — PF ≈ 1 is
        # not meaningful as a "design metric" the user is choosing.
        if (
            spec.topology == "boost_ccm"
            or result.L_actual_uH <= 0
        ):
            self._lbl_pf.setText("PF  —")
            self._lbl_S.setText("S  —")
            self._lbl_thd.setText("THD  —")
            self._set_pf_tone(None)
            return
        L = float(result.L_actual_uH)
        pf = pfm.pf_at_L(spec, L)
        S_VA = pfm.apparent_power_VA(spec, L)
        thd_pct = pfm.thd_at_L(spec, L)
        self._lbl_pf.setText(f"PF  {pf:.2f}")
        self._lbl_S.setText(f"S  {S_VA / 1000.0:.1f} kVA")
        self._lbl_thd.setText(f"THD  {thd_pct:.0f} %")
        self._set_pf_tone(pf)

    def clear(self) -> None:
        self._chart.clear()
        self._lbl_pf.setText("PF  —")
        self._lbl_S.setText("S  —")
        self._lbl_thd.setText("THD  —")
        self._set_pf_tone(None)

    # ------------------------------------------------------------------
    def _set_pf_tone(self, pf: Optional[float]) -> None:
        """Tint the PF label with the same green/warning/danger
        thresholds that match standards-compliance practice:
        ≥ 0.92 is generally acceptable, ≥ 0.85 borderline,
        below that fails most utility connection rules."""
        p = get_theme().palette
        if pf is None:
            color = p.text
        elif pf >= 0.92:
            color = p.success
        elif pf >= 0.85:
            color = p.warning
        else:
            color = p.danger
        self._lbl_pf.setStyleSheet(
            f"color: {color}; font-weight: 600;",
        )

    def _refresh_qss(self) -> None:
        p = get_theme().palette
        self._strip.setStyleSheet(
            f"QFrame#PFvsLSummary {{"
            f"  background: transparent;"
            f"  border-top: 1px solid {p.border};"
            f"  padding-top: 6px;"
            f"}}"
            f"QLabel {{ color: {p.text}; font-size: 12px; }}"
        )


class PFvsLCard(Card):
    """Dashboard card wrapping :class:`PFInductanceChart`."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _PFvsLBody()
        super().__init__("Power factor vs inductance", body,
                          parent=parent)
        self._wbody = body

    def update_from_design(self, *args, **kwargs) -> None:
        self._wbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._wbody.clear()
