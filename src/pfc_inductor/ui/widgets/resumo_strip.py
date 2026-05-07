"""``ResumoStrip`` — horizontal 6-tile KPI bar without card chrome.

Replaces :class:`ResumoCard <pfc_inductor.ui.dashboard.cards.resumo_card>`
at the top of the Projeto bento. Same six metrics (L, I_dc, ripple,
B_pk, ΔT, Perdas) but laid out as a single 84 px-tall horizontal strip
so they stop competing with the Núcleo table for vertical real estate.

Aggregate status is shown as a Pill on the right edge — same colour
language as the v2 ``ResumoCard`` badge ("Aprovado" / "Verificar" /
"Reprovado"), driven by the worst per-tile status.
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.theme import ANIMATION, CARD_MIN, get_theme, on_theme_changed
from pfc_inductor.ui.widgets.metric_card import MetricCard, MetricStatus


# Status helpers — inlined here (instead of importing from
# ``dashboard.cards.resumo_card``) to keep ``ui.widgets`` independent
# from ``ui.dashboard``. Otherwise the chain
#   widgets.__init__ -> resumo_strip -> resumo_card -> dashboard.__init__
#   -> dashboard_page -> widgets.ResumoStrip
# closes a circular import. Keep these in lock-step with the original
# definitions in ``resumo_card.py``; both files document the thresholds.
def _status_for_b(B_pk_T: float, B_sat_T: float) -> MetricStatus:
    if B_sat_T <= 0:
        return "neutral"
    margin = (B_sat_T - B_pk_T) / B_sat_T
    if margin >= 0.30:
        return "ok"
    if margin >= 0.15:
        return "warn"
    return "err"


def _status_for_temp(T_C: float) -> MetricStatus:
    if T_C <= 90:
        return "ok"
    if T_C <= 110:
        return "warn"
    return "err"


def _finite_or_dash(
    value: float, fmt: str = "{:.0f}", clamp_max: float = 1e6
) -> str:
    """Format ``value`` defensively, falling back to ``"—"``.

    The engine occasionally emits ``inf``, ``nan`` or absurd magnitudes
    (e.g. ``η < 0`` or ``P_total > 1 MW``) when given an uninitialised
    spec or when its solver has diverged. Rendering those raw makes
    the KPI strip look broken; ``"—"`` communicates "no valid data"
    while preserving cell width.

    ``clamp_max`` is the upper limit beyond which we treat the number
    as nonsense — defaults to 1 000 000 for regular metrics, callers
    can tighten it (e.g. losses are clamped to 100 kW).
    """
    if not math.isfinite(value):
        return "—"
    if abs(value) > clamp_max:
        return "—"
    return fmt.format(value)


class ResumoStrip(QFrame):
    """6-tile horizontal KPI bar + aggregate status pill on the right.

    Designed to occupy a single full-width row (col-span 12) at the top
    of the Projeto dashboard. Fixed height so the 3-row bento below
    gets a predictable amount of vertical room.
    """

    # 80 px is just tall enough for the metric_compact tiles (64 px
    # content + 8/8 padding) and lets ProjetoPage breathe on a 768 px
    # laptop screen. Was 96 px in v3.4.
    HEIGHT = 80

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ResumoStrip")
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setStyleSheet(self._self_qss())

        h = QHBoxLayout(self)
        h.setContentsMargins(16, 8, 16, 8)
        h.setSpacing(12)

        self.m_L = MetricCard("Indutância", "—", "µH", compact=True)
        self.m_I = MetricCard("Corrente DC", "—", "A", compact=True)
        self.m_dI = MetricCard("Ripple", "—", "App", compact=True)
        self.m_B = MetricCard("B pico", "—", "mT", compact=True)
        self.m_T = MetricCard("ΔT", "—", "°C", compact=True,
                              trend_better="lower")
        self.m_P = MetricCard("Perdas", "—", "W", compact=True,
                              trend_better="lower")
        self._tiles = (
            self.m_L, self.m_I, self.m_dI, self.m_B, self.m_T, self.m_P,
        )
        for mc in self._tiles:
            mc.setMinimumSize(*CARD_MIN.metric_compact)
            h.addWidget(mc, 1)

        # Vertical separator before the aggregate badge.
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {get_theme().palette.border};")
        sep.setFixedWidth(1)
        h.addSpacing(4)
        h.addWidget(sep)
        h.addSpacing(8)

        self.badge = QLabel("—")
        self.badge.setProperty("class", "Pill")
        self.badge.setProperty("pill", "neutral")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)

        on_theme_changed(self._refresh_qss)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        # Defensive formatting: when the engine produces non-finite
        # numbers (uninitialised spec, divergent solver) or absurd
        # magnitudes (η = -834 516 %, P > 1 MW), render '—' instead of
        # the raw figure. Showing a 7-digit nonsense Wattage made the
        # ResumoStrip look broken — '—' communicates "no valid data
        # yet" cleanly while preserving cell width.
        self.m_L.set_value(_finite_or_dash(result.L_actual_uH, "{:.0f}"))
        self.m_I.set_value(_finite_or_dash(result.I_line_pk_A, "{:.1f}"))
        self.m_dI.set_value(_finite_or_dash(result.I_ripple_pk_pk_A, "{:.2f}"))
        self.m_B.set_value(_finite_or_dash(result.B_pk_T * 1000.0, "{:.0f}"))
        self.m_T.set_value(_finite_or_dash(result.T_rise_C, "{:.0f}"))
        self.m_P.set_value(_finite_or_dash(result.losses.P_total_W, "{:.2f}",
                                           clamp_max=1e5))

        # Statuses — same logic as ResumoCard for parity.
        self.m_B.set_status(_status_for_b(result.B_pk_T, result.B_sat_limit_T))
        self.m_T.set_status(_status_for_temp(result.T_winding_C))
        target = max(spec.Pout_W, 1.0) * 0.05
        if result.losses.P_total_W <= target:
            self.m_P.set_status("ok")
        elif result.losses.P_total_W <= target * 2:
            self.m_P.set_status("warn")
        else:
            self.m_P.set_status("err")
        self.m_L.set_status("ok")
        self.m_I.set_status("ok")
        if result.I_line_rms_A > 0:
            ratio = result.I_ripple_pk_pk_A / max(result.I_line_pk_A, 1e-6)
            self.m_dI.set_status("ok" if ratio <= 0.30 else "warn")
        else:
            self.m_dI.set_status("neutral")

        agg, reasons = self._aggregate_status()
        self._set_badge(agg, reasons)

    def flash_applied(self) -> None:
        """Brief violet outline on the strip that confirms a recalc /
        selection-apply just completed.

        Called by :class:`ProjetoPage <pfc_inductor.ui.workspace.projeto_page.ProjetoPage>`
        right after ``update_from_design`` fans out, so the user has
        an unambiguous visual anchor for "your change landed" instead
        of having to scan every tile to spot what shifted.
        """
        self.setProperty("flash", "true")
        st = self.style()
        st.unpolish(self)
        st.polish(self)
        self.update()
        QTimer.singleShot(ANIMATION.flash_ms, self._clear_flash)

    def _clear_flash(self) -> None:
        self.setProperty("flash", "false")
        st = self.style()
        st.unpolish(self)
        st.polish(self)
        self.update()

    def clear(self) -> None:
        for mc in self._tiles:
            mc.set_value("—")
            mc.set_status("neutral")
        self._set_badge("neutral", [])

    # ------------------------------------------------------------------
    def _aggregate_status(self) -> tuple[MetricStatus, list[str]]:
        # Use the public ``status()`` / ``label_text()`` accessors (added
        # in v3.x) instead of reaching into ``_status`` / ``_lbl.text()``
        # — keeps the cross-widget contract surface small.
        statuses = [(mc.status(), mc.label_text()) for mc in self._tiles]
        errors = [title for status, title in statuses if status == "err"]
        if errors:
            return "err", errors
        warnings = [title for status, title in statuses if status == "warn"]
        if warnings:
            return "warn", warnings
        return "ok", []

    def _set_badge(self, status: MetricStatus, reasons: list[str]) -> None:
        if status == "ok":
            text, variant = "Aprovado", "success"
        elif status == "warn":
            text, variant = "Verificar", "warning"
        elif status == "err":
            text, variant = "Reprovado", "danger"
        else:
            text, variant = "—", "neutral"

        # Truncate the inline reason summary so the badge can't grow
        # unbounded. Show up to 2 names + "+N" for the rest; the full
        # list is preserved on hover via the tooltip below.
        if reasons:
            if len(reasons) <= 2:
                text += " — " + " · ".join(reasons)
            else:
                text += " — " + " · ".join(reasons[:2]) + f" +{len(reasons) - 2}"
            self.badge.setToolTip("Atenção em: " + ", ".join(reasons))
        else:
            self.badge.setToolTip("")

        self.badge.setText(text)
        self.badge.setProperty("pill", variant)
        # Force re-evaluation of dynamic-property selectors.
        st = self.badge.style()
        st.unpolish(self.badge)
        st.polish(self.badge)
        self.badge.update()

    def _refresh_qss(self) -> None:
        self.setStyleSheet(self._self_qss())

    @staticmethod
    def _self_qss() -> str:
        p = get_theme().palette
        r = get_theme().radius
        return (
            f"QFrame#ResumoStrip {{"
            f"  background: {p.surface};"
            f"  border: 1px solid {p.border};"
            f"  border-radius: {r.card}px;"
            f"}}"
            # Flash state — applied for ANIMATION.flash_ms after each
            # update_from_design. We only change the **border** (1 →
            # 2 px, accent_violet) and keep the surface background
            # intact: the previous version tinted the strip with
            # ``accent_violet_subtle_bg`` which then cascaded into the
            # transparent-backed children, especially the danger badge
            # — leaving a sticky violet halo behind the "REPROVADO"
            # text in dark mode. A border-only flash reads as "fresh"
            # without contaminating any child.
            f"QFrame#ResumoStrip[flash=\"true\"] {{"
            f"  background: {p.surface};"
            f"  border: 2px solid {p.accent_violet};"
            f"  border-radius: {r.card}px;"
            f"}}"
        )
