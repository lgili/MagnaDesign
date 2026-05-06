"""Formas de Onda card — current waveform plot + 4 metric tiles."""
from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from pfc_inductor.models import Spec, Material, Core, Wire, DesignResult
from pfc_inductor.ui.widgets import Card, MetricCard
from pfc_inductor.ui.theme import get_theme


def _figure_imports():
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
    from matplotlib.figure import Figure
    return Canvas, Figure


class _FormasOndaBody(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        Canvas, Figure = _figure_imports()
        p = get_theme().palette
        self._fig = Figure(figsize=(4.0, 1.6), dpi=100,
                           facecolor=p.surface, tight_layout=True)
        self._ax = self._fig.add_subplot(1, 1, 1)
        self._canvas = Canvas(self._fig)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        outer.addWidget(self._canvas, 1)

        # ---- 4 small metric tiles ------------------------------------
        row = QHBoxLayout()
        row.setSpacing(8)
        self.m_Irms = MetricCard("Irms", "—", "A")
        self.m_Ipk = MetricCard("Ipk", "—", "A")
        self.m_THD = MetricCard("THD", "—", "%")
        self.m_CF = MetricCard("Crest", "—", "")
        for mc in (self.m_Irms, self.m_Ipk, self.m_THD, self.m_CF):
            row.addWidget(mc)
        outer.addLayout(row)

    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        self._render_waveform(result)
        self.m_Irms.set_value(f"{result.I_rms_total_A:.2f}")
        self.m_Ipk.set_value(f"{result.I_pk_max_A:.2f}")
        if result.thd_estimate_pct is not None:
            self.m_THD.set_value(f"{result.thd_estimate_pct:.0f}")
        else:
            self.m_THD.set_value("—")
        if result.I_rms_total_A > 1e-9:
            cf = result.I_pk_max_A / result.I_rms_total_A
            self.m_CF.set_value(f"{cf:.2f}")
        else:
            self.m_CF.set_value("—")

    def clear(self) -> None:
        self._ax.clear()
        self._canvas.draw_idle()
        for mc in (self.m_Irms, self.m_Ipk, self.m_THD, self.m_CF):
            mc.set_value("—")

    # ------------------------------------------------------------------
    def _render_waveform(self, result: DesignResult) -> None:
        p = get_theme().palette
        self._ax.clear()
        self._ax.set_facecolor(p.surface)
        if result.waveform_t_s and result.waveform_iL_A:
            t = np.array(result.waveform_t_s) * 1e3  # ms
            i = np.array(result.waveform_iL_A)
            self._ax.plot(t, i, color=p.accent, linewidth=1.4)
            self._ax.axhline(0, color=p.border, linewidth=0.6, linestyle="--")
            self._ax.set_xlabel("t (ms)", fontsize=8, color=p.text_muted)
            self._ax.set_ylabel("iL (A)", fontsize=8, color=p.text_muted)
        for spine in ("top", "right"):
            self._ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            self._ax.spines[spine].set_color(p.border)
        self._ax.tick_params(colors=p.text_muted, labelsize=8, length=3)
        self._ax.grid(True, color=p.border, linewidth=0.4, alpha=0.6)
        self._canvas.draw_idle()


class FormasOndaCard(Card):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _FormasOndaBody()
        super().__init__("Formas de Onda", body, parent=parent)
        self._wbody = body

    def update_from_design(self, *args, **kwargs) -> None:
        self._wbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._wbody.clear()
