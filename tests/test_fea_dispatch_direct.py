"""Tests for the Phase 5.1 dual-backend dispatch.

The FEA orchestrator (``pfc_inductor.fea.runner.validate_design``)
gained a ``PFC_FEA_BACKEND`` env override so users / CI / cascade
runs can pick between the legacy FEMMT + FEMM stack and the new
in-tree direct backend.

The tests below lock in:

1. Default env (no override) preserves the legacy dispatch.
2. ``PFC_FEA_BACKEND=direct`` routes through the direct backend
   and returns an FEAValidation with the marker binary string.
3. The direct adapter populates the analytical-vs-FEA pct_error
   fields correctly when the DesignResult carries a non-zero
   ``L_actual_uH``.
4. Unknown values of the env var fall back to the legacy
   dispatch silently (no warning loop, no crash).
"""

from __future__ import annotations

from unittest import mock

import pytest

ENV_VAR = "PFC_FEA_BACKEND"


@pytest.fixture
def restore_env():
    """Ensure each test starts and ends without the override set."""
    import os

    prev = os.environ.pop(ENV_VAR, None)
    try:
        yield
    finally:
        if prev is not None:
            os.environ[ENV_VAR] = prev
        elif ENV_VAR in os.environ:
            os.environ.pop(ENV_VAR, None)


# ─── Direct-backend dispatch on a toroidal core ────────────────────


def test_direct_dispatch_routes_toroidal_to_direct_backend(restore_env):
    """``PFC_FEA_BACKEND=direct`` on a toroidal core must land in
    the analytical toroidal solver. The FEAValidation we get back
    carries the marker femm_binary so callers can introspect.
    """
    import os

    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.design import design
    from pfc_inductor.fea.runner import validate_design
    from pfc_inductor.models import Spec

    os.environ[ENV_VAR] = "direct"

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    core = next(c for c in cores if "magnetics-c058150a2" in c.id.lower())
    mat = next(m for m in mats if m.id == core.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)
    spec = Spec()  # type: ignore[call-arg]

    design_result = design(spec, core, wire, mat)
    fea = validate_design(spec, core, wire, mat, design_result)

    assert "direct" in fea.femm_binary.lower()
    assert fea.L_FEA_uH > 0
    # Toroidal analytical path: extremely fast.
    assert fea.solve_time_s < 0.1


def test_direct_dispatch_pct_error_when_analytical_present(restore_env):
    """When the DesignResult carries a non-zero ``L_actual_uH``,
    the dispatcher populates a meaningful ``L_pct_error``. On a
    powder-core toroid the engine + direct backend agree well
    (the analytical formula they both use is identical).
    """
    import os

    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.design import design
    from pfc_inductor.fea.runner import validate_design
    from pfc_inductor.models import Spec

    os.environ[ENV_VAR] = "direct"

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    core = next(c for c in cores if "magnetics-c058150a2" in c.id.lower())
    mat = next(m for m in mats if m.id == core.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)
    spec = Spec()  # type: ignore[call-arg]

    design_result = design(spec, core, wire, mat)
    fea = validate_design(spec, core, wire, mat, design_result)

    # Both backends should agree to ≤ 2% on this powder core (they
    # use the same closed-form L = μ·N²·Ae/le formula).
    assert abs(fea.L_pct_error) < 2.0


# ─── Default + fallback paths ─────────────────────────────────────


def test_default_dispatch_does_not_use_direct_backend(restore_env):
    """Without the env var, dispatch falls through to the legacy
    code path (FEMMT or FEMM via select_backend_for_shape).
    We don't actually invoke FEMMT here — we patch it to assert
    the call goes through the legacy entry point.
    """
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.fea.runner import validate_design
    from pfc_inductor.models import Spec

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    core = next(c for c in cores if "magnetics-c058150a2" in c.id.lower())
    mat = next(m for m in mats if m.id == core.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)

    # The toroidal goes to FEMM via shape-based selection in legacy
    # mode. Patch FEMM to a stub so the test doesn't depend on
    # xfemm being installed.
    with (
        mock.patch("pfc_inductor.fea.runner.select_backend_for_shape", return_value="femm"),
        mock.patch("pfc_inductor.fea.runner._validate_design_femm") as femm_stub,
    ):
        from pfc_inductor.fea.models import FEAValidation

        femm_stub.return_value = FEAValidation(
            L_FEA_uH=100.0,
            L_analytic_uH=100.0,
            L_pct_error=0.0,
            B_pk_FEA_T=0.5,
            B_pk_analytic_T=0.5,
            B_pct_error=0.0,
            flux_linkage_FEA_Wb=0.01,
            test_current_A=1.0,
            solve_time_s=0.0,
            femm_binary="legacy stub",
            fem_path="",
        )
        from pfc_inductor.design import design

        spec = Spec()  # type: ignore[call-arg]
        design_result = design(spec, core, wire, mat)
        fea = validate_design(spec, core, wire, mat, design_result)
        assert "legacy stub" in fea.femm_binary
        femm_stub.assert_called_once()


def test_unknown_backend_value_falls_back_silently(restore_env):
    """An invalid ``PFC_FEA_BACKEND=bogus`` value must NOT crash —
    just fall through to shape-based dispatch. This protects
    users from typos in shell-env exports.
    """
    import os

    from pfc_inductor.data_loader import load_cores, load_materials, load_wires
    from pfc_inductor.fea.runner import validate_design
    from pfc_inductor.models import Spec

    os.environ[ENV_VAR] = "bogus_backend"

    cores = load_cores()
    mats = load_materials()
    wires = load_wires()
    core = next(c for c in cores if "magnetics-c058150a2" in c.id.lower())
    mat = next(m for m in mats if m.id == core.default_material_id)
    wire = next(w for w in wires if "AWG18" in w.id)

    with (
        mock.patch("pfc_inductor.fea.runner.select_backend_for_shape", return_value="femm"),
        mock.patch("pfc_inductor.fea.runner._validate_design_femm") as femm_stub,
    ):
        from pfc_inductor.fea.models import FEAValidation

        femm_stub.return_value = FEAValidation(
            L_FEA_uH=100.0,
            L_analytic_uH=100.0,
            L_pct_error=0.0,
            B_pk_FEA_T=0.5,
            B_pk_analytic_T=0.5,
            B_pct_error=0.0,
            flux_linkage_FEA_Wb=0.01,
            test_current_A=1.0,
            solve_time_s=0.0,
            femm_binary="legacy fallback",
            fem_path="",
        )
        from pfc_inductor.design import design

        spec = Spec()  # type: ignore[call-arg]
        design_result = design(spec, core, wire, mat)
        fea = validate_design(spec, core, wire, mat, design_result)
        assert "fallback" in fea.femm_binary
        femm_stub.assert_called_once()
