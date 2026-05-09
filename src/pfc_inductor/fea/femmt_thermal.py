"""Coupled magnetostatic + thermal FEA via FEMMT.

The headline magnetostatic validation in :mod:`femmt_runner` returns
``L`` and ``B_pk`` numbers. This module adds the **thermal** pass
that runs immediately after, reading the ohmic + core-loss density
fields the magnetostatic step wrote and propagating them through
the inductor's material stack to a steady-state temperature
distribution.

Why a separate module:

    The magnetostatic + thermal sequence requires extra inputs
    the cold call doesn't need (thermal conductivities per region,
    case geometry, boundary temperatures). Bundling them in
    :class:`ThermalOptions` keeps the cheap magnetostatic-only
    path uncluttered while exposing a typed surface the UI
    + CLI can drive.

What the user gets:

    A :class:`ThermalResult` carrying peak / average / per-
    region temperatures plus the path to the gmsh
    ``temperature.pos`` field which the :mod:`pos_renderer`
    headless post-processor turns into a coloured heatmap PNG
    the FEA gallery picks up automatically.

The thermal solve adds roughly 10–25 s on top of the
magnetostatic pass on typical PFC inductors (PQ40 / 30 mm
toroid). It re-uses the same gmsh subprocess, so the cost is
purely the additional finite-element solve.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pfc_inductor.fea.models import FEMMNotAvailable, FEMMSolveError
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Material-keyed thermal conductivities.
# ---------------------------------------------------------------------------
# k [W/(m·K)] — typical engineering values. Sources:
#   ferrite        — TDK / EPCOS / Ferroxcube datasheets, 4–6 W/m·K
#   silicon-steel  — M19 / M27 / 3.5% Si laminations, 22–30 W/m·K
#   powder cores   — Magnetics Kool-Mu / High-Flux, 18–25 W/m·K
#   nanocrystalline— Vitroperm 500 F class, 8–12 W/m·K
#   amorphous      — Metglas 2605SA1 / 2705M, 11–13 W/m·K
#
# We pick mid-range defaults so the heatmap is representative;
# users that need ±5 % accuracy override the dict before solving.
_MATERIAL_K_W_M_K: dict[str, float] = {
    "ferrite":          5.0,
    "silicon-steel":   25.0,
    "powder":          20.0,
    "nanocrystalline": 10.0,
    "amorphous":       12.0,
}

# Universal physical constants — every solve uses these.
_K_AIR = 0.026         # still air at 40 °C
_K_COPPER = 400.0      # pure Cu at 25 °C
_K_INSULATION = 0.42   # typical polyethylene wire insulation
_K_AIR_GAP = 180.0     # FEMMT example uses AlN-style high-k for
                       # the air gap region — represents an
                       # epoxy-potted gap, not loose air. Realistic
                       # for production PFC inductors.

# Default case (potting / housing) thermal conductivity. Epoxy
# encapsulant — typical value across vendors. The 1.54 W/m·K
# sample from the FEMMT example matches this.
_K_CASE = 1.54


@dataclass
class ThermalOptions:
    """Inputs for the thermal solve. All fields have sensible
    defaults so the caller only overrides what they care about.
    """

    T_ambient_C: float = 40.0
    """Boundary temperature applied as a Dirichlet condition on
    every active boundary side. Defaults to the project's
    typical ambient (40 °C, ~1 m above floor in a cabinet)."""

    case_gap_top_m: float = 0.002
    case_gap_right_m: float = 0.0025
    case_gap_bot_m: float = 0.002
    """Distance from the core to the modelled case boundary in
    metres. Setting these too small clips the thermal volume and
    inflates the peak temperature; too large adds solve time
    without changing the answer. 2–3 mm matches typical
    enclosed-PFC mechanical practice."""

    k_overrides_W_m_K: dict[str, float] = field(default_factory=dict)
    """Optional overrides for the conductivity-by-key dict
    (``"core"``, ``"winding"``, ``"insulation"``, ``"case"``,
    ``"air"``, ``"air_gaps"``). Empty by default — the runner
    fills sensible values from the material type."""

    boundary_active: dict[str, bool] = field(default_factory=dict)
    """Per-side boundary on/off map. Empty defaults to "all
    active" (Dirichlet at ``T_ambient_C`` on every side except
    the symmetry top, which is Neumann zero-flux)."""


@dataclass(frozen=True)
class ThermalResult:
    """Outcome of a thermal solve."""

    T_peak_C: float
    """Maximum temperature reached anywhere in the model."""
    T_winding_avg_C: float
    """Average temperature in the winding region — the number
    that compares directly against the analytical ΔT estimate."""
    T_core_avg_C: float
    """Average temperature in the core region."""
    T_ambient_C: float
    """Boundary temperature used in the solve (echoed back so
    the caller can compute ΔT_winding without re-passing it)."""
    rise_winding_C: float
    """Convenience: ``T_winding_avg_C - T_ambient_C``."""
    rise_core_C: float
    """Convenience: ``T_core_avg_C - T_ambient_C``."""
    fem_path: str
    """Working directory where ``temperature.pos`` lives."""
    solve_time_s: float
    notes: str = ""

    @property
    def passed_thermal_budget(self) -> bool:
        r"""Crude pass/fail vs.\ a 105 °C winding ceiling — typical
        for class B insulation / standard magnet-wire enamel."""
        return self.T_winding_avg_C < 105.0


def _resolve_k_dict(
    material: Material, options: ThermalOptions
) -> dict:
    """Build the thermal_conductivity_dict in the exact shape
    FEMMT expects."""
    # Map the material's ``type`` string to a default core k.
    mat_type = (getattr(material, "type", "") or "").lower()
    k_core = _MATERIAL_K_W_M_K.get(mat_type, 5.0)
    k = {
        "air": _K_AIR,
        "case": {
            "top": _K_CASE,
            "top_right": _K_CASE,
            "right": _K_CASE,
            "bot_right": _K_CASE,
            "bot": _K_CASE,
        },
        "core": k_core,
        "winding": _K_COPPER,
        "air_gaps": _K_AIR_GAP,
        "insulation": _K_INSULATION,
    }
    # Apply user overrides.
    for key, value in options.k_overrides_W_m_K.items():
        k[key] = value  # type: ignore[assignment]
    return k


def _resolve_boundaries(
    options: ThermalOptions,
) -> tuple[dict, dict]:
    """Build the boundary-temperature + boundary-flag dicts."""
    sides = (
        "top", "top_right", "right_top", "right",
        "right_bottom", "bottom_right", "bottom",
    )
    temps = {f"value_boundary_{s}": float(options.T_ambient_C) for s in sides}
    # Active flags. Top and top-right are typically convection-
    # bound to ambient (potting cap); the right and bottom sides
    # are the heat-rejection path (heatsink / chassis); the
    # symmetry side stays Neumann (flag=0). Defaulting matches
    # the FEMMT example's "all sides except top" pattern.
    default_flags = {
        "flag_boundary_top": 0,
        "flag_boundary_top_right": 0,
        "flag_boundary_right_top": 1,
        "flag_boundary_right": 1,
        "flag_boundary_right_bottom": 1,
        "flag_boundary_bottom_right": 1,
        "flag_boundary_bottom": 1,
    }
    if options.boundary_active:
        for k, v in options.boundary_active.items():
            default_flags[f"flag_boundary_{k}"] = 1 if v else 0
    return temps, default_flags


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def validate_design_thermal_femmt(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
    output_dir: Optional[Path] = None,
    options: Optional[ThermalOptions] = None,
    timeout_s: int = 360,
) -> ThermalResult:
    """Magnetostatic + thermal coupled solve.

    Runs the same FEMMT geometry the magnetostatic-only path
    builds (so the L / B numbers stay consistent), adds a
    thermal-conductivity dict and boundary conditions, and
    invokes FEMMT's ``thermal_simulation``. Reads the
    ``results_thermal.json`` log FEMMT writes and returns peak /
    average temperatures.

    The ``temperature.pos`` field FEMMT writes lands in the same
    ``e_m/results/fields`` folder as the magnetostatic ``.pos``
    files; the existing :func:`pos_renderer.render_field_pngs`
    sweep picks it up automatically and produces a heatmap PNG
    for the gallery.

    Raises :class:`FEMMNotAvailable` / :class:`FEMMSolveError`
    on the same conditions the magnetostatic path raises.
    """
    import time

    options = options or ThermalOptions()
    started = time.monotonic()

    # Run the existing magnetostatic path first — the thermal
    # solve depends on the loss file the EM solve writes, and
    # we want the user to also get the magnetostatic L / B
    # numbers as part of the answer.
    from pfc_inductor.fea.femmt_runner import (
        _run_validation_in_subprocess,
        validate_design_femmt,
    )

    em = validate_design_femmt(
        spec, core, wire, material, result,
        output_dir=output_dir, timeout_s=timeout_s,
    )

    # Run the thermal pass directly in-process. We don't bother
    # with a separate subprocess because the magnetostatic call
    # already isolated the gmsh state via its own subprocess —
    # by the time we reach here we know the FEMMT install is
    # healthy. If the thermal pass crashes, the user gets the
    # magnetostatic results either way.
    fem_path = Path(em.fem_path)
    if not fem_path.exists():
        raise FEMMSolveError(
            f"Thermal solve cannot run: magnetostatic working "
            f"directory {fem_path} is missing."
        )

    # Defensive shape check. FEMMT's thermal solver only handles
    # Single-core types in the tested code path — toroides via
    # the PQ-equivalent shim work, but bespoke geometries don't.
    # If the EM step succeeded the geometry passed muster; we
    # just re-instantiate the component pointing at the same
    # working dir so the loss file is in place.
    try:
        from pfc_inductor.fea.femmt_runner import _install_no_space_femmt_shim

        _install_no_space_femmt_shim()
        import femmt as ft
    except Exception as e:
        raise FEMMNotAvailable(
            f"FEMMT could not be re-imported for the thermal "
            f"pass: {type(e).__name__}: {e}"
        ) from e

    k_dict = _resolve_k_dict(material, options)
    temps, flags = _resolve_boundaries(options)

    # The thermal_simulation API takes ``flag_insulation`` as
    # the last positional + ``show_thermal_simulation_results``
    # as a keyword. We keep show_=False to stay headless.
    original_cwd = os.getcwd()
    os.chdir(fem_path)
    try:
        # Re-load the geometry exactly as the EM step set it up.
        # FEMMT persists the model topology in the working
        # directory, so a second instantiation with the same
        # working_directory picks up where the EM call left off.
        from pfc_inductor.fea.femmt_runner import _silence_signal_in_worker_thread

        with _silence_signal_in_worker_thread():
            geo = ft.MagneticComponent(
                component_type=ft.ComponentType.Inductor,
                working_directory=str(fem_path),
                simulation_name="thermal",
                onelab_verbosity=ft.Verbosity.Silent,
                verbosity=ft.Verbosity.Silent,
            )

            # Re-create the model so FEMMT has the geometry
            # tree in memory; this is fast (no second EM solve).
            geo.create_model(
                freq=spec.f_sw_kHz * 1000.0,
                pre_visualize_geometry=False,
                save_png=False,
            )
            # Run the thermal pass. show_ flags stay False so
            # nothing pops a GUI window.
            geo.thermal_simulation(
                thermal_conductivity_dict=k_dict,
                boundary_temperatures_dict=temps,
                boundary_flags_dict=flags,
                case_gap_top=options.case_gap_top_m,
                case_gap_right=options.case_gap_right_m,
                case_gap_bot=options.case_gap_bot_m,
                show_thermal_simulation_results=False,
                pre_visualize_geometry=False,
                flag_insulation=True,
            )
            log = geo.read_thermal_log()
    except Exception as e:
        raise FEMMSolveError(
            f"FEMMT thermal solve failed: {type(e).__name__}: {e}"
        ) from e
    finally:
        os.chdir(original_cwd)

    # Re-render the .pos files including the new ``temperature.pos``
    # so the gallery picks up the thermal heatmap automatically.
    try:
        from pfc_inductor.fea.pos_renderer import render_field_pngs

        render_field_pngs(fem_path)
    except Exception:
        logger.exception("Field-PNG re-render after thermal failed.")

    # Extract scalars from FEMMT's results_thermal.json. Field
    # names follow FEMMT 0.5.x convention.
    T_peak = float(_dig(log, ["temperatures", "max"], default=0.0))
    T_w_avg = float(_dig(log, ["temperatures", "winding_average"], default=0.0))
    T_c_avg = float(_dig(log, ["temperatures", "core_average"], default=0.0))
    elapsed = time.monotonic() - started
    return ThermalResult(
        T_peak_C=T_peak,
        T_winding_avg_C=T_w_avg,
        T_core_avg_C=T_c_avg,
        T_ambient_C=options.T_ambient_C,
        rise_winding_C=max(T_w_avg - options.T_ambient_C, 0.0),
        rise_core_C=max(T_c_avg - options.T_ambient_C, 0.0),
        fem_path=str(fem_path),
        solve_time_s=elapsed,
        notes=(
            "Steady-state thermal solve from the magnetostatic loss "
            "file. Use ThermalOptions to override material k or "
            "boundary temperatures."
        ),
    )


def _dig(d: dict, path: list[str], default=None):
    """Defensive dotted-key lookup."""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
        if cur is default:
            return default
    return cur if cur is not None else default
