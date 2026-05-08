"""Sampled waveform — the output type of `simulate_to_steady_state`.

Carries time, inductor current, and flux density on a uniform grid.
The constructor is intentionally bare; convenience metrics
(`i_pk_A`, `B_pk_T`, `i_rms_A`) are computed lazily.

The companion ``CycleStats`` aggregates per-cycle peaks the
integrator uses for steady-state detection, kept on the waveform
so callers can audit how convergence was declared.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class CycleStats:
    """Per-line-cycle peak metrics; populated by the integrator."""

    i_pk_per_cycle_A: np.ndarray  # shape (n_cycles,)
    B_pk_per_cycle_T: np.ndarray  # shape (n_cycles,)
    converged: bool  # True iff peaks stabilised
    rel_tol: float  # tolerance the integrator declared on
    convergence_window: int  # how many cycles were compared


@dataclass(frozen=True)
class Waveform:
    """Steady-state waveform of one transient simulation."""

    t_s: np.ndarray
    i_L_A: np.ndarray
    B_T: np.ndarray
    f_line_Hz: float
    cycle_stats: CycleStats = field(
        default_factory=lambda: CycleStats(
            i_pk_per_cycle_A=np.array([]),
            B_pk_per_cycle_T=np.array([]),
            converged=False,
            rel_tol=0.0,
            convergence_window=0,
        ),
    )

    # ─── Convenience metrics ─────────────────────────────────────

    @property
    def i_pk_A(self) -> float:
        """Maximum |i_L| across the whole sampled window."""
        if self.i_L_A.size == 0:
            return 0.0
        return float(np.max(np.abs(self.i_L_A)))

    @property
    def i_rms_A(self) -> float:
        """RMS of i_L over the whole sampled window."""
        if self.i_L_A.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(self.i_L_A * self.i_L_A)))

    @property
    def B_pk_T(self) -> float:
        """Maximum |B| across the whole sampled window."""
        if self.B_T.size == 0:
            return 0.0
        return float(np.max(np.abs(self.B_T)))

    @property
    def n_samples(self) -> int:
        return int(self.t_s.size)

    @property
    def duration_s(self) -> float:
        if self.t_s.size < 2:
            return 0.0
        return float(self.t_s[-1] - self.t_s[0])

    @property
    def n_line_cycles(self) -> int:
        return round(self.duration_s * self.f_line_Hz)

    # ─── Last-cycle subset (steady-state slice) ──────────────────

    def last_cycle(self) -> Waveform:
        """A `Waveform` containing only the final line cycle's samples.

        After the integrator declares steady state, the last cycle
        is the cleanest sample for Tier-2 metrics.
        """
        if self.f_line_Hz <= 0 or self.t_s.size == 0:
            return self
        T_line = 1.0 / self.f_line_Hz
        cutoff = self.t_s[-1] - T_line
        mask = self.t_s >= cutoff
        return Waveform(
            t_s=self.t_s[mask],
            i_L_A=self.i_L_A[mask],
            B_T=self.B_T[mask],
            f_line_Hz=self.f_line_Hz,
            cycle_stats=self.cycle_stats,
        )
