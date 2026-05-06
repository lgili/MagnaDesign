"""Entreferro card — 3 metrics: A_L, μ_eff, H_peak."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget, QGridLayout

from pfc_inductor.models import Spec, Material, Core, Wire, DesignResult
from pfc_inductor.ui.widgets import Card, MetricCard


class _EntreferroBody(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(10)
        self.m_AL = MetricCard("A_L", "—", "nH/N²")
        self.m_mu = MetricCard("μ_eff", "—", "")
        self.m_H = MetricCard("H_peak", "—", "Oe", trend_better="lower")
        g.addWidget(self.m_AL, 0, 0)
        g.addWidget(self.m_mu, 0, 1)
        g.addWidget(self.m_H, 0, 2)

    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        # A_L (nH/N²): L = A_L · N²  ⇒  A_L = L / N² (in nH/N²)
        L_nH = result.L_actual_uH * 1000.0
        A_L = L_nH / max(result.N_turns ** 2, 1)

        # μ_eff: percentage @ peak from rolloff curve.
        mu = result.mu_pct_at_peak

        self.m_AL.set_value(f"{A_L:.0f}")
        self.m_mu.set_value(f"{mu:.0f} %")
        self.m_H.set_value(f"{result.H_dc_peak_Oe:.1f}")

        # Saturation margin status applied to H_peak.
        margin = result.sat_margin_pct / 100.0
        if margin >= 0.30:
            self.m_H.set_status("ok")
        elif margin >= 0.15:
            self.m_H.set_status("warn")
        else:
            self.m_H.set_status("err")

    def clear(self) -> None:
        for mc in (self.m_AL, self.m_mu, self.m_H):
            mc.set_value("—")
            mc.set_status("neutral")


class EntreferroCard(Card):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _EntreferroBody()
        super().__init__("Entreferro", body, parent=parent)
        self._ebody = body

    def update_from_design(self, *args, **kwargs) -> None:
        self._ebody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._ebody.clear()
