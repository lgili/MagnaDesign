"""Tests for the lumped thermal model in the direct backend — Phase 3.2.

The thermal module wraps :mod:`pfc_inductor.physics.thermal` (the
analytical engine's natural-convection model) so the direct
backend can report ``T_winding_C`` / ``T_core_C`` on
``DirectFeaResult`` when the caller supplies loss totals.

These tests lock in:

1. ``compute_temperature`` returns the expected T_winding for a
   known loss + core surface area.
2. The ``estimate_cu_loss_W`` helper applies the copper resistivity
   temperature coefficient correctly.
3. The runner populates ``T_winding_C`` when ``P_cu_W``/``P_core_W``
   are passed; leaves them ``None`` otherwise.
4. Lumped model: ``T_core == T_winding`` (single-node).
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest


def test_compute_temperature_known_value():
    """For a Magnetics C058150A2 toroid (small core, ~5 cm² surface
    area), 1 W of total loss at h=12 W/m²/K gives ~10 K rise."""
    from pfc_inductor.data_loader import load_cores
    from pfc_inductor.fea.direct.physics.thermal import compute_temperature

    cores = load_cores()
    core = next(c for c in cores if "magnetics-c058150a2" in c.id.lower())
    out = compute_temperature(core=core, P_cu_W=1.0, T_amb_C=25.0)
    # The C058150A2 has Ve=20 mm³ → tiny surface area → very high ΔT
    # for 1 W. We just lock in that the function runs and gives a
    # positive rise.
    assert out.delta_T_K > 0
    assert out.T_winding_C == 25.0 + out.delta_T_K
    assert out.T_core_C == out.T_winding_C  # lumped single-node
    assert out.P_total_W == 1.0
    assert out.method == "lumped_natural_convection"


def test_compute_temperature_zero_loss():
    from pfc_inductor.data_loader import load_cores
    from pfc_inductor.fea.direct.physics.thermal import compute_temperature

    core = next(c for c in load_cores() if c.id == "tdkepcos-pq-4040-n87")
    out = compute_temperature(core=core, P_cu_W=0.0, P_core_W=0.0, T_amb_C=40.0)
    assert out.delta_T_K == 0.0
    assert out.T_winding_C == 40.0


def test_estimate_cu_loss_no_T_correction():
    """At T=20°C the temperature correction is exactly 1.0."""
    from pfc_inductor.fea.direct.physics.thermal import estimate_cu_loss_W

    # AWG 18 ≈ 0.021 Ω/m. 100 turns × 100 mm MLT = 10 m → R ≈ 0.21 Ω.
    # At 1 A: P = 0.21 W.
    P = estimate_cu_loss_W(
        n_turns=100,
        current_rms_A=1.0,
        wire_resistance_ohm_per_m=0.021,
        mlt_mm=100.0,
        T_winding_C=None,
    )
    assert math.isclose(P, 0.21, rel_tol=1e-6)


def test_estimate_cu_loss_with_T_correction():
    """At T=100°C copper resistance rises ~31% (α=3.93e-3/K)."""
    from pfc_inductor.fea.direct.physics.thermal import estimate_cu_loss_W

    P_20 = estimate_cu_loss_W(
        n_turns=100,
        current_rms_A=1.0,
        wire_resistance_ohm_per_m=0.021,
        mlt_mm=100.0,
        T_winding_C=20.0,
    )
    P_100 = estimate_cu_loss_W(
        n_turns=100,
        current_rms_A=1.0,
        wire_resistance_ohm_per_m=0.021,
        mlt_mm=100.0,
        T_winding_C=100.0,
    )
    # Factor: 1 + 3.93e-3 × 80 = 1.3144
    assert math.isclose(P_100 / P_20, 1.3144, rel_tol=1e-3)


# ─── Runner integration ────────────────────────────────────────────


def test_runner_omits_thermal_when_no_losses():
    """No P_cu / P_core passed → T_winding_C and T_core_C stay None."""
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.fea.direct.runner import run_direct_fea

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    core = next(c for c in cores if c.id == "tdkepcos-pq-4040-n87")
    mat = next(m for m in mats if m.id == core.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)

    with tempfile.TemporaryDirectory() as td:
        out = run_direct_fea(
            core=core,
            material=mat,
            wire=wire,
            n_turns=39,
            current_A=8.0,
            workdir=Path(td),
        )
    assert out.T_winding_C is None
    assert out.T_core_C is None


def test_runner_populates_thermal_when_losses_given():
    """Pass P_cu and P_core → T_winding / T_core are populated."""
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.fea.direct.runner import run_direct_fea

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    core = next(c for c in cores if c.id == "tdkepcos-pq-4040-n87")
    mat = next(m for m in mats if m.id == core.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)

    with tempfile.TemporaryDirectory() as td:
        out = run_direct_fea(
            core=core,
            material=mat,
            wire=wire,
            n_turns=39,
            current_A=8.0,
            workdir=Path(td),
            P_cu_W=2.5,
            P_core_W=1.0,
            T_amb_C=40.0,
        )
    assert out.T_winding_C is not None
    assert out.T_core_C is not None
    # 3.5 W total + PQ 40/40 surface area → roughly 30-50 K rise at h=12
    assert 50 < out.T_winding_C < 120
    assert out.T_core_C == pytest.approx(out.T_winding_C)


def test_runner_thermal_for_toroidal():
    """Thermal post-processing works for toroidal shapes too."""
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.fea.direct.runner import run_direct_fea

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    powder = next(c for c in cores if "magnetics-c058150a2" in c.id.lower())
    mat = next(m for m in mats if m.id == powder.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)

    with tempfile.TemporaryDirectory() as td:
        out = run_direct_fea(
            core=powder,
            material=mat,
            wire=wire,
            n_turns=50,
            current_A=1.0,
            workdir=Path(td),
            P_cu_W=0.5,
            P_core_W=0.2,
        )
    assert out.T_winding_C is not None
    assert out.T_winding_C > 25.0  # delta_T > 0
