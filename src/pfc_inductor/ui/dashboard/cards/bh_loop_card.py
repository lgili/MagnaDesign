"""``BHLoopCard`` — operating-point trajectory on the saturation curve.

Wraps :class:`BHLoopChart <pfc_inductor.ui.widgets.bh_loop_chart.BHLoopChart>`
in a dashboard ``Card`` so the Analysis tab can show flux behaviour as a
2-D B-H trajectory rather than just a 1-D B(t) line. The picture is
much more informative for an inductor designer:

- *Where* on the saturation curve the design is sitting (toe vs knee).
- *How wide* the line-cycle envelope sweeps in H.
- *How tall* the high-frequency ripple rides at the peak (ferrite vs
  powder shows a visibly different ripple amplitude).
- The dashed Bsat line + the danger-coloured peak marker make
  saturation margin readable in one glance.

The chart itself is owned by the existing widget; this card adds:

- A short title + 1-line caption so the engineer doesn't have to
  decode the legend on every glance.
- A tiny summary strip (B_pk / Bsat / margin) below the chart for
  the "I just want the number" workflow.
- Empty-state guard so the card doesn't show a half-rendered axes
  before the first ``update_from_design``.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.theme import get_theme, on_theme_changed
from pfc_inductor.ui.widgets import BHLoopChart, Card


class _BHLoopBody(QWidget):
    """Body of the BH-loop card: caption + chart + summary strip."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        caption = QLabel(
            "Operating-point trajectory over the material's static "
            "B–H curve — line envelope + peak ripple (when present). "
            "The dashed line is Bsat at 100 °C.",
        )
        caption.setProperty("role", "muted")
        caption.setWordWrap(True)
        v.addWidget(caption)

        self._chart = BHLoopChart()
        # 220 px is just enough for the legend to sit comfortably under
        # the curves without crowding the operating-point marker.
        self._chart.setMinimumHeight(220)
        v.addWidget(self._chart, 1)

        # Summary strip — three small numeric labels separated by
        # vertical bars. Reads as a sentence:
        # "B_pk = 220 mT  ·  Bsat = 320 mT  ·  Margem 31 %"
        self._strip = QFrame()
        self._strip.setObjectName("BHLoopSummary")
        strip_h = QHBoxLayout(self._strip)
        strip_h.setContentsMargins(0, 0, 0, 0)
        strip_h.setSpacing(12)
        self._lbl_bpk = QLabel("B_pk —")
        self._lbl_bsat = QLabel("Bsat —")
        self._lbl_margin = QLabel("Margem —")
        for lbl in (self._lbl_bpk, self._lbl_bsat, self._lbl_margin):
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
        # ``BHLoopChart`` only cares about result + core + material; the
        # other args are accepted for the cards' uniform signature.
        self._chart.update_from_design(result, core, material)

        # Summary strip — keep the engineer's eye on the saturation
        # margin even when they aren't reading the chart legend.
        b_pk_mT = result.B_pk_T * 1000.0
        b_sat_mT = result.B_sat_limit_T * 1000.0 if result.B_sat_limit_T > 0 else 0.0
        if b_sat_mT > 0:
            margin_pct = (b_sat_mT - b_pk_mT) / b_sat_mT * 100.0
            self._lbl_bpk.setText(f"B_pk  {b_pk_mT:.0f} mT")
            self._lbl_bsat.setText(f"Bsat  {b_sat_mT:.0f} mT")
            self._lbl_margin.setText(f"Margem  {margin_pct:.0f} %")
            self._set_margin_tone(margin_pct)
        else:
            self._lbl_bpk.setText(f"B_pk  {b_pk_mT:.0f} mT")
            self._lbl_bsat.setText("Bsat  —")
            self._lbl_margin.setText("Margem  —")
            self._set_margin_tone(None)

    def clear(self) -> None:
        self._chart.clear()
        self._lbl_bpk.setText("B_pk  —")
        self._lbl_bsat.setText("Bsat  —")
        self._lbl_margin.setText("Margem  —")
        self._set_margin_tone(None)

    # ------------------------------------------------------------------
    def _set_margin_tone(self, margin_pct: Optional[float]) -> None:
        """Tint the margin label based on saturation headroom.

        Mirrors the ``ResumoStrip`` policy: ≥ 30 % green, ≥ 15 %
        warning, otherwise danger. ``None`` reverts to the default
        text colour (engine couldn't compute Bsat).
        """
        p = get_theme().palette
        if margin_pct is None:
            color = p.text
        elif margin_pct >= 30:
            color = p.success
        elif margin_pct >= 15:
            color = p.warning
        else:
            color = p.danger
        self._lbl_margin.setStyleSheet(
            f"color: {color}; font-weight: 600;",
        )

    def _refresh_qss(self) -> None:
        p = get_theme().palette
        self._strip.setStyleSheet(
            f"QFrame#BHLoopSummary {{"
            f"  background: transparent;"
            f"  border-top: 1px solid {p.border};"
            f"  padding-top: 6px;"
            f"}}"
            f"QLabel {{ color: {p.text}; font-size: 12px; }}"
        )
        # Re-apply margin tone so theme-toggle keeps the colour.
        # The cached margin value isn't stored on the body; we recompute
        # at next ``update_from_design`` instead.


class BHLoopCard(Card):
    """Dashboard card wrapping :class:`BHLoopChart`."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _BHLoopBody()
        super().__init__("Magnetic flux (B–H)", body, parent=parent)
        self._wbody = body

    def update_from_design(self, *args, **kwargs) -> None:
        self._wbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._wbody.clear()
