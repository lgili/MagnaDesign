"""Litz wire optimizer.

Picks a strand diameter that hits a target AC/DC resistance ratio at the
switching frequency, sizes the strand count to a target current density,
and returns a `Wire` object that drops into the existing design pipeline.

Sullivan / Dowell relation for round-wire windings (small-ξ approximation):

    F_R = R_ac / R_dc ≈ 1 + (N_l² · (d/δ)⁴) / 9

where N_l is the effective layer count and δ is the skin depth in copper.
Solving for d at a target F_R = 1 + ε:

    d_opt = δ · (9·ε / N_l²)^(1/4)

For our toroidal cores N_l ≈ 1 (single-layer winding); for E/ETD/PQ
bobbin cores N_l grows with the number of vertical layers in the window.
The recommend() function defaults to N_l=1 for toroids, 5 otherwise.

Reference: C. Sullivan, "Optimal Choice for Number of Strands in a
Litz-Wire Transformer Winding", IEEE Trans. PE, vol. 14, no. 2, 1999.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional

from pfc_inductor.models import Spec, Core, Wire, Material, DesignResult
from pfc_inductor.physics.dowell import skin_depth_m, Rac_over_Rdc_litz
from pfc_inductor.physics.cost import wire_mass_per_meter_g, CU_DENSITY_KG_M3


# Standard AWG strand diameters (mm) used in Litz construction.
_AWG_STRAND_TABLE_MM: dict[int, float] = {
    28: 0.321, 30: 0.255, 32: 0.202, 34: 0.160, 36: 0.127,
    38: 0.101, 40: 0.080, 42: 0.064, 44: 0.050,
}


def optimal_strand_diameter_mm(
    f_Hz: float,
    layers: int = 1,
    target_AC_DC: float = 1.10,
    T_C: float = 25.0,
) -> float:
    """Strand diameter [mm] hitting the requested AC/DC ratio in a winding
    with N_l effective layers."""
    eps = max(target_AC_DC - 1.0, 1e-4)
    delta_mm = skin_depth_m(f_Hz, T_C) * 1000.0
    return delta_mm * (9.0 * eps / max(layers, 1) ** 2) ** 0.25


def closest_strand_AWG(d_mm: float) -> tuple[int, float]:
    """Closest AWG to a target strand diameter; returns (awg, d_mm_actual)."""
    best_awg = min(_AWG_STRAND_TABLE_MM, key=lambda a: abs(_AWG_STRAND_TABLE_MM[a] - d_mm))
    return best_awg, _AWG_STRAND_TABLE_MM[best_awg]


def strand_count_for_current(
    I_rms_A: float,
    target_J_A_mm2: float,
    d_strand_mm: float,
) -> int:
    """Strand count to satisfy I/J_target."""
    A_strand_mm2 = math.pi * d_strand_mm ** 2 / 4.0
    A_required_mm2 = I_rms_A / max(target_J_A_mm2, 1e-6)
    return max(1, math.ceil(A_required_mm2 / A_strand_mm2))


def bundle_diameter_mm(
    n_strands: int,
    d_strand_mm: float,
    packing: float = 0.7,
) -> float:
    """Outer bundle diameter [mm] including a packing service factor."""
    A_strand = math.pi * d_strand_mm ** 2 / 4.0
    A_total = n_strands * A_strand / max(packing, 0.05)
    return 2.0 * math.sqrt(A_total / math.pi)


def make_litz_wire(
    n_strands: int,
    d_strand_mm: float,
    awg_strand: Optional[int] = None,
    packing: float = 0.7,
    cost_per_kg_USD: float = 18.0,
    wire_id: Optional[str] = None,
) -> Wire:
    """Build a `Wire` model from a Litz construction with derived properties."""
    A_cu_mm2 = n_strands * math.pi * d_strand_mm ** 2 / 4.0
    d_bundle = bundle_diameter_mm(n_strands, d_strand_mm, packing)
    if wire_id is None:
        wire_id = f"Litz-{n_strands}x{d_strand_mm:.3f}mm"
    if awg_strand is None:
        awg_strand, _ = closest_strand_AWG(d_strand_mm)
    mass_per_m_g = (A_cu_mm2 * 1e-6) * CU_DENSITY_KG_M3 * 1000.0
    cost_per_m = (mass_per_m_g / 1000.0) * cost_per_kg_USD
    return Wire(
        id=wire_id,
        type="litz",
        awg_strand=awg_strand,
        d_strand_mm=d_strand_mm,
        n_strands=n_strands,
        d_bundle_mm=d_bundle,
        A_cu_mm2=A_cu_mm2,
        mass_per_meter_g=round(mass_per_m_g, 4),
        cost_per_meter=round(cost_per_m, 4),
        notes=(
            f"Litz {n_strands}×AWG{awg_strand} ({d_strand_mm:.3f} mm); "
            f"packing={packing:.2f}; demo cost @ ${cost_per_kg_USD:.0f}/kg"
        ),
    )


@dataclass
class LitzCandidate:
    wire: Wire
    awg_strand: int
    n_strands: int
    d_strand_mm: float
    d_bundle_mm: float
    A_cu_mm2: float
    AC_DC_ratio: float
    result: Optional[DesignResult] = None
    cost: Optional[float] = None  # total design cost
    feasible: bool = False
    reason: str = ""


@dataclass
class LitzRecommendation:
    spec: Spec
    core: Core
    material: Material
    layers_assumed: int
    target_J_A_mm2: float
    target_AC_DC: float
    fsw_Hz: float
    candidates: list[LitzCandidate] = field(default_factory=list)
    best: Optional[LitzCandidate] = None
    round_wire_baseline: Optional[LitzCandidate] = None  # repurposed dataclass

    @property
    def has_recommendation(self) -> bool:
        return self.best is not None and self.best.feasible


def _layers_for(core: Core) -> int:
    """Heuristic effective layer count for the Litz formula."""
    if "tor" in (core.shape or "").lower():
        return 1
    return 5  # E/ETD/PQ generic


def _evaluate(
    spec: Spec, core: Core, material: Material, wire: Wire,
    fsw_Hz: float, layers: int, max_bundle_mm: Optional[float] = None,
) -> LitzCandidate:
    """Run the design engine and assemble a LitzCandidate."""
    from pfc_inductor.design import design
    from pfc_inductor.physics.cost import estimate as estimate_cost

    cand = LitzCandidate(
        wire=wire,
        awg_strand=wire.awg_strand or 0,
        n_strands=wire.n_strands or 1,
        d_strand_mm=wire.d_strand_mm or 0.0,
        d_bundle_mm=wire.d_bundle_mm or 0.0,
        A_cu_mm2=wire.A_cu_mm2,
        AC_DC_ratio=Rac_over_Rdc_litz(
            (wire.d_strand_mm or 0.0) * 1e-3,
            wire.n_strands or 1, fsw_Hz, layers, T_C=25.0,
        ),
    )
    if max_bundle_mm is not None and cand.d_bundle_mm > max_bundle_mm:
        cand.reason = (
            f"Bundle {cand.d_bundle_mm:.2f} mm > limite {max_bundle_mm:.2f} mm"
        )
        return cand
    try:
        r = design(spec, core, wire, material)
    except Exception as e:
        cand.reason = f"design erro: {e}"
        return cand
    cand.result = r
    cand.feasible = r.is_feasible()
    if not cand.feasible:
        cand.reason = "; ".join(r.warnings) if r.warnings else "Inviável"
    cb = estimate_cost(core, wire, material, r.N_turns)
    cand.cost = cb.total_cost if cb is not None else None
    return cand


def recommend(
    spec: Spec,
    core: Core,
    material: Material,
    current_round_wires: list[Wire],
    target_J_A_mm2: float = 4.0,
    target_AC_DC: float = 1.10,
    max_strands: int = 2000,
    max_bundle_mm: Optional[float] = None,
    awg_search: tuple[int, ...] = (36, 38, 40, 42),
) -> LitzRecommendation:
    """Search across strand AWGs around the Sullivan optimum and return the
    best feasible Litz construction, plus a baseline best round wire."""
    from pfc_inductor.topology import boost_ccm

    fsw_Hz = spec.f_sw_kHz * 1000.0
    layers = _layers_for(core)

    # Operating-current at low-line worst case
    I_rms = boost_ccm.line_rms_current_A(spec, spec.Vin_min_Vrms)
    rec = LitzRecommendation(
        spec=spec, core=core, material=material,
        layers_assumed=layers, target_J_A_mm2=target_J_A_mm2,
        target_AC_DC=target_AC_DC, fsw_Hz=fsw_Hz,
    )

    for awg in awg_search:
        d_strand = _AWG_STRAND_TABLE_MM[awg]
        n = strand_count_for_current(I_rms, target_J_A_mm2, d_strand)
        if n > max_strands:
            continue
        wire = make_litz_wire(n, d_strand, awg_strand=awg)
        cand = _evaluate(spec, core, material, wire, fsw_Hz, layers, max_bundle_mm)
        rec.candidates.append(cand)

    feasible = [c for c in rec.candidates if c.feasible and c.result is not None]
    if feasible:
        feasible.sort(key=lambda c: c.result.losses.P_total_W)
        rec.best = feasible[0]

    # Round-wire baseline: pick the round wire that minimizes P_total
    round_wires = [w for w in current_round_wires if w.type == "round"]
    rw_cands: list[LitzCandidate] = []
    for w in round_wires:
        c = _evaluate(spec, core, material, w, fsw_Hz, layers)
        if c.feasible and c.result is not None:
            rw_cands.append(c)
    if rw_cands:
        rw_cands.sort(key=lambda c: c.result.losses.P_total_W)
        rec.round_wire_baseline = rw_cands[0]
    return rec
