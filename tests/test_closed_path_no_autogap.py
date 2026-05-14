"""Regression tests for the Si-Fe / amorphous / nanocrystalline auto-gap fix.

Background
----------
Before this fix landed, ``_resolve_gap_and_AL`` in
:mod:`pfc_inductor.design.engine` treated any material with
``rolloff=None`` as a gapped ferrite and synthesised an air gap
to limit B_pk to ``Bsat_limit``. That blew up on Si-Fe lamination
cores (closed magnetic path by design, no rolloff curve): the
engine injected 10+ mm phantom gaps and overwrote the catalog
``AL_nH`` (e.g. 392 → 12.8 nH on the EI3311), making the
analytical engine disagree with the direct FEA backend by 70–177 %
on every closed-core line-reactor design.

The fix gates the auto-gap path by material type so closed-path
materials (silicon-steel, amorphous, nanocrystalline) keep their
catalog ``AL_nH`` untouched. Saturating designs now surface as a
warning ("B_pk exceeds Bsat_limit") instead of being silently
masked by an inventado gap.

These tests pin three guarantees:

1. **Closed-path catalog AL is preserved** — ``AL_eff = AL_nH``,
   ``lgap = catalog_lgap`` regardless of how the design saturates.
2. **Engine vs direct backend agree to <1 %** on closed-path
   line-reactor cases (previously: 70–177 % off).
3. **Saturating closed-core designs warn** so the user picks a
   bigger core instead of trusting a hidden gap.
"""

from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ──────────────────────────────────────────────────────────────────────
# Synthetic catalog (no I/O — keeps the test fast and deterministic)
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def closed_path_core_and_material():
    """Si-Fe EI3311 — closed magnetic path, no rolloff."""
    from pfc_inductor.models import Core

    core = Core(
        id="test-ei3311-sife",
        vendor="test",
        part_number="ei3311",
        shape="EI",
        Ae_mm2=121.0,
        Wa_mm2=240.0,
        le_mm=64.0,
        Ve_mm3=7744.0,
        MLT_mm=72.0,
        AL_nH=392.0,
        lgap_mm=0.0,
        default_material_id="test-sife-50h800",
    )
    material = _make_material(
        id_="test-sife-50h800",
        name="50H800",
        type_="silicon-steel",
        family="silicon-steel",
        mu_initial=3000.0,
        Bsat_25C_T=1.65,
        Bsat_100C_T=1.5675,
    )
    return core, material


@pytest.fixture
def ferrite_core_and_material():
    """N87 PQ40/40 — gapped ferrite, no rolloff but auto-gap is correct here."""
    from pfc_inductor.models import Core

    core = Core(
        id="test-pq4040-n87",
        vendor="test",
        part_number="pq4040",
        shape="PQ",
        Ae_mm2=201.0,
        Wa_mm2=160.0,
        le_mm=102.0,
        Ve_mm3=20502.0,
        MLT_mm=83.5,
        AL_nH=5500.0,
        lgap_mm=0.0,
        default_material_id="test-n87",
    )
    material = _make_material(
        id_="test-n87",
        name="N87",
        type_="ferrite",
        family="MnZn",
        mu_initial=2200.0,
        Bsat_25C_T=0.49,
        Bsat_100C_T=0.39,
    )
    return core, material


def _make_material(
    *,
    id_: str,
    name: str,
    type_: str,
    family: str,
    mu_initial: float,
    Bsat_25C_T: float,
    Bsat_100C_T: float,
):
    """Build a minimal Material — Steinmetz/rolloff irrelevant for these tests."""
    from pfc_inductor.models import Material
    from pfc_inductor.models.material import SteinmetzParams

    return Material(
        id=id_,
        vendor="test",
        family=family,
        name=name,
        type=type_,  # type: ignore[arg-type]
        mu_initial=mu_initial,
        Bsat_25C_T=Bsat_25C_T,
        Bsat_100C_T=Bsat_100C_T,
        steinmetz=SteinmetzParams(Pv_ref_mWcm3=100.0, alpha=1.5, beta=2.5),
        rolloff=None,
    )


# ──────────────────────────────────────────────────────────────────────
# Guarantee 1: closed-path AL is preserved
# ──────────────────────────────────────────────────────────────────────


def test_silicon_steel_skip_autogap(closed_path_core_and_material):
    """Si-Fe core: ``AL_eff == catalog AL``, no phantom gap."""
    from pfc_inductor.design.engine import _resolve_gap_and_AL

    core, mat = closed_path_core_and_material

    # Aggressive design that would normally trigger the auto-gap:
    # I_pk = 42 A, L = 1 mH on a 121 mm² core would need a ~12 mm gap
    # to limit B_pk to 1.25 T. The fix must NOT inject that gap.
    eff_core, gap_mm = _resolve_gap_and_AL(
        core,
        mat,
        L_req_uH=1000.0,
        I_pk_A=42.4,
        Bsat_limit_T=1.254,
        N_override=None,
    )

    assert eff_core.AL_nH == pytest.approx(392.0, rel=1e-9), (
        f"Si-Fe AL should be unchanged (catalog 392 nH); got {eff_core.AL_nH:.2f}"
    )
    assert gap_mm == 0.0, f"No phantom gap should be injected; got {gap_mm:.3f} mm"
    assert eff_core.lgap_mm == 0.0


@pytest.mark.parametrize("mat_type", ["amorphous", "nanocrystalline"])
def test_amorphous_nanocrystalline_skip_autogap(
    closed_path_core_and_material, mat_type: str
):
    """Same protection for amorphous (Metglas) and nanocrystalline (Finemet)."""
    from pfc_inductor.design.engine import _resolve_gap_and_AL

    core, mat = closed_path_core_and_material
    mat = mat.model_copy(update={"type": mat_type})

    eff_core, gap_mm = _resolve_gap_and_AL(
        core,
        mat,
        L_req_uH=1000.0,
        I_pk_A=42.4,
        Bsat_limit_T=1.254,
        N_override=None,
    )
    assert eff_core.AL_nH == pytest.approx(392.0, rel=1e-9)
    assert gap_mm == 0.0


# ──────────────────────────────────────────────────────────────────────
# Guarantee 2: ferrites still get the auto-gap (regression — the fix
# must NOT break the ferrite path)
# ──────────────────────────────────────────────────────────────────────


def test_ferrite_still_gets_autogap(ferrite_core_and_material):
    """Ferrite ungapped → AL gets overwritten to match the auto-gap."""
    from pfc_inductor.design.engine import _resolve_gap_and_AL

    core, mat = ferrite_core_and_material

    eff_core, gap_mm = _resolve_gap_and_AL(
        core,
        mat,
        L_req_uH=500.0,
        I_pk_A=10.0,
        Bsat_limit_T=0.31,
        N_override=None,
    )
    assert gap_mm > 0.0, "Ferrite core ungapped → auto-gap should fire"
    assert eff_core.AL_nH < core.AL_nH, "AL_eff must drop below catalog"


# ──────────────────────────────────────────────────────────────────────
# Guarantee 3: engine vs direct backend agree on closed-path cores
# ──────────────────────────────────────────────────────────────────────


def _make_line_reactor_spec(I_rated: float = 30.0):
    """Minimal line-reactor Spec — relies on Spec's many defaults.

    All Spec fields have defaults, so we only override the few that
    matter for the line-reactor B_pk / L calculation.
    """
    from pfc_inductor.models import Spec

    return Spec(
        topology="line_reactor",
        Vin_nom_Vrms=220.0,
        n_phases=1,
        f_line_Hz=60.0,
        I_rated_Arms=I_rated,
        L_req_mH=1.0,
        Bsat_margin=0.20,
    )


def test_line_reactor_si_fe_engine_vs_direct_agree(closed_path_core_and_material):
    """End-to-end: engine analytical L,B match direct FEA backend <1%.

    Before the fix this gap was 174 %. Anything above 1 % here means
    the fix regressed: the engine and direct backend are silently
    using different models for closed-path Si-Fe cores again.
    """
    from pfc_inductor.design.engine import design
    from pfc_inductor.fea.runner import validate_design
    from pfc_inductor.models import Wire

    os.environ["PFC_FEA_BACKEND"] = "direct"

    core, mat = closed_path_core_and_material
    wire = Wire(
        id="test-awg14",
        type="round",
        awg=14,
        d_cu_mm=1.628,
        d_iso_mm=1.78,
        A_cu_mm2=2.08,
    )

    spec = _make_line_reactor_spec(I_rated=30.0)
    res = design(spec, core, wire, mat)
    assert res is not None

    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path

        val = validate_design(spec, core, wire, mat, res, output_dir=Path(td))

    assert abs(val.L_pct_error) < 1.0, (
        f"Engine L={val.L_analytic_uH:.1f}μH vs direct L={val.L_FEA_uH:.1f}μH "
        f"differ by {val.L_pct_error:+.2f}% — the Si-Fe auto-gap regression "
        f"is back. Check engine._resolve_gap_and_AL."
    )
    assert abs(val.B_pct_error) < 1.0, (
        f"Engine B={val.B_pk_analytic_T * 1000:.0f}mT vs direct "
        f"B={val.B_pk_FEA_T * 1000:.0f}mT differ by {val.B_pct_error:+.2f}%"
    )


# ──────────────────────────────────────────────────────────────────────
# Guarantee 4: Fringing-aware auto-gap — ferrite parity
# ──────────────────────────────────────────────────────────────────────


def test_ferrite_autogap_applies_roters_fringing(ferrite_core_and_material):
    """Engine and direct backend must agree on L within 5 % on a gapped ferrite.

    Before the fringing fix, the engine sized the auto-gap with
    ``k_fringe = 1`` (no fringing flux) while the direct backend
    applied Roters fringing to the same physical gap — yielding
    +30–200 % L disagreement on ferrite boost-PFC designs.

    After the fix, the engine iterates to find the lgap that hits
    L_target *with* fringing, and AL_eff is computed from
    ``le/μ_r + lgap_phys/k_fringe``. The two backends now read the
    same model and agree to numerical precision.
    """
    from pathlib import Path

    from pfc_inductor.design.engine import design
    from pfc_inductor.fea.runner import validate_design
    from pfc_inductor.models import Spec, Wire

    os.environ["PFC_FEA_BACKEND"] = "direct"

    core, mat = ferrite_core_and_material
    wire = Wire(
        id="test-awg14",
        type="round",
        awg=14,
        d_cu_mm=1.628,
        d_iso_mm=1.78,
        A_cu_mm2=2.08,
    )

    # Boost-PFC operating point that lands well within the core's
    # window. Chose ripple_pct so the resulting auto-gap is non-
    # trivial (≥ 1 mm) and Roters k_fringe is meaningfully > 1.
    spec = Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=230.0,
        Vout_V=400.0,
        Pout_W=600.0,
        eta=0.97,
        f_sw_kHz=65.0,
        ripple_pct=30.0,
        T_amb_C=40.0,
        Bsat_margin=0.20,
        L_req_mH=1.0,
        I_rated_Arms=4.0,
    )
    res = design(spec, core, wire, mat)
    assert res is not None

    with tempfile.TemporaryDirectory() as td:
        val = validate_design(spec, core, wire, mat, res, output_dir=Path(td))

    assert abs(val.L_pct_error) < 5.0, (
        f"Engine L={val.L_analytic_uH:.1f}μH vs direct L={val.L_FEA_uH:.1f}μH "
        f"differ by {val.L_pct_error:+.2f}% — the Roters-fringing-aware "
        f"auto-gap regressed. Check engine._solve_lgap_with_fringing."
    )


def test_fringing_factor_matches_direct_backend_implementation():
    """``_fringing_factor_roters`` must match the direct backend bit-for-bit.

    The two copies (engine.py and fea/direct/physics/reluctance_axi.py)
    are duplicated by design so the engine doesn't pull in FEA imports.
    But they MUST stay in lock-step — otherwise the engine sizes a gap
    against one model and the direct backend evaluates it against
    another, reintroducing the 30–200 % disagreement.
    """
    from pfc_inductor.design.engine import _fringing_factor_roters as engine_k
    from pfc_inductor.fea.direct.physics.reluctance_axi import (
        fringing_factor_roters as direct_k,
    )

    test_pairs = [
        (0.5, 14.0),  # PQ40 / typical gap
        (3.4, 14.4),  # ETD49
        (5.6, 13.1),  # PQ35
        (0.09, 6.8),  # EP10 gapped
        (10.0, 5.0),  # gap > leg width (clamping regime)
        (0.0, 14.0),  # no gap → k = 1
    ]
    for lgap, w in test_pairs:
        assert engine_k(lgap, w) == pytest.approx(direct_k(lgap, w), rel=1e-9), (
            f"Fringing-factor drift at lgap={lgap}, w={w}: "
            f"engine={engine_k(lgap, w):.6f} vs direct={direct_k(lgap, w):.6f}"
        )


def test_saturating_si_fe_design_surfaces_warning(closed_path_core_and_material):
    """A clearly-undersized closed core must produce a B_pk warning.

    The fix removed the silent auto-gap — saturating designs need to
    raise a visible flag so the user picks a bigger core instead of
    being fooled by a phantom gap.
    """
    from pfc_inductor.design.engine import design
    from pfc_inductor.models import Wire

    core, mat = closed_path_core_and_material
    wire = Wire(
        id="test-awg14",
        type="round",
        awg=14,
        d_cu_mm=1.628,
        d_iso_mm=1.78,
        A_cu_mm2=2.08,
    )

    spec = _make_line_reactor_spec(I_rated=30.0)
    res = design(spec, core, wire, mat)
    assert res is not None

    Bsat_limit = mat.Bsat_100C_T * (1.0 - spec.Bsat_margin)
    assert res.B_pk_T > Bsat_limit, (
        f"Test scenario should saturate the core (B_pk={res.B_pk_T:.2f}T > "
        f"{Bsat_limit:.2f}T), but B_pk fell below the limit. "
        f"The test is mis-calibrated."
    )

    warnings_text = " | ".join(getattr(res, "warnings", []) or [])
    assert "B_pk" in warnings_text or "saturation" in warnings_text.lower(), (
        f"Saturating design must warn about B_pk > Bsat_limit; "
        f"warnings={getattr(res, 'warnings', None)}"
    )
