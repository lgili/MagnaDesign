"""``LCurrentCard`` — inductance vs DC bias current saturation card.

Wraps :class:`LCurrentChart <pfc_inductor.ui.widgets.l_current_chart.LCurrentChart>`
in a dashboard ``Card``. Sits on the Analysis tab next to the B–H card
so the engineer reads the saturation story from two angles:

- **B–H** answers "where on the saturation knee are we?"
- **L vs I** answers "how much has the inductance fallen by the time
  the current hits I_pk?"

Both surface the same physical phenomenon (powder-core μ%(H) rolloff)
but the L vs I view is what the protection / control engineer
actually thinks about — the small-signal control loop sees L at the
operating point, not L₀.

The card adds a tiny summary strip below the chart so the rolloff
percentage reads at a glance without decoding the legend:
"L₀ 410 µH · L_op 383 µH · Rolloff 7 %".
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.physics import rolloff as rf
from pfc_inductor.ui.theme import get_theme, on_theme_changed
from pfc_inductor.ui.widgets import Card
from pfc_inductor.ui.widgets.l_current_chart import LCurrentChart


class _LCurrentBody(QWidget):
    """Body of the L-vs-I card: caption + chart + summary strip."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        caption = QLabel(
            "Effective inductance as a function of DC bias current. "
            "L drops from L₀ (zero-bias) toward saturation as the "
            "current rises through and past the operating point."
        )
        caption.setProperty("role", "muted")
        caption.setWordWrap(True)
        v.addWidget(caption)

        self._chart = LCurrentChart()
        # Same minimum height as ``BHLoopChart`` so the Analysis-tab
        # row reads with consistent vertical rhythm.
        self._chart.setMinimumHeight(220)
        v.addWidget(self._chart, 1)

        # Summary strip — three small numeric labels separated by
        # vertical bars. Reads "L₀ 410 µH · L_op 383 µH · Rolloff 7 %".
        self._strip = QFrame()
        self._strip.setObjectName("LCurrentSummary")
        strip_h = QHBoxLayout(self._strip)
        strip_h.setContentsMargins(0, 0, 0, 0)
        strip_h.setSpacing(12)
        self._lbl_l0 = QLabel("L₀ —")
        self._lbl_lop = QLabel("L_op —")
        self._lbl_rolloff = QLabel("Rolloff —")
        for lbl in (self._lbl_l0, self._lbl_lop, self._lbl_rolloff):
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
        # Compute L₀ + rolloff for the summary strip — the chart
        # widget computes the same numbers internally; here we
        # re-derive the two scalars so the strip is independent
        # (and stays synced when the chart silently bails because
        # the material lacks rolloff data).
        if material.rolloff is not None and result.N_turns > 0:
            mu0 = rf.mu_pct(material, 0.01)
            L0 = rf.inductance_uH(int(result.N_turns), core.AL_nH, mu0)
            L_op = float(result.L_actual_uH)
            rolloff_pct = (1.0 - L_op / L0) * 100.0 if L0 > 0 else 0.0
            self._lbl_l0.setText(f"L₀  {L0:.0f} µH")
            self._lbl_lop.setText(f"L_op  {L_op:.0f} µH")
            self._lbl_rolloff.setText(f"Rolloff  {rolloff_pct:.0f} %")
            self._set_rolloff_tone(rolloff_pct)
        else:
            self._lbl_l0.setText("L₀  —")
            self._lbl_lop.setText(f"L_op  {result.L_actual_uH:.0f} µH")
            self._lbl_rolloff.setText("Rolloff  —")
            self._set_rolloff_tone(None)

    def clear(self) -> None:
        self._chart.clear()
        self._lbl_l0.setText("L₀  —")
        self._lbl_lop.setText("L_op  —")
        self._lbl_rolloff.setText("Rolloff  —")
        self._set_rolloff_tone(None)

    # ------------------------------------------------------------------
    def _set_rolloff_tone(self, rolloff_pct: Optional[float]) -> None:
        """Tint the rolloff label based on the design's headroom.

        Inverse logic to the BH margin: more rolloff = worse, so
        ≤ 10 % is green, ≤ 25 % is warning, > 25 % is danger. The
        thresholds reflect the rule of thumb that powder-core PFC
        designs aim for ≤ 20 % rolloff at I_pk so the small-signal
        control loop's pole stays close to the design value.
        """
        p = get_theme().palette
        if rolloff_pct is None:
            color = p.text
        elif rolloff_pct <= 10:
            color = p.success
        elif rolloff_pct <= 25:
            color = p.warning
        else:
            color = p.danger
        self._lbl_rolloff.setStyleSheet(
            f"color: {color}; font-weight: 600;",
        )

    def _refresh_qss(self) -> None:
        p = get_theme().palette
        self._strip.setStyleSheet(
            f"QFrame#LCurrentSummary {{"
            f"  background: transparent;"
            f"  border-top: 1px solid {p.border};"
            f"  padding-top: 6px;"
            f"}}"
            f"QLabel {{ color: {p.text}; font-size: 12px; }}"
        )


class LCurrentCard(Card):
    """Dashboard card wrapping :class:`LCurrentChart`."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _LCurrentBody()
        super().__init__("Inductance vs current (saturation)", body, parent=parent)
        self._wbody = body

    def update_from_design(self, *args, **kwargs) -> None:
        self._wbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._wbody.clear()
