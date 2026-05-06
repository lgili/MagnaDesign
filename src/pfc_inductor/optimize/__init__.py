from pfc_inductor.optimize.feasibility import (
    Verdict,
    core_quick_check,
    filter_viable_cores,
    peak_current_A,
    required_L_uH,
)
from pfc_inductor.optimize.litz import (
    LitzCandidate,
    LitzRecommendation,
    bundle_diameter_mm,
    closest_strand_AWG,
    make_litz_wire,
    optimal_strand_diameter_mm,
    strand_count_for_current,
)
from pfc_inductor.optimize.litz import (
    recommend as recommend_litz,
)
from pfc_inductor.optimize.similar import (
    SimilarityCriteria,
    SimilarMatch,
    find_equivalents,
)
from pfc_inductor.optimize.sweep import SweepResult, pareto_front, sweep

__all__ = [
    "sweep", "SweepResult", "pareto_front",
    "SimilarityCriteria", "SimilarMatch", "find_equivalents",
    "LitzRecommendation", "LitzCandidate", "recommend_litz",
    "make_litz_wire", "optimal_strand_diameter_mm", "closest_strand_AWG",
    "strand_count_for_current", "bundle_diameter_mm",
    # Feasibility public API (was previously underscore-prefixed in
    # ``optimize.feasibility``; aliases there preserve back-compat).
    "Verdict", "core_quick_check", "filter_viable_cores",
    "required_L_uH", "peak_current_A",
]
