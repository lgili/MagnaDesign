"""Validar tab — FEA + BH-loop + Compare quick-look.

Three cards stacked. Each card is a thin façade over an existing
dialog/feature so the inner-loop is "everything I need to *trust* the
design before exporting".
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.icons import icon as ui_icon
from pfc_inductor.ui.theme import get_theme
from pfc_inductor.ui.widgets import BHLoopChart, Card


class ValidarTab(QWidget):
    """Validar workspace tab.

    Signals
    -------
    fea_requested
        Emitted when the user clicks "Rodar validação FEM".
    bh_loop_requested
        Emitted when the user clicks "Mostrar B-H loop".
    compare_requested
        Emitted when the user clicks "Abrir comparativo".
    """

    fea_requested = Signal()
    compare_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        intro = QLabel(
            "Compare o projeto analítico contra simuladores de campo "
            "(FEMM/FEMMT) e veja a trajetória B–H no operating point. "
            "Use Comparativo para checar contra alternativas."
        )
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        outer.addWidget(self._build_fea_card())
        outer.addWidget(self._build_bh_card())
        outer.addWidget(self._build_compare_card())
        outer.addStretch(1)

        # State refreshed by ``update_from_design``.
        self._last_result: Optional[DesignResult] = None

    # ------------------------------------------------------------------
    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        self._last_result = result
        # Refresh the FEA summary line.
        self._fea_summary.setText(
            f"Spec atual: {spec.topology} · {spec.Pout_W:.0f} W · "
            f"L = {result.L_actual_uH:.0f} µH · ΔT = {result.T_rise_C:.0f} °C"
        )
        self._bh_summary.setText(
            f"H_pk = {result.H_dc_peak_Oe:.1f} Oe · B_pk = "
            f"{result.B_pk_T * 1000:.0f} mT · margem saturação = "
            f"{result.sat_margin_pct:.0f} %"
        )
        # Live B-H trajectory plot.
        self._bh_chart.update_from_design(result, core, material)

    def clear(self) -> None:
        self._fea_summary.setText("Aguardando cálculo…")
        self._bh_summary.setText("Aguardando cálculo…")
        self._bh_chart.clear()

    # ------------------------------------------------------------------
    def _build_fea_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Roda FEMM (toroide axissimétrico) ou FEMMT (EE/ETD/PQ) "
            "no design atual e devolve L_FEA, B_pk e perdas para "
            "comparar com a estimativa analítica.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        self._fea_summary = QLabel("Aguardando cálculo…")
        self._fea_summary.setStyleSheet(self._summary_qss())
        btn = QPushButton("Rodar validação FEM")
        btn.setProperty("class", "Secondary")
        btn.setIcon(ui_icon("cube", color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(
            "Resolve o problema magnético no operating point — leva "
            "alguns minutos. Bloqueia a UI até terminar."
        )
        btn.clicked.connect(self.fea_requested.emit)
        # Inline time estimate so the engineer doesn't click expecting
        # a sub-second response and then think the app froze. Kept as
        # a separate caption-styled label so it doesn't add a CTA-
        # weight competitor next to the button.
        time_hint = QLabel("≈ 2–5 min  ·  bloqueia a interface")
        time_hint.setStyleSheet(self._hint_qss())
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addSpacing(12)
        row.addWidget(time_hint)
        row.addStretch(1)
        v.addWidget(desc)
        v.addWidget(self._fea_summary)
        v.addLayout(row)
        return Card("Validação FEM", body)

    @staticmethod
    def _hint_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"color: {p.text_muted};"
            f"font-size: {t.caption}px;"
        )

    def _build_bh_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Trajetória do operating point sobre a curva B–H estática "
            "do material — envelope de rede, ripple no pico (quando "
            "presente) e linha de Bsat. Atualiza automaticamente após "
            "cada Recalcular.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        self._bh_summary = QLabel("Aguardando cálculo…")
        self._bh_summary.setStyleSheet(self._summary_qss())
        # Live chart embedded inline — no separate dialog.
        self._bh_chart = BHLoopChart()
        self._bh_chart.setMinimumHeight(260)
        v.addWidget(desc)
        v.addWidget(self._bh_summary)
        v.addWidget(self._bh_chart, 1)
        return Card("B–H loop no operating point", body)

    def _build_compare_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Compara este design lado a lado com até 3 alternativas. "
            "Diff colorido por métrica (verde melhor, vermelho pior). "
            "Útil quando você está em dúvida entre duas escolhas de "
            "material/núcleo/fio.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("Abrir comparativo")
        btn.setProperty("class", "Secondary")
        btn.setIcon(ui_icon("compare", color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.compare_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("Comparativo de designs", body)

    @staticmethod
    def _summary_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"color: {p.text}; font-family: {t.numeric_family};"
            f" font-size: {t.body_md}px; padding: 8px 0;"
        )
