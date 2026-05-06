"""``MetricCard`` — compact tile with label, value, unit, and optional trend.

Used in dense KPI groups (Resumo do Projeto, Formas de Onda metrics row,
Entreferro). Numeric value uses the project monospace numeric face so
digits do not jitter when the value updates.
"""
from __future__ import annotations

from typing import Literal, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.ui.theme import get_theme, on_theme_changed

MetricStatus = Literal["ok", "warn", "err", "neutral"]


class MetricCard(QFrame):
    """Single-metric tile."""

    def __init__(
        self,
        label: str,
        value: str = "—",
        unit: str = "",
        *,
        trend_pct: Optional[float] = None,
        trend_better: Literal["lower", "higher"] = "lower",
        status: MetricStatus = "neutral",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)
        self.setStyleSheet(self._self_qss(status))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(2)

        # ---- label (caption) ------------------------------------------
        self._lbl = QLabel(label.upper())
        self._lbl.setProperty("role", "caption")
        outer.addWidget(self._lbl)

        # ---- value + unit row -----------------------------------------
        row = QHBoxLayout()
        row.setSpacing(4)
        row.setContentsMargins(0, 0, 0, 0)

        self._val = QLabel(value)
        self._val.setObjectName("MetricValue")
        font: QFont = self._val.font()
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFamilies([
            "JetBrains Mono", "SF Mono", "Menlo", "Cascadia Code",
            "Consolas", "monospace",
        ])
        font.setPixelSize(get_theme().type.title_lg + 2)
        font.setWeight(QFont.Weight.DemiBold)
        # ``QFont.setFeature`` for tabular-nums is Qt 6.7+ and requires a
        # ``QFont.Tag`` instance — best-effort try, no-op when unavailable.
        try:
            font.setFeature(QFont.Tag("tnum"), 1)  # type: ignore[attr-defined]
        except Exception:
            pass
        self._val.setFont(font)

        self._unit = QLabel(unit)
        self._unit.setProperty("role", "muted")

        row.addWidget(self._val, 0, Qt.AlignmentFlag.AlignBaseline)
        row.addWidget(self._unit, 0, Qt.AlignmentFlag.AlignBaseline)
        row.addStretch(1)
        outer.addLayout(row)

        # ---- trend chip (optional) ------------------------------------
        self._trend_lbl = QLabel("")
        self._trend_lbl.setProperty("role", "muted")
        outer.addWidget(self._trend_lbl)

        # State storage
        self._trend_better = trend_better
        self._status: MetricStatus = status
        self._trend_pct = trend_pct
        self.set_trend(trend_pct)
        on_theme_changed(self._refresh_qss)

    def _refresh_qss(self) -> None:
        """Re-apply inline QSS after a theme toggle."""
        self.setStyleSheet(self._self_qss(self._status))
        # Re-apply trend so colour follows the new palette.
        self.set_trend(self._trend_pct)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_value(self, value: str, unit: Optional[str] = None) -> None:
        self._val.setText(value)
        if unit is not None:
            self._unit.setText(unit)

    def set_status(self, status: MetricStatus) -> None:
        self._status = status
        self.setStyleSheet(self._self_qss(status))

    def set_trend(self, pct: Optional[float]) -> None:
        self._trend_pct = pct
        if pct is None:
            self._trend_lbl.setText("")
            self._trend_lbl.setStyleSheet("")
            return
        arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "•")
        text = f"{arrow} {pct:+.1f} %"
        # Determine "good" direction.
        if self._trend_better == "lower":
            good = pct < 0
        else:
            good = pct > 0
        p = get_theme().palette
        color = p.success if good else p.danger
        if pct == 0:
            color = p.text_muted
        self._trend_lbl.setText(text)
        self._trend_lbl.setStyleSheet(
            f"color: {color}; font-size: {get_theme().type.caption}px;"
            f"font-weight: {get_theme().type.medium};"
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _self_qss(status: MetricStatus) -> str:
        p = get_theme().palette
        # Left accent bar 3 px when status is non-neutral.
        if status == "ok":
            color = p.success
        elif status == "warn":
            color = p.warning
        elif status == "err":
            color = p.danger
        else:
            color = "transparent"
        return (
            f"QFrame#MetricCard {{"
            f"  background: {p.bg};"
            f"  border: 1px solid {p.border};"
            f"  border-left: 3px solid {color};"
            f"  border-radius: 8px;"
            f"}}"
        )
