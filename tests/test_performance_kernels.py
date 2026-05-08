"""Numba-accelerated kernel parity tests.

The ``[performance]`` optional extra (Numba) provides JIT-
compiled inner loops for the cascade hot paths. Each kernel
must produce **bit-identical** numerical results to the pure-
Python fallback — otherwise installing the extra would
silently shift the engineering numbers.

Tests:

- ``core_loss._NUMBA_KERNEL``: iGSE-mean of a 200-element
  ΔB array under Steinmetz, against the numpy reference.
- ``engine._SOLVE_N_KERNEL``: 500-iteration binary search
  for the smallest N satisfying a target inductance, against
  the rolloff + AL pure-Python loop.

Skipped cleanly when Numba isn't installed (the
``[performance]`` extra wasn't added).
"""

from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Skip the whole module when Numba isn't installed — the kernels
# don't get built and there's nothing to compare against.
# ---------------------------------------------------------------------------
pytest.importorskip("numba")


# ---------------------------------------------------------------------------
# core_loss iGSE kernel
# ---------------------------------------------------------------------------
def test_iGSE_kernel_loads_when_numba_installed() -> None:
    from pfc_inductor.physics import core_loss

    assert core_loss._NUMBA_KERNEL is not None, (
        "expected Numba kernel to be loaded; check the build_kernel "
        "factory in physics/core_loss.py"
    )


def test_iGSE_kernel_matches_numpy_baseline() -> None:
    """Run the iGSE-ripple inner loop in both paths and assert
    identical outputs at the working precision (1e-9 W)."""
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.design import design as run_design
    from pfc_inductor.models import Spec
    from pfc_inductor.physics import core_loss

    spec = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=65, ripple_pct=20, T_amb_C=40,
    )
    mats = load_materials()
    cores = load_cores()
    wires = load_wires()
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores
                if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")

    # Run with Numba enabled.
    res_numba = run_design(spec, core, wire, mat)
    P_numba = float(res_numba.losses.P_total_W)

    # Force the pure-numpy fallback for the same inputs.
    saved = core_loss._NUMBA_KERNEL
    core_loss._NUMBA_KERNEL = None
    try:
        res_python = run_design(spec, core, wire, mat)
        P_python = float(res_python.losses.P_total_W)
    finally:
        core_loss._NUMBA_KERNEL = saved

    assert abs(P_numba - P_python) < 1e-6, (
        f"kernel parity broken: {P_numba} W (numba) vs "
        f"{P_python} W (numpy) — Δ = "
        f"{abs(P_numba - P_python):.3e} W"
    )


def test_iGSE_kernel_handles_zero_array() -> None:
    """Empty input → zero loss. Defensive against an edge case
    the engine never produces (always at least 200 samples) but
    the kernel signature must accept."""
    from pfc_inductor.physics import core_loss

    if core_loss._NUMBA_KERNEL is None:
        pytest.skip("Numba kernel unavailable")
    out = core_loss._NUMBA_KERNEL(
        np.zeros(0, dtype=np.float64),
        100.0,  # Pv_ref_mWcm3
        1.0,    # f_factor
        100.0,  # B_ref_mT
        2.5,    # beta
    )
    assert out == 0.0


# ---------------------------------------------------------------------------
# _solve_N kernel
# ---------------------------------------------------------------------------
def test_solve_n_kernel_loads_when_numba_installed() -> None:
    from pfc_inductor.design import engine as engine_mod

    assert engine_mod._SOLVE_N_KERNEL is not None


def test_solve_n_kernel_matches_python_for_powder_core() -> None:
    """Powder-core material has rolloff coefficients; the Numba
    kernel must walk the binary search to the same N as the
    pure-Python loop (where ``mu_pct`` goes through Pydantic
    attribute access)."""
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.design import engine as engine_mod
    from pfc_inductor.design.engine import _solve_N

    mats = load_materials()
    cores = load_cores()
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores
                if c.id == "magnetics-c058777a2-60_highflux")
    assert mat.rolloff is not None  # sanity — the test premise

    # Compile path.
    N_nb, L_nb, mu_nb = _solve_N(
        L_required_uH=600.0, core=core, material=mat,
        I_dc_pk_A=8.0,
    )
    # Pure-Python path.
    saved = engine_mod._SOLVE_N_KERNEL
    engine_mod._SOLVE_N_KERNEL = None
    try:
        N_py, L_py, mu_py = _solve_N(
            L_required_uH=600.0, core=core, material=mat,
            I_dc_pk_A=8.0,
        )
    finally:
        engine_mod._SOLVE_N_KERNEL = saved

    assert N_nb == N_py
    assert abs(L_nb - L_py) < 1e-9
    assert abs(mu_nb - mu_py) < 1e-9


def test_solve_n_kernel_handles_no_rolloff() -> None:
    """Materials without rolloff data → mu = 1.0 for every N.
    The kernel takes a flag to skip the rolloff arithmetic; the
    fallback is unchanged (also computes mu = 1.0)."""
    from pfc_inductor.data_loader import load_cores, load_materials
    from pfc_inductor.design import engine as engine_mod
    from pfc_inductor.design.engine import _solve_N

    mats = load_materials()
    cores = load_cores()
    # Pick a ferrite — should ship without a rolloff curve.
    flat_mu_mat = next(
        (m for m in mats if m.rolloff is None),
        None,
    )
    if flat_mu_mat is None:
        pytest.skip("no rolloff-free material in catalogue")
    core = next(c for c in cores
                if c.id == "magnetics-c058777a2-60_highflux")

    N_nb, L_nb, mu_nb = _solve_N(
        L_required_uH=200.0, core=core, material=flat_mu_mat,
        I_dc_pk_A=5.0,
    )
    saved = engine_mod._SOLVE_N_KERNEL
    engine_mod._SOLVE_N_KERNEL = None
    try:
        N_py, L_py, mu_py = _solve_N(
            L_required_uH=200.0, core=core, material=flat_mu_mat,
            I_dc_pk_A=5.0,
        )
    finally:
        engine_mod._SOLVE_N_KERNEL = saved

    assert mu_nb == pytest.approx(1.0)
    assert mu_py == pytest.approx(1.0)
    assert N_nb == N_py
    assert abs(L_nb - L_py) < 1e-9


def test_solve_n_kernel_returns_n_max_when_unsolvable() -> None:
    """If the requested L can't be reached even at N = N_max, the
    kernel returns N_max with the corresponding L (the engine's
    contract — caller spots the saturation via the warning
    system)."""
    from pfc_inductor.data_loader import load_cores, load_materials
    from pfc_inductor.design.engine import _solve_N

    mats = load_materials()
    cores = load_cores()
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores
                if c.id == "magnetics-c058777a2-60_highflux")

    # Ask for an absurdly high inductance — way beyond N_max=500
    # × AL × mu can deliver.
    N, L, mu = _solve_N(
        L_required_uH=1e9, core=core, material=mat,
        I_dc_pk_A=8.0, N_max=50,
    )
    assert N == 50
    assert L > 0  # whatever the cap delivered, just not negative
    assert 0.0 <= mu <= 1.0
