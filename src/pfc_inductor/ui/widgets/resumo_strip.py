"""``ResumoStrip`` — horizontal 6-tile KPI bar without card chrome.

Replaces :class:`ResumoCard <pfc_inductor.ui.dashboard.cards.resumo_card>`
at the top of the Project bento. Same six metrics (L, I_dc, ripple,
B_pk, ΔT, Losses) but laid out as a single 84 px-tall horizontal strip
so they stop competing with the Core table for vertical real estate.

Aggregate status is shown as a Pill on the right edge — same colour
language as the v2 ``ResumoCard`` badge ("Approved" / "Check" /
"Failed"), driven by the worst per-tile status.
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
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
    of the Project dashboard. Fixed height so the 3-row bento below
    gets a predictable amount of vertical room.
    """

    # Emitted when the "Fill in the spec" empty-state badge is clicked
    # — host (ProjetoPage) opens the SpecDrawer in response.
    spec_drawer_requested = Signal()
    # Emitted when the user clicks the badge while it shows
    # "Failed" or "Check" — host scrolls / switches to the
    # tab that explains *why* (the Analysis card with the failing
    # metric). String payload is the metric name (e.g. "ΔT", "B")
    # for future per-metric routing; the empty string means "no
    # specific metric, just take me to the analysis".
    failed_metric_clicked = Signal(str)

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

        self.m_L = MetricCard("Inductance", "—", "µH", compact=True)
        self.m_I = MetricCard("DC current", "—", "A", compact=True)
        self.m_dI = MetricCard("Ripple", "—", "App", compact=True)
        self.m_B = MetricCard("B peak", "—", "mT", compact=True)
        self.m_T = MetricCard("ΔT", "—", "°C", compact=True,
                              trend_better="lower")
        self.m_P = MetricCard("Losses", "—", "W", compact=True,
                              trend_better="lower")
        self._tiles = (
            self.m_L, self.m_I, self.m_dI, self.m_B, self.m_T, self.m_P,
        )
        for mc in self._tiles:
            # Width-only minimum so the strip can compress horizontally
            # if the window is narrow. ``setMinimumSize`` would pin
            # both axes and turn each row into an 80-px-tall block
            # even on tablets. ``CARD_MIN.metric_compact`` is the
            # canonical pair; we honour the width and let height stay
            # elastic.
            mc.setMinimumWidth(CARD_MIN.metric_compact[0])
            h.addWidget(mc, 1)

        # Vertical separator before the aggregate badge.
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {get_theme().palette.border};")
        sep.setFixedWidth(1)
        h.addSpacing(4)
        h.addWidget(sep)
        h.addSpacing(8)

        # Empty-state flag — strip starts in "pending" until the host
        # calls ``update_from_design``. While pending, the badge shows
        # the "fill spec" hint and is clickable. Initialised BEFORE
        # ``installEventFilter`` so the polish/show events that fire
        # during ``addWidget`` find the attribute defined.
        self._pending: bool = True
        # Worst-metric name (e.g. "ΔT", "B pico") cached when the
        # aggregate badge resolves to warning/danger. Surfaced via
        # ``failed_metric_clicked`` so the host can route to the
        # explanation. Empty string = no failing metric or pending.
        self._worst_metric: str = ""

        self.badge = QLabel("—")
        self.badge.setProperty("class", "Pill")
        self.badge.setProperty("pill", "neutral")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Cap the badge width so it doesn't push the strip past the
        # window edge when ``_set_badge`` appends a long reason
        # summary ("Failed — ΔT · Losses"). 160 px holds
        # "Fill in the spec" comfortably; longer status strings get
        # elided. The full text stays in the tooltip.
        self.badge.setMaximumWidth(160)
        self.badge.setMinimumWidth(110)
        # Make the badge clickable for the empty-state path (P0.B):
        # when the strip starts in "pending" mode, clicking the badge
        # emits ``spec_drawer_requested`` so the host can open the
        # drawer. The cursor change is a discoverability cue.
        self.badge.installEventFilter(self)
        h.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)

        # Apply the empty-state look now that all widgets exist.
        self.set_pending_state()

        on_theme_changed(self._refresh_qss)

    # ------------------------------------------------------------------
    # Empty-state path (P0.B)
    # ------------------------------------------------------------------
    def set_pending_state(self) -> None:
        """Render the "no design yet" empty state.

        Called once at construction and again whenever the host
        explicitly clears the strip. Tiles show ``—`` with neutral
        status; the badge becomes a clickable hint linking to the
        SpecDrawer (host wires the signal).
        """
        self._pending = True
        for mc in self._tiles:
            mc.set_value("—")
            mc.set_status("neutral")
        self.badge.setText("Fill in the spec")
        self.badge.setProperty("pill", "neutral")
        self.badge.setToolTip("Click to open the Spec drawer on the left.")
        self.badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self._poke_badge_style()

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if (
            obj is self.badge
            and event.type() == QEvent.Type.MouseButtonRelease
        ):
            if self._pending:
                self.spec_drawer_requested.emit()
                return True
            # Failed-design path (P1.H): user clicks the
            # "Failed" / "Check" badge to ask "where did I fail?".
            # Pass the *worst* metric name (cached by ``_set_badge``)
            # so the host can route to the explanation. ``"ok"`` =
            # nothing to click on.
            variant = str(self.badge.property("pill") or "neutral")
            if variant in ("danger", "warning"):
                self.failed_metric_clicked.emit(self._worst_metric)
                return True
        return super().eventFilter(obj, event)

    def _poke_badge_style(self) -> None:
        """Force Qt to re-evaluate ``[pill="…"]`` selectors after a
        property change. Without this the new variant only takes
        effect after the next paint event."""
        st = self.badge.style()
        st.unpolish(self.badge)
        st.polish(self.badge)
        self.badge.update()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        # First successful update clears the "fill spec" empty-state.
        if self._pending:
            self._pending = False
            self.badge.setCursor(Qt.CursorShape.ArrowCursor)
            self.badge.setToolTip("")
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
        # Cache the *first* failing metric name so the badge click
        # handler can emit it via ``failed_metric_clicked``. ``reasons``
        # is already ordered by severity (errors before warnings) by
        # ``_aggregate_status``.
        self._worst_metric = reasons[0] if reasons else ""
        self._set_badge(agg, reasons)
        # Badge is now interactive when there's a failure to inspect.
        if agg in ("err", "warn"):
            self.badge.setCursor(Qt.CursorShape.PointingHandCursor)
            self.badge.setToolTip(
                "Click to see which metric failed this analysis."
            )
        else:
            self.badge.setCursor(Qt.CursorShape.ArrowCursor)
            self.badge.setToolTip("")

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
            text, variant = "Approved", "success"
        elif status == "warn":
            text, variant = "Check", "warning"
        elif status == "err":
            text, variant = "Failed", "danger"
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
            self.badge.setToolTip("Watch: " + ", ".join(reasons))
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
            # — leaving a sticky violet halo behind the "FAILED"
            # text in dark mode. A border-only flash reads as "fresh"
            # without contaminating any child.
            f"QFrame#ResumoStrip[flash=\"true\"] {{"
            f"  background: {p.surface};"
            f"  border: 2px solid {p.accent_violet};"
            f"  border-radius: {r.card}px;"
            f"}}"
        )
