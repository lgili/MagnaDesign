"""Tests for the direct backend's toroidal analytical solver — Phase 2.5.

The toroidal solver is closed-form (no GetDP, no mesh), so the
tests can be exhaustive and microsecond-fast. We cover:

1. Exact match against hand-computed ``L = μ·N²·HT·ln(OD/ID)/(2π)``
   for the geometric (OD/ID/HT) path.
2. Exact match against ``L = μ·N²·Ae/le`` for the aggregate (Ae/le)
   path.
3. Catalog-driven dispatch — both ferrite (OD/ID/HT) and powder
   core (Ae/le) entries go through the right branch.
4. Datasheet AL × N² parity for a Magnetics HighFlux powder core
   (where the catalog AL was measured at the linear-μ operating
   point we're modelling).
5. End-to-end runner dispatch: ``run_direct_fea`` on a toroidal
   shape lands in the analytical path, returns a valid
   ``DirectFeaResult``, and writes the report file.
6. Discrete azimuthal gap behaviour — a 0.5 mm cut should lower
   L by the expected fraction.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest

# ─── Unit tests for solve_toroidal (geometric path) ────────────────


def _exact_ln(N: int, mu_r: float, OD: float, ID: float, HT: float) -> float:
    """Hand reference: L_uH = μ·N²·HT·ln(OD/ID)/(2π)."""
    mu0 = 4 * math.pi * 1e-7
    return mu0 * mu_r * (N**2) * (HT * 1e-3) * math.log(OD / ID) / (2 * math.pi) * 1e6


def test_geometric_solver_matches_closed_form():
    """A canonical T106-class ferrite toroid: solver result must
    equal the hand-computed ln(OD/ID) formula to floating-point
    precision.
    """
    from pfc_inductor.fea.direct.physics.magnetostatic_toroidal import (
        ToroidalInputs,
        solve_toroidal,
    )

    OD, ID, HT, mu_r, N = 27.0, 14.0, 11.0, 2300.0, 50
    out = solve_toroidal(
        ToroidalInputs(OD_mm=OD, ID_mm=ID, HT_mm=HT, mu_r_core=mu_r, n_turns=N, current_A=1.0)
    )
    L_exact = _exact_ln(N, mu_r, OD, ID, HT)
    assert math.isclose(out.L_uH, L_exact, rel_tol=1e-9), (
        f"closed-form mismatch: solver={out.L_uH:.6f} μH vs exact={L_exact:.6f} μH"
    )


def test_geometric_solver_B_pk_location():
    """B_pk should occur at the innermost radius r_inner = ID/2,
    where Ampère's law gives the largest H_φ.
    """
    from pfc_inductor.fea.direct.physics.magnetostatic_toroidal import (
        ToroidalInputs,
        solve_toroidal,
    )

    OD, ID, HT, mu_r, N, I = 27.0, 14.0, 11.0, 2300.0, 50, 1.0
    out = solve_toroidal(
        ToroidalInputs(OD_mm=OD, ID_mm=ID, HT_mm=HT, mu_r_core=mu_r, n_turns=N, current_A=I)
    )
    mu0 = 4 * math.pi * 1e-7
    r_inner = ID / 2.0 * 1e-3
    B_pk_expected = mu0 * mu_r * N * I / (2 * math.pi * r_inner)
    assert math.isclose(out.B_pk_T, B_pk_expected, rel_tol=1e-9)


def test_geometric_solver_validates_inputs():
    """The solver rejects degenerate geometries with a clear error."""
    from pfc_inductor.fea.direct.physics.magnetostatic_toroidal import (
        ToroidalInputs,
        solve_toroidal,
    )

    with pytest.raises(ValueError, match="OD"):
        solve_toroidal(ToroidalInputs(OD_mm=10.0, ID_mm=20.0, HT_mm=5.0, mu_r_core=100, n_turns=1))
    with pytest.raises(ValueError, match="HT"):
        solve_toroidal(ToroidalInputs(OD_mm=20.0, ID_mm=10.0, HT_mm=0.0, mu_r_core=100, n_turns=1))
    with pytest.raises(ValueError, match="mu_r"):
        solve_toroidal(ToroidalInputs(OD_mm=20.0, ID_mm=10.0, HT_mm=5.0, mu_r_core=0.5, n_turns=1))


def test_geometric_solver_coverage_scaling():
    """A partial-coverage winding (effective N → N×coverage) gives
    L proportional to coverage². Half-coverage should drop L by 4×.
    """
    from pfc_inductor.fea.direct.physics.magnetostatic_toroidal import (
        ToroidalInputs,
        solve_toroidal,
    )

    common = dict(OD_mm=27.0, ID_mm=14.0, HT_mm=11.0, mu_r_core=2300.0, n_turns=50)
    L_full = solve_toroidal(ToroidalInputs(coverage_fraction=1.0, **common)).L_uH
    L_half = solve_toroidal(ToroidalInputs(coverage_fraction=0.5, **common)).L_uH
    assert math.isclose(L_full / L_half, 4.0, rel_tol=1e-9)


def test_geometric_solver_discrete_gap_lowers_L():
    """A 0.5 mm azimuthal cut in a high-μ ferrite toroid should
    drop L by a factor close to ``μ_r·lgap/le`` (gap reluctance
    dominates iron's).
    """
    from pfc_inductor.fea.direct.physics.magnetostatic_toroidal import (
        ToroidalInputs,
        solve_toroidal,
    )

    common = dict(OD_mm=27.0, ID_mm=14.0, HT_mm=11.0, mu_r_core=2300.0, n_turns=50)
    L_closed = solve_toroidal(ToroidalInputs(discrete_gap_mm=0.0, **common)).L_uH
    L_gapped = solve_toroidal(ToroidalInputs(discrete_gap_mm=0.5, **common)).L_uH
    # Iron path length le ≈ π·(OD+ID)/2 = π·20.5 ≈ 64.4 mm.
    # Gap reluctance ratio ≈ μ_r·lgap/le = 2300·0.5/64.4 ≈ 17.9.
    # So L_gapped/L_closed ≈ 1/(1+17.9) = 0.053 (roughly 19× drop).
    drop = L_closed / L_gapped
    assert drop > 5.0, f"discrete gap had too little effect: L_closed/L_gapped = {drop:.2f}"


# ─── Unit tests for solve_toroidal_aggregate (Ae/le path) ──────────


def test_aggregate_solver_matches_mu_N2_Ae_le():
    """Aggregate solver result must equal ``μ·N²·Ae/le`` exactly."""
    from pfc_inductor.fea.direct.physics.magnetostatic_toroidal import (
        solve_toroidal_aggregate,
    )

    Ae, le, mu_r, N = 2.11, 9.42, 125.0, 50  # Magnetics C058150A2 + 125 HighFlux
    out = solve_toroidal_aggregate(Ae_mm2=Ae, le_mm=le, mu_r_core=mu_r, n_turns=N, current_A=1.0)
    mu0 = 4 * math.pi * 1e-7
    L_expected_uH = mu0 * mu_r * (N**2) * (Ae * 1e-6) / (le * 1e-3) * 1e6
    assert math.isclose(out.L_uH, L_expected_uH, rel_tol=1e-9)


def test_aggregate_solver_validates_inputs():
    from pfc_inductor.fea.direct.physics.magnetostatic_toroidal import (
        solve_toroidal_aggregate,
    )

    with pytest.raises(ValueError):
        solve_toroidal_aggregate(Ae_mm2=0.0, le_mm=10.0, mu_r_core=125, n_turns=1)
    with pytest.raises(ValueError):
        solve_toroidal_aggregate(Ae_mm2=2.0, le_mm=0.0, mu_r_core=125, n_turns=1)


# ─── Catalog dispatch tests ────────────────────────────────────────


def test_from_core_dispatches_geometric_for_ferrite_toroid():
    """Ferrite toroids carry explicit OD/ID/HT — must use the
    closed-form ln solver, not the aggregate fallback.
    """
    from pfc_inductor.data_loader import load_cores, load_materials
    from pfc_inductor.fea.direct.physics.magnetostatic_toroidal import (
        solve_toroidal_from_core,
    )

    cores = load_cores()
    mats = load_materials()
    ferrite = next(c for c in cores if c.id == "mas-ferroxcube-t-t-107-65-18---3c90---ungapped")
    mat = next(m for m in mats if m.id == ferrite.default_material_id)
    out = solve_toroidal_from_core(core=ferrite, material=mat, n_turns=20, current_A=1.0)
    assert out.method == "analytical_toroidal"
    assert out.L_uH > 0


def test_from_core_dispatches_aggregate_for_powder_core():
    """Powder cores have Ae/le but no OD/ID/HT — must use the
    aggregate solver.
    """
    from pfc_inductor.data_loader import load_cores, load_materials
    from pfc_inductor.fea.direct.physics.magnetostatic_toroidal import (
        solve_toroidal_from_core,
    )

    cores = load_cores()
    mats = load_materials()
    powder = next(c for c in cores if "magnetics-c058150a2" in c.id.lower())
    mat = next(m for m in mats if m.id == powder.default_material_id)
    out = solve_toroidal_from_core(core=powder, material=mat, n_turns=50, current_A=1.0)
    assert out.method == "analytical_toroidal_aggregate"
    assert out.L_uH > 0


def test_powder_core_matches_AL_within_1pct():
    """The Magnetics HighFlux datasheet AL × N² is the experimental
    self-inductance measurement at the linear-μ operating point —
    our solver should match it within 1 % since both use the
    ``L = μ·N²·Ae/le`` formula at small signal.
    """
    from pfc_inductor.data_loader import load_cores, load_materials
    from pfc_inductor.fea.direct.physics.magnetostatic_toroidal import (
        solve_toroidal_from_core,
    )

    cores = load_cores()
    mats = load_materials()
    powder = next(c for c in cores if "magnetics-c058150a2" in c.id.lower())
    mat = next(m for m in mats if m.id == powder.default_material_id)
    N = 50
    out = solve_toroidal_from_core(core=powder, material=mat, n_turns=N, current_A=0.1)
    L_AL_uH = powder.AL_nH * 1e-3 * (N**2)
    delta_pct = abs(out.L_uH - L_AL_uH) / L_AL_uH * 100.0
    assert delta_pct < 1.0, (
        f"L_direct={out.L_uH:.3f} μH vs L_AL={L_AL_uH:.3f} μH (|Δ|={delta_pct:.2f} %)"
    )


# ─── DC-bias rolloff (Phase 2.5b) ──────────────────────────────────


def test_powder_core_rolloff_active_at_high_current():
    """At a high DC current (large N·I/le → large H), the Magnetics
    rolloff factor should pull ``μ_eff`` well below ``μ_initial``,
    so ``L_with_rolloff < L_no_rolloff``. The catalog 125-HighFlux
    rolloff curve gives ≈ 50 % at H = 66.7 Oe (the test condition);
    we lock in this value to ±5 %.
    """
    from pfc_inductor.data_loader import load_cores, load_materials
    from pfc_inductor.fea.direct.physics.magnetostatic_toroidal import (
        solve_toroidal_from_core,
    )

    cores = load_cores()
    mats = load_materials()
    powder = next(c for c in cores if "magnetics-c058150a2" in c.id.lower())
    mat = next(m for m in mats if m.id == powder.default_material_id)

    # N=50, I=1A → H = 50/0.00942 = 5307 A/m = 66.7 Oe.
    # Per Magnetics 125-HighFlux fit: μ% = 1 / (0.01 + 0.01636·66.7^1.13)
    # = 1/1.891 ≈ 0.529. Verify the solver applies it.
    L_no = solve_toroidal_from_core(
        core=powder, material=mat, n_turns=50, current_A=1.0, apply_dc_bias_rolloff=False
    ).L_uH
    L_yes = solve_toroidal_from_core(
        core=powder, material=mat, n_turns=50, current_A=1.0, apply_dc_bias_rolloff=True
    ).L_uH
    ratio = L_yes / L_no
    assert 0.50 <= ratio <= 0.56, (
        f"rolloff factor out of expected range: L_yes/L_no = {ratio:.3f} "
        f"(expected ~0.53 per catalog 125-HighFlux fit)"
    )


def test_rolloff_inactive_at_low_current():
    """At very low current the rolloff factor clips to 1.0 (formula
    saturates at small H), so ``L`` with and without rolloff is
    identical. This is the boundary case that keeps the small-
    signal AL × N² match working.
    """
    from pfc_inductor.data_loader import load_cores, load_materials
    from pfc_inductor.fea.direct.physics.magnetostatic_toroidal import (
        solve_toroidal_from_core,
    )

    cores = load_cores()
    mats = load_materials()
    powder = next(c for c in cores if "magnetics-c058150a2" in c.id.lower())
    mat = next(m for m in mats if m.id == powder.default_material_id)

    L_no = solve_toroidal_from_core(
        core=powder, material=mat, n_turns=50, current_A=0.01, apply_dc_bias_rolloff=False
    ).L_uH
    L_yes = solve_toroidal_from_core(
        core=powder, material=mat, n_turns=50, current_A=0.01, apply_dc_bias_rolloff=True
    ).L_uH
    assert math.isclose(L_no, L_yes, rel_tol=1e-9)


def test_rolloff_monotonic_in_current():
    """Sweeping current upward must monotonically decrease L (more
    saturation → less μ_eff → less L). Locks in the qualitative
    behaviour against accidental sign flips or off-by-one issues
    in the rolloff polynomial.
    """
    from pfc_inductor.data_loader import load_cores, load_materials
    from pfc_inductor.fea.direct.physics.magnetostatic_toroidal import (
        solve_toroidal_from_core,
    )

    cores = load_cores()
    mats = load_materials()
    powder = next(c for c in cores if "magnetics-c058150a2" in c.id.lower())
    mat = next(m for m in mats if m.id == powder.default_material_id)

    Ls = []
    for I in (0.5, 1.0, 2.0, 5.0, 10.0):
        out = solve_toroidal_from_core(
            core=powder, material=mat, n_turns=50, current_A=I, apply_dc_bias_rolloff=True
        )
        Ls.append(out.L_uH)
    # Monotonic descending
    from itertools import pairwise

    for prev, curr in pairwise(Ls):
        assert curr < prev, f"L should drop with rising I, got sequence {Ls}"


# ─── End-to-end runner dispatch ────────────────────────────────────


def test_runner_dispatches_toroidal_to_analytical_path():
    """``run_direct_fea`` on a toroidal core must hand off to the
    analytical solver — no GetDP invocation, no mesh generation,
    and the result carries 0 mesh_n_elements as a tell.
    """
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.fea.direct.runner import run_direct_fea

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()

    toroidal_core = next(c for c in cores if "magnetics-c058150a2" in c.id.lower())
    mat = next(m for m in mats if m.id == toroidal_core.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        result = run_direct_fea(
            core=toroidal_core,
            material=mat,
            wire=wire,
            n_turns=50,
            current_A=1.0,
            workdir=td_path,
        )
        # Analytical path: no mesh.
        assert result.mesh_n_elements == 0
        assert result.mesh_n_nodes == 0
        # Solve wall time is microseconds.
        assert result.solve_wall_s < 0.1, (
            f"toroidal solve should be fast, got {result.solve_wall_s} s"
        )
        # Report file written.
        assert (td_path / "toroidal_report.txt").exists()
        # L positive and sensible
        assert result.L_dc_uH > 0
