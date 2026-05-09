"""Harmonic-spectrum dashboard card — visible only for line-frequency
filtering topologies (line_reactor, passive_choke, pfc_passive).

Wraps :class:`HarmonicSpectrumChart` in a ``Card`` chrome and computes
the per-harmonic amplitudes by dispatching to the relevant topology
module's ``harmonic_amplitudes_pct`` (line_reactor / passive_choke).

Visibility rule:
    Hidden when ``spec.topology`` is not one of the line-frequency
    suppressing topologies. For boost-CCM and flyback the harmonics
    plot would be a category error — those designs handle harmonics
    via active control, not the inductor.

IEC class selection:
    Class D for ≤ 600 W single-phase equipment (typical SMPS / PFC
    pre-converter); Class A otherwise. The chart applies the
    appropriate per-harmonic limit and reports PASSED / FAILED.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QVBoxLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.widgets.card import Card
from pfc_inductor.ui.widgets.harmonic_spectrum_chart import (
    HarmonicSpectrumChart,
    HarmonicSpectrumPayload,
)

# Topologies whose value proposition is harmonic suppression on the
# AC side. For these the chart shows whether the design meets IEC
# emission limits at full load.
_HARMONIC_TOPOLOGIES = frozenset({
    "line_reactor",
    "passive_choke",
    "pfc_passive",
})


class _HarmonicSpectrumBody(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self._chart = HarmonicSpectrumChart()
        v.addWidget(self._chart, 1)

    def update_from_design(
        self,
        result: DesignResult,
        spec: Spec,
        core: Core,
        wire: Wire,
        material: Material,
    ) -> None:
        topology = str(getattr(spec, "topology", "")).lower()
        L_uH = float(getattr(result, "L_actual_uH", 0.0) or 0.0)
        L_mH = L_uH / 1000.0

        orders, amplitudes_pct = self._dispatch_harmonics(
            topology, spec, L_mH
        )
        if orders is None or amplitudes_pct is None:
            self._chart.show_payload(HarmonicSpectrumPayload(
                orders=(), amplitudes_A=(),
            ))
            return

        # Convert % of fundamental peak → Arms per harmonic.
        # ``harmonic_amplitudes_pct`` returns the FFT peak ratio,
        # which equals the RMS ratio for sinusoidal harmonics.
        # Multiplying by I_1 (line RMS) gives I_h in Arms, which is
        # what the IEC limits are tabulated against.
        I_1_rms = self._fundamental_rms_A(topology, spec)
        amplitudes_A = tuple(
            (pct / 100.0) * I_1_rms for pct in amplitudes_pct
        )

        # IEC class — D for SMPS-style ≤ 600 W single-phase, A otherwise.
        Pin_W = float(getattr(spec, "Pout_W", 0.0) or 0.0) / max(
            float(getattr(spec, "eta", 0.95) or 0.95), 0.01
        )
        n_phases = int(getattr(spec, "n_phases", 1) or 1)
        if n_phases == 1 and Pin_W <= 600.0:
            iec_class = "D"
        else:
            iec_class = "A"

        self._chart.show_payload(HarmonicSpectrumPayload(
            orders=tuple(int(o) for o in orders),
            amplitudes_A=amplitudes_A,
            iec_class=iec_class,
            P_in_W=Pin_W,
            f_line_Hz=float(getattr(spec, "f_line_Hz", 60.0) or 60.0),
            topology_name=topology,
        ))

    def clear(self) -> None:
        self._chart.show_payload(HarmonicSpectrumPayload(
            orders=(), amplitudes_A=(),
        ))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _dispatch_harmonics(topology: str, spec: Spec, L_mH: float):
        """Pick the right topology module and return
        ``(orders, amplitudes_pct)`` arrays. Returns ``(None, None)``
        on failure so the caller can show the empty state."""
        try:
            if topology in ("line_reactor",):
                from pfc_inductor.topology import line_reactor as lr

                pct = lr.harmonic_amplitudes_pct(
                    spec, L_mH, n_harmonics=15
                )
                orders = list(range(1, len(pct) + 1))
                return orders, list(pct)
            if topology in ("passive_choke", "pfc_passive"):
                # ``passive_choke.estimate_thd_pct`` delegates into
                # ``line_reactor`` already, so the harmonic shape is
                # the same; we just need a bias L conversion. The
                # passive_choke module doesn't expose a per-harmonic
                # API yet, so we route through ``line_reactor`` with
                # ``n_phases=1`` (single-phase capacitor-input).
                from pfc_inductor.topology import line_reactor as lr

                pct = lr.harmonic_amplitudes_pct(
                    spec, L_mH, n_harmonics=15
                )
                orders = list(range(1, len(pct) + 1))
                return orders, list(pct)
        except Exception:
            pass
        return None, None

    @staticmethod
    def _fundamental_rms_A(topology: str, spec: Spec) -> float:
        """Compute the line-frequency fundamental RMS current."""
        try:
            Vin = float(getattr(spec, "Vin_nom_Vrms", 0.0) or 0.0)
            if topology == "line_reactor":
                from pfc_inductor.topology import line_reactor as lr

                return float(lr.line_rms_current_A(spec))
            if topology in ("passive_choke", "pfc_passive"):
                from pfc_inductor.topology import passive_choke as pc

                return float(pc.line_rms_current_A(spec, Vin))
        except Exception:
            pass
        return 0.0


class HarmonicSpectrumCard(Card):
    """Dashboard card that surfaces the IEC 61000-3-2 compliance
    plot for line-frequency filtering inductors."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _HarmonicSpectrumBody()
        super().__init__(
            "Harmonics — IEC 61000-3-2 compliance",
            body,
            badge="EMC",
            badge_variant="info",
            parent=parent,
        )
        self._body = body

    def update_from_design(
        self,
        result: DesignResult,
        spec: Spec,
        core: Core,
        wire: Wire,
        material: Material,
    ) -> None:
        # Topology guard.
        topology = str(getattr(spec, "topology", "")).lower()
        if topology not in _HARMONIC_TOPOLOGIES:
            self.setVisible(False)
            return
        self.setVisible(True)
        self._body.update_from_design(result, spec, core, wire, material)

    def clear(self) -> None:
        self._body.clear()
