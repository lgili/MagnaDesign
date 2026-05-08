"""Validate tab — FEA + BH-loop + Compare quick-look.

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
    """Validate workspace tab.

    Signals
    -------
    fea_requested
        Emitted when the user clicks "Run FEM validation".
    bh_loop_requested
        Emitted when the user clicks "Show B-H loop".
    compare_requested
        Emitted when the user clicks "Open comparator".
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
            "Compare the analytical design against field simulators "
            "(FEMM/FEMMT) and look at the B–H trajectory at the "
            "operating point. Use Comparator to check against "
            "alternatives."
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
            f"Current spec: {spec.topology} · {spec.Pout_W:.0f} W · "
            f"L = {result.L_actual_uH:.0f} µH · ΔT = {result.T_rise_C:.0f} °C"
        )
        self._bh_summary.setText(
            f"H_pk = {result.H_dc_peak_Oe:.1f} Oe · B_pk = "
            f"{result.B_pk_T * 1000:.0f} mT · saturation margin = "
            f"{result.sat_margin_pct:.0f} %"
        )
        # Live B-H trajectory plot.
        self._bh_chart.update_from_design(result, core, material)
        # Enable the FEM CTA now that there's a design to validate.
        self._set_fea_enabled(True)

    def clear(self) -> None:
        self._fea_summary.setText("Waiting for calculation…")
        self._bh_summary.setText("Waiting for calculation…")
        self._bh_chart.clear()
        self._last_result = None
        self._set_fea_enabled(False)

    def _set_fea_enabled(self, enabled: bool) -> None:
        """Gate the "Run FEM validation" button on whether there's a
        design to validate.

        Without this, a user clicking Validate before any Recalculate
        would press the FEM button and watch FEMMT crunch on a default
        / inconsistent spec — confusing wall-clock cost for no useful
        output. Disabled state shows a tooltip explaining the
        prerequisite.
        """
        btn = getattr(self, "_btn_fea", None)
        if btn is None:
            return
        btn.setEnabled(enabled)
        btn.setToolTip(
            "Solves the magnetic problem at the operating point — "
            "takes a few minutes. Blocks the UI until done."
            if enabled else
            "Calculate a design first (Ctrl+R) to enable FEM validation."
        )

    # ------------------------------------------------------------------
    def _build_fea_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Runs FEMM (axisymmetric toroid) or FEMMT (EE/ETD/PQ) on "
            "the current design and returns L_FEA, B_pk and losses to "
            "compare against the analytical estimate.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        self._fea_summary = QLabel("Waiting for calculation…")
        self._fea_summary.setStyleSheet(self._summary_qss())
        # Stored on ``self`` so ``_set_fea_enabled`` can toggle it
        # later — disabled until ``update_from_design`` runs at least
        # once.
        self._btn_fea = QPushButton("Run FEM validation")
        btn = self._btn_fea
        btn.setProperty("class", "Secondary")
        btn.setIcon(ui_icon("cube", color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setEnabled(False)         # gated until first design lands
        btn.setToolTip(
            "Calculate a design first (Ctrl+R) to enable FEM validation."
        )
        btn.clicked.connect(self.fea_requested.emit)
        # Inline time estimate so the engineer doesn't click expecting
        # a sub-second response and then think the app froze. Kept as
        # a separate caption-styled label so it doesn't add a CTA-
        # weight competitor next to the button.
        time_hint = QLabel("≈ 2–5 min  ·  blocks the UI")
        time_hint.setStyleSheet(self._hint_qss())
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addSpacing(12)
        row.addWidget(time_hint)
        row.addStretch(1)
        v.addWidget(desc)
        v.addWidget(self._fea_summary)
        v.addLayout(row)
        return Card("FEM validation", body)

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
            "Operating-point trajectory over the static B–H curve of "
            "the material — line envelope, ripple at the peak (when "
            "present) and Bsat line. Refreshes automatically after "
            "each Recalculate.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        self._bh_summary = QLabel("Waiting for calculation…")
        self._bh_summary.setStyleSheet(self._summary_qss())
        # Live chart embedded inline — no separate dialog.
        self._bh_chart = BHLoopChart()
        self._bh_chart.setMinimumHeight(260)
        v.addWidget(desc)
        v.addWidget(self._bh_summary)
        v.addWidget(self._bh_chart, 1)
        return Card("B–H loop at the operating point", body)

    def _build_compare_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Compares this design side by side with up to 3 "
            "alternatives. Per-metric coloured diff (green = better, "
            "red = worse). Useful when you're torn between two "
            "material / core / wire choices.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("Open comparator")
        btn.setProperty("class", "Secondary")
        btn.setIcon(ui_icon("compare", color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.compare_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("Design comparator", body)

    @staticmethod
    def _summary_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"color: {p.text}; font-family: {t.numeric_family};"
            f" font-size: {t.body_md}px; padding: 8px 0;"
        )
