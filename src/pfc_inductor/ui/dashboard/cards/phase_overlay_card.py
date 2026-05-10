"""Phase-overlay dashboard card — visible only for interleaved PFC.

Wraps the standalone :class:`PhaseOverlayChart` widget in a ``Card``
chrome and implements the ``DesignDisplay`` protocol so the dashboard
can fan ``update_from_design`` calls to it like any other card.

Visibility rule:
    Hidden (``setVisible(False)``) when the active topology is not
    ``interleaved_boost_pfc`` *or* the spec resolves to a single
    phase. The grid layout collapses around hidden widgets, so the
    row disappears for designs that don't need it.

Data conversion:
    The chart's ``_synthesise()`` builds N triangular phase currents
    from (n_phases, I_avg_per_phase, ΔI_pp_per_phase, fsw, duty).
    All five come straight from ``Spec`` + ``DesignResult``; we use
    the worst-case ripple duty so the user sees the topology's
    worst-case cancellation, not a duty where it accidentally
    nulls.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QVBoxLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.widgets.card import Card
from pfc_inductor.ui.widgets.phase_overlay_chart import (
    PhaseOverlayChart,
    PhaseOverlayPayload,
)


class _PhaseOverlayBody(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self._chart = PhaseOverlayChart()
        v.addWidget(self._chart, 1)

    def update_from_design(
        self,
        result: DesignResult,
        spec: Spec,
        core: Core,
        wire: Wire,
        material: Material,
    ) -> None:
        # Per-phase average current — the topology distributes the
        # input current evenly, so each phase carries 1/N. Use line
        # RMS to keep the chart's vertical scale realistic across
        # the line cycle (peak A would scale 1.41× higher).
        N = max(int(getattr(spec, "n_interleave", 1)), 1)
        I_total_rms = float(getattr(result, "I_line_rms_A", 0.0) or 0.0)
        I_per_phase = I_total_rms / N if I_total_rms > 0 else 0.0
        ripple_pp = float(getattr(result, "I_ripple_pk_pk_A", 0.0) or 0.0)
        fsw_Hz = float(getattr(spec, "f_sw_kHz", 0.0) or 0.0) * 1000.0

        # Choose a duty that demonstrates *visible* residual ripple
        # rather than the perfect-cancellation null at D = k/N. The
        # topology has a closed-form worst-case duty; that's what
        # we plot, since it's the worst case the input cap has to
        # handle.
        from pfc_inductor.topology import interleaved_boost_pfc as itl

        try:
            duty = itl.worst_case_duty_for_ripple(N)
        except Exception:
            duty = 0.5

        self._chart.show_payload(
            PhaseOverlayPayload(
                n_phases=N,
                I_avg_per_phase_A=I_per_phase,
                delta_iL_pp_A=ripple_pp,
                fsw_Hz=fsw_Hz,
                duty=duty,
            )
        )

    def clear(self) -> None:
        # ``PhaseOverlayChart`` has no public clear; show the empty
        # state by passing an all-zero payload.
        self._chart.show_payload(PhaseOverlayPayload())


class PhaseOverlayCard(Card):
    """Dashboard card that surfaces the N-phase ripple-cancellation
    chart for interleaved-boost designs."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _PhaseOverlayBody()
        super().__init__(
            "Phase ripple — interleaved cancellation",
            body,
            badge="N-phase",
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
        # Topology guard. Hide the whole card on non-interleaved
        # designs so a single-phase boost user never sees a "phase
        # cancellation" plot that has nothing to cancel.
        topology = str(getattr(spec, "topology", "")).lower()
        n_phases = int(getattr(spec, "n_interleave", 1) or 1)
        if topology != "interleaved_boost_pfc" or n_phases < 2:
            self.setVisible(False)
            return
        self.setVisible(True)
        self._body.update_from_design(result, spec, core, wire, material)

    def clear(self) -> None:
        self._body.clear()
