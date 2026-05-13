"""Side-by-side calibration scaffold — FEMMT vs direct backend.

Phase 1.0 + 1.1 of the direct backend got the pipeline running
end-to-end and fixed the region-tagging bug, but the L_dc value
is still ~89× off the analytical ideal on synthetic test cases.
That's a calibration problem, not a pipeline problem.

This module exposes :func:`compare_backends` — a single call that
runs both FEMMT and the direct backend on the same input and
returns a structured diff. Use it as the oracle for Phase 1.2
iteration: tweak the ``.pro`` template, re-run, check whether
the L_direct moves closer to L_femmt.

The function is wrapped in heavy try/excepts because either
backend can fail on a given case (FEMMT crashes on high-N
geometries, our direct backend doesn't yet handle every shape).
Callers see partial results rather than hard exceptions; the
structured ``CalibrationReport`` carries error strings instead.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pfc_inductor.fea.direct.models import DirectFeaResult

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackendOutcome:
    """Per-backend result + diagnostics for one calibration run.

    ``L_dc_uH`` is the only canonical comparison metric for now;
    Phase 2 will add ``L_ac_uH`` and ``P_core_W`` once the AC
    template lands. ``error`` carries the exception message when
    the backend fails (so the report explains the miss).
    """

    backend: str
    """One of ``"femmt"`` / ``"direct"`` / ``"analytical"``."""

    L_dc_uH: Optional[float] = None
    B_pk_T: Optional[float] = None
    wall_s: float = 0.0
    error: Optional[str] = None
    workdir: Optional[Path] = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CalibrationReport:
    """Aggregate of all backend outcomes for one input.

    The ``diff_pct`` field is the canonical "how close are we?"
    number — relative error of ``direct`` vs ``femmt`` (or
    ``analytical`` when FEMMT is unavailable). Phase 1.2's goal
    is to land this < 5 % across the curated EI test set.
    """

    outcomes: dict[str, BackendOutcome]

    @property
    def femmt(self) -> Optional[BackendOutcome]:
        return self.outcomes.get("femmt")

    @property
    def direct(self) -> Optional[BackendOutcome]:
        return self.outcomes.get("direct")

    @property
    def analytical(self) -> Optional[BackendOutcome]:
        return self.outcomes.get("analytical")

    @property
    def diff_pct(self) -> Optional[float]:
        """Relative error of direct vs the best available oracle.

        Preferred oracle: FEMMT (full FEA). Fallback: analytical
        gap-dominated formula ``μ₀N²Ae/lgap`` (ignores fringing
        and iron contribution, so good only as a sanity floor).
        """
        d = self.direct
        if d is None or d.L_dc_uH is None:
            return None
        oracle = self.femmt or self.analytical
        if oracle is None or oracle.L_dc_uH is None or oracle.L_dc_uH == 0:
            return None
        return (d.L_dc_uH - oracle.L_dc_uH) / oracle.L_dc_uH * 100.0

    def __str__(self) -> str:
        lines = ["Calibration report:"]
        for name in ("femmt", "direct", "analytical"):
            o = self.outcomes.get(name)
            if o is None:
                lines.append(f"  {name:>10s}: (skipped)")
                continue
            if o.error:
                lines.append(f"  {name:>10s}: ERROR — {o.error[:80]}")
                continue
            l = o.L_dc_uH
            b = o.B_pk_T
            lines.append(
                f"  {name:>10s}: L={l:>8.1f} μH"
                f"{f' · B_pk={b:.3f} T' if b is not None else ''}"
                f" · {o.wall_s:.2f}s"
            )
        if self.diff_pct is not None:
            lines.append(f"  diff_pct  = {self.diff_pct:+.1f}% (direct vs oracle)")
        return "\n".join(lines)


# ─── Analytical reference ────────────────────────────────────────


def analytical_L_uH(*, core: object, n_turns: int, mu_r: float) -> float:
    """Closed-form gap-dominated inductance.

    Returns ``L ≈ μ₀ · N² · Ae / (le/μ_r + lgap)`` in μH. Treats
    the core as a single-loop magnetic circuit, no fringing, no
    leakage, no saturation. The FEM result will diverge from this
    by ~5 % on real EI cores (fringing) and more for short gaps
    (where fringing dominates), but it's a useful sanity floor —
    if the FEM says 100× more, something is broken in the FEM.
    """
    import math

    mu0 = 4.0 * math.pi * 1e-7
    Ae = float(core.Ae_mm2) * 1e-6
    le = float(core.le_mm) * 1e-3
    lgap = float(getattr(core, "lgap_mm", 0.0)) * 1e-3
    if lgap <= 0.0:
        lgap = 1e-6  # closed core — treat as a tiny equivalent gap
    reluctance = le / (mu_r * mu0 * Ae) + lgap / (mu0 * Ae)
    L_H = (n_turns * n_turns) / reluctance
    return L_H * 1e6


# ─── Backend runners ──────────────────────────────────────────────


def _run_direct(
    *,
    core,
    material,
    wire,
    n_turns: int,
    current_A: float,
    workdir: Path,
) -> BackendOutcome:
    """Run the direct ONELAB backend, catching all failures."""
    from pfc_inductor.fea.direct.runner import run_direct_fea

    t0 = time.perf_counter()
    try:
        res: DirectFeaResult = run_direct_fea(
            core=core,
            material=material,
            wire=wire,
            n_turns=n_turns,
            current_A=current_A,
            workdir=workdir,
        )
        return BackendOutcome(
            backend="direct",
            L_dc_uH=res.L_dc_uH,
            B_pk_T=res.B_pk_T,
            wall_s=time.perf_counter() - t0,
            workdir=res.workdir,
            extra={"mesh_nodes": res.mesh_n_nodes, "mesh_elems": res.mesh_n_elements},
        )
    except Exception as exc:
        return BackendOutcome(
            backend="direct",
            wall_s=time.perf_counter() - t0,
            error=f"{type(exc).__name__}: {exc}",
        )


def _run_femmt(
    *,
    spec,
    core,
    material,
    wire,
    result,
    workdir: Path,
) -> BackendOutcome:
    """Run FEMMT validation through our adapter. Returns an outcome
    with ``error`` set if FEMMT isn't installed or hits any other
    failure path.

    Wired to ``pfc_inductor.fea.femmt_runner.validate_design_femmt``
    (the same path the cascade Tier 3 production code uses). That
    adapter takes care of:

    - subprocess isolation against GetDP SIGSEGV
    - ``pkg_resources`` availability probe (setuptools<70)
    - ONELAB binary discovery
    - turn-count sanity check (FEMMT crashes above ~150 turns)

    Returns L_dc_uH from FEMMT's ``L_FEA_uH`` field. Note that
    FEMMT's number is an inductance at zero DC bias from the
    flux-linkage / current ratio; the direct backend's
    ``DirectFeaResult.L_dc_uH`` is the equivalent quantity, so
    direct comparison is meaningful.
    """
    from pfc_inductor.fea.femmt_runner import validate_design_femmt
    from pfc_inductor.fea.models import FEMMNotAvailable, FEMMSolveError

    t0 = time.perf_counter()
    try:
        val = validate_design_femmt(
            spec=spec,
            core=core,
            wire=wire,
            material=material,
            result=result,
            output_dir=workdir,
        )
        # FEAValidation uses ``L_FEA_uH``/``B_pk_FEA_T``; older
        # branches used different names — be defensive against
        # version drift.
        L = (
            getattr(val, "L_FEA_uH", None)
            or getattr(val, "L_uH", None)
            or getattr(val, "L_dc_uH", None)
        )
        B = (
            getattr(val, "B_pk_FEA_T", None)
            or getattr(val, "B_pk_T", None)
            or getattr(val, "B_peak_T", None)
        )
        return BackendOutcome(
            backend="femmt",
            L_dc_uH=float(L) if L is not None else None,
            B_pk_T=float(B) if B is not None else None,
            wall_s=time.perf_counter() - t0,
            workdir=workdir,
            extra={
                "femm_binary": getattr(val, "femm_binary", ""),
                "L_analytic_uH": getattr(val, "L_analytic_uH", None),
                "L_pct_error": getattr(val, "L_pct_error", None),
            },
        )
    except FEMMNotAvailable as exc:
        return BackendOutcome(
            backend="femmt",
            wall_s=time.perf_counter() - t0,
            error=f"FEMMNotAvailable: {exc}",
        )
    except FEMMSolveError as exc:
        return BackendOutcome(
            backend="femmt",
            wall_s=time.perf_counter() - t0,
            error=f"FEMMSolveError: {exc}",
        )
    except Exception as exc:
        return BackendOutcome(
            backend="femmt",
            wall_s=time.perf_counter() - t0,
            error=f"{type(exc).__name__}: {exc}",
        )


# ─── Public entry point ───────────────────────────────────────────


def compare_backends(
    *,
    core,
    material,
    wire,
    n_turns: int,
    current_A: float,
    spec=None,
    design_result=None,
    workdir_root: Optional[Path] = None,
    include_femmt: bool = True,
    include_direct: bool = True,
    include_analytical: bool = True,
) -> CalibrationReport:
    """Run multiple FEA backends on the same input, return a diff.

    Each backend gets its own subdirectory under ``workdir_root``
    (auto-created in a tmp dir if not given). The ``spec`` and
    ``design_result`` arguments are only needed for FEMMT — the
    direct backend works from ``core``/``material``/``wire``
    alone.

    Returns a :class:`CalibrationReport` with one
    :class:`BackendOutcome` per requested backend. Use the
    ``diff_pct`` property to assess "how close are we to the
    oracle?".

    Typical Phase 1.2 use::

        report = compare_backends(
            core=ei_core,
            material=ferrite,
            wire=awg14,
            n_turns=80,
            current_A=5.0,
        )
        print(report)
        if abs(report.diff_pct) > 5.0:
            ... iterate on physics/magnetostatic.py
    """
    if workdir_root is None:
        import tempfile

        workdir_root = Path(tempfile.mkdtemp(prefix="fea_calib_"))
    else:
        workdir_root.mkdir(parents=True, exist_ok=True)

    outcomes: dict[str, BackendOutcome] = {}

    if include_direct:
        outcomes["direct"] = _run_direct(
            core=core,
            material=material,
            wire=wire,
            n_turns=n_turns,
            current_A=current_A,
            workdir=workdir_root / "direct",
        )

    if include_femmt and spec is not None and design_result is not None:
        outcomes["femmt"] = _run_femmt(
            spec=spec,
            core=core,
            material=material,
            wire=wire,
            result=design_result,
            workdir=workdir_root / "femmt",
        )

    if include_analytical:
        mu_r = float(
            getattr(material, "mu_r", None) or getattr(material, "mu_r_initial", None) or 1.0
        )
        L = analytical_L_uH(core=core, n_turns=n_turns, mu_r=mu_r)
        outcomes["analytical"] = BackendOutcome(
            backend="analytical",
            L_dc_uH=L,
            wall_s=0.0,
            extra={"formula": "μ₀N²Ae/(le/μ_r + lgap)"},
        )

    return CalibrationReport(outcomes=outcomes)


__all__ = [
    "BackendOutcome",
    "CalibrationReport",
    "analytical_L_uH",
    "compare_backends",
]
