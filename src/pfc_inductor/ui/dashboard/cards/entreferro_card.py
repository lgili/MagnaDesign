"""Entreferro card — 4 metrics in 2×2: A_L · B/B_sat · H_peak · Margem.

The previous layout exposed A_L / μ_eff / H_peak in a single row. ``μ_eff``
moved to the Detalhes Técnicos card (it's diagnostic for rolloff but
not a primary status signal); the freed slot now shows the
**saturation margin** as both an absolute B/B_sat ratio and a
percentage — the two numbers an engineer reads first to confirm a
design isn't sitting on the saturation knee.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QGridLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.widgets import Card, MetricCard


class _EntreferroBody(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(10)
        self.m_AL = MetricCard("A_L", "—", "nH/N²", compact=True)
        self.m_BBs = MetricCard("B / B_sat", "—", "T", compact=True)
        self.m_H = MetricCard("H_peak", "—", "Oe",
                              trend_better="lower", compact=True)
        self.m_margin = MetricCard("Margem sat.", "—", "%",
                                   trend_better="higher", compact=True)
        # 2×2 grid keeps the card squarish and exposes 4 facts at a
        # glance — was 1×3 with ``μ_eff`` in the middle slot.
        g.addWidget(self.m_AL, 0, 0)
        g.addWidget(self.m_BBs, 0, 1)
        g.addWidget(self.m_H, 1, 0)
        g.addWidget(self.m_margin, 1, 1)

    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        # A_L (nH/N²): L = A_L · N²  ⇒  A_L = L / N² (in nH/N²)
        L_nH = result.L_actual_uH * 1000.0
        A_L = L_nH / max(result.N_turns ** 2, 1)
        self.m_AL.set_value(f"{A_L:.0f}")

        # B / B_sat — pico de fluxo vs limite (mostra os dois números
        # juntos para o usuário ver "0.36 / 0.49" e julgar a folga).
        B = result.B_pk_T
        Bsat = result.B_sat_limit_T
        self.m_BBs.set_value(f"{B:.2f} / {Bsat:.2f}")

        self.m_H.set_value(f"{result.H_dc_peak_Oe:.1f}")

        # Saturation margin %: status ramp same as before, applied to
        # the dedicated tile so colour follows the number.
        margin = result.sat_margin_pct / 100.0
        self.m_margin.set_value(f"{result.sat_margin_pct:.1f}")
        if margin >= 0.30:
            self.m_margin.set_status("ok")
            self.m_BBs.set_status("ok")
        elif margin >= 0.15:
            self.m_margin.set_status("warn")
            self.m_BBs.set_status("warn")
        else:
            self.m_margin.set_status("err")
            self.m_BBs.set_status("err")
        # H_peak inherits the same status — purely informational tile.
        self.m_H.set_status(self.m_margin.status())

    def clear(self) -> None:
        for mc in (self.m_AL, self.m_BBs, self.m_H, self.m_margin):
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
