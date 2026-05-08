"""Acoustic-noise card on the Analysis tab.

Single-line hero label (the SPL value at 1 m) + dominant
mechanism + per-mechanism contribution table + headroom-to-
threshold strip. Drives the "will this design hum at idle?"
engineering judgement that compressor-VFD designers can't
otherwise see in the app.

Hidden when the engine doesn't have enough data (B_pk, ripple,
fsw, geometry) to estimate noise — the card never shows a
nonsense number.

UI shape
--------

::

    ┌── Acoustic noise (estimated) ────────────────────────┐
    │                                                      │
    │           24.1 dB(A) at 130 kHz                      │
    │                                                      │
    │  Dominant: magnetostriction                          │
    │  Headroom: +5.9 dB to 30 dB(A) appliance threshold   │
    │                                                      │
    │  ┌── per-mechanism ───────────────────────┐           │
    │  │ magnetostriction      12.1 dB(A)       │           │
    │  │ winding_lorentz       -inf dB(A)       │           │
    │  └────────────────────────────────────────┘           │
    │                                                      │
    │  Estimate ±3 dB(A) — anechoic measurement still      │
    │  required for certification.                         │
    └──────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.acoustic import NoiseEstimate, estimate_noise
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.theme import get_theme, on_theme_changed
from pfc_inductor.ui.widgets import Card


class AcousticCard(Card):
    """Card façade — public ``update_from_design`` mirror of the
    other Analysis-tab cards. Internally wraps the body widget
    that does the actual rendering."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _AcousticBody()
        super().__init__("Acoustic noise (estimated)", body, parent=parent)
        self._body = body
        # Hidden by default — the parent Analysis tab decides when
        # to mount the card based on whether the engine has the
        # inputs the model needs. We start hidden so a freshly
        # opened project doesn't flash an em-dash hero label.
        self.setVisible(False)

    def update_from_design(
        self,
        result: DesignResult,
        spec: Spec,
        core: Core,
        wire: Wire,
        material: Material,
    ) -> None:
        """Run the estimator and populate the body. The card hides
        itself when the engine reports zero B_pk or ripple — those
        are the inputs the model actually needs, and seeing a
        nonsense "0 dB(A)" would mislead the user."""
        try:
            estimate = estimate_noise(spec, core, wire, material, result)
        except Exception:  # noqa: BLE001 — surface as silent hide
            self.setVisible(False)
            return
        if estimate.dominant_mechanism == "none":
            # Estimator declined to produce a number — usually
            # zero B_pk on a degenerate / unfeasible spec. Hide
            # rather than show a fake "0 dB(A)".
            self.setVisible(False)
            return
        self._body.show_estimate(estimate)
        self.setVisible(True)

    def clear(self) -> None:
        self._body.clear()
        self.setVisible(False)


class _AcousticBody(QFrame):
    """Internal body widget — separate from ``AcousticCard``
    so the Card chrome (title, padding, theme hooks) can be
    reused without re-implementing the layout."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred,
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(8)

        # Hero — big SPL value + dominant frequency.
        self._hero = QLabel("—")
        self._hero.setObjectName("AcousticHero")
        self._hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self._hero)

        # Subtitle — dominant mechanism + headroom.
        sub = QHBoxLayout()
        sub.setSpacing(20)
        sub.setContentsMargins(0, 0, 0, 0)

        self._dominant = QLabel("")
        self._dominant.setProperty("role", "muted")
        self._dominant.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        self._headroom = QLabel("")
        self._headroom.setObjectName("AcousticHeadroom")
        self._headroom.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        sub.addWidget(self._dominant, 1)
        sub.addWidget(self._headroom)
        v.addLayout(sub)

        # Per-mechanism contribution table.
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Mechanism", "Contribution"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setMinimumHeight(80)
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self._table)

        # Caveat footer — the model is documented as ±3 dB(A) so
        # the user should never treat its number as a guarantee.
        self._caveat = QLabel(
            "Analytical estimate ±3 dB(A) — anechoic-mic "
            "measurement still required for certification.",
        )
        self._caveat.setProperty("role", "muted")
        self._caveat.setWordWrap(True)
        v.addWidget(self._caveat)

        on_theme_changed(self._refresh_theme)
        self._refresh_theme()

    # ------------------------------------------------------------------
    def show_estimate(self, est: NoiseEstimate) -> None:
        # Hero: SPL value + dominant tone frequency in kHz.
        self._hero.setText(
            f"{est.dB_a_at_1m:.1f} dB(A) "
            f"@ {est.dominant_frequency_Hz / 1000:.1f} kHz",
        )
        self._refresh_hero_color(est)

        mechanism_label = {
            "magnetostriction":  "Magnetostriction",
            "winding_lorentz":   "Winding Lorentz",
            "bobbin_resonance":  "Bobbin resonance",
            "none":              "—",
        }.get(est.dominant_mechanism, est.dominant_mechanism)
        self._dominant.setText(f"Dominant: {mechanism_label}")

        # Threshold = current SPL + headroom — recover the
        # threshold the estimator was scored against so the
        # caption reads "to 30 dB(A) appliance threshold" without
        # the user having to remember the default.
        threshold = est.dB_a_at_1m + est.headroom_to_threshold_dB
        sign = "+" if est.headroom_to_threshold_dB >= 0 else "−"
        magnitude = abs(est.headroom_to_threshold_dB)
        self._headroom.setText(
            f"Headroom: {sign}{magnitude:.1f} dB to {threshold:.0f} dB(A)",
        )
        self._refresh_headroom_color(est)

        # Per-mechanism contribution table.
        contributors = [
            (mech, db) for mech, db in est.contributors_dba.items()
            if math.isfinite(db)
        ]
        contributors.sort(key=lambda kv: -kv[1])
        self._table.setRowCount(len(contributors))
        for r, (mech, db) in enumerate(contributors):
            label_text = mechanism_label = {
                "magnetostriction":  "Magnetostriction",
                "winding_lorentz":   "Winding Lorentz",
                "bobbin_resonance":  "Bobbin resonance",
            }.get(mech, mech)
            self._table.setItem(r, 0, QTableWidgetItem(label_text))
            cell = QTableWidgetItem(f"{db:.1f} dB(A)")
            cell.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )
            self._table.setItem(r, 1, cell)

    def clear(self) -> None:
        self._hero.setText("—")
        self._dominant.setText("")
        self._headroom.setText("")
        self._table.setRowCount(0)

    # ------------------------------------------------------------------
    def _refresh_hero_color(self, est: NoiseEstimate) -> None:
        p = get_theme().palette
        t = get_theme().type
        # Threshold-relative band:
        #   ≥ +6 dB headroom → success (well under)
        #   0 to +6 dB       → warning
        #   < 0 dB           → danger
        head = est.headroom_to_threshold_dB
        color = (
            p.success if head >= 6.0
            else p.warning if head >= 0.0
            else p.danger
        )
        self._hero.setStyleSheet(
            f"color: {color}; "
            f"font-family: {t.numeric_family}; "
            f"font-size: {t.title_lg}px; "
            f"font-weight: {t.semibold};"
        )

    def _refresh_headroom_color(self, est: NoiseEstimate) -> None:
        p = get_theme().palette
        t = get_theme().type
        head = est.headroom_to_threshold_dB
        color = (
            p.success if head >= 0.0
            else p.danger
        )
        self._headroom.setStyleSheet(
            f"color: {color}; font-size: {t.body}px;"
            f"font-weight: {t.medium};"
        )

    def _refresh_theme(self) -> None:
        # Idle / pre-data state: hero label muted em-dash. The
        # value-driven colours are applied via the show_estimate
        # path which calls the per-state refreshers above.
        if self._hero.text() == "—":
            p = get_theme().palette
            t = get_theme().type
            self._hero.setStyleSheet(
                f"color: {p.text_muted}; "
                f"font-family: {t.numeric_family}; "
                f"font-size: {t.title_lg}px; "
                f"font-weight: {t.semibold};"
            )
