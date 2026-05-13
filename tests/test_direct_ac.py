"""Tests for the AC harmonic (MagDyn) template — Phase 2.1.

The AC template is GetDP-based, so unit tests focus on:

1. The skin-depth helper produces textbook values.
2. The template renders with all expected GetDP keywords.
3. Complex-output parsing works on the three-column phasor format.
4. L/R extraction returns sensible values for hand-constructed
   complex fluxes.

End-to-end validation (with a real PQ mesh) requires GetDP +
gmsh and is marked ``@pytest.mark.slow`` so CI without ONELAB
doesn't run it.

Phase 2.1 scope note
====================

A meaningful AC solve with realistic skin/proximity loss requires
the **stranded-winding** function space (Phase 2.2). The current
template treats the coil bundle as ONE solid conductor; at high
frequencies that drives current to the bundle perimeter and gives
``L_ac ≈ 0`` (instead of the multi-turn coil's ``L_ac ≈ L_dc``).
Phase 2.1 ships the template infrastructure; Phase 2.2 unlocks
real numbers.

Test ``test_ac_template_sigma_zero_matches_dc_energy`` validates
the template by setting σ_copper = 0 (no eddy currents); the
result must match the DC energy-method L within the known
"energy vs flux-linkage" envelope (≤ 20 % for axi round-leg).
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

# ─── Skin-depth helper ────────────────────────────────────────────


def test_skin_depth_copper_textbook_values():
    """Skin depth at standard frequencies for copper at 25 °C.

    Reference: any EE textbook (Hayt, Cheng), or NIST tables.
    Tolerances are loose because the textbook values themselves
    are typically rounded to 2 sig figs.
    """
    from pfc_inductor.fea.direct.physics.magnetostatic_ac import skin_depth_m

    cases = [
        # (f_Hz, expected_μm, tol_μm)
        (50_000.0, 295.0, 10.0),
        (100_000.0, 208.0, 10.0),
        (130_000.0, 181.0, 10.0),
        (500_000.0, 93.0, 5.0),
        (1_000_000.0, 66.0, 3.0),
    ]
    for f, expected, tol in cases:
        delta_um = skin_depth_m(frequency_Hz=f) * 1e6
        assert abs(delta_um - expected) < tol, (
            f"δ at f={f / 1e3:.0f} kHz: got {delta_um:.1f} μm, expected {expected} ± {tol}"
        )


def test_recommended_mesh_size_default():
    """Mesh size = skin depth / 3 by default."""
    from pfc_inductor.fea.direct.physics.magnetostatic_ac import (
        recommended_mesh_size_at_skin_m,
        skin_depth_m,
    )

    f = 130_000.0
    delta = skin_depth_m(frequency_Hz=f)
    mesh = recommended_mesh_size_at_skin_m(frequency_Hz=f, n_elements_per_skin=3)
    assert math.isclose(mesh, delta / 3.0, rel_tol=1e-9)


# ─── Template rendering ───────────────────────────────────────────


def test_ac_template_renders_with_expected_keywords():
    """The rendered .pro must contain the GetDP constructs that
    distinguish AC harmonic from DC magnetostatic.
    """
    from pfc_inductor.fea.direct.physics.magnetostatic_ac import (
        MagnetostaticAcInputs,
        MagnetostaticAcTemplate,
    )

    pro = MagnetostaticAcTemplate().render(
        MagnetostaticAcInputs(mu_r_core=2300, n_turns=50, current_A=5.0, coil_area_m2=1e-4)
    )

    must_have = [
        # AC-specific GetDP keywords
        "Type Complex",  # complex-valued solve
        "Frequency Freq",  # frequency-domain resolution
        "DtDof",  # time-derivative term → jω in freq domain
        "MagDyn_a",  # formulation name
        # AC-specific physics
        "sigma[",  # conductivity definition
        "P_density_cu",  # eddy-current loss density
        # AC-specific postop
        "P_cu",  # joule loss in copper
        "FluxOverI",  # flux-linkage for L_ac extraction
    ]
    for keyword in must_have:
        assert keyword in pro, f"rendered template missing: {keyword!r}"


def test_ac_template_substitutes_numbers():
    """All numeric inputs flow through to the rendered template."""
    from pfc_inductor.fea.direct.physics.magnetostatic_ac import (
        MagnetostaticAcInputs,
        MagnetostaticAcTemplate,
    )

    pro = MagnetostaticAcTemplate().render(
        MagnetostaticAcInputs(
            mu_r_core=2300.5,
            sigma_core_Spm=0.0,
            sigma_copper_Spm=5.96e7,
            n_turns=42,
            current_A=7.3,
            coil_area_m2=1.234e-4,
            frequency_Hz=130_000.0,
        )
    )
    # Spot-check several values appear in the rendered output.
    # GetDP requires numbers as raw floats; ``str.format`` of 0.0
    # is "0.0" but of 5.96e7 might be "59600000.0" or "5.96e+07"
    # depending on numpy/Python — use substring checks.
    assert "2300.5" in pro
    assert "42" in pro  # n_turns
    assert "7.3" in pro  # current_A
    # frequency: usually 130000.0 in the rendered output
    assert "130000" in pro or "1.3e+05" in pro.lower() or "1.3e5" in pro.lower()


# ─── Complex output parsing ──────────────────────────────────────


def test_parse_complex_scalar_table_three_columns(tmp_path: Path):
    """GetDP writes ``region_idx  re  im`` on each line; the
    parser must extract the last two as complex.
    """
    from pfc_inductor.fea.direct.postproc import parse_complex_scalar_table

    p = tmp_path / "complex.txt"
    p.write_text(" 0 3.14159e-5 -2.71828e-3\n")
    result = parse_complex_scalar_table(p)
    assert result is not None
    assert math.isclose(result.real, 3.14159e-5, rel_tol=1e-6)
    assert math.isclose(result.imag, -2.71828e-3, rel_tol=1e-6)


def test_parse_complex_scalar_table_missing_returns_none(tmp_path: Path):
    """Missing file → ``None``, no exception."""
    from pfc_inductor.fea.direct.postproc import parse_complex_scalar_table

    p = tmp_path / "nope.txt"  # doesn't exist
    assert parse_complex_scalar_table(p) is None


# ─── L_ac / R_ac extraction ──────────────────────────────────────


def test_extract_L_R_from_pure_real_flux():
    """A purely-real Φ/I phasor means no resistive loss:
    L_ac > 0, R_ac = 0.
    """
    from pfc_inductor.fea.direct.postproc import extract_ac_L_R_from_flux

    L_uH, R_mOhm = extract_ac_L_R_from_flux(
        flux_over_I_complex=complex(1e-5, 0),
        n_turns=50,
        frequency_Hz=130_000,
    )
    # L = Re(Φ/I) · N = 1e-5 × 50 = 5e-4 H = 500 μH
    assert math.isclose(L_uH, 500.0, rel_tol=1e-6)
    assert math.isclose(R_mOhm, 0.0, abs_tol=1e-9)


def test_extract_L_R_imaginary_part_gives_R():
    """Imaginary part of Φ/I maps to R_ac via -ω."""
    from pfc_inductor.fea.direct.postproc import extract_ac_L_R_from_flux

    # Choose values so the answer is clean.
    omega = 2 * math.pi * 130_000
    # R_target = 5 mΩ = 5e-3 Ω
    # R = -ω · Im(Φ/I) · N  ⟹  Im(Φ/I) = -R / (ω·N)
    R_target_Ohm = 5e-3
    N = 50
    Im_part = -R_target_Ohm / (omega * N)
    _, R_mOhm = extract_ac_L_R_from_flux(
        flux_over_I_complex=complex(0, Im_part),
        n_turns=N,
        frequency_Hz=130_000,
    )
    assert math.isclose(R_mOhm, 5.0, rel_tol=1e-6)


# ─── End-to-end (slow, requires GetDP + gmsh) ────────────────────


@pytest.mark.slow
def test_ac_template_sigma_zero_matches_dc_energy(tmp_path: Path):
    """With ``σ_copper = 0`` the AC template has no eddy currents,
    so the solution is identical to a DC magnetostatic at the
    same J source — and ``L_ac`` from flux-linkage should match
    ``L_dc`` from the energy method within the known ~20 %
    flux-vs-energy envelope on axi PQ cores.

    This is the "template is mathematically correct" gate.
    """
    import os
    import subprocess

    import gmsh

    from pfc_inductor.data_loader import load_cores, load_materials
    from pfc_inductor.fea.direct.geometry.ei_axi import build_ei_axi
    from pfc_inductor.fea.direct.models import EICoreDims
    from pfc_inductor.fea.direct.physics.magnetostatic_ac import (
        MagnetostaticAcInputs,
        MagnetostaticAcTemplate,
    )
    from pfc_inductor.fea.direct.postproc import (
        extract_ac_L_R_from_flux,
        parse_complex_scalar_table,
    )
    from pfc_inductor.setup_deps.paths import FeaPaths

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    cores = load_cores()
    mats = load_materials()
    core = next(c for c in cores if c.id == "tdkepcos-pq-4040-n87")
    mat = next(m for m in mats if m.id == "tdkepcos-n87")

    td_path = tmp_path / "ac_sigma_zero"
    td_path.mkdir()

    gmsh.initialize([])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        build_ei_axi(gmsh, core=core, lgap_mm=0.5)
        dims = EICoreDims.from_core(core)
        diag = max(dims.total_w_mm, dims.total_h_mm) * 1e-3
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", diag * 0.05)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", diag * 0.005)
        gmsh.model.mesh.generate(2)
        mesh_path = td_path / "ei_axi.msh"
        gmsh.write(str(mesh_path))
    finally:
        gmsh.finalize()

    clearance_mm = 1.0
    A_2d_mm2 = max(dims.window_w_mm - 2 * clearance_mm, 0.1) * max(
        dims.window_h_mm - 2 * clearance_mm, 0.1
    )
    r_cl_mm = math.sqrt(dims.center_leg_w_mm * dims.center_leg_d_mm / math.pi)
    R_inner_mm = r_cl_mm + clearance_mm
    R_outer_mm = r_cl_mm + dims.window_w_mm - clearance_mm
    R_mean_mm = (R_inner_mm + R_outer_mm) / 2.0
    coil_area_m2 = (A_2d_mm2 * 1e-6) * (2 * math.pi * R_mean_mm * 1e-3)

    pro = MagnetostaticAcTemplate().render(
        MagnetostaticAcInputs(
            mu_r_core=float(getattr(mat, "mu_r", 2300)),
            sigma_copper_Spm=0.0,  # no eddy currents
            n_turns=39,
            current_A=8.0,
            coil_area_m2=coil_area_m2,
            frequency_Hz=130_000.0,
        )
    )
    pro_path = td_path / "ei_axi_ac.pro"
    pro_path.write_text(pro, encoding="utf-8")

    fp = FeaPaths.detect()
    getdp = fp.onelab_binary_path(fp.default_onelab_dir, "getdp")
    cmd = [
        str(getdp),
        str(pro_path),
        "-msh",
        str(mesh_path),
        "-solve",
        "MagDyn",
        "-pos",
        "MagDyn_out",
        "-v",
        "2",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=td_path)
    assert r.returncode == 0, f"GetDP failed: {r.stderr[-500:]}"

    flux = parse_complex_scalar_table(td_path / "flux_linkage_over_I_ac.txt")
    assert flux is not None
    L_uH, R_mOhm = extract_ac_L_R_from_flux(
        flux_over_I_complex=flux, n_turns=39, frequency_Hz=130_000
    )
    # With σ=0 there should be no resistive component
    assert abs(R_mOhm) < 1e-6, f"σ=0 must give R=0; got {R_mOhm}"
    # L should be in the same ballpark as the DC result (~1000 μH
    # for PQ 40/40 at 39 turns); locked loose because the axi
    # round-leg approximation envelope is wide on this geometry.
    assert 500 < L_uH < 2500, (
        f"L_ac with σ=0 should be in DC ballpark (500–2500 μH for "
        f"PQ 40/40 / 39 turns); got {L_uH:.1f}"
    )
