"""Smoke tests for ``pfc_inductor.fea.direct.calibration``.

Phase 1.2 scaffolding test. The goal of the calibration module
is to be the **oracle for direct-backend iteration**: tweak the
``.pro`` template, re-run, watch ``diff_pct`` shrink. These tests
just pin the module's API + structure so we don't accidentally
break the oracle while iterating on physics.

Note: the direct backend is exercised here but tolerances are
loose because the Phase 1.1 result is still ~89% off the
analytical ideal. Phase 1.2 will tighten the tolerance to 5 %
on the same test case once the physics template is calibrated.
"""

from __future__ import annotations

import pytest


# Synthetic EI core — minimal duck-typed object the direct backend
# accepts (it reads ``Ae_mm2``, ``Wa_mm2``, ``le_mm``, ``MLT_mm``,
# ``lgap_mm``, ``shape`` only).
class _FakeEICore:
    shape = "ei"
    Ae_mm2 = 480.0
    Wa_mm2 = 280.0
    le_mm = 114.0
    Ve_mm3 = 55_000.0
    MLT_mm = 80.0
    lgap_mm = 0.5
    AL_nH = 0
    OD_mm = ID_mm = HT_mm = None
    id = "fake-EI"
    vendor = "fake"
    part_number = "fake"
    default_material_id = "fake"


class _FakeMaterial:
    mu_r = 2000.0
    id = "fake-ferrite"


class _FakeWire:
    id = "fake-AWG14"


# ─── analytical_L_uH ──────────────────────────────────────────────


def test_analytical_L_air_only():
    from pfc_inductor.fea.direct.calibration import analytical_L_uH

    # μ_r = 1 → pure-air case. Iron path contributes nothing,
    # so L ≈ μ₀N²Ae/(le + lgap).
    L = analytical_L_uH(core=_FakeEICore(), n_turns=80, mu_r=1.0)
    # Expected ≈ 4π·1e-7 × 80² × 480e-6 / (114e-3 + 0.5e-3)
    # ≈ 33.7 μH
    assert 30.0 < L < 40.0


def test_analytical_L_high_mur_gap_dominated():
    from pfc_inductor.fea.direct.calibration import analytical_L_uH

    # μ_r = 2000 → iron reluctance is small, gap dominates.
    # L ≈ μ₀N²Ae/lgap = 6930 μH for our test case.
    L = analytical_L_uH(core=_FakeEICore(), n_turns=80, mu_r=2000.0)
    assert 6500.0 < L < 7100.0


def test_analytical_L_scales_quadratically_with_n():
    """``L ∝ N²`` — doubling turns quadruples L."""
    from pfc_inductor.fea.direct.calibration import analytical_L_uH

    L1 = analytical_L_uH(core=_FakeEICore(), n_turns=40, mu_r=2000.0)
    L2 = analytical_L_uH(core=_FakeEICore(), n_turns=80, mu_r=2000.0)
    assert L2 / L1 == pytest.approx(4.0, rel=1e-9)


# ─── compare_backends — structural API ────────────────────────────


def test_compare_backends_returns_report_with_analytical():
    """Skip FEMMT + direct, exercise the analytical-only path.

    Confirms the public API surface stays stable as the backends
    underneath evolve. Phase 1.2 will replace this with a 5 %-
    tolerance roundtrip once the physics template is calibrated.
    """
    from pfc_inductor.fea.direct.calibration import compare_backends

    report = compare_backends(
        core=_FakeEICore(),
        material=_FakeMaterial(),
        wire=_FakeWire(),
        n_turns=80,
        current_A=5.0,
        include_femmt=False,
        include_direct=False,
        include_analytical=True,
    )
    assert "analytical" in report.outcomes
    assert report.analytical is not None
    assert report.analytical.L_dc_uH is not None
    assert 6500.0 < report.analytical.L_dc_uH < 7100.0


def test_compare_backends_omits_femmt_when_disabled():
    from pfc_inductor.fea.direct.calibration import compare_backends

    report = compare_backends(
        core=_FakeEICore(),
        material=_FakeMaterial(),
        wire=_FakeWire(),
        n_turns=80,
        current_A=5.0,
        include_femmt=False,
        include_direct=False,
    )
    assert report.femmt is None


def test_compare_backends_str_format():
    """The ``__str__`` is the canonical CLI dump for Phase 1.2
    iteration — pin its broad shape so the calibration loop
    doesn't break on a stray refactor.
    """
    from pfc_inductor.fea.direct.calibration import compare_backends

    report = compare_backends(
        core=_FakeEICore(),
        material=_FakeMaterial(),
        wire=_FakeWire(),
        n_turns=80,
        current_A=5.0,
        include_femmt=False,
        include_direct=False,
    )
    text = str(report)
    assert "Calibration report" in text
    assert "analytical" in text
    assert "μH" in text


# ─── diff_pct property ────────────────────────────────────────────


def test_diff_pct_none_when_direct_missing():
    """If the direct backend was skipped, ``diff_pct`` is N/A."""
    from pfc_inductor.fea.direct.calibration import compare_backends

    report = compare_backends(
        core=_FakeEICore(),
        material=_FakeMaterial(),
        wire=_FakeWire(),
        n_turns=80,
        current_A=5.0,
        include_femmt=False,
        include_direct=False,
        include_analytical=True,
    )
    assert report.diff_pct is None
