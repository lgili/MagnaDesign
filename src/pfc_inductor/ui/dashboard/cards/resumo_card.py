"""Project Summary card — 6 metric tiles + aggregate status pill."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QGridLayout, QVBoxLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.widgets import Card, MetricCard, MetricStatus


def _status_for_b(B_pk_T: float, B_sat_T: float) -> MetricStatus:
    if B_sat_T <= 0:
        return "neutral"
    margin = (B_sat_T - B_pk_T) / B_sat_T
    if margin >= 0.30:
        return "ok"
    if margin >= 0.15:
        return "warn"
    return "err"


def _status_for_temp(T_C: float) -> MetricStatus:
    if T_C <= 90:
        return "ok"
    if T_C <= 110:
        return "warn"
    return "err"


def _status_for_fill(Ku_actual: float, Ku_max: float) -> MetricStatus:
    if Ku_max <= 0:
        return "neutral"
    pct = Ku_actual / Ku_max
    if pct <= 0.85:
        return "ok"
    if pct <= 1.0:
        return "warn"
    return "err"


class _ResumoBody(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self.m_L = MetricCard("Inductance", "—", "µH")
        self.m_I = MetricCard("DC current", "—", "A")
        self.m_dI = MetricCard("Ripple", "—", "A pp")
        self.m_B = MetricCard("Peak flux", "—", "mT")
        self.m_T = MetricCard("ΔT winding", "—", "°C", trend_better="lower")
        self.m_P = MetricCard("Total losses", "—", "W", trend_better="lower")

        for r, c, mc in [
            (0, 0, self.m_L),
            (0, 1, self.m_I),
            (0, 2, self.m_dI),
            (1, 0, self.m_B),
            (1, 1, self.m_T),
            (1, 2, self.m_P),
        ]:
            grid.addWidget(mc, r, c)
        outer.addLayout(grid)

    def update_from_design(
        self, result: DesignResult, spec: Spec, core: Core, wire: Wire, material: Material
    ) -> None:
        self.m_L.set_value(f"{result.L_actual_uH:.0f}")
        self.m_I.set_value(f"{result.I_line_pk_A:.1f}")
        self.m_dI.set_value(f"{result.I_ripple_pk_pk_A:.2f}")
        self.m_B.set_value(f"{result.B_pk_T * 1000.0:.0f}")
        self.m_T.set_value(f"{result.T_rise_C:.0f}")
        self.m_P.set_value(f"{result.losses.P_total_W:.2f}")

        # Statuses
        self.m_B.set_status(_status_for_b(result.B_pk_T, result.B_sat_limit_T))
        self.m_T.set_status(_status_for_temp(result.T_winding_C))
        # Loss "ok" if < 5 % of input power, otherwise warn.
        target = max(spec.Pout_W, 1.0) * 0.05
        if result.losses.P_total_W <= target:
            self.m_P.set_status("ok")
        elif result.losses.P_total_W <= target * 2:
            self.m_P.set_status("warn")
        else:
            self.m_P.set_status("err")
        self.m_L.set_status("ok")
        self.m_I.set_status("ok")
        # Ripple: "warn" if exceeds 30 % of I_dc.
        if result.I_line_rms_A > 0:
            ripple_ratio = result.I_ripple_pk_pk_A / max(result.I_line_pk_A, 1e-6)
            self.m_dI.set_status("ok" if ripple_ratio <= 0.30 else "warn")
        else:
            self.m_dI.set_status("neutral")

    def aggregate_status(self) -> MetricStatus:
        statuses = [
            self.m_L._status,
            self.m_I._status,
            self.m_dI._status,
            self.m_B._status,
            self.m_T._status,
            self.m_P._status,
        ]
        if "err" in statuses:
            return "err"
        if "warn" in statuses:
            return "warn"
        return "ok"

    def clear(self) -> None:
        for mc in (self.m_L, self.m_I, self.m_dI, self.m_B, self.m_T, self.m_P):
            mc.set_value("—")
            mc.set_status("neutral")


class ResumoCard(Card):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _ResumoBody()
        super().__init__("Project Summary", body, badge="—", badge_variant="neutral", parent=parent)
        self._rbody = body

    def update_from_design(
        self, result: DesignResult, spec: Spec, core: Core, wire: Wire, material: Material
    ) -> None:
        self._rbody.update_from_design(result, spec, core, wire, material)
        agg = self._rbody.aggregate_status()
        if agg == "ok":
            self.set_badge("Pass", "success")
        elif agg == "warn":
            self.set_badge("Check", "warning")
        elif agg == "err":
            self.set_badge("Fail", "danger")
        else:
            self.set_badge("—", "neutral")

    def clear(self) -> None:
        self._rbody.clear()
        self.set_badge("—", "neutral")
