"""Right-side result panel: KPI groups + warnings + status pill."""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QGroupBox,
    QScrollArea, QFrame,
)

from pfc_inductor.models import DesignResult
from pfc_inductor.physics import CostBreakdown


class ResultPanel(QWidget):
    """KPI groups for the active design.

    Visual hierarchy:
      - Header: feasibility pill + headline label.
      - KPI groups: one QGroupBox per logical area, with monospaced numerics.
      - Cost group hides automatically when no cost data is available.
      - Warnings group always present, with semantic pill colours.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._build()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        inner = QWidget()
        scroll.setWidget(inner)

        layout = QVBoxLayout(inner)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addLayout(self._build_header())
        layout.addWidget(self._build_inductance_box())
        layout.addWidget(self._build_currents_box())
        layout.addWidget(self._build_flux_box())
        layout.addWidget(self._build_loss_box())
        layout.addWidget(self._build_thermal_box())
        layout.addWidget(self._build_window_box())
        self.cost_box = self._build_cost_box()
        layout.addWidget(self.cost_box)
        self.cost_box.hide()
        layout.addWidget(self._build_warnings_box())
        layout.addStretch(1)

    def _build_header(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(8)

        title = QLabel("Resultado")
        title.setProperty("role", "title")
        h.addWidget(title)

        h.addStretch(1)

        self.l_pill = QLabel("—")
        self.l_pill.setProperty("pill", "neutral")
        h.addWidget(self.l_pill)
        return h

    @staticmethod
    def _kpi_row(form: QFormLayout, label: str, strong: bool = False) -> QLabel:
        lbl_caption = QLabel(label)
        lbl_caption.setProperty("role", "kpi-label")
        value = QLabel("—")
        value.setProperty("role", "kpi-value-strong" if strong else "kpi-value")
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.addRow(lbl_caption, value)
        return value

    def _build_inductance_box(self) -> QGroupBox:
        box = QGroupBox("INDUTÂNCIA E VOLTAS")
        form = QFormLayout(box)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(3)
        form.setContentsMargins(4, 2, 4, 2)
        self.l_required = self._kpi_row(form, "L necessária")
        self.l_actual   = self._kpi_row(form, "L atual (rolloff)", strong=True)
        self.l_n        = self._kpi_row(form, "Voltas N")
        self.l_mu       = self._kpi_row(form, "μ% no pico DC")
        # Line reactor extras (filled only when topology = line_reactor;
        # rows are hidden otherwise via row visibility toggle).
        self.l_pctZ     = self._kpi_row(form, "% Z atual")
        self.l_vdrop    = self._kpi_row(form, "Queda de tensão")
        self.l_thd      = self._kpi_row(form, "THD estimada")
        self._lr_form = form
        self._lr_rows = (self.l_pctZ, self.l_vdrop, self.l_thd)
        for w in self._lr_rows:
            w.setVisible(False)
            lbl = form.labelForField(w)
            if lbl is not None:
                lbl.setVisible(False)
        return box

    def _build_currents_box(self) -> QGroupBox:
        box = QGroupBox("CORRENTES")
        form = QFormLayout(box)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(3)
        form.setContentsMargins(4, 2, 4, 2)
        self.l_ipk_line   = self._kpi_row(form, "I pico de linha")
        self.l_irms_line  = self._kpi_row(form, "I RMS de linha")
        self.l_ripple_max = self._kpi_row(form, "Ripple máx pp")
        self.l_ipk_total  = self._kpi_row(form, "I pico total")
        self.l_irms_total = self._kpi_row(form, "I RMS total")
        return box

    def _build_flux_box(self) -> QGroupBox:
        box = QGroupBox("FLUXO MAGNÉTICO")
        form = QFormLayout(box)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(3)
        form.setContentsMargins(4, 2, 4, 2)
        self.l_h          = self._kpi_row(form, "H pico DC")
        self.l_b          = self._kpi_row(form, "B pico", strong=True)
        self.l_bsat       = self._kpi_row(form, "B limite (Bsat·(1−margem))")
        self.l_satmargin  = self._kpi_row(form, "Margem de saturação")
        return box

    def _build_loss_box(self) -> QGroupBox:
        box = QGroupBox("PERDAS")
        form = QFormLayout(box)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(3)
        form.setContentsMargins(4, 2, 4, 2)
        self.l_p_cu_dc      = self._kpi_row(form, "Cu DC")
        self.l_p_cu_ac      = self._kpi_row(form, "Cu AC (fsw)")
        self.l_p_core_line  = self._kpi_row(form, "Núcleo (rede)")
        self.l_p_core_ripple= self._kpi_row(form, "Núcleo (ripple)")
        self.l_p_total      = self._kpi_row(form, "Total", strong=True)
        return box

    def _build_thermal_box(self) -> QGroupBox:
        box = QGroupBox("TÉRMICO")
        form = QFormLayout(box)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(3)
        form.setContentsMargins(4, 2, 4, 2)
        self.l_trise = self._kpi_row(form, "ΔT")
        self.l_twind = self._kpi_row(form, "T enrolamento", strong=True)
        self.l_rdc   = self._kpi_row(form, "Rdc (na T final)")
        self.l_rac   = self._kpi_row(form, "Rac em fsw")
        return box

    def _build_window_box(self) -> QGroupBox:
        box = QGroupBox("JANELA / FABRICABILIDADE")
        form = QFormLayout(box)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(3)
        form.setContentsMargins(4, 2, 4, 2)
        self.l_ku = self._kpi_row(form, "Ku atual / máx")
        return box

    def _build_cost_box(self) -> QGroupBox:
        box = QGroupBox("CUSTO ESTIMADO (BOM)")
        form = QFormLayout(box)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(3)
        form.setContentsMargins(4, 2, 4, 2)
        self.l_cost_core  = self._kpi_row(form, "Núcleo")
        self.l_cost_wire  = self._kpi_row(form, "Cobre (fio)")
        self.l_cost_total = self._kpi_row(form, "Total", strong=True)
        self.l_cost_meta  = self._kpi_row(form, "Comprim. · massa fio")
        return box

    def _build_warnings_box(self) -> QGroupBox:
        box = QGroupBox("AVISOS")
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(6)
        self.l_warnings = QLabel("—")
        self.l_warnings.setWordWrap(True)
        self.l_warnings.setProperty("role", "muted")
        v.addWidget(self.l_warnings)
        return box

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update_result(self, r: DesignResult) -> None:
        from pfc_inductor.ui.theme import get_theme
        p = get_theme().palette

        # Header pill: feasibility status.
        if r.is_feasible():
            self.l_pill.setText("FACTÍVEL")
            self.l_pill.setProperty("pill", "success")
        else:
            self.l_pill.setText(f"⚠ {len(r.warnings)} AVISO(S)")
            self.l_pill.setProperty("pill", "danger")
        self._restyle(self.l_pill)

        # Inductance group. For line reactors L is in mH, not µH —
        # show the larger unit so the engineer doesn't read 970000 µH.
        is_line_reactor = r.pct_impedance_actual is not None
        if is_line_reactor:
            self.l_required.setText(f"{r.L_required_uH/1000:>7.2f} mH")
            self.l_actual.setText(f"{r.L_actual_uH/1000:>7.2f} mH")
        else:
            self.l_required.setText(f"{r.L_required_uH:>7.0f} µH")
            self.l_actual.setText(f"{r.L_actual_uH:>7.0f} µH")
        self.l_n.setText(f"{r.N_turns:>7d}")
        self.l_mu.setText(f"{r.mu_pct_at_peak*100:>6.1f} %")

        # Line-reactor specific rows: visible only for that topology.
        for w in self._lr_rows:
            w.setVisible(is_line_reactor)
            lbl = self._lr_form.labelForField(w)
            if lbl is not None:
                lbl.setVisible(is_line_reactor)
        if is_line_reactor:
            self.l_pctZ.setText(f"{r.pct_impedance_actual:>6.2f} %")
            self.l_vdrop.setText(f"{r.voltage_drop_pct:>6.2f} %")
            thd_color = (p.success if (r.thd_estimate_pct or 0) <= 25
                         else p.warning if (r.thd_estimate_pct or 0) <= 35
                         else p.danger)
            self.l_thd.setText(
                f"<span style='color:{thd_color}'>{r.thd_estimate_pct:>6.1f} %</span>"
            )

        # Currents
        self.l_ipk_line.setText(f"{r.I_line_pk_A:>7.2f} A")
        self.l_irms_line.setText(f"{r.I_line_rms_A:>7.2f} A")
        self.l_ripple_max.setText(f"{r.I_ripple_pk_pk_A:>7.2f} A")
        self.l_ipk_total.setText(f"{r.I_pk_max_A:>7.2f} A")
        self.l_irms_total.setText(f"{r.I_rms_total_A:>7.2f} A")

        # Flux
        self.l_h.setText(f"{r.H_dc_peak_Oe:>7.0f} Oe")
        self.l_b.setText(f"{r.B_pk_T*1000:>7.0f} mT")
        self.l_bsat.setText(f"{r.B_sat_limit_T*1000:>7.0f} mT")
        sat_color = (p.success if r.sat_margin_pct > 10
                     else p.warning if r.sat_margin_pct > 0
                     else p.danger)
        self.l_satmargin.setText(
            f"<span style='color:{sat_color}'>{r.sat_margin_pct:>6.1f} %</span>"
        )

        # Losses
        L = r.losses
        self.l_p_cu_dc.setText(f"{L.P_cu_dc_W:>7.2f} W")
        self.l_p_cu_ac.setText(f"{L.P_cu_ac_W:>7.3f} W")
        self.l_p_core_line.setText(f"{L.P_core_line_W:>7.3f} W")
        self.l_p_core_ripple.setText(f"{L.P_core_ripple_W:>7.3f} W")
        self.l_p_total.setText(f"{L.P_total_W:>7.2f} W")

        # Thermal
        t_color = (p.success if r.T_winding_C < 90
                   else p.warning if r.T_winding_C < 110
                   else p.danger)
        self.l_trise.setText(f"{r.T_rise_C:>7.1f} K")
        self.l_twind.setText(
            f"<span style='color:{t_color}'>{r.T_winding_C:>5.0f} °C</span>"
        )
        self.l_rdc.setText(f"{r.R_dc_ohm*1000:>7.1f} mΩ")
        self.l_rac.setText(f"{r.R_ac_ohm*1000:>7.1f} mΩ")

        # Window
        ku_color = p.success if r.Ku_actual <= r.Ku_max else p.danger
        self.l_ku.setText(
            f"<span style='color:{ku_color}'>{r.Ku_actual*100:>5.1f} %</span>"
            f"  /  {r.Ku_max*100:.0f} %"
        )

        # Warnings
        if r.warnings:
            html = "<br>".join(
                f'<span style="color:{p.danger}">●</span> {w}' for w in r.warnings
            )
            self.l_warnings.setText(html)
        else:
            self.l_warnings.setText(
                f'<span style="color:{p.success}">●</span> '
                f"Nenhum aviso. Design factível."
            )

    def set_cost(self, cost: CostBreakdown | None) -> None:
        if cost is None:
            self.cost_box.hide()
            return
        self.cost_box.show()
        cur = cost.currency
        self.l_cost_core.setText(f"{cur} {cost.core_cost:>6.2f}")
        self.l_cost_wire.setText(f"{cur} {cost.wire_cost:>6.2f}")
        self.l_cost_total.setText(f"{cur} {cost.total_cost:>6.2f}")
        self.l_cost_meta.setText(
            f"{cost.wire_length_m:>5.2f} m · {cost.wire_mass_g:>6.1f} g"
        )

    def refresh_theme(self) -> None:
        """Re-apply theme-dependent styling. Called on theme toggle."""
        # Re-paint pill so the dynamic property is re-evaluated.
        self._restyle(self.l_pill)

    @staticmethod
    def _restyle(w: QWidget):
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()
