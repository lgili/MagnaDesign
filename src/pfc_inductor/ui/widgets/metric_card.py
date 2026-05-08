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
        compact: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._compact = compact
        self.setStyleSheet(self._self_qss(status))

        outer = QVBoxLayout(self)
        # Compact tiles trim 6 px off each axis so a strip of 6 fits
        # into ~84 px of total height with the surrounding chrome.
        if compact:
            outer.setContentsMargins(10, 8, 10, 8)
            outer.setSpacing(0)
        else:
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
        font.setFamilies(
            [
                "JetBrains Mono",
                "SF Mono",
                "Menlo",
                "Cascadia Code",
                "Consolas",
                "monospace",
            ]
        )
        # Compact uses the title_md ramp (14 px) instead of title_lg+2 (18)
        # so values stay readable but the strip is half the height.
        if compact:
            font.setPixelSize(get_theme().type.title_md)
        else:
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
        # In compact mode the trend chip is hidden — there's no vertical
        # room. Callers can still call ``set_trend()``; the value is
        # cached and surfaced when the card is rebuilt non-compact.
        if not compact:
            outer.addWidget(self._trend_lbl)
        else:
            self._trend_lbl.hide()

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

    def status(self) -> MetricStatus:
        """Current status. Public read accessor — prefer this over
        accessing the private ``_status`` attribute from sibling widgets
        (e.g. :class:`~pfc_inductor.ui.widgets.resumo_strip.ResumoStrip`)."""
        return self._status

    def label_text(self) -> str:
        """Text of the caption label as currently shown (already
        upper-cased per the constructor). Public read accessor used by
        the strip's aggregate-status summary."""
        return self._lbl.text()

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
        # Card background uses ``surface`` (not ``bg``) so the tile
        # sits *above* the page background — without this the entire
        # KPI row blended into the page in dark mode and read as
        # blank white blocks (the page bg leaked through). Same fix
        # applied across other Card-like widgets that wrap this one.
        return (
            f"QFrame#MetricCard {{"
            f"  background: {p.surface};"
            f"  border: 1px solid {p.border};"
            f"  border-left: 3px solid {color};"
            f"  border-radius: 8px;"
            f"}}"
        )
