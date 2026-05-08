"""Bottom scoreboard — replaces ``BottomStatusBar``.

Layout (left → right):

    ● Salvo · v0.2 Pro     L=376 µH · B=360 mT · ΔT=60 °C · η=97 %     [Recalcular ⌘R]

The KPI strip in the centre is the user's *constant scoreboard* —
they always know whether the design is sane without switching tabs.
The Recalcular icon button on the right is bound to ``Ctrl+R`` so the
inner-loop action is one chord away from anywhere in the workspace.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from pfc_inductor.models import DesignResult, Spec
from pfc_inductor.ui.icons import icon as ui_icon
from pfc_inductor.ui.theme import get_theme, on_theme_changed


def _finite_kpi(
    name: str,
    value: float,
    fmt: str,
    unit: str,
    *,
    clamp_max: float = 1e6,
    clamp_min: float = -1e6,
) -> str:
    """Compose ``"name=val unit"`` with a defensive ``"—"`` fallback.

    Mirrors ``resumo_strip._finite_or_dash`` — the scoreboard footer
    needs the same protection because it's the second place a user
    looks (after the top KPI strip) and a stray ``η = -834 516 %``
    here erodes trust in everything above.

    ``clamp_min`` is exposed so percentages can use a tighter window
    than ±1 M (e.g. ``η`` is bound to roughly [-50, 100] %).
    """
    if not math.isfinite(value) or value > clamp_max or value < clamp_min:
        return f"{name}=—"
    return f"{name}={fmt.format(value)} {unit}"


class Scoreboard(QFrame):
    """Persistent bottom scoreboard."""

    HEIGHT = 36
    recalculate_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Scoreboard")
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        h = QHBoxLayout(self)
        h.setContentsMargins(20, 0, 12, 0)
        h.setSpacing(12)

        # ---- left: save status -----------------------------------------
        self._save_label = QLabel("● Pronto")
        h.addWidget(self._save_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._selection_label = QLabel("")
        self._selection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self._selection_label, 1, Qt.AlignmentFlag.AlignVCenter)

        # ---- centre: KPI strip -----------------------------------------
        self._kpi = QLabel("")
        self._kpi.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self._kpi, 1, Qt.AlignmentFlag.AlignVCenter)

        # ---- right: Recalcular -----------------------------------------
        self._btn_recalc = QToolButton()
        self._btn_recalc.setIconSize(QSize(16, 16))
        self._btn_recalc.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_recalc.setToolTip("Recalcular (Ctrl+R)")
        self._btn_recalc.setStyleSheet(self._btn_qss())
        self._btn_recalc.clicked.connect(self.recalculate_requested.emit)
        # Compose icon + label (icon-only too small to discover).
        self._btn_recalc.setText("Recalcular")
        self._btn_recalc.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
        )
        h.addWidget(self._btn_recalc, 0, Qt.AlignmentFlag.AlignVCenter)

        # ---- shortcut --------------------------------------------------
        self._shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        self._shortcut.activated.connect(self.recalculate_requested.emit)

        # ---- relative-time refresh timer -------------------------------
        self._last_saved_at: Optional[datetime] = None
        self._unsaved = False
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self._refresh_save_text)
        self._timer.start()

        self._refresh_qss()
        on_theme_changed(self._refresh_qss)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_save_status(self, *, unsaved: bool,
                        last_saved_at: Optional[datetime] = None) -> None:
        self._unsaved = unsaved
        self._last_saved_at = last_saved_at
        self._refresh_save_text()

    def update_from_result(self, result: Optional[DesignResult],
                           spec: Optional[Spec] = None) -> None:
        if result is None:
            self._kpi.setText("—")
            return
        # Compose the KPI strip — keep it tight, and switch the last
        # slot based on topology so the engineer sees what *matters*
        # for the current design type:
        #   boost CCM      → η      (efficiency is the headline figure)
        #   passive choke  → η      (same — Pout is meaningful)
        #   line reactor   → THD    (Pout flow is two-way; THD is the
        #                            compliance metric IEC 61000-3-2
        #                            actually scores)
        # Each slot uses ``_finite_kpi`` so non-finite or out-of-range
        # values render as ``—`` instead of ``η = -834 516 %``. The
        # ResumoStrip got this treatment in commit 491da51; the
        # scoreboard footer was missed in that pass.
        try:
            parts = [
                _finite_kpi("L", result.L_actual_uH, "{:.0f}", "µH"),
                _finite_kpi("B", result.B_pk_T * 1000.0, "{:.0f}", "mT"),
                _finite_kpi("ΔT", result.T_rise_C, "{:.0f}", "°C"),
            ]
            topology = getattr(spec, "topology", None) if spec is not None else None
            if topology == "line_reactor":
                thd = getattr(result, "thd_estimate_pct", None)
                if thd is not None:
                    parts.append(_finite_kpi("THD", thd, "{:.0f}", "%"))
                else:
                    pctz = getattr(result, "pct_impedance_actual", None)
                    if pctz is not None:
                        parts.append(_finite_kpi("%Z", pctz, "{:.1f}", "%"))
            elif spec is not None and spec.Pout_W > 0:
                eta_pct = (1.0 - result.losses.P_total_W / spec.Pout_W) * 100.0
                parts.append(_finite_kpi("η", eta_pct, "{:.1f}", "%",
                                         clamp_max=100.0, clamp_min=-50.0))
            self._kpi.setText(" · ".join(parts))
        except (AttributeError, ZeroDivisionError):
            self._kpi.setText("—")

    def kpi_text(self) -> str:
        return self._kpi.text()

    def save_text(self) -> str:
        return self._save_label.text()

    def set_current_selection(self, material, core, wire) -> None:
        if material is None or core is None or wire is None:
            self._selection_label.setText("")
            return

        selection_text = f"{material.name} · {core.part_number} · {wire.id}"
        self._selection_label.setText(selection_text)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _refresh_save_text(self) -> None:
        if self._unsaved:
            self._save_label.setText("● Alterações não salvas")
        elif self._last_saved_at is None:
            self._save_label.setText("● Pronto")
        else:
            delta = datetime.now() - self._last_saved_at
            seconds = int(delta.total_seconds())
            if seconds < 60:
                self._save_label.setText("● Salvo agora")
            elif seconds < 3600:
                self._save_label.setText(f"● Salvo há {seconds // 60} min")
            elif seconds < 86_400:
                self._save_label.setText(f"● Salvo há {seconds // 3600} h")
            else:
                self._save_label.setText(
                    f"● Salvo em {self._last_saved_at:%d/%m %H:%M}",
                )
        self._refresh_save_label_qss()

    def _refresh_save_label_qss(self) -> None:
        p = get_theme().palette
        t = get_theme().type
        color = p.warning if self._unsaved else p.success
        self._save_label.setStyleSheet(
            f"color: {color}; font-family: {t.ui_family_brand};"
            f" font-size: {t.caption}px; font-weight: {t.medium};"
            f" background: transparent; border: 0;"
        )

    def _refresh_qss(self) -> None:
        self.setStyleSheet(self._self_qss())
        self._refresh_save_label_qss()
        p = get_theme().palette
        t = get_theme().type
        self._selection_label.setStyleSheet(
            f"color: {p.text_secondary};"
            f" font-family: {t.numeric_family};"
            f" font-size: {t.body_md}px;"
            f" background: transparent; border: 0;"
        )
        self._kpi.setStyleSheet(
            f"color: {p.text_secondary};"
            f" font-family: {t.numeric_family};"
            f" font-size: {t.body_md}px;"
            f" background: transparent; border: 0;"
        )
        self._btn_recalc.setStyleSheet(self._btn_qss())
        self._btn_recalc.setIcon(
            ui_icon("zap", color=p.text_inverse, size=14),
        )

    @staticmethod
    def _self_qss() -> str:
        p = get_theme().palette
        return (
            f"QFrame#Scoreboard {{"
            f"  background: {p.surface};"
            f"  border: 0;"
            f"  border-top: 1px solid {p.border};"
            f"}}"
        )

    @staticmethod
    def _btn_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"QToolButton {{"
            f"  background: {p.accent}; color: {p.text_inverse};"
            f"  border: 0; border-radius: {t.body_md - 4}px;"
            f"  padding: 4px 12px; font-weight: {t.semibold};"
            f"  font-family: {t.ui_family_brand};"
            f"}}"
            f"QToolButton:hover {{ background: {p.accent_hover}; }}"
            f"QToolButton:pressed {{ background: {p.accent_pressed}; }}"
        )
