"""Formas de Onda card — current waveform plot + 4 metric tiles.

The plot toggles between two traces — ``iL(t)`` (default, current
through the inductor) and ``B(t)`` (flux density). The B trace is
the engineer's diagnostic for "is this design near saturation
during ripple?" — previously the engine computed ``waveform_B_T``
but no UI surface showed it.
"""
from __future__ import annotations

from typing import Literal, Optional

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.theme import get_theme
from pfc_inductor.ui.widgets import Card, MetricCard

PlotTrace = Literal["iL", "B"]


def _figure_imports():
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
    from matplotlib.figure import Figure
    return Canvas, Figure


class _FormasOndaBody(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        Canvas, Figure = _figure_imports()
        p = get_theme().palette
        # NB: no ``figsize`` — the canvas inherits its size from the
        # surrounding layout and we want it to follow the v3 bento
        # row's available width, not a hard-coded 4×1.6 inch grid.
        # ``tight_layout=True`` still wraps the axes safely as the
        # widget resizes.
        self._fig = Figure(dpi=100, facecolor=p.surface, tight_layout=True)
        self._ax = self._fig.add_subplot(1, 1, 1)
        self._canvas = Canvas(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding,
                                   QSizePolicy.Policy.Expanding)
        # Preserve a usable plot height even when the card is short.
        self._canvas.setMinimumHeight(200)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        # ---- iL ↔ B(t) toggle ----------------------------------------
        # Pair of small text buttons above the canvas — checkable, only
        # one active at a time. Default trace is iL (the current is the
        # natural starting point for a designer); B is one click away
        # for "is the flux waveform near saturation?" inspection.
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(0)
        self._btn_iL = QPushButton("iL(t)")
        self._btn_B = QPushButton("B(t)")
        for btn in (self._btn_iL, self._btn_B):
            btn.setCheckable(True)
            btn.setProperty("class", "Tertiary")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(24)
            btn.setStyleSheet(self._toggle_qss())
        self._btn_iL.setChecked(True)
        self._btn_grp = QButtonGroup(self)
        self._btn_grp.setExclusive(True)
        self._btn_grp.addButton(self._btn_iL, 0)
        self._btn_grp.addButton(self._btn_B, 1)
        self._btn_grp.idToggled.connect(self._on_trace_toggled)
        toggle_row.addStretch(1)
        toggle_row.addWidget(self._btn_iL)
        toggle_row.addWidget(self._btn_B)
        outer.addLayout(toggle_row)

        outer.addWidget(self._canvas, 1)

        # State: which trace are we showing right now.
        self._trace: PlotTrace = "iL"
        # Cached last result so a toggle re-renders without re-running
        # the design.
        self._last_result: Optional[DesignResult] = None

        # ---- 4 small metric tiles ------------------------------------
        row = QHBoxLayout()
        row.setSpacing(8)
        self.m_Irms = MetricCard("Irms", "—", "A", compact=True)
        self.m_Ipk = MetricCard("Ipk", "—", "A", compact=True)
        self.m_THD = MetricCard("THD", "—", "%", compact=True)
        self.m_CF = MetricCard("Crest", "—", "", compact=True)
        for mc in (self.m_Irms, self.m_Ipk, self.m_THD, self.m_CF):
            row.addWidget(mc)
        outer.addLayout(row)

    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        self._last_result = result
        # Disable the B button if no flux waveform is computed (e.g.
        # the engine hasn't been extended to produce it for this
        # topology). The user still sees iL by default.
        has_B = bool(result.waveform_B_T)
        self._btn_B.setEnabled(has_B)
        if not has_B and self._trace == "B":
            self._btn_iL.setChecked(True)
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
        self._last_result = None
        for mc in (self.m_Irms, self.m_Ipk, self.m_THD, self.m_CF):
            mc.set_value("—")

    # ------------------------------------------------------------------
    def _on_trace_toggled(self, btn_id: int, checked: bool) -> None:
        if not checked:
            return
        self._trace = "iL" if btn_id == 0 else "B"
        if self._last_result is not None:
            self._render_waveform(self._last_result)

    def _render_waveform(self, result: DesignResult) -> None:
        p = get_theme().palette
        self._ax.clear()
        self._ax.set_facecolor(p.surface)

        # Pick the trace to draw based on the toggle's state. iL is
        # the default; B is shown when the user clicks the second
        # button AND the engine emitted ``waveform_B_T``.
        if self._trace == "B" and result.waveform_t_s and result.waveform_B_T:
            t = np.array(result.waveform_t_s) * 1e3  # ms
            y = np.array(result.waveform_B_T) * 1000.0  # mT
            color = p.accent_violet
            ylabel = "B (mT)"
            # Saturation guide line — engineers want to see the
            # ripple's worst excursion vs the limit.
            if result.B_sat_limit_T > 0:
                self._ax.axhline(
                    result.B_sat_limit_T * 1000.0,
                    color=p.danger, linewidth=0.8, linestyle=":",
                    alpha=0.7,
                )
            self._ax.plot(t, y, color=color, linewidth=1.6)
        elif result.waveform_t_s and result.waveform_iL_A:
            t = np.array(result.waveform_t_s) * 1e3  # ms
            y = np.array(result.waveform_iL_A)
            color = p.accent
            ylabel = "iL (A)"
            self._ax.plot(t, y, color=color, linewidth=1.6)
        else:
            ylabel = "iL (A)"

        self._ax.axhline(0, color=p.border, linewidth=0.6, linestyle="--")
        self._ax.set_xlabel("t (ms)", fontsize=10, color=p.text_secondary)
        self._ax.set_ylabel(ylabel, fontsize=10, color=p.text_secondary)
        for spine in ("top", "right"):
            self._ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            self._ax.spines[spine].set_color(p.border)
        self._ax.tick_params(colors=p.text_secondary, labelsize=10, length=3)
        self._ax.grid(True, color=p.border, linewidth=0.4, alpha=0.6)
        self._canvas.draw_idle()

    @staticmethod
    def _toggle_qss() -> str:
        p = get_theme().palette
        # Slim text buttons that read as a segmented control. Active
        # state inverts to accent so the chosen trace is unambiguous.
        return (
            f"QPushButton {{"
            f"  background: transparent;"
            f"  border: 1px solid {p.border};"
            f"  color: {p.text_secondary};"
            f"  padding: 2px 10px;"
            f"  font-size: 11px;"
            f"  border-radius: 0;"
            f"}}"
            f"QPushButton:checked {{"
            f"  background: {p.accent_subtle_bg};"
            f"  color: {p.accent_subtle_text};"
            f"  border-color: {p.accent};"
            f"}}"
            f"QPushButton:hover:!checked {{"
            f"  background: {p.bg};"
            f"}}"
        )


class FormasOndaCard(Card):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _FormasOndaBody()
        super().__init__("Formas de Onda", body, parent=parent)
        self._wbody = body

    def update_from_design(self, *args, **kwargs) -> None:
        self._wbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._wbody.clear()
