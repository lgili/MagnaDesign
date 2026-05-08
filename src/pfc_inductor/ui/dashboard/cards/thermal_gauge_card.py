"""``ThermalGaugeCard`` — visual heat budget for the inductor.

Replaces the buried ``T_winding_C`` scalar in the Detalhes card with a
graphical gauge that tells the engineer at a glance:

- **Where the design sits** on the T_amb → T_max axis.
- **How much margin** is left before T_max trips.
- **Whether the rise is dominated by Cu or core losses** (mini bar
  underneath, same colour scheme as :class:`PerdasCard`).

Visual: a horizontal gradient bar from cool (T_amb) to hot (T_max),
with a needle at T_winding. Three pills above the bar (Ambient /
Current / Limit) anchor the numeric values, and a short caption below
gives the headroom in °C and as a percentage of the ΔT span.

Why a custom-painted gauge instead of a plain progress bar
----------------------------------------------------------
``QProgressBar`` uses the platform palette and the dashboard theme
tokens don't apply consistently across light / dark; the bar reads as
"a generic progress widget" rather than "the design's thermal budget".
A hand-drawn gauge with the same gradient palette as the BH-loop
danger line keeps the visual language coherent across the Analysis
tab.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.theme import get_theme, on_theme_changed
from pfc_inductor.ui.widgets import Card

# Threshold (°C) of margin where the gauge tone flips. Mirrors the
# ResumoStrip's policy used for B-margin so the colour language stays
# consistent across the dashboard.
MARGIN_OK_C = 25.0
MARGIN_WARN_C = 10.0


class _ThermalGauge(QWidget):
    """Custom-painted horizontal thermal gauge.

    Logical layout (left → right): ``T_amb`` band, ``T_winding``
    needle, ``T_max`` band. Painted in two passes — gradient-filled
    rounded rectangle for the budget axis, then a needle + label for
    the current temperature.
    """

    BAR_HEIGHT = 18
    NEEDLE_HEIGHT = 26

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(48)
        self._t_amb: float = 25.0
        self._t_winding: Optional[float] = None
        self._t_max: float = 125.0
        on_theme_changed(self.update)

    def set_temperatures(self, t_amb: float, t_winding: Optional[float], t_max: float) -> None:
        self._t_amb = float(t_amb)
        self._t_winding = float(t_winding) if t_winding is not None else None
        self._t_max = float(t_max)
        self.update()

    # ------------------------------------------------------------------
    def paintEvent(self, _event):
        p = get_theme().palette
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        margin_x = 8.0
        bar_y = (h - self.BAR_HEIGHT) / 2.0 + 4.0
        bar_w = w - 2 * margin_x

        # ---- Gradient gauge bar -----------------------------------------
        # The gradient colour stops are picked so the eye reads
        # "comfortable → hot" without needing a legend. We anchor them
        # to fixed temperature ratios rather than to the spec's T_max
        # so the same design always paints the same colours regardless
        # of how generous T_max is.
        grad = QLinearGradient(margin_x, 0, margin_x + bar_w, 0)
        grad.setColorAt(0.00, QColor(p.success))  # cool
        grad.setColorAt(0.55, QColor(p.warning))  # warm
        grad.setColorAt(0.85, QColor(p.danger))  # hot
        grad.setColorAt(1.00, QColor(p.danger).darker(115))  # over

        bar_rect = QRectF(margin_x, bar_y, bar_w, self.BAR_HEIGHT)
        qp.setPen(QPen(QColor(p.border), 1.0))
        qp.setBrush(QBrush(grad))
        qp.drawRoundedRect(bar_rect, 6, 6)

        # ---- T_amb / T_max tick labels (left + right anchors) -----------
        font = QFont()
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.Medium)
        qp.setFont(font)
        qp.setPen(QPen(QColor(p.text_secondary), 1.0))
        amb_rect = QRectF(margin_x, bar_y + self.BAR_HEIGHT + 2, 60, 14)
        qp.drawText(
            amb_rect,
            int(Qt.AlignmentFlag.AlignLeft),
            f"{self._t_amb:.0f}°C",
        )
        max_rect = QRectF(margin_x + bar_w - 60, bar_y + self.BAR_HEIGHT + 2, 60, 14)
        qp.drawText(
            max_rect,
            int(Qt.AlignmentFlag.AlignRight),
            f"{self._t_max:.0f}°C",
        )

        # ---- Needle at T_winding ---------------------------------------
        if self._t_winding is None or self._t_max <= self._t_amb:
            return
        # Clamp so an over-temp design pins to the right edge instead
        # of painting outside the rect.
        t_clamped = max(self._t_amb, min(self._t_winding, self._t_max + 5))
        ratio = (t_clamped - self._t_amb) / (self._t_max - self._t_amb)
        needle_x = margin_x + ratio * bar_w
        needle_top = bar_y - 4
        needle_bot = bar_y + self.BAR_HEIGHT + 4

        # Needle: tall thin black line on top of the gauge so it's
        # visible against any gradient stop.
        qp.setPen(QPen(QColor(p.text), 2.4))
        qp.drawLine(int(needle_x), int(needle_top), int(needle_x), int(needle_bot))
        # Cap with a small filled circle for visual weight.
        qp.setBrush(QBrush(QColor(p.text)))
        qp.setPen(Qt.PenStyle.NoPen)
        qp.drawEllipse(int(needle_x - 4), int(needle_top - 4), 8, 8)


class _ThermalGaugeBody(QWidget):
    """Body of the Thermal Gauge card — gauge + summary pills + caption."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # Pills row — Ambiente / Atual / Limite with delta-T below.
        pills = QHBoxLayout()
        pills.setSpacing(8)
        self._pill_amb = self._make_pill("Ambient", "—")
        self._pill_now = self._make_pill("Current", "—", emphasised=True)
        self._pill_max = self._make_pill("Limit", "—")
        for col in (self._pill_amb, self._pill_now, self._pill_max):
            pills.addWidget(col, 1)
        v.addLayout(pills)

        # Gauge bar.
        self._gauge = _ThermalGauge()
        v.addWidget(self._gauge)

        # Margin caption.
        self._caption = QLabel("—")
        self._caption.setProperty("role", "muted")
        self._caption.setWordWrap(True)
        v.addWidget(self._caption)

        # Loss origin breakdown — short two-segment bar that says
        # whether the heat is mostly from copper or core. Cheap to
        # render with QSS and avoids a second matplotlib canvas.
        self._origin_strip = self._build_origin_strip()
        v.addWidget(self._origin_strip)

        on_theme_changed(self._refresh_qss)

    def _make_pill(self, caption: str, value: str, *, emphasised: bool = False) -> QFrame:
        """Three-stat pill: caption (small) + value (big)."""
        f = QFrame()
        f.setObjectName("ThermalPillEmphasised" if emphasised else "ThermalPill")
        col = QVBoxLayout(f)
        col.setContentsMargins(10, 6, 10, 6)
        col.setSpacing(2)
        cap = QLabel(caption)
        cap.setProperty("role", "muted")
        val = QLabel(value)
        val.setProperty("role", "metric")
        col.addWidget(cap)
        col.addWidget(val)
        # Stash the value label on the frame so we can update later.
        f._value_label = val  # type: ignore[attr-defined]
        return f

    def _build_origin_strip(self) -> QWidget:
        """Cu vs core split bar — a horizontal proportional rectangle."""
        wrap = QFrame()
        wv = QVBoxLayout(wrap)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.setSpacing(4)
        legend = QLabel("Heat origin: Cu  vs  Core")
        legend.setProperty("role", "muted")
        wv.addWidget(legend)

        bar = QFrame()
        bar.setObjectName("ThermalOriginBar")
        bar.setFixedHeight(10)
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(0)
        self._cu_seg = QFrame()
        self._cu_seg.setObjectName("ThermalCuSeg")
        self._core_seg = QFrame()
        self._core_seg.setObjectName("ThermalCoreSeg")
        bh.addWidget(self._cu_seg, 1)
        bh.addWidget(self._core_seg, 1)
        wv.addWidget(bar)
        return wrap

    # ------------------------------------------------------------------
    def update_from_design(
        self, result: DesignResult, spec: Spec, core: Core, wire: Wire, material: Material
    ) -> None:
        t_amb = float(spec.T_amb_C)
        t_max = float(spec.T_max_C)
        t_winding = float(result.T_winding_C)
        t_rise = float(result.T_rise_C)

        # Pills — values + tone of "Atual".
        self._pill_amb._value_label.setText(  # type: ignore[attr-defined]
            f"{t_amb:.0f} °C",
        )
        self._pill_now._value_label.setText(  # type: ignore[attr-defined]
            f"{t_winding:.0f} °C",
        )
        self._pill_max._value_label.setText(  # type: ignore[attr-defined]
            f"{t_max:.0f} °C",
        )

        # Gauge.
        self._gauge.set_temperatures(t_amb, t_winding, t_max)

        # Caption: "ΔT 53 °C · margin 38 °C before the limit (good)".
        margin_c = max(t_max - t_winding, 0.0)
        if margin_c >= MARGIN_OK_C:
            verdict = "good thermal margin"
        elif margin_c >= MARGIN_WARN_C:
            verdict = "tight margin — consider better cooling"
        else:
            verdict = "no margin — design does not meet T_max"
        self._caption.setText(
            f"ΔT_rise <b>{t_rise:.0f} °C</b> over ambient · "
            f"margin <b>{margin_c:.0f} °C</b> to T_max — {verdict}.",
        )

        # Recolour the "Atual" pill border in tone with the margin.
        self._set_pill_tone(self._pill_now, margin_c)

        # Origin split — proportional Cu vs core.
        cu_W = max(
            0.0, getattr(result.losses, "P_cu_dc_W", 0.0) + getattr(result.losses, "P_cu_ac_W", 0.0)
        )
        core_W = max(
            0.0,
            getattr(result.losses, "P_core_line_W", 0.0)
            + getattr(result.losses, "P_core_ripple_W", 0.0),
        )
        total = cu_W + core_W
        if total <= 1e-9:
            cu_ratio, core_ratio = 0.5, 0.5
        else:
            cu_ratio = cu_W / total
            core_ratio = core_W / total
        # Re-apply layout stretch via setStretch so the proportions
        # update each call.
        bar_layout = self._cu_seg.parent().layout()
        if bar_layout is not None:
            bar_layout.setStretch(0, max(int(cu_ratio * 1000), 1))
            bar_layout.setStretch(1, max(int(core_ratio * 1000), 1))
        self._refresh_qss()

    def clear(self) -> None:
        for pill in (self._pill_amb, self._pill_now, self._pill_max):
            pill._value_label.setText("—")  # type: ignore[attr-defined]
        self._gauge.set_temperatures(25.0, None, 125.0)
        self._caption.setText("—")
        self._set_pill_tone(self._pill_now, None)

    # ------------------------------------------------------------------
    def _set_pill_tone(self, pill: QFrame, margin_c: Optional[float]) -> None:
        p = get_theme().palette
        if margin_c is None:
            border = p.border
        elif margin_c >= MARGIN_OK_C:
            border = p.success
        elif margin_c >= MARGIN_WARN_C:
            border = p.warning
        else:
            border = p.danger
        pill.setStyleSheet(self._pill_qss(border, emphasised=True))

    def _refresh_qss(self) -> None:
        p = get_theme().palette
        self._pill_amb.setStyleSheet(self._pill_qss(p.border))
        self._pill_max.setStyleSheet(self._pill_qss(p.border))
        # Don't overwrite the emphasised pill's tonal border here.
        if not self._pill_now.styleSheet():
            self._pill_now.setStyleSheet(self._pill_qss(p.border, emphasised=True))
        self._cu_seg.setStyleSheet(
            f"QFrame#ThermalCuSeg {{ background: {p.accent};"
            f" border-top-left-radius: 5px;"
            f" border-bottom-left-radius: 5px; }}",
        )
        self._core_seg.setStyleSheet(
            f"QFrame#ThermalCoreSeg {{ background: {p.accent_violet};"
            f" border-top-right-radius: 5px;"
            f" border-bottom-right-radius: 5px; }}",
        )

    @staticmethod
    def _pill_qss(border_color: str, emphasised: bool = False) -> str:
        p = get_theme().palette
        bg = p.bg if not emphasised else p.surface
        weight = "1px" if not emphasised else "1.5px"
        return (
            f"QFrame {{"
            f"  background: {bg};"
            f"  border: {weight} solid {border_color};"
            f"  border-radius: 8px;"
            f"}}"
            f"QLabel {{ color: {p.text}; }}"
            f'QLabel[role="muted"] {{ color: {p.text_secondary};'
            f" font-size: 10px; font-weight: 500; }}"
            f'QLabel[role="metric"] {{ color: {p.text};'
            f" font-size: 18px; font-weight: 700; }}"
        )


class ThermalGaugeCard(Card):
    """Dashboard card showing the design's thermal budget as a gauge."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _ThermalGaugeBody()
        super().__init__("Thermal", body, parent=parent)
        self._wbody = body

    def update_from_design(self, *args, **kwargs) -> None:
        self._wbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._wbody.clear()
