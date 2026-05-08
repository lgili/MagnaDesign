"""Detalhes Técnicos card — collapsible datasheet view of every
``DesignResult`` field the engine produces.

Why this exists
---------------
The v3 split (Núcleo / Análise / Validar / Exportar) replaced the
v2 ``ResultPanel`` (a flat tabular dump of every computed value)
with focused cards. Each card is great for "one fact at a time",
but that left ~13 ``DesignResult`` fields invisible:

- ``L_required_uH`` (target — only L_actual was shown)
- ``B_sat_limit_T`` (only used in status colour calc)
- ``Ku_max`` / ``Ku_actual`` ratio
- ``losses.P_core_line_W`` / ``P_core_ripple_W`` split
- ``converged`` flag, ``warnings`` list, ``notes``
- ``pct_impedance_actual``, ``voltage_drop_pct``, ``Pi_W`` (line reactor)

The audit's recommendation: a **datasheet-style** card, default
collapsed, that exposes ALL fields in a 2-column grid grouped by
domain (Indutância / Magnético / Bobinamento / Térmico / Perdas /
Convergência). One click to expand, one click to fold.

This is *the* place an experienced engineer goes when they say
"show me the numbers" — without polluting the at-a-glance cards
above.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.icons import icon as ui_icon
from pfc_inductor.ui.theme import get_theme, on_theme_changed
from pfc_inductor.ui.widgets import Card


# ---------------------------------------------------------------------------
# A single label/value row inside one of the 2-column groups.
# ---------------------------------------------------------------------------
def _make_row(label: str, value: str, unit: str = "") -> tuple[QLabel, QLabel, QLabel]:
    """Build a (label, value, unit) trio of QLabels styled per role.

    Returned as a tuple so the parent grid lays them out itself —
    different group columns share row indices and alignment.
    """
    p = get_theme().palette
    t = get_theme().type
    lbl = QLabel(label)
    lbl.setStyleSheet(
        f"color: {p.text_secondary}; font-size: {t.body}px;"
    )
    val = QLabel(value)
    val.setObjectName("DetalheValue")
    val.setStyleSheet(
        f"color: {p.text}; font-size: {t.body_md}px;"
        f" font-family: {t.numeric_family}; font-weight: {t.semibold};"
    )
    val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    unit_lbl = QLabel(unit)
    unit_lbl.setStyleSheet(
        f"color: {p.text_muted}; font-size: {t.caption}px;"
    )
    return lbl, val, unit_lbl


class _DatasheetGroup(QFrame):
    """A titled column of (label · value · unit) rows.

    Six of these stack into a 2 × 3 grid inside ``_DetalhesBody``.
    """

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._rows: list[tuple[QLabel, QLabel, QLabel]] = []
        self._row_keys: dict[str, int] = {}      # label → row index
        self._title_text = title

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self._title = QLabel(title)
        self._title.setObjectName("DetalheGroupTitle")
        self._title.setStyleSheet(self._title_qss())
        v.addWidget(self._title)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(4)
        self._grid.setColumnStretch(0, 1)        # label fills
        self._grid.setColumnStretch(1, 0)        # value hugs
        self._grid.setColumnStretch(2, 0)        # unit hugs
        v.addLayout(self._grid)
        v.addStretch(1)

        on_theme_changed(self._refresh_qss)

    def set_row(self, key: str, label: str, value: str, unit: str = "") -> None:
        """Upsert a row by key. New rows append; existing rows update
        their value/unit in place — avoids the QLabel churn we'd hit
        if every refresh rebuilt the whole grid."""
        if key in self._row_keys:
            r = self._row_keys[key]
            _, val_lbl, unit_lbl = self._rows[r]
            val_lbl.setText(value)
            unit_lbl.setText(unit)
            return
        r = len(self._rows)
        lbl, val, unit_lbl = _make_row(label, value, unit)
        self._grid.addWidget(lbl, r, 0,
                             alignment=Qt.AlignmentFlag.AlignVCenter)
        self._grid.addWidget(val, r, 1,
                             alignment=Qt.AlignmentFlag.AlignVCenter)
        self._grid.addWidget(unit_lbl, r, 2,
                             alignment=Qt.AlignmentFlag.AlignVCenter)
        self._rows.append((lbl, val, unit_lbl))
        self._row_keys[key] = r

    def clear(self) -> None:
        for _, val_lbl, unit_lbl in self._rows:
            val_lbl.setText("—")
            unit_lbl.setText("")

    # ------------------------------------------------------------------
    def _refresh_qss(self) -> None:
        self._title.setStyleSheet(self._title_qss())
        # Re-apply per-row inline QSS so colours follow the new theme.
        p = get_theme().palette
        t = get_theme().type
        for lbl, val, unit_lbl in self._rows:
            lbl.setStyleSheet(
                f"color: {p.text_secondary}; font-size: {t.body}px;"
            )
            val.setStyleSheet(
                f"color: {p.text}; font-size: {t.body_md}px;"
                f" font-family: {t.numeric_family}; font-weight: {t.semibold};"
            )
            unit_lbl.setStyleSheet(
                f"color: {p.text_muted}; font-size: {t.caption}px;"
            )

    @staticmethod
    def _title_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"QLabel#DetalheGroupTitle {{"
            f"  color: {p.text_secondary};"
            f"  font-size: {t.caption}px;"
            f"  font-weight: {t.semibold};"
            f"  text-transform: uppercase;"
            f"  letter-spacing: 0.5px;"
            f"  padding-bottom: 4px;"
            f"  border-bottom: 1px solid {p.border};"
            f"}}"
        )


# ---------------------------------------------------------------------------
# Card body — collapse-aware container with the 6 datasheet groups inside.
# ---------------------------------------------------------------------------
class _DetalhesBody(QWidget):
    """Body widget — a 2 × 3 grid of ``_DatasheetGroup``s, all hidden
    behind a single Q "Mostrar / Ocultar" toggle.

    Default collapsed: clicking the chevron expands; clicking again
    folds. The toggle state survives data updates so the user's
    preference sticks while they iterate on a design.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        self._toggle = QPushButton("Mostrar todos os parâmetros")
        self._toggle.setProperty("class", "Tertiary")
        self._toggle.setCheckable(True)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.setStyleSheet(self._toggle_qss())
        self._toggle.toggled.connect(self._on_toggled)
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignLeft)
        toggle_row.addStretch(1)
        outer.addLayout(toggle_row)

        # Container that holds the actual groups; toggled visible via
        # ``setVisible`` on the body so the card collapses cleanly.
        self._content = QFrame()
        self._content.setSizePolicy(QSizePolicy.Policy.Expanding,
                                    QSizePolicy.Policy.Maximum)
        self._content.setVisible(False)
        outer.addWidget(self._content)

        grid = QGridLayout(self._content)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(20)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self.g_l = _DatasheetGroup("Indutância")
        self.g_mag = _DatasheetGroup("Magnético")
        self.g_wind = _DatasheetGroup("Bobinamento")
        self.g_thermal = _DatasheetGroup("Térmico")
        self.g_loss = _DatasheetGroup("Perdas")
        self.g_conv = _DatasheetGroup("Convergência")

        # 3 rows × 2 cols.
        grid.addWidget(self.g_l,       0, 0)
        grid.addWidget(self.g_mag,     0, 1)
        grid.addWidget(self.g_wind,    1, 0)
        grid.addWidget(self.g_thermal, 1, 1)
        grid.addWidget(self.g_loss,    2, 0)
        grid.addWidget(self.g_conv,    2, 1)

        on_theme_changed(self._refresh_qss)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        # ---- Indutância ------------------------------------------------
        l_target = result.L_required_uH
        l_actual = result.L_actual_uH
        delta_pct = ((l_actual - l_target) / l_target * 100.0) if l_target > 0 else 0.0
        AL = (l_actual * 1000.0) / max(result.N_turns ** 2, 1)
        self.g_l.set_row("L_alvo", "L alvo", f"{l_target:.1f}", "µH")
        self.g_l.set_row("L_real", "L real",
                         f"{l_actual:.1f} ({delta_pct:+.1f}%)", "µH")
        self.g_l.set_row("AL", "AL", f"{AL:.1f}", "nH/N²")
        self.g_l.set_row("N", "Voltas (N)", f"{result.N_turns}")

        # ---- Magnético -------------------------------------------------
        Bsat = result.B_sat_limit_T
        sat_pct = (result.B_pk_T / Bsat * 100.0) if Bsat > 0 else 0.0
        self.g_mag.set_row("B_pk", "B pico",
                           f"{result.B_pk_T*1000.0:.0f} ({sat_pct:.0f}% B_sat)", "mT")
        self.g_mag.set_row("Bsat", "B saturação",
                           f"{Bsat*1000.0:.0f}", "mT")
        self.g_mag.set_row("margin", "Margem sat.",
                           f"{result.sat_margin_pct:.1f}", "%")
        self.g_mag.set_row("H_pk", "H pico DC",
                           f"{result.H_dc_peak_Oe:.1f}", "Oe")
        self.g_mag.set_row("mu", "μ efetivo (rolloff)",
                           f"{result.mu_pct_at_peak:.0f}", "%")

        # ---- Bobinamento ----------------------------------------------
        ku_pct = result.Ku_actual * 100.0
        ku_max_pct = result.Ku_max * 100.0
        r_dc_mohm = result.R_dc_ohm * 1000.0
        r_ac_mohm = result.R_ac_ohm * 1000.0
        r_ratio = (result.R_ac_ohm / result.R_dc_ohm) if result.R_dc_ohm > 0 else 0.0
        wire_len_m = (core.MLT_mm * result.N_turns) / 1000.0
        self.g_wind.set_row("Ku", "Ku real",
                            f"{ku_pct:.1f} (lim {ku_max_pct:.0f})", "%")
        self.g_wind.set_row("Rdc", "R DC", f"{r_dc_mohm:.1f}", "mΩ")
        self.g_wind.set_row("Rac", "R AC@fsw",
                            f"{r_ac_mohm:.1f} ({r_ratio:.2f}× DC)", "mΩ")
        self.g_wind.set_row("len", "Comprimento fio", f"{wire_len_m:.2f}", "m")

        # ---- Térmico ---------------------------------------------------
        T_amb = spec.T_amb_C
        self.g_thermal.set_row("T_amb", "T ambiente", f"{T_amb:.0f}", "°C")
        self.g_thermal.set_row("dT", "ΔT (rise)", f"{result.T_rise_C:.0f}", "°C")
        self.g_thermal.set_row("T_wind", "T enrolamento",
                               f"{result.T_winding_C:.0f} (lim 130)", "°C")
        # Line-reactor-only metrics (None for boost/passive)
        if result.pct_impedance_actual is not None:
            self.g_thermal.set_row("pctZ", "%Z impedância",
                                   f"{result.pct_impedance_actual:.2f}", "%")
        if result.voltage_drop_pct is not None:
            self.g_thermal.set_row("vdrop", "Queda V no reator",
                                   f"{result.voltage_drop_pct:.2f}", "%")

        # ---- Perdas (full breakdown) ----------------------------------
        L = result.losses
        self.g_loss.set_row("Cu_dc", "Cu DC", f"{L.P_cu_dc_W:.2f}", "W")
        self.g_loss.set_row("Cu_ac", "Cu AC@fsw", f"{L.P_cu_ac_W:.2f}", "W")
        self.g_loss.set_row("Cu_total", "Cu total",
                            f"{L.P_cu_total_W:.2f}", "W")
        self.g_loss.set_row("core_line", "Núcleo @ linha",
                            f"{L.P_core_line_W:.2f}", "W")
        self.g_loss.set_row("core_ripple", "Núcleo @ ripple",
                            f"{L.P_core_ripple_W:.2f}", "W")
        self.g_loss.set_row("core_total", "Núcleo total",
                            f"{L.P_core_total_W:.2f}", "W")
        self.g_loss.set_row("p_total", "Total", f"{L.P_total_W:.2f}", "W")
        if result.Pi_W is not None:
            eta_pct = (1.0 - L.P_total_W / result.Pi_W) * 100.0 if result.Pi_W > 0 else 0.0
            self.g_loss.set_row("eta", "Eficiência",
                                f"{eta_pct:.2f}", "%")

        # ---- Convergência ---------------------------------------------
        self.g_conv.set_row("status", "Status",
                            "✓ Convergiu" if result.converged else "✗ Não convergiu")
        if result.warnings:
            self.g_conv.set_row("warn", "Avisos",
                                f"{len(result.warnings)} alerta(s)")
        else:
            self.g_conv.set_row("warn", "Avisos", "Nenhum")
        if result.notes:
            self.g_conv.set_row("notes", "Notas",
                                result.notes if len(result.notes) <= 28
                                else result.notes[:25] + "…")
        if result.thd_estimate_pct is not None:
            self.g_conv.set_row("thd", "THD estimada",
                                f"{result.thd_estimate_pct:.1f}", "%")

    def clear(self) -> None:
        for grp in (self.g_l, self.g_mag, self.g_wind,
                    self.g_thermal, self.g_loss, self.g_conv):
            grp.clear()

    # ------------------------------------------------------------------
    def _on_toggled(self, checked: bool) -> None:
        self._content.setVisible(checked)
        self._toggle.setText(
            "Ocultar parâmetros" if checked
            else "Mostrar todos os parâmetros"
        )
        self._toggle.setIcon(ui_icon(
            "chevron-down" if checked else "chevron-right",
            color=get_theme().palette.text_secondary, size=14,
        ))

    def _refresh_qss(self) -> None:
        self._toggle.setStyleSheet(self._toggle_qss())
        self._toggle.setIcon(ui_icon(
            "chevron-down" if self._toggle.isChecked() else "chevron-right",
            color=get_theme().palette.text_secondary, size=14,
        ))

    @staticmethod
    def _toggle_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"QPushButton {{"
            f"  background: transparent;"
            f"  border: 0;"
            f"  color: {p.text_secondary};"
            f"  font-size: {t.body_md}px;"
            f"  font-weight: {t.medium};"
            f"  padding: 4px 0;"
            f"  text-align: left;"
            f"}}"
            f"QPushButton:hover {{"
            f"  color: {p.text};"
            f"}}"
        )


class DetalhesTecnicosCard(Card):
    """Public façade — collapsible datasheet of every computed parameter.

    Mounts as the last row of ``AnalisePage`` (full width). On screens
    ≥ 1080 px tall the card auto-expands at construction time so the
    engineer with monitor space sees the full datasheet without
    hunting for the toggle. Smaller viewports stay collapsed by
    default to keep the at-a-glance row above the fold.

    The user's manual toggle wins over the auto-expand heuristic —
    once they collapse it explicitly the choice survives data updates.
    """

    expanded_changed = Signal(bool)

    # Threshold in CSS pixels above which we auto-expand the card on
    # construction. 1080 px clears MacBook Air (1080) and most modern
    # external monitors; 1366×768 laptops stay collapsed.
    AUTO_EXPAND_HEIGHT_PX = 1080

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _DetalhesBody()
        super().__init__("Detalhes técnicos", body, parent=parent)
        self._dbody = body
        self._dbody._toggle.toggled.connect(self.expanded_changed.emit)
        self._auto_expand_if_tall()

    def _auto_expand_if_tall(self) -> None:
        """Open the datasheet by default when the screen has the room.

        ``QGuiApplication.primaryScreen()`` is None on headless /
        offscreen platforms (CI, screenshot harness) — we leave the
        card collapsed in that case so test snapshots stay stable.
        """
        try:
            from PySide6.QtGui import QGuiApplication
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            h = screen.availableGeometry().height()
            if h >= self.AUTO_EXPAND_HEIGHT_PX:
                self._dbody._toggle.setChecked(True)
        except Exception:
            # Defensive: never let a screen-info hiccup block card
            # construction.
            pass

    def update_from_design(self, *args, **kwargs) -> None:
        self._dbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._dbody.clear()
