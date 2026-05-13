"""Tests for the analytical reluctance solver (Phase 2.6 calibration).

The reluctance solver replaces the FEM-based axi backend for
non-toroidal shapes. It runs in microseconds and matches FEMMT
within ~15 % on every PQ/EE/EI/ETD case in the benchmark.

These tests lock in:

1. The Roters fringing factor matches the closed-form formula.
2. ``solve_reluctance`` gives the correct ``N²/R_total`` answer.
3. The catalog adapter handles missing μ_r gracefully.
4. The runner dispatches non-toroidal axi shapes through the
   reluctance path by default (no GetDP solve).
5. Validation against FEMMT on PQ ferrites stays within
   the documented 15 % envelope.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest


def test_roters_fringing_factor_known_values():
    """Spot-check the Roters/McLyman fringing formula."""
    from pfc_inductor.fea.direct.physics.reluctance_axi import fringing_factor_roters

    # No gap → k = 1.0
    assert fringing_factor_roters(0.0, 10.0) == 1.0
    # Tiny gap → k ≈ 1.0 (sqrt(0.001) ≈ 0.032)
    k = fringing_factor_roters(0.001, 10.0)
    assert 1.0 < k < 1.1
    # Standard PFC gap: 0.5 mm / 13 mm center leg → k = 1 + 2·sqrt(0.0385) ≈ 1.39
    k = fringing_factor_roters(0.5, 13.0)
    assert math.isclose(k, 1.0 + 2 * math.sqrt(0.5 / 13.0), rel_tol=1e-6)
    # Wide gap clamped at 3.0
    k = fringing_factor_roters(50.0, 10.0)
    assert k == 3.0


def test_solve_reluctance_closed_form_no_gap():
    """No gap → L = μ·N²·Ae/le exactly (no fringing applied)."""
    from pfc_inductor.fea.direct.physics.reluctance_axi import (
        ReluctanceInputs,
        solve_reluctance,
    )

    mu0 = 4 * math.pi * 1e-7
    out = solve_reluctance(
        ReluctanceInputs(
            Ae_mm2=200.0,
            le_mm=100.0,
            center_leg_w_mm=14.0,
            mu_r_core=2200.0,
            n_turns=39,
            current_A=1.0,
            lgap_mm=0.0,
        )
    )
    L_expected = mu0 * 2200.0 * 39**2 * 200e-6 / 100e-3 * 1e6
    assert math.isclose(out.L_uH, L_expected, rel_tol=1e-9)
    assert out.R_gap_per_turn == 0.0
    assert out.k_fringe == 1.0


def test_solve_reluctance_with_gap_drops_L():
    """A 0.5 mm gap in a high-μ ferrite drops L by ~80 %."""
    from pfc_inductor.fea.direct.physics.reluctance_axi import (
        ReluctanceInputs,
        solve_reluctance,
    )

    common = dict(
        Ae_mm2=200.0,
        le_mm=100.0,
        center_leg_w_mm=14.0,
        mu_r_core=2200.0,
        n_turns=39,
        current_A=1.0,
    )
    L_closed = solve_reluctance(ReluctanceInputs(lgap_mm=0.0, **common)).L_uH
    L_gapped = solve_reluctance(ReluctanceInputs(lgap_mm=0.5, **common)).L_uH
    assert L_gapped < L_closed
    drop = L_closed / L_gapped
    # With μ=2200 and 0.5mm gap, gap reluctance dominates → ~5-10× drop
    assert drop > 3.0
    assert drop < 30.0


def test_solve_reluctance_validates_inputs():
    from pfc_inductor.fea.direct.physics.reluctance_axi import (
        ReluctanceInputs,
        solve_reluctance,
    )

    with pytest.raises(ValueError, match="Ae"):
        solve_reluctance(
            ReluctanceInputs(
                Ae_mm2=0.0, le_mm=100.0, center_leg_w_mm=10, mu_r_core=2200, n_turns=39
            )
        )
    with pytest.raises(ValueError, match="mu_r"):
        solve_reluctance(
            ReluctanceInputs(
                Ae_mm2=200.0, le_mm=100.0, center_leg_w_mm=10, mu_r_core=0.5, n_turns=39
            )
        )


# ─── Catalog adapter ───────────────────────────────────────────────


def test_from_core_handles_ferrite():
    """Ferrite PQ resolves cleanly: Ae+le from catalog, mu from material."""
    from pfc_inductor.data_loader import load_cores, load_materials
    from pfc_inductor.fea.direct.physics.reluctance_axi import (
        solve_reluctance_from_core,
    )

    cores = load_cores()
    mats = load_materials()
    core = next(c for c in cores if c.id == "tdkepcos-pq-4040-n87")
    mat = next(m for m in mats if m.id == core.default_material_id)
    out = solve_reluctance_from_core(core=core, material=mat, n_turns=39, current_A=8.0, gap_mm=0.5)
    assert out.L_uH > 0
    # PQ 40/40 with 0.5 mm gap @ N=39: textbook says ~666 μH;
    # with Roters fringing (~1.39), ~900 μH. FEMMT measures 823 μH.
    # Our analytical should land in the 750-1000 μH window.
    assert 750 < out.L_uH < 1000


def test_from_core_rejects_missing_dims():
    """Cores without Ae/le must raise rather than silently produce 0."""
    from pfc_inductor.data_loader import load_materials
    from pfc_inductor.fea.direct.physics.reluctance_axi import (
        solve_reluctance_from_core,
    )

    class FakeCore:
        id = "fake"
        Ae_mm2 = None
        le_mm = None
        lgap_mm = 0.0

    mat = next(iter(load_materials()))
    with pytest.raises(ValueError, match="Ae/le"):
        solve_reluctance_from_core(core=FakeCore(), material=mat, n_turns=10)


# ─── Runner dispatch ───────────────────────────────────────────────


def test_runner_uses_reluctance_for_pq():
    """``run_direct_fea`` on a PQ core defaults to the reluctance
    path — no mesh, no GetDP, microsecond wall.
    """
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.fea.direct.runner import run_direct_fea

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    core = next(c for c in cores if c.id == "tdkepcos-pq-4040-n87")
    mat = next(m for m in mats if m.id == core.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)

    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        out = run_direct_fea(
            core=core,
            material=mat,
            wire=wire,
            n_turns=39,
            current_A=8.0,
            workdir=td_p,
            gap_mm=0.5,
        )
        assert out.mesh_n_elements == 0  # no FEM
        assert out.solve_wall_s < 0.1
        assert (td_p / "reluctance_report.txt").exists()
        # L within the documented envelope vs FEMMT (823 μH)
        assert 750 < out.L_dc_uH < 1000


def test_runner_pq_50_50_within_15pct_of_femmt():
    """PQ 50/50 is the largest of the bench PQs — historically the
    case where direct over-shot FEMMT. With reluctance, |Δ| ≤ 15 %.
    Locks the calibration in.
    """
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.fea.direct.runner import run_direct_fea

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    core = next(c for c in cores if c.id == "tdkepcos-pq-5050-n87")
    mat = next(m for m in mats if m.id == core.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)
    L_femmt_uH = 1342.6  # measured in the Phase 2.6 benchmark

    with tempfile.TemporaryDirectory() as td:
        out = run_direct_fea(
            core=core,
            material=mat,
            wire=wire,
            n_turns=39,
            current_A=8.0,
            workdir=Path(td),
            gap_mm=0.5,
        )
    delta_pct = abs(out.L_dc_uH - L_femmt_uH) / L_femmt_uH * 100
    assert delta_pct < 15.0, f"PQ 50/50 |ΔL| = {delta_pct:.1f}% (expected < 15% vs FEMMT)"


def test_runner_toroidal_still_uses_closed_form():
    """The toroidal dispatch (Phase 2.5) must still route through
    the analytical toroidal solver, not the new reluctance path.
    """
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.fea.direct.runner import run_direct_fea

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    powder = next(c for c in cores if "magnetics-c058150a2" in c.id.lower())
    mat = next(m for m in mats if m.id == powder.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        out = run_direct_fea(
            core=powder,
            material=mat,
            wire=wire,
            n_turns=50,
            current_A=1.0,
            workdir=td_p,
        )
        # Toroidal path writes its own report file
        assert (td_p / "toroidal_report.txt").exists()
        # Not the reluctance one
        assert not (td_p / "reluctance_report.txt").exists()
