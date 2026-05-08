"""Cheap feasibility heuristics for core selection.

The full design engine takes 5–10 ms per (core, wire, material) combo;
running it across 50 cores when the user just wants to see "which cores
even fit?" feels laggy. This module provides O(1) filters per core that
catch the obvious losers (too small to reach L_required, window way too
small for the wire) without any solver work.

The logic intentionally stays loose — false negatives (rejecting a core
that *would* have produced a feasible design) are worse than false
positives (showing one that turns out infeasible after the user clicks
"Calcular"). Tunable thresholds:

- ``N_estimate <= N_HARD_CAP`` (250 turns) — anything beyond is unlikely
  to fit physically, even with thin wire.
- ``Ku_estimate <= 0.7`` — the engine itself caps at user's ``Ku_max``,
  but we allow a healthy 0.7 cushion in the heuristic to avoid
  rejecting cores the engine could solve with a slightly different
  wire.
"""
from __future__ import annotations

import math
from typing import Literal

from pfc_inductor.models import Core, Material, Spec, Wire
from pfc_inductor.topology import boost_ccm, line_reactor, passive_choke

# Per-topology cap on the heuristic's estimated turn count. PFC
# chokes are HF (≥ 50 kHz) so their L sits in the µH band — even a
# 2 kW design rarely needs more than ~150 turns. Line-frequency
# inductors (passive_choke at 50/60 Hz, line_reactor 1φ/3φ) sit
# in the mH band; with the same AL nH/turn² the wire count to
# reach a few mH naturally lands in the 300–800 range. A single
# global cap rejected every passive-choke candidate in the
# curated DB; topology-aware caps keep the boost path tight while
# letting AC chokes through.
N_HARD_CAP_BY_TOPOLOGY: dict[str, int] = {
    "boost_ccm": 250,
    "passive_choke": 1000,
    "line_reactor": 1000,
}
N_HARD_CAP_DEFAULT = 250

# Back-compat: external code (and tests) read `N_HARD_CAP` as a
# constant. We keep the name pointing at the boost-CCM cap, which
# was the only value the constant ever held in practice.
N_HARD_CAP = N_HARD_CAP_BY_TOPOLOGY["boost_ccm"]

KU_HEADROOM = 0.7    # quick-check cap; engine has its own user-set Ku_max
B_HEADROOM = 1.6     # accept B_pk up to 1.6 × Bsat in heuristic — engine
                     # may still produce feasible after rolloff/saturation


def _n_hard_cap(spec: Spec) -> int:
    """Heuristic turn-count cap for `spec.topology`."""
    return N_HARD_CAP_BY_TOPOLOGY.get(spec.topology, N_HARD_CAP_DEFAULT)


Verdict = Literal["ok", "too_small_L", "window_overflow", "saturates"]


def required_L_uH(spec: Spec) -> float:
    """Pre-design L target (no rolloff, just topology math).

    Public helper used by both the feasibility filter and the scoring
    layer. Dispatches to the topology module that owns the analytical
    formula for the requested topology.
    """
    if spec.topology == "line_reactor":
        return line_reactor.required_inductance_uH(spec)
    if spec.topology == "boost_ccm":
        return boost_ccm.required_inductance_uH(spec, spec.Vin_min_Vrms)
    return passive_choke.required_inductance_uH(spec, spec.Vin_min_Vrms)


def peak_current_A(spec: Spec) -> float:
    """Worst-case peak inductor current for the spec's topology.

    Public helper used by feasibility checks, scoring heuristics, and
    any caller that needs a quick I_pk estimate without spinning the
    full ``design()`` pipeline.
    """
    if spec.topology == "line_reactor":
        return line_reactor.line_pk_current_A(spec)
    if spec.topology == "boost_ccm":
        return boost_ccm.line_peak_current_A(spec, spec.Vin_min_Vrms)
    return passive_choke.line_peak_current_A(spec, spec.Vin_min_Vrms)


# Back-compat aliases — leading underscore previously implied "private",
# but ``optimize.scoring`` had to import them anyway. Keep the old names
# pointing to the new public functions so any external caller (or test)
# that was reaching in still works while we migrate.
_required_L_uH = required_L_uH
_peak_current_A = peak_current_A


def core_quick_check(
    spec: Spec, core: Core, material: Material, wire: Wire,
) -> Verdict:
    """O(1) viability check.

    Returns ``"ok"`` for cores that *might* yield a feasible design,
    or a one-word reason otherwise. Designed for combo-box filtering
    where running the full engine would be too slow.
    """
    L_req_uH = required_L_uH(spec)
    if L_req_uH <= 0:
        return "ok"

    n_cap = _n_hard_cap(spec)

    # 1. Can we reach L_required with at most `n_cap` turns,
    #    assuming the worst-case rolloff penalty?
    AL_nH = max(core.AL_nH, 1e-9)
    # Worst-case rolloff: powder cores with high DC bias drop to ~30 %
    # of initial μ. We use 0.5 as a generous heuristic so we don't
    # exclude cores that could survive moderate bias.
    L_max_uH = (n_cap ** 2) * AL_nH * 0.5 * 1e-3
    if L_max_uH < L_req_uH:
        return "too_small_L"

    # 2. Estimate N at unit μ_pct (lower bound on N).
    N_estimate = math.ceil(math.sqrt(L_req_uH / (AL_nH * 1e-3)))
    if N_estimate > n_cap:
        return "too_small_L"

    # 3. Window check at the estimated N. Single-layer wire area;
    #    we know the engine inflates Ku by insulation/airgap factors,
    #    so we accept up to KU_HEADROOM here.
    Wa_mm2 = max(core.Wa_mm2, 1e-9)
    Ku_estimate = N_estimate * wire.A_cu_mm2 / Wa_mm2
    if Ku_estimate > KU_HEADROOM:
        return "window_overflow"

    # 4. Saturation. For line reactor at fundamental: B_pk grows
    #    linearly with N for a fixed core. For boost/choke: B_pk grows
    #    with N · I_pk / le.
    Bsat_T = material.Bsat_25C_T
    if spec.topology == "line_reactor":
        omega = 2.0 * math.pi * max(spec.f_line_Hz, 1.0)
        L_at_N_H = (N_estimate ** 2) * AL_nH * 1e-9
        V_L_rms = omega * L_at_N_H * spec.I_rated_Arms
        Ae_m2 = max(core.Ae_mm2 * 1e-6, 1e-12)
        B_pk = math.sqrt(2.0) * V_L_rms / (omega * N_estimate * Ae_m2)
    else:
        I_pk = peak_current_A(spec)
        Ae_m2 = max(core.Ae_mm2 * 1e-6, 1e-12)
        le_m = max(core.le_mm * 1e-3, 1e-9)
        # B = μ₀ · μᵣ · N · I / le (powder/ferrite) before rolloff
        mu_eff = material.mu_initial
        B_pk = (4.0 * math.pi * 1e-7) * mu_eff * N_estimate * I_pk / le_m

    if B_pk > B_HEADROOM * Bsat_T:
        return "saturates"

    return "ok"


def filter_viable_cores(
    spec: Spec, cores: list[Core], material: Material, wire: Wire,
) -> tuple[list[Core], dict[str, int]]:
    """Return ``(viable_cores, reason_counts)`` for the given spec.

    The reason_counts tally is useful for the UI label
    ("9 feasible · 23 hidden: 18 Ku, 5 saturation").
    """
    viable: list[Core] = []
    reasons: dict[str, int] = {"too_small_L": 0, "window_overflow": 0,
                               "saturates": 0}
    for c in cores:
        v = core_quick_check(spec, c, material, wire)
        if v == "ok":
            viable.append(c)
        else:
            reasons[v] = reasons.get(v, 0) + 1
    return viable, reasons


# ---------------------------------------------------------------------------
# Wire pre-filter — collapses 1 433-entry round-wire catalogs (every gauge
# from 0.0001 mm² grade-1 magnet wire to 107 mm² welding cable) down to
# the handful that could realistically carry the spec's rated current.
# Without this filter the cartesian Tier-0 sweep produces 1.7 M
# candidates per run; with it we land closer to ~10 k.
# ---------------------------------------------------------------------------

# Sane current-density window for a forced-air or natural-convection
# inductor. Below 1.0 A/mm² the wire is grossly oversized (huge window,
# wasted copper). Above 15 A/mm² the wire would smoke at full load on
# any realistic enclosure. The window is intentionally permissive —
# the engine itself rebalances Ku and applies thermal limits
# downstream, so this filter only needs to drop the *obvious* dead
# wood (0.0001 mm² magnet wire, 100 mm² welding cable) before the
# Tier 0 envelope check sees them.
J_MIN_A_PER_MM2 = 1.0
J_MAX_A_PER_MM2 = 15.0


def rated_current_A(spec: Spec) -> float:
    """RMS current the inductor will see at full load.

    Used by :func:`viable_wires_for_spec` and the cascade pre-filter.
    Honours ``spec.eta`` when present (boost CCM input current scales
    inversely with converter efficiency).
    """
    if spec.topology == "line_reactor":
        return float(spec.I_rated_Arms or 0.0)
    if spec.Vin_min_Vrms <= 0 or spec.Pout_W <= 0:
        return 0.0
    eta = float(getattr(spec, "eta", 0.95) or 0.95)
    if spec.topology == "boost_ccm":
        # I_in_rms ≈ Pout / (Vin_rms · η) at low-line worst case.
        return spec.Pout_W / (spec.Vin_min_Vrms * max(eta, 0.5))
    # passive_choke and any future topology — derive from Pout / Vin.
    return spec.Pout_W / (spec.Vin_min_Vrms * max(eta, 0.5))


def viable_wires_for_spec(
    spec: Spec,
    wires: list[Wire],
    *,
    j_min: float = J_MIN_A_PER_MM2,
    j_max: float = J_MAX_A_PER_MM2,
) -> list[Wire]:
    """Drop wires whose ``J = I_rated / A_cu`` is out of the sensible band.

    Operates on the round-wire subset only (Litz wires have their own
    optimizer). Returns wires sorted by ascending A_cu so downstream
    sweeps see the smallest-viable-first ordering — useful for cores
    that are window-tight.

    When the spec has no rated-current information (Pout=0 or
    Vin_min=0), returns the input list unchanged so we don't silently
    swallow every wire on a half-configured spec.
    """
    i_rated = rated_current_A(spec)
    if i_rated <= 0:
        return list(wires)

    viable = []
    for w in wires:
        if w.A_cu_mm2 <= 0:
            continue
        j = i_rated / w.A_cu_mm2
        if j_min <= j <= j_max:
            viable.append(w)
    # Stable, deterministic ordering: smallest cross-section first.
    viable.sort(key=lambda w: w.A_cu_mm2)
    return viable
