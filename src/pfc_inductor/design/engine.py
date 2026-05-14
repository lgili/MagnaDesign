"""Design engine: orchestrates everything from (Spec, Core, Wire, Material) -> DesignResult.

Workflow:
1. Compute operating point from spec + Vin_nom (currents, required L).
2. Solve N: smallest integer N such that L_actual(N) >= L_required.
   - L_actual(N) = N^2 * AL * mu_pct(H_dc(N, I_dc_pk))
   - For powder cores this is iterative: H depends on N, mu depends on H.
3. Compute B_pk and check saturation.
4. Compute losses at temperature T:
   - DC copper at I_line_rms.
   - AC copper at I_ripple_rms (Dowell with layers from window).
   - Core loss line + ripple (Steinmetz, both bands).
5. Iterate on temperature until converged.
6. Generate waveforms for plotting.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

import numpy as np

from pfc_inductor.models import (
    Core,
    DesignResult,
    LossBreakdown,
    Material,
    Spec,
    Wire,
)
from pfc_inductor.physics import copper as cp
from pfc_inductor.physics import core_loss as cl
from pfc_inductor.physics import rolloff as rf
from pfc_inductor.physics import thermal as th
from pfc_inductor.topology import (
    boost_ccm,
    buck_ccm,
    flyback,
    interleaved_boost_pfc,
    line_reactor,
    passive_choke,
)


def _solve_N(
    L_required_uH: float,
    core: Core,
    material: Material,
    I_dc_pk_A: float,
    N_max: int = 500,
) -> tuple[int, float, float]:
    """Smallest N such that L(N) >= L_required, with rolloff applied at peak DC bias.

    Returns (N, L_actual_uH, mu_pct_at_peak).

    Hot path — iterates 1–500× per ``engine.design()`` call, with
    ``rf.mu_pct`` going through Pydantic attribute access on every
    iteration. The Numba kernel (when the ``[performance]`` extra
    is installed) pulls the rolloff coefficients out once and runs
    the entire loop in compiled native code; the pure-Python
    branch below is the fallback.
    """
    if _SOLVE_N_KERNEL is not None:
        rl = material.rolloff
        if rl is not None:
            N, L_uH, mu = _SOLVE_N_KERNEL(
                float(L_required_uH),
                float(core.AL_nH),
                float(core.le_mm),
                float(I_dc_pk_A),
                int(N_max),
                float(rl.a),
                float(rl.b),
                float(rl.c),
                True,
            )
        else:
            N, L_uH, mu = _SOLVE_N_KERNEL(
                float(L_required_uH),
                float(core.AL_nH),
                float(core.le_mm),
                float(I_dc_pk_A),
                int(N_max),
                0.0,
                0.0,
                0.0,
                False,
            )
        return int(N), float(L_uH), float(mu)
    # Pure-Python fallback (Numba not installed).
    AL = core.AL_nH
    le = core.le_mm
    for N in range(1, N_max + 1):
        H_pk = rf.H_from_NI(N, I_dc_pk_A, le, units="Oe")
        mu = rf.mu_pct(material, H_pk)
        L_uH = rf.inductance_uH(N, AL, mu)
        if L_uH >= L_required_uH:
            return N, L_uH, mu
    H_pk = rf.H_from_NI(N_max, I_dc_pk_A, le, units="Oe")
    mu = rf.mu_pct(material, H_pk)
    L_uH = rf.inductance_uH(N_max, AL, mu)
    return N_max, L_uH, mu


# ─── Numba-accelerated _solve_N kernel ────────────────────────────
#
# The pure-Python loop calls ``rf.mu_pct(material, H)`` up to 500
# times per design. Each call goes through Pydantic attribute
# lookup on ``material.rolloff.{a,b,c}`` — the per-call overhead
# dominates. The kernel pulls coefficients out once and runs the
# entire binary search in compiled native code.

_OE_PER_AM_KERNEL = 1.0 / 79.5774715459  # mirrors ``rolloff.OE_PER_AM``


def _build_solve_n_kernel() -> Callable[..., tuple[int, float, float]] | None:
    """Compile the ``_solve_N`` inner loop with Numba if available.

    Returns the compiled function or ``None`` if Numba isn't
    installed (the public API falls back to pure Python in that
    case). The ``Callable`` return type is intentionally loose —
    the kernel's exact JIT-compiled signature is opaque to Python
    and we only ever ``call`` it with a fixed argument bundle.
    """
    try:
        from numba import njit
    except ImportError:
        return None

    @njit(fastmath=True, cache=True, nogil=True)
    def _kernel(
        L_required_uH: float,
        AL_nH: float,
        le_mm: float,
        I_dc_pk_A: float,
        N_max: int,
        rolloff_a: float,
        rolloff_b: float,
        rolloff_c: float,
        has_rolloff: bool,
    ) -> tuple[int, float, float]:
        le_m = le_mm * 1e-3
        for N in range(1, N_max + 1):
            if has_rolloff:
                H_Oe = N * I_dc_pk_A / le_m * _OE_PER_AM_KERNEL
                if H_Oe < 1e-6:
                    H_Oe = 1e-6
                val = 1.0 / (rolloff_a + rolloff_b * (H_Oe**rolloff_c))
                if val > 1.0:
                    val = 1.0
                elif val < 0.0:
                    val = 0.0
                mu = val
            else:
                mu = 1.0
            L_uH = (N * N * AL_nH * mu) * 1e-3
            if L_uH >= L_required_uH:
                return N, L_uH, mu
        # N_max hit — return the cap.
        if has_rolloff:
            H_Oe = N_max * I_dc_pk_A / le_m * _OE_PER_AM_KERNEL
            if H_Oe < 1e-6:
                H_Oe = 1e-6
            val = 1.0 / (rolloff_a + rolloff_b * (H_Oe**rolloff_c))
            if val > 1.0:
                val = 1.0
            elif val < 0.0:
                val = 0.0
            mu = val
        else:
            mu = 1.0
        L_uH = (N_max * N_max * AL_nH * mu) * 1e-3
        return N_max, L_uH, mu

    return _kernel


_SOLVE_N_KERNEL = _build_solve_n_kernel()


def _line_envelope_B_pk_T(
    N: int, I_line_pk_A: float, Ae_mm2: float, AL_nH: float, mu_pct_at_peak: float
) -> float:
    """Peak flux density from the line-frequency envelope (peak DC current)."""
    return rf.B_dc_T(N, I_line_pk_A, AL_nH, Ae_mm2, mu_pct_at_peak)


# Lamination materials that ship as a CLOSED magnetic path by design.
# Their high μ_i (3000–10000) combined with high B_sat (1.5–2.0 T)
# means line-frequency reactors are sized by N alone — adding an air
# gap only reduces L without any saturation benefit. The catalog
# ``AL_nH`` for these cores already reflects the as-shipped closed
# geometry (manufacturer-measured).
#
# Why this matters: before this gate landed, the auto-gap path below
# (case 3) was inventing 10+ mm air gaps for closed Si-Fe EI cores
# whenever the line reactor design saturated at the candidate N — a
# physically nonexistent gap that drove AL_eff from 392 nH down to
# 12.8 nH and made the engine disagree with the direct FEA backend by
# 170 %. The right answer for a saturating closed core is "pick a
# bigger core", not "synthesise a gap that doesn't exist".
_CLOSED_PATH_MATERIAL_TYPES = frozenset(
    {"silicon-steel", "amorphous", "nanocrystalline"}
)


# Shapes that are CLOSED magnetic paths by topology — adding an air
# gap is physically impossible (you'd have to break the core in two,
# which is what a discrete-gap E/EI does but a toroid can't).
#
# Without this gate, ``_resolve_gap_and_AL`` was injecting phantom
# gaps into ferrite toroids when the design saturated, then reporting
# nonsense AL values that disagreed with the direct backend's
# toroidal solver by 1500 %+ (the toroidal solver ignores any
# fake gap and uses the analytical closed-form for the toroid's
# magnetic path).
_CLOSED_PATH_SHAPES = frozenset({"toroid", "toroidal", "t"})


def _fringing_factor_roters(lgap_mm: float, w_centerleg_mm: float) -> float:
    """Roters / McLyman fringing factor — must mirror the direct backend.

    ``k = 1 + 2·sqrt(lgap / w_centerleg)`` clamped to ``[1.0, 3.0]``.

    Lives in this module (not imported from the direct backend) to keep
    ``design.engine`` free of any FEA-pipeline dependencies. The
    formula is duplicated by intent — the direct backend's copy lives
    at :func:`pfc_inductor.fea.direct.physics.reluctance_axi.fringing_factor_roters`
    and both must stay in lock-step (verified by the parity tests in
    ``tests/test_closed_path_no_autogap.py`` and the comprehensive
    boost-PFC sweep).
    """
    if lgap_mm <= 0.0 or w_centerleg_mm <= 0.0:
        return 1.0
    k = 1.0 + 2.0 * math.sqrt(lgap_mm / w_centerleg_mm)
    return max(1.0, min(k, 3.0))


def _estimate_center_leg_width_mm(core: Core) -> float:
    """Estimate the centre-leg cross-section width for Roters' formula.

    The Roters fringing factor needs ``w_centerleg`` — the linear
    dimension of the side perpendicular to the gap. The catalog
    rarely populates that field directly, so we back-derive an
    equivalent width from ``Ae`` assuming a roughly square / circular
    cross-section::

        w_eq = sqrt(Ae)

    For non-square legs the error is bounded: a 1:2 rectangle gives
    ``w_eq`` between the short and long sides, which is the right
    ballpark for fringing flux that wraps the smaller side. The
    direct backend's reluctance solver uses the same approximation
    when it computes its own k_fringe (so the two stay aligned even
    on cores with anisotropic legs).
    """
    Ae_mm2 = float(getattr(core, "Ae_mm2", 0.0) or 0.0)
    if Ae_mm2 <= 0:
        return 0.0
    return math.sqrt(Ae_mm2)


def _solve_lgap_with_fringing(
    *,
    l_eff_required_m: float,
    le_m: float,
    mu_r: float,
    w_centerleg_mm: float,
    max_iter: int = 8,
    tol_m: float = 1e-7,
) -> tuple[float, float]:
    """Iterate to find ``lgap_phys`` that delivers ``L_required``
    after fringing flux is accounted for.

    Closed-form reluctance model with fringing::

        l_eff_total = le / μ_r + lgap_phys / k_fringe(lgap_phys)

    where ``l_eff_total`` is the effective reluctance length that
    satisfies ``L = μ₀·N²·Ae / l_eff_total``. Without fringing the
    naive answer is ``lgap_phys = l_eff_total − le/μ_r``. But
    fringing flux around the gap shortens its effective length, so
    the *physical* gap must be larger by exactly the factor
    ``k_fringe``. Fixed-point iteration on::

        lgap_phys_{n+1} = (l_eff_total − le/μ_r) × k_fringe(lgap_phys_n)

    converges in 3–5 steps for the [1.0, 3.0] Roters range (the
    fringing factor is a slowly-varying function of lgap).

    Returns ``(lgap_phys_m, k_fringe)``. When the iron path already
    dominates (``le/μ_r ≥ l_eff_total``), the design doesn't need a
    gap and we return ``(0, 1.0)``.
    """
    iron_path_m = le_m / mu_r
    no_fringe_gap = l_eff_required_m - iron_path_m
    if no_fringe_gap <= 0.0:
        return 0.0, 1.0

    # First guess: no fringing.
    lgap_m = no_fringe_gap
    k_fringe = 1.0
    for _ in range(max_iter):
        k_new = _fringing_factor_roters(lgap_m * 1e3, w_centerleg_mm)
        lgap_new = no_fringe_gap * k_new
        if abs(lgap_new - lgap_m) < tol_m:
            lgap_m = lgap_new
            k_fringe = k_new
            break
        lgap_m = lgap_new
        k_fringe = k_new
    return lgap_m, k_fringe


def _resolve_gap_and_AL(
    core: Core,
    material: Material,
    L_req_uH: float,
    I_pk_A: float,
    Bsat_limit_T: float,
    N_override: Optional[int],
) -> tuple[Core, float]:
    """Return ``(effective_core, gap_used_mm)`` accounting for the air gap.

    Four regimes, decided by the material type + rolloff field:

    1. **Powder / rolloff materials** — the catalog ``AL_nH`` already
       reflects the manufacturer's distributed gap and ``mu_pct``
       handles DC-bias rolloff. Returns the core unchanged.

    2. **Si-Fe / amorphous / nanocrystalline lamination** — closed
       magnetic path by design. Catalog ``AL_nH`` is the as-shipped
       value; no auto-gap. If the design saturates, the engine warns
       downstream so the user picks a bigger core. Honours an
       explicit ``lgap_mm > 0`` in the catalog (rare — some line-
       reactor cores ship with a stamped gap) without overwriting AL.

    3. **Ferrite / no-rolloff with catalog or user-set ``lgap_mm > 0``**
       — the catalog ``AL_nH`` for these cores is the *ungapped* value;
       the engine recomputes ``AL_eff = μ₀·Ae / (le/μ_r + lgap)`` so
       both the iron-path and gap reluctance are accounted for. Returns
       a derived core with the corrected ``AL_nH``.

    4. **Ferrite / no-rolloff with ``lgap_mm == 0``** — the engineering
       no-op the user warned about. Auto-compute the gap from the
       saturation constraint::

           N_min = L · I_pk / (Bsat · Ae)        # energy-storage form
           N     = ceil(N_min)
           l_eff = N² · μ₀ · Ae / L              # required reluctance
           lgap  = max(0, l_eff − le/μ_r)        # subtract iron path

       Then ``AL_eff = μ₀·Ae / l_eff``. The forced-N path (``N_override``)
       takes the user's N as authoritative and solves for the gap that
       hits the L target.

    The returned ``effective_core`` is a Pydantic copy with ``AL_nH``
    and ``lgap_mm`` updated; ``Ae``, ``le``, ``Wa``, ``MLT`` etc. are
    unchanged.
    """
    # Powder: distributed gap is baked into AL_nH. Trust the catalog.
    if material.rolloff is not None:
        return core, float(core.lgap_mm)

    # Si-Fe / amorphous / nanocrystalline lamination: closed path,
    # no auto-gap. See ``_CLOSED_PATH_MATERIAL_TYPES`` docstring above.
    mat_type = str(getattr(material, "type", "") or "").strip().lower()
    if mat_type in _CLOSED_PATH_MATERIAL_TYPES:
        return core, float(core.lgap_mm)

    # Toroidal ferrites (and other closed-shape topologies): same
    # rationale as Si-Fe — the core has no place for a discrete air
    # gap, so the auto-gap path produces a phantom number that
    # disagrees with the direct backend's toroidal closed-form solver.
    shape = str(getattr(core, "shape", "") or "").strip().lower()
    if shape in _CLOSED_PATH_SHAPES:
        return core, float(core.lgap_mm)

    Ae_m2 = float(core.Ae_mm2) * 1e-6
    le_m = float(core.le_mm) * 1e-3
    mu_r = max(float(getattr(material, "mu_initial", 0.0) or 1.0), 1.0)
    L_H = max(float(L_req_uH) * 1e-6, 1e-15)
    w_centerleg_mm = _estimate_center_leg_width_mm(core)

    if N_override is not None:
        # User-forced N. The gap is whatever makes ``L = N²·μ₀·Ae/l_eff``
        # land on ``L_req`` at that turn count, accounting for fringing
        # flux around the gap (otherwise the engine under-sizes the gap
        # and over-estimates the final L by 30–200 %).
        N_use = max(1, int(N_override))
        l_eff_m = rf.MU_0 * N_use * N_use * Ae_m2 / L_H
        lgap_m, k_fringe = _solve_lgap_with_fringing(
            l_eff_required_m=l_eff_m,
            le_m=le_m,
            mu_r=mu_r,
            w_centerleg_mm=w_centerleg_mm,
        )
    elif core.lgap_mm > 0.0:
        # Catalog (or user-override) gap. The physical gap is fixed;
        # we just compute its fringing factor so AL_eff matches the
        # direct backend's reluctance model.
        lgap_m = float(core.lgap_mm) * 1e-3
        k_fringe = _fringing_factor_roters(lgap_m * 1e3, w_centerleg_mm)
    else:
        # Auto-compute gap from the saturation constraint.
        Bsat = max(float(Bsat_limit_T), 1e-6)
        N_min = L_H * max(float(I_pk_A), 0.0) / (Bsat * Ae_m2)
        N_use = max(1, math.ceil(N_min))
        l_eff_m = rf.MU_0 * N_use * N_use * Ae_m2 / L_H
        lgap_m, k_fringe = _solve_lgap_with_fringing(
            l_eff_required_m=l_eff_m,
            le_m=le_m,
            mu_r=mu_r,
            w_centerleg_mm=w_centerleg_mm,
        )

    # AL_eff accounts for the gap's effective reluctance after fringing.
    # The total reluctance path the flux sees is
    # ``le/μ_r + lgap_phys/k_fringe`` (fringing shortens the gap's
    # effective length). Both the engine and the direct backend's
    # reluctance solver use this expression — keeping them in lock-step
    # is what closes the previous 30–200 % engine-vs-direct disagreement
    # on ferrite boost-PFC designs.
    l_eff_total_m = max(le_m / mu_r + lgap_m / max(k_fringe, 1e-9), 1e-9)
    AL_eff_nH = (rf.MU_0 * Ae_m2 / l_eff_total_m) * 1e9
    effective_core = core.model_copy(
        update={
            "AL_nH": float(AL_eff_nH),
            "lgap_mm": float(lgap_m) * 1e3,
        }
    )
    return effective_core, lgap_m * 1e3


# Initial guess for the iterative thermal solver. The first ``total_loss``
# evaluation needs *some* temperature; +30 K above ambient is a reasonable
# midpoint between "design works comfortably" and "near thermal runaway"
# for typical PFC chokes — it converges in 2–4 iterations from there.
# Exposed as a module constant so tweaks are visible to git blame.
_T_INIT_RISE_K_DEFAULT: float = 30.0


def design(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    Vin_design_Vrms: Optional[float] = None,
    *,
    T_init_rise_K: float = _T_INIT_RISE_K_DEFAULT,
    N_override: Optional[int] = None,
) -> DesignResult:
    """Run the full design pipeline.

    Parameters
    ----------
    spec, core, wire, material
        Inputs as documented at module level.
    Vin_design_Vrms
        Override for the worst-case input voltage used in current
        calculations. Defaults to ``spec.Vin_min_Vrms``.
    T_init_rise_K
        Initial winding-temperature rise above ambient handed to the
        thermal solver. Pure tuning knob — does not change the converged
        answer, only the iteration count. Keep at the module default
        unless profiling a slow case.
    N_override
        Force the winding turn count. When provided, ``_solve_N`` is
        skipped and the rest of the pipeline (rolloff, B_pk, copper /
        core losses, thermal converge) runs against the user-given
        ``N``. Used by the "Ajustar protótipo" panel — the engineer
        types the turn count they actually wound and the engine
        reports the resulting performance. If ``L_actual < L_required``
        the ``warnings`` list flags it; the engine does not raise.
    """
    # ---- Interleaved boost PFC ----
    # Each of N parallel boost stages carries 1/N of the total
    # input current. We size *one* inductor (the engine's
    # output represents one of the N identical units) by
    # delegating to the standard boost-CCM path on a per-phase
    # spec; ``result.notes`` carries the ``× N units`` badge so
    # the report layer multiplies the BOM accordingly. The
    # aggregate (input ripple cancellation, total losses ×N) is
    # presented as a derived view in the report — the per-unit
    # ``DesignResult`` stays the engine's canonical artefact.
    if spec.topology == "interleaved_boost_pfc":
        per_phase = interleaved_boost_pfc.per_phase_spec(spec)
        result = design(
            per_phase,
            core,
            wire,
            material,
            Vin_design_Vrms=Vin_design_Vrms,
            T_init_rise_K=T_init_rise_K,
            N_override=N_override,
        )
        n_phase = spec.n_interleave
        # Stash the multiplicity + topology marker in the
        # result so downstream consumers (UI, report) read
        # "× N identical units" without re-computing the spec.
        existing_notes = (result.notes or "").strip()
        badge = (
            f"× {n_phase} identical units (interleaved boost PFC, "
            f"per-phase Pout = {per_phase.Pout_W:.0f} W). "
            f"Aggregate input ripple is suppressed by Hwu-Yau "
            f"cancellation; the input filter sees ripple at "
            f"{n_phase} · f_sw."
        )
        result.notes = f"{badge}\n{existing_notes}" if existing_notes else badge
        return result

    warnings: list[str] = []

    # Worst-case for current is low line.
    Vin_design = Vin_design_Vrms or spec.Vin_min_Vrms

    if spec.topology == "boost_ccm":
        I_pk = boost_ccm.line_peak_current_A(spec, Vin_design)
        I_rms_line = boost_ccm.line_rms_current_A(spec, Vin_design)
        L_req = boost_ccm.required_inductance_uH(spec, Vin_design)
    elif spec.topology == "line_reactor":
        # Line reactor: sized by %Z at f_line. Rated current already
        # respected via spec.I_rated_Arms; Vin_design is ignored.
        I_pk = line_reactor.line_pk_current_A(spec)
        I_rms_line = line_reactor.line_rms_current_A(spec)
        L_req = line_reactor.required_inductance_uH(spec)
    elif spec.topology == "buck_ccm":
        # Buck DC-DC: ``I_pk`` here is the *average* output current —
        # the saturation-relevant peak (``Iout + ΔI_pp/2``) is recomputed
        # below once L is sized via ``buck_ccm.peak_inductor_current_A``.
        # ``I_rms_line`` is identical to ``Iout`` since buck has no AC
        # input on the inductor side.
        I_pk = buck_ccm.output_current_A(spec)
        I_rms_line = I_pk
        L_req = buck_ccm.required_inductance_uH(spec)
    elif spec.topology == "flyback":
        # Flyback: the engine treats the primary winding as "the
        # inductor" — N_turns becomes Np, L_actual becomes Lp,
        # I_pk becomes Ip_pk. The secondary winding is sized
        # afterwards from the turns ratio + window split, and its
        # copper loss is added to the primary's via the
        # ``P_cu_secondary`` term emitted in the result. ``I_pk``
        # here uses the design-time Lp (``required_primary_inductance``)
        # for the saturation envelope; the actual ``Lp_actual``-
        # informed peak is recomputed below.
        L_req = flyback.required_primary_inductance_uH(spec)
        I_pk = flyback.primary_peak_current(spec, L_req)
        I_rms_line = flyback.primary_rms_current(spec, L_req, I_pk)
    else:
        I_pk = passive_choke.line_peak_current_A(spec, Vin_design)
        I_rms_line = passive_choke.line_rms_current_A(spec, Vin_design)
        L_req = passive_choke.required_inductance_uH(spec, Vin_design)

    # Resolve the gap (and corresponding AL) BEFORE turn-count solving.
    # For powder cores the call is a no-op (catalog AL is correct); for
    # ferrites it auto-computes the gap if the catalog leaves it at 0,
    # which keeps an ungapped E core from silently saturating.
    Bsat_limit_pre = material.Bsat_100C_T * (1.0 - spec.Bsat_margin)
    core, gap_used_mm = _resolve_gap_and_AL(
        core,
        material,
        L_req_uH=L_req,
        I_pk_A=I_pk,
        Bsat_limit_T=Bsat_limit_pre,
        N_override=N_override,
    )

    if N_override is not None:
        # User-forced turn count — bypass the solver and just
        # evaluate L at the given N with the rolloff applied.
        # ``L_actual`` may fall below ``L_required``; we capture
        # that downstream via the warnings list, not by raising.
        N = int(N_override)
        H_pk_for_mu = rf.H_from_NI(N, I_pk, core.le_mm, units="Oe")
        mu_at_peak = rf.mu_pct(material, H_pk_for_mu)
        L_actual = rf.inductance_uH(N, core.AL_nH, mu_at_peak)
        if L_actual < L_req:
            warnings.append(
                f"L_actual={L_actual:.0f} µH below required {L_req:.0f} µH "
                f"with forced N={N} (Δ={L_req - L_actual:+.0f} µH)"
            )
    else:
        N, L_actual, mu_at_peak = _solve_N(L_req, core, material, I_pk)

    # Buck-CCM: now that L is sized, recompute I_pk to include the
    # worst-case ripple half so saturation is checked at the actual
    # peak current the inductor sees, not just Iout.
    if spec.topology == "buck_ccm":
        I_pk = buck_ccm.peak_inductor_current_A(spec, L_actual)

    # Flyback: same idea — once Lp_actual is known the primary
    # peak current may differ from the design-time estimate
    # because the chosen core's AL forces a slightly different
    # Np than the math expected.
    if spec.topology == "flyback":
        I_pk = flyback.primary_peak_current(spec, L_actual)
        I_rms_line = flyback.primary_rms_current(spec, L_actual, I_pk)

    H_pk = rf.H_from_NI(N, I_pk, core.le_mm, units="Oe")
    if spec.topology == "line_reactor":
        # B_pk for a line reactor comes from the fundamental V across it,
        # not from the DC bias envelope (we are at line frequency, not
        # switching frequency, and silicon-steel laminations have no
        # gradual rolloff — μ stays roughly constant up to Bsat).
        L_actual_mH = L_actual / 1000.0
        V_L_rms = line_reactor.voltage_drop_Vrms(L_actual_mH, spec)
        B_pk = line_reactor.fundamental_B_pk_T(N, V_L_rms, core.Ae_mm2, spec.f_line_Hz)
    else:
        B_pk = _line_envelope_B_pk_T(N, I_pk, core.Ae_mm2, core.AL_nH, mu_at_peak)
    T_amb = spec.T_amb_C
    Bsat = material.Bsat_100C_T  # use hot Bsat as safe limit
    Bsat_limit = Bsat * (1.0 - spec.Bsat_margin)
    # Cap B used in the Steinmetz loss model to Bsat (above that the material
    # is saturated and the loss model is invalid; we keep a sane number so the
    # warning is the user-facing signal, not absurd loss values).
    B_pk_for_loss = min(B_pk, Bsat)

    Ku = cp.window_utilization(N, wire, core.Wa_mm2)
    layers = cp.estimate_layers(N, wire, core.Wa_mm2)
    if Ku > spec.Ku_max:
        warnings.append(
            f"Window utilization {Ku * 100:.1f}% exceeds limit {spec.Ku_max * 100:.1f}%"
        )
    if B_pk > Bsat_limit:
        warnings.append(
            f"B_pk={B_pk * 1000:.0f} mT exceeds saturation limit "
            f"{Bsat_limit * 1000:.0f} mT (margin {spec.Bsat_margin * 100:.0f}%)"
        )

    # Waveforms (boost CCM and buck CCM carry switching-frequency
    # ripple). Line reactors and passive chokes carry only fundamental
    # + harmonics, no fsw ripple.
    if spec.topology == "boost_ccm":
        wf = boost_ccm.waveforms(spec, Vin_design, L_actual)
        I_total_rms = boost_ccm.rms_inductor_current_A(wf)
        delta_iL_avg = boost_ccm.ripple_avg_pp_A(wf)
        delta_iL_max = boost_ccm.ripple_max_pp_A(wf)
        I_pk_total = boost_ccm.peak_inductor_current_A(wf)
        # AC RMS of ripple component: from delta_iL(t)^2/12 averaged
        I_rip_rms = math.sqrt(float(np.mean(wf["delta_iL_pp_A"] ** 2 / 12.0)))
    elif spec.topology == "buck_ccm":
        wf = buck_ccm.waveforms(spec, L_actual)
        I_total_rms = buck_ccm.rms_inductor_current_from_waveform(wf)
        delta_iL_avg = buck_ccm.ripple_avg_pp_A(wf)
        delta_iL_max = buck_ccm.ripple_max_pp_A(wf)
        I_pk_total = buck_ccm.peak_inductor_current_from_waveform(wf)
        I_rip_rms = math.sqrt(float(np.mean(wf["delta_iL_pp_A"] ** 2 / 12.0)))
    elif spec.topology == "flyback":
        # Flyback's primary current is a triangular pulse over
        # ``D · Tsw`` (DCM) or a trapezoidal one (CCM). The engine
        # treats it the same way as the buck waveform — the per-
        # cycle ΔI_pp drives the AC-Cu / iGSE core-loss path. The
        # secondary trace lives in ``wf["is_pk_A"]`` and is surfaced
        # via the result's ``waveform_is_A`` field for the Análise
        # card; the primary RMS already covers the loss budget.
        n_ratio = flyback.optimal_turns_ratio(spec)
        wf = flyback.waveforms(spec, L_actual, n_ratio)
        I_total_rms = flyback.rms_inductor_current_from_waveform(wf)
        # Primary delta_iL ≈ Ip_pk (DCM ramps from 0).
        delta_iL_avg = float(np.mean(wf["delta_iL_pp_A"]))
        delta_iL_max = float(np.max(wf["delta_iL_pp_A"]))
        I_pk_total = float(wf["iL_pk_A"].max())
        I_rip_rms = math.sqrt(float(np.mean(wf["delta_iL_pp_A"] ** 2 / 12.0)))
    else:
        wf = None
        I_total_rms = I_rms_line
        delta_iL_avg = 0.0
        delta_iL_max = 0.0
        I_pk_total = I_pk
        I_rip_rms = 0.0

    # For a line reactor we treat the line frequency as the only
    # excitation, so the fsw column in the loss model is set to f_line.
    # That keeps `core_loss_W_pfc`'s "line band" computation honest and
    # zeroes out the "ripple band" by construction (delta_iL_avg = 0).
    fsw_kHz_for_loss = spec.f_line_Hz / 1000.0 if spec.topology == "line_reactor" else spec.f_sw_kHz
    fsw_Hz_for_skin = spec.f_line_Hz if spec.topology == "line_reactor" else spec.f_sw_kHz * 1000.0

    Ae_m2 = core.Ae_mm2 * 1e-6
    delta_B_avg_T = (L_actual * 1e-6) * delta_iL_avg / (max(N, 1) * Ae_m2) if N > 0 else 0.0
    delta_B_avg_T = min(delta_B_avg_T, 2.0 * Bsat)
    # Per-instant ΔB(t) array along line cycle for iGSE.
    if wf is not None and N > 0:
        delta_B_pp_T_array = (L_actual * 1e-6) * wf["delta_iL_pp_A"] / (N * Ae_m2)
        delta_B_pp_T_array = np.minimum(delta_B_pp_T_array, 2.0 * Bsat)
    else:
        delta_B_pp_T_array = None

    # Thermal-coupled loss iteration
    A_surface = th.surface_area_m2(core)
    T_init = T_amb + T_init_rise_K

    # ── Fused Numba kernel fast path ──
    # When the ``[performance]`` extra is installed, run the
    # entire thermal-converge + per-leaf-loss pipeline in a
    # single Numba kernel. Eliminates 6 thermal iterations × 5
    # Python boundary crossings = 30 dispatch calls per
    # ``engine.design()``. See ``physics/fused_kernel.py`` for
    # the kernel internals.
    fused_result = _try_fused_thermal(
        spec=spec,
        core=core,
        wire=wire,
        material=material,
        N=N,
        layers=layers,
        fsw_Hz_for_skin=fsw_Hz_for_skin,
        fsw_kHz_for_loss=fsw_kHz_for_loss,
        I_rms_line=I_rms_line,
        I_rip_rms=I_rip_rms,
        B_pk_for_loss=B_pk_for_loss,
        delta_B_avg_T=delta_B_avg_T,
        delta_B_pp_T_array=delta_B_pp_T_array,
        A_surface=A_surface,
        T_amb=T_amb,
        T_init=T_init,
    )
    if fused_result is not None:
        # ``P_total`` is reconstructed from the per-leaf components
        # below (sum into ``losses.P_total_W``), so the kernel's
        # composite return is unpacked into ``_`` to avoid a
        # shadowing ``RUF059`` warning.
        T_final, _, P_cu_dc, P_cu_ac, P_line, P_ripple, conv = fused_result
        Rdc_final = cp.Rdc_ohm(N, core.MLT_mm, wire.A_cu_mm2, T_final)
        Rac_final = cp.Rac_ohm(wire, fsw_Hz_for_skin, Rdc_final, layers, T_final)
    else:
        # ── Per-leaf fallback (no Numba, or material lacks Steinmetz) ──
        def total_loss_at_T(T_C: float) -> float:
            Rdc = cp.Rdc_ohm(N, core.MLT_mm, wire.A_cu_mm2, T_C)
            Rac = cp.Rac_ohm(wire, fsw_Hz_for_skin, Rdc, layers, T_C)
            P_cu_dc = cp.loss_dc_W(I_rms_line, Rdc)
            P_cu_ac = cp.loss_ac_W(I_rip_rms, Rac)
            P_line, P_ripple = cl.core_loss_W_pfc(
                material,
                spec.f_line_Hz,
                fsw_kHz_for_loss,
                B_pk_for_loss,
                delta_B_avg_T,
                core.Ve_mm3,
                delta_B_pp_T_array=delta_B_pp_T_array,
            )
            return P_cu_dc + P_cu_ac + P_line + P_ripple

        T_final, conv, _ = th.converge_temperature(
            total_loss_at_T,
            A_surface,
            T_amb,
            T_init_C=T_init,
        )
        # Final breakdown at T_final
        Rdc_final = cp.Rdc_ohm(N, core.MLT_mm, wire.A_cu_mm2, T_final)
        Rac_final = cp.Rac_ohm(wire, fsw_Hz_for_skin, Rdc_final, layers, T_final)
        P_cu_dc = cp.loss_dc_W(I_rms_line, Rdc_final)
        P_cu_ac = cp.loss_ac_W(I_rip_rms, Rac_final)
        # Pass ``delta_B_pp_T_array`` so the final-breakdown
        # ``P_core_ripple_W`` uses the same iGSE that drove the
        # thermal converge above. Pre-fix the final breakdown
        # silently fell back to the naïve <ΔB>/2 Steinmetz path,
        # making ``losses.P_total_W`` disagree with whatever loss
        # the converged temperature was actually balancing — a
        # subtle bug that surfaced when the fused Numba kernel
        # (which is iGSE-consistent) parity-tested against this
        # branch.
        P_line, P_ripple = cl.core_loss_W_pfc(
            material,
            spec.f_line_Hz,
            fsw_kHz_for_loss,
            B_pk_for_loss,
            delta_B_avg_T,
            core.Ve_mm3,
            delta_B_pp_T_array=delta_B_pp_T_array,
        )

    if not conv:
        warnings.append("Thermal solve did not fully converge")

    losses = LossBreakdown(
        P_cu_dc_W=P_cu_dc,
        P_cu_ac_W=P_cu_ac,
        P_core_line_W=P_line,
        P_core_ripple_W=P_ripple,
    )
    T_rise = T_final - T_amb

    if T_final > spec.T_max_C:
        warnings.append(f"Winding temperature {T_final:.1f}°C exceeds limit {spec.T_max_C:.1f}°C")

    sat_margin_pct = ((Bsat_limit - B_pk) / Bsat_limit) * 100.0 if Bsat_limit > 0 else 0.0

    # Line-reactor specific outputs (None for other topologies)
    pct_Z_actual: Optional[float] = None
    v_drop_pct: Optional[float] = None
    thd_pct: Optional[float] = None
    Pi_W: Optional[float] = None
    lr_waveform_t: Optional[list[float]] = None
    lr_waveform_i: Optional[list[float]] = None
    if spec.topology == "line_reactor":
        L_actual_mH = L_actual / 1000.0
        v_drop_pct = line_reactor.voltage_drop_pct(L_actual_mH, spec)
        # %Z actual is the realised drop expressed as a fraction of V_phase.
        pct_Z_actual = v_drop_pct
        thd_pct = line_reactor.estimate_thd_pct(pct_Z_actual, n_phases=spec.n_phases)
        # Synthesise the line current from its harmonic decomposition so
        # the plot panel can show the waveform + spectrum without doing
        # any solver work.
        t_arr, i_arr = line_reactor.line_current_waveform(
            spec,
            L_actual_mH,
            n_cycles=2,
            n_points=1200,
        )
        lr_waveform_t = t_arr.tolist()
        lr_waveform_i = i_arr.tolist()
        # Active input power used by IEC 61000-3-2 Class D limit. For a
        # diode bridge + cap + reactor the actual power factor sits in
        # the 0.93–0.97 band; we use 0.95 as a defensible default. The
        # user can override per-design later if calibration data exists.
        ASSUMED_PF = 0.95
        if spec.n_phases == 3:
            # Total 3-phase active power: √3 · V_LL · I · pf
            Pi_W = math.sqrt(3.0) * spec.Vin_nom_Vrms * spec.I_rated_Arms * ASSUMED_PF
        else:
            Pi_W = spec.Vin_nom_Vrms * spec.I_rated_Arms * ASSUMED_PF
    elif spec.topology == "boost_ccm":
        # Active PFC: line-side THD is a *control quality* metric
        # (the PFC loop forces i_in ≈ k·v_in). Calibrated empirical:
        # THD% ≈ ripple_pct/6 + 1, matching published TI / ON-Semi
        # reference designs.
        thd_pct = boost_ccm.estimate_thd_pct(spec)
    elif spec.topology == "passive_choke":
        # Topologically identical to a 1-φ line reactor: same
        # series-L + diode-bridge + bulk-cap loop. Reuse the
        # IEEE-519 fit through the choke's pct_Z.
        thd_pct = passive_choke.estimate_thd_pct(spec, L_actual)
        # Surface pct_Z too so the Análise label can show "pct_Z = X %"
        # the same way line_reactor does.
        pct_Z_actual = passive_choke.voltage_drop_pct(
            L_actual / 1000.0,
            spec.Vin_min_Vrms,
            spec.Pout_W,
            spec.f_line_Hz,
        )
    elif spec.topology == "buck_ccm":
        # Buck has DC output — line-side THD is undefined (depends on
        # the input EMI filter, not the inductor). The Análise card's
        # THD tile reads "—" for thd_estimate_pct == 0.
        thd_pct = buck_ccm.estimate_thd_pct(spec)
    elif spec.topology == "flyback":
        # Flyback runs from a DC bus too — same story as buck.
        thd_pct = flyback.estimate_thd_pct(spec)

    # ─── Flyback-specific outputs (None for every other topology) ─
    Lp_actual_uH: Optional[float] = None
    Np_turns: Optional[int] = None
    Ns_turns: Optional[int] = None
    Ip_peak_A: Optional[float] = None
    Ip_rms_A: Optional[float] = None
    Is_peak_A: Optional[float] = None
    Is_rms_A: Optional[float] = None
    L_leak_uH_out: Optional[float] = None
    V_drain_pk_V: Optional[float] = None
    V_diode_pk_V: Optional[float] = None
    P_snubber_W: Optional[float] = None
    waveform_is_A: Optional[list[float]] = None
    if spec.topology == "flyback":
        # Re-derive the secondary-side numbers from the as-built
        # primary. ``N`` is Np (the engine treats the primary as
        # "the inductor"); Ns falls out from the turns ratio.
        n_ratio = flyback.optimal_turns_ratio(spec)
        Lp_actual_uH = float(L_actual)
        # ``N`` is already an int (engine's ``_solve_N`` returns
        # the smallest integer turn-count); ``Np_turns`` is just an
        # alias for clarity in the flyback context.
        Np_turns = N
        Ns_turns = max(1, round(N / max(n_ratio, 1e-3)))
        Ip_peak_A = flyback.primary_peak_current(spec, L_actual)
        Ip_rms_A = flyback.primary_rms_current(spec, L_actual, Ip_peak_A)
        Is_peak_A = flyback.secondary_peak_current(spec, Ip_peak_A, n_ratio)
        Is_rms_A = flyback.secondary_rms_current(
            spec,
            L_actual,
            Ip_peak_A,
            n_ratio,
        )
        # Leakage inductance — empirical sandwich-winding default.
        # Layer count tracks the engine's own ``layers`` estimate
        # because more bobbin layers → more flux that doesn't link.
        L_leak_uH_out = flyback.leakage_inductance_uH(
            L_actual,
            layout="sandwich",
            n_layers=max(layers, 2),
        )
        V_drain_pk_V, V_diode_pk_V = flyback.reflected_voltages(
            spec,
            n_ratio,
        )
        P_snubber_W = flyback.snubber_dissipation_W(
            L_leak_uH_out,
            Ip_peak_A,
            spec.f_sw_kHz,
            n=n_ratio,
            Vout=spec.Vout_V,
        )
        # Surface the secondary-side trace separately so the Análise
        # card's stacked-trace plot has both currents.
        if wf is not None and "is_pk_A" in wf:
            waveform_is_A = wf["is_pk_A"].tolist()

    res = DesignResult(
        L_required_uH=L_req,
        L_actual_uH=L_actual,
        N_turns=N,
        I_line_pk_A=I_pk,
        I_line_rms_A=I_rms_line,
        I_ripple_pk_pk_A=delta_iL_max,
        I_pk_max_A=I_pk_total,
        I_rms_total_A=I_total_rms,
        H_dc_peak_Oe=H_pk,
        mu_pct_at_peak=mu_at_peak,
        B_pk_T=B_pk,
        B_sat_limit_T=Bsat_limit,
        sat_margin_pct=sat_margin_pct,
        R_dc_ohm=Rdc_final,
        R_ac_ohm=Rac_final,
        losses=losses,
        T_rise_C=T_rise,
        T_winding_C=T_final,
        Ku_actual=Ku,
        Ku_max=spec.Ku_max,
        converged=conv,
        warnings=warnings,
        waveform_t_s=(wf["t_s"].tolist() if wf is not None else lr_waveform_t),
        waveform_iL_A=(wf["iL_pk_A"].tolist() if wf is not None else lr_waveform_i),
        waveform_B_T=None,
        pct_impedance_actual=pct_Z_actual,
        voltage_drop_pct=v_drop_pct,
        thd_estimate_pct=thd_pct,
        Pi_W=Pi_W,
        Lp_actual_uH=Lp_actual_uH,
        Np_turns=Np_turns,
        Ns_turns=Ns_turns,
        Ip_peak_A=Ip_peak_A,
        Ip_rms_A=Ip_rms_A,
        Is_peak_A=Is_peak_A,
        Is_rms_A=Is_rms_A,
        L_leak_uH=L_leak_uH_out,
        V_drain_pk_V=V_drain_pk_V,
        V_diode_pk_V=V_diode_pk_V,
        P_snubber_W=P_snubber_W,
        waveform_is_A=waveform_is_A,
        gap_actual_mm=float(gap_used_mm),
        notes=(
            f"Design at Vin={Vin_design:.0f} Vrms (worst-case current). "
            f"Layers~{layers}. Material {material.name} ({material.vendor})."
        ),
    )
    return res


# ─── Fused thermal-converge fast path (Numba) ────────────────────


def _try_fused_thermal(
    *,
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    N: int,
    layers: int,
    fsw_Hz_for_skin: float,
    fsw_kHz_for_loss: float,
    I_rms_line: float,
    I_rip_rms: float,
    B_pk_for_loss: float,
    delta_B_avg_T: float,
    delta_B_pp_T_array: Optional[np.ndarray],
    A_surface: float,
    T_amb: float,
    T_init: float,
) -> Optional[tuple[float, float, float, float, float, float, bool]]:
    """Hand the thermal-converge + total-loss block to the Numba
    fused kernel when it's available.

    Returns ``(T_final, P_total, P_cu_dc, P_cu_ac, P_core_line,
    P_core_ripple, converged)`` — or ``None`` to signal the
    caller should use the per-leaf fallback (kernel not
    installed, or material lacks Steinmetz coefficients).
    """
    try:
        from pfc_inductor.physics.fused_kernel import (
            WIRE_LITZ,
            WIRE_OTHER,
            WIRE_ROUND,
            fused_converge,
        )
    except ImportError:
        return None
    # ``Material.steinmetz`` is a required field (see ``models.material``);
    # the kernel is callable for any catalog entry that loaded successfully.
    s = material.steinmetz

    if wire.type == "round" and wire.d_cu_mm:
        wire_kind = WIRE_ROUND
        d_cu_m = float(wire.d_cu_mm) * 1e-3
        d_strand_m = 0.0
        n_strands = 0
    elif wire.type == "litz" and wire.d_strand_mm and wire.n_strands:
        wire_kind = WIRE_LITZ
        d_cu_m = 0.0
        d_strand_m = float(wire.d_strand_mm) * 1e-3
        n_strands = int(wire.n_strands)
    else:
        wire_kind = WIRE_OTHER
        d_cu_m = 0.0
        d_strand_m = 0.0
        n_strands = 0

    return fused_converge(
        spec_T_amb_C=float(T_amb),
        spec_f_line_Hz=float(spec.f_line_Hz),
        A_surface_m2=float(A_surface),
        T_init_C=float(T_init),
        N=int(N),
        MLT_mm=float(core.MLT_mm),
        A_cu_mm2=float(wire.A_cu_mm2),
        fsw_Hz_skin=float(fsw_Hz_for_skin),
        fsw_kHz_loss=float(fsw_kHz_for_loss),
        layers=int(layers),
        wire_kind=int(wire_kind),
        d_cu_m=d_cu_m,
        d_strand_m=d_strand_m,
        n_strands=n_strands,
        I_dc_line=float(I_rms_line),
        I_rip_rms=float(I_rip_rms),
        B_pk_for_loss_T=float(B_pk_for_loss),
        delta_B_avg_T=float(delta_B_avg_T),
        delta_B_pp_T_array=delta_B_pp_T_array,
        Ve_mm3=float(core.Ve_mm3),
        Pv_ref=float(s.Pv_ref_mWcm3),
        alpha=float(s.alpha),
        beta=float(s.beta),
        B_ref_mT=float(s.B_ref_mT),
        f_ref_kHz=float(s.f_ref_kHz),
        f_min_kHz=float(s.f_min_kHz),
    )
