"""Regression tests for the "Ajustar protótipo" override path.

Cover the contract of ``engine.design(..., N_override=...)`` and the
:class:`DesignOverrides` model round-trip through the project file.
"""

from __future__ import annotations

import pytest

from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.design import design
from pfc_inductor.models import DesignOverrides, Spec, stack_core
from pfc_inductor.project import ProjectFile, load_project, save_project


@pytest.fixture
def db():
    return load_materials(), load_cores(), load_wires()


@pytest.fixture
def baseline_inputs(db):
    """A boost-CCM design that yields a sensible (non-cap-hit) N."""
    materials, cores, wires = db
    spec = Spec(
        topology="boost_ccm",
        Pout_W=400.0,
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=220.0,
        Vout_V=400.0,
        f_sw_kHz=65.0,
        ripple_pct=30.0,
    )
    mat = find_material(materials, "magnetics-60_highflux")
    core = next(
        c
        for c in cores
        if c.default_material_id == "magnetics-60_highflux" and 40000 < c.Ve_mm3 < 100000
    )
    wire = next(w for w in wires if w.id == "AWG14")
    return spec, core, wire, mat


def test_overrides_empty_matches_legacy_design(baseline_inputs):
    """``N_override=None`` must produce the same result as not passing it."""
    spec, core, wire, mat = baseline_inputs
    r_legacy = design(spec, core, wire, mat)
    r_explicit_none = design(spec, core, wire, mat, N_override=None)
    assert r_explicit_none.N_turns == r_legacy.N_turns
    assert r_explicit_none.L_actual_uH == pytest.approx(r_legacy.L_actual_uH, rel=1e-9)
    assert r_explicit_none.B_pk_T == pytest.approx(r_legacy.B_pk_T, rel=1e-9)
    assert r_explicit_none.T_winding_C == pytest.approx(r_legacy.T_winding_C, rel=1e-9)
    assert r_explicit_none.losses.P_total_W == pytest.approx(r_legacy.losses.P_total_W, rel=1e-9)


def test_n_override_forces_engine_turn_count(baseline_inputs):
    """``N_override=k`` returns ``N_turns == k`` even when the solver would pick less."""
    spec, core, wire, mat = baseline_inputs
    r_base = design(spec, core, wire, mat)
    forced = r_base.N_turns + 3
    r_force = design(spec, core, wire, mat, N_override=forced)
    assert r_force.N_turns == forced
    # More turns → larger L (until rolloff dominates) and larger B at the
    # same peak current. Sanity check the direction of change.
    assert r_force.L_actual_uH > r_base.L_actual_uH
    assert r_force.B_pk_T > r_base.B_pk_T


def test_n_override_below_solver_emits_inductance_warning(baseline_inputs):
    """When the user forces N below what's needed, the engine surfaces a warning
    rather than raising — matches the "I want to see this anyway" use case."""
    spec, core, wire, mat = baseline_inputs
    r_base = design(spec, core, wire, mat)
    if r_base.N_turns < 3:
        pytest.skip("solver picked a value too small to step below")
    forced = max(1, r_base.N_turns - 2)
    r_low = design(spec, core, wire, mat, N_override=forced)
    assert r_low.N_turns == forced
    assert r_low.L_actual_uH < r_base.L_required_uH
    assert any("L_actual" in w and "below required" in w for w in r_low.warnings), r_low.warnings


def test_design_overrides_is_empty():
    """``is_empty()`` returns ``True`` only when every field is ``None``
    (or n_stacks == 1, the no-op stack)."""
    assert DesignOverrides().is_empty() is True
    assert DesignOverrides(N_turns=5).is_empty() is False
    assert DesignOverrides(T_amb_C=60.0).is_empty() is False
    assert DesignOverrides(wire_id="AWG12").is_empty() is False
    assert DesignOverrides(n_stacks=1).is_empty() is True
    assert DesignOverrides(n_stacks=2).is_empty() is False


def test_stack_core_n1_is_identity(baseline_inputs):
    """``stack_core(core, 1)`` returns the original core unchanged —
    callers can call this blindly."""
    _, core, _, _ = baseline_inputs
    out = stack_core(core, 1)
    assert out is core


def test_stack_core_n2_scales_dimensions(baseline_inputs):
    """``n_stacks=2`` doubles Ae, Ve, AL; window and magnetic path stay;
    MLT bumps by ``2·HT``."""
    _, core, _, _ = baseline_inputs
    stacked = stack_core(core, 2)
    assert stacked.Ae_mm2 == pytest.approx(core.Ae_mm2 * 2)
    assert stacked.Ve_mm3 == pytest.approx(core.Ve_mm3 * 2)
    assert stacked.AL_nH == pytest.approx(core.AL_nH * 2)
    assert stacked.Wa_mm2 == pytest.approx(core.Wa_mm2)
    assert stacked.le_mm == pytest.approx(core.le_mm)
    if core.HT_mm is not None:
        assert stacked.HT_mm == pytest.approx(core.HT_mm * 2)
        assert stacked.MLT_mm == pytest.approx(core.MLT_mm + 2.0 * core.HT_mm)


def test_stack_core_through_engine_increases_inductance(baseline_inputs):
    """Designing against a 2× stacked core (same N) yields higher L
    and lower required N for the same L target — Ae and AL both
    double, so reluctance halves.

    B_pk at the same N·I stays the same: doubled flux divided by
    doubled cross-section is identical flux density (the physical
    saturation metric). The benefit of stacking is the increased L
    headroom (or reduced N for the same L), not a lower B at the
    same operating point.
    """
    spec, core, wire, mat = baseline_inputs
    r_single = design(spec, core, wire, mat)
    stacked = stack_core(core, 2)
    # Force the single's N so we can read pure stacking effect on L.
    r_stack = design(spec, stacked, wire, mat, N_override=r_single.N_turns)
    # Doubled AL with the same N ≈ doubles L.
    assert r_stack.L_actual_uH == pytest.approx(r_single.L_actual_uH * 2, rel=0.10)
    # B_pk unchanged at same N·I (flux ∝ N·I, Ae doubles, ratio holds).
    assert r_stack.B_pk_T == pytest.approx(r_single.B_pk_T, rel=0.05)
    # The solver re-run can hit the required L with fewer turns.
    r_solve = design(spec, stacked, wire, mat)
    assert r_solve.N_turns <= r_single.N_turns


def test_ferrite_auto_gap_keeps_b_below_saturation(db):
    """Designing on an ungapped ferrite E core — the engine must
    auto-compute a gap so B_pk lands inside the Bsat margin instead
    of saturating. Without the fix, the catalog AL (ungapped, ~6500
    nH) would produce ~5 turns and B ≫ Bsat — a silent catastrophic
    error."""
    materials, cores, wires = db
    mdict = {m.id: m for m in materials}
    ferrite_core = next(c for c in cores if c.id == "tdkepcos-e-1006028-n87")
    mat = mdict[ferrite_core.default_material_id]
    assert mat.rolloff is None, "expected a no-rolloff ferrite"
    assert ferrite_core.lgap_mm == 0, "expected catalog gap of 0 (ungapped)"

    wire = next(w for w in wires if w.id == "AWG14")
    spec = Spec(topology="boost_ccm", Pout_W=800.0)
    r = design(spec, ferrite_core, wire, mat)

    # Auto-gap was applied.
    assert r.gap_actual_mm is not None
    assert r.gap_actual_mm > 0.1, f"expected a positive computed gap, got {r.gap_actual_mm}"
    # B_pk must land below the engine's saturation limit.
    assert r.B_pk_T < r.B_sat_limit_T
    # L_actual hits the requirement.
    assert r.L_actual_uH == pytest.approx(r.L_required_uH, rel=0.05)
    # N is in the realistic ferrite range (not the ~5 the broken path
    # would have produced).
    assert 10 <= r.N_turns <= 200


def test_powder_core_gap_actual_is_zero(baseline_inputs):
    """Powder cores have a distributed gap that's already baked into
    the catalog ``AL_nH`` — the engine must NOT auto-compute a
    discrete gap there. ``gap_actual_mm`` is expected to be ``0`` (or
    whatever the catalog reports, which is also 0 in the curated set)."""
    spec, core, wire, mat = baseline_inputs
    assert mat.rolloff is not None, "expected a powder material with rolloff"
    r = design(spec, core, wire, mat)
    assert r.gap_actual_mm == pytest.approx(0.0, abs=1e-9)


def test_gap_override_replaces_engine_gap(db):
    """A user-supplied ``gap_mm`` override wins over the engine's
    auto-computed gap and lands in the result unchanged."""
    materials, cores, wires = db
    mdict = {m.id: m for m in materials}
    ferrite_core = next(c for c in cores if c.id == "tdkepcos-e-1006028-n87")
    mat = mdict[ferrite_core.default_material_id]
    wire = next(w for w in wires if w.id == "AWG14")
    spec = Spec(topology="boost_ccm", Pout_W=800.0)

    r_auto = design(spec, ferrite_core, wire, mat)
    # Force a clearly different gap.
    auto_gap = float(r_auto.gap_actual_mm or 0.0)
    forced_gap = max(0.1, auto_gap * 2)
    overridden_core = ferrite_core.model_copy(update={"lgap_mm": forced_gap})
    r_forced = design(spec, overridden_core, wire, mat)
    assert r_forced.gap_actual_mm == pytest.approx(forced_gap, rel=0.001)
    # Bigger gap → smaller effective AL → more turns needed for the
    # same L target.
    assert r_forced.N_turns > r_auto.N_turns


def test_main_window_n_stacks_override_doubles_inductance():
    """End-to-end: setting ``n_stacks=2`` in the overrides leads the
    engine's result to reflect a doubled-area core — L at the same N
    is roughly double the single-stack value."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    inst = QApplication.instance() or QApplication([])
    assert inst is not None
    from pfc_inductor.ui.main_window import MainWindow

    win = MainWindow(defer_initial_calc=False)
    try:
        win._on_calculate()
        assert win._last_design_snapshot is not None
        single_result = win._last_design_snapshot[0]
        single_N = int(getattr(single_result, "N_turns"))
        single_L = float(getattr(single_result, "L_actual_uH"))

        win._design_overrides = DesignOverrides(n_stacks=2, N_turns=single_N)
        win._on_calculate()
        stacked_result = win._last_design_snapshot[0]
        stacked_L = float(getattr(stacked_result, "L_actual_uH"))
        # Doubled Ae·AL at same N → ~doubled L.
        assert stacked_L > single_L * 1.7
    finally:
        win.close()


def test_project_file_roundtrips_overrides(tmp_path):
    """Saving + loading a project preserves the overrides payload bit-for-bit."""
    pf = ProjectFile.from_session(
        name="Tweak test",
        spec=Spec(),
        overrides=DesignOverrides(N_turns=42, T_amb_C=55.0, wire_id="AWG12"),
    )
    out = save_project(tmp_path / "tweak.pfc", pf)
    loaded = load_project(out)
    assert loaded.overrides.N_turns == 42
    assert loaded.overrides.T_amb_C == pytest.approx(55.0)
    assert loaded.overrides.wire_id == "AWG12"
    assert loaded.overrides.core_id is None


def test_legacy_project_file_without_overrides_field_loads_empty(tmp_path):
    """A .pfc that predates the overrides field must still load — the
    field defaults to an empty ``DesignOverrides``."""
    import json

    legacy = {
        "version": "1.0",
        "name": "Legacy session",
        "spec": Spec().model_dump(mode="json"),
        "selection": {"material_id": "", "core_id": "", "wire_id": ""},
    }
    path = tmp_path / "legacy.pfc"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    loaded = load_project(path)
    assert loaded.overrides.is_empty()


def test_controller_calculate_with_overrides_applies_tamb(baseline_inputs):
    """The controller wrapper threads a T_amb override into the spec
    before calling ``design()``."""
    from pfc_inductor.ui.controllers.calculation_controller import CalculationController

    spec, core, wire, mat = baseline_inputs

    class _Panel:
        def get_spec(self):
            return spec

        def get_core_id(self):
            return core.id

        def get_wire_id(self):
            return wire.id

        def get_material_id(self):
            return mat.id

    ctrl = CalculationController(_Panel(), [mat], [core], [wire])
    inputs, result = ctrl.calculate_with_overrides(
        DesignOverrides(T_amb_C=spec.T_amb_C + 25.0)
    )
    assert inputs.spec.T_amb_C == pytest.approx(spec.T_amb_C + 25.0)
    # Hotter ambient → hotter winding (everything else equal).
    _, baseline = ctrl.calculate()
    assert result.T_winding_C > baseline.T_winding_C


def test_controller_calculate_with_overrides_forces_n(baseline_inputs):
    """``calculate_with_overrides`` with an ``N_turns`` override returns
    a result whose ``N_turns`` matches the override."""
    from pfc_inductor.ui.controllers.calculation_controller import CalculationController

    spec, core, wire, mat = baseline_inputs

    class _Panel:
        def get_spec(self):
            return spec

        def get_core_id(self):
            return core.id

        def get_wire_id(self):
            return wire.id

        def get_material_id(self):
            return mat.id

    ctrl = CalculationController(_Panel(), [mat], [core], [wire])
    _, base = ctrl.calculate()
    forced = base.N_turns + 2
    _, result = ctrl.calculate_with_overrides(DesignOverrides(N_turns=forced))
    assert result.N_turns == forced


def test_main_window_tweak_pipeline_forces_n():
    """Integration: setting ``_design_overrides`` and calling
    ``_on_calculate`` lands a ``DesignResult`` whose ``N_turns``
    matches the override.

    Drives the same path the "Tweak" button takes — bypasses the
    actual ``TweakDialog`` modal (it can't ``exec()`` headlessly)
    and sets the state field directly.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    inst = QApplication.instance() or QApplication([])
    assert inst is not None
    from pfc_inductor.ui.main_window import MainWindow

    win = MainWindow(defer_initial_calc=False)
    try:
        # Baseline run — populates ``_last_design_snapshot`` so the
        # tweak path has a reference point.
        win._on_calculate()
        assert win._last_design_snapshot is not None
        base_result = win._last_design_snapshot[0]
        base_N = int(getattr(base_result, "N_turns"))
        assert win._baseline_N_solver == base_N

        # Apply N override and re-run.
        forced_N = base_N + 2
        win._design_overrides = DesignOverrides(N_turns=forced_N)
        win._on_calculate()
        assert win._last_design_snapshot is not None
        forced_result = win._last_design_snapshot[0]
        assert int(getattr(forced_result, "N_turns")) == forced_N
        # Solver baseline must stay pinned at the pre-override value —
        # the override run does not update it.
        assert win._baseline_N_solver == base_N
    finally:
        win.close()


def test_main_window_save_load_preserves_overrides(tmp_path):
    """Saving and reloading a project carries the prototype overrides
    through to the next session."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    inst = QApplication.instance() or QApplication([])
    assert inst is not None
    from pfc_inductor.ui.main_window import MainWindow

    win = MainWindow(defer_initial_calc=False)
    try:
        win._design_overrides = DesignOverrides(N_turns=42, T_amb_C=55.0)
        captured = win._capture_project()
        out = save_project(tmp_path / "saved.pfc", captured)
        assert load_project(out).overrides.N_turns == 42

        # Reset the in-memory state, then re-apply — overrides ride
        # back through ``_apply_project``.
        win._design_overrides = DesignOverrides()
        win._apply_project(load_project(out))
        assert win._design_overrides.N_turns == 42
        assert win._design_overrides.T_amb_C == pytest.approx(55.0)
    finally:
        win.close()
